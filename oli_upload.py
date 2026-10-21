"""Enlace privado y temporal para archivos que no se puedan bajar de Telegram."""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlparse
import uuid
from oli_media import MAX_ARCHIVO, validar_archivo, MediaError

SLOT=threading.BoundedSemaphore(1)


class UploadError(Exception):
    def __init__(self,status,message):self.status,self.message=status,message


def db(api):
    connection=sqlite3.connect(api.DATA/'subidas.sqlite',timeout=5)
    connection.execute('CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,uid TEXT,modo TEXT,nonce TEXT,vence REAL,cantidad INTEGER,finalizado INTEGER)')
    return connection


def crear(api,uid,modo,nonce):
    token=secrets.token_urlsafe(32)
    connection=db(api)
    try:
        with connection:
            connection.execute('DELETE FROM tokens WHERE vence<?',(time.time(),))
            connection.execute('UPDATE tokens SET finalizado=1 WHERE uid=? AND modo=?',(uid,modo))
            connection.execute('INSERT INTO tokens VALUES(?,?,?,?,?,0,0)',(hashlib.sha256(token.encode()).hexdigest(),uid,modo,nonce,time.time()+900))
    finally:connection.close()
    return api.SITE_URL+'/carga-oli/#'+token


def validar_token(api,token):
    if not isinstance(token,str) or len(token)!=43:
        raise UploadError(403,'Volvé a pedir un enlace desde tu bot de Telegram.')
    hashed=hashlib.sha256(token.encode()).hexdigest();connection=db(api)
    try:row=connection.execute('SELECT uid,modo,nonce,vence,cantidad,finalizado FROM tokens WHERE hash=?',(hashed,)).fetchone()
    finally:connection.close()
    if not row or row[3]<time.time() or row[5] or row[0] not in api.USUARIOS_PERMITIDOS:
        raise UploadError(403,'El enlace venció o ya fue utilizado. Pedí otro desde Telegram.')
    return hashed,row


def destino(ses,row):
    if row[1]=='edicion':
        edit=ses.get('edicion') or {}
        if edit.get('id')!=row[2]:raise UploadError(409,'La edición cambió. Pedí un enlace nuevo.')
        return edit
    if ses.get('carga_id')!=row[2] or ses.get('paso')!='fotos':
        raise UploadError(409,'La carga cambió. Pedí un enlace nuevo.')
    return ses['modelo']


def manejar(handler,api,path):
    if handler.headers.get('Origin')!=api.SITE_URL or handler.headers.get('Transfer-Encoding'):
        raise UploadError(403,'No se pudo validar la carga.')
    hashed,row=validar_token(api,handler.headers.get('X-Oli-Upload',''))
    if path=='/api/subida/finalizar':
        if int(handler.headers.get('Content-Length','0'))>64:raise UploadError(413,'Solicitud demasiado grande.')
        handler.rfile.read(int(handler.headers.get('Content-Length','0')))
        with api.Bloqueo():
            sessions=api.leer_json(api.SESIONES_FILE,{})
            target=destino(sessions.get(row[0],{}),row)
            n=len(target.get('fotos_tmp',[]));has_video=bool(target.get('video_tmp'))
        connection=db(api)
        try:
            with connection:connection.execute('UPDATE tokens SET finalizado=1 WHERE hash=?',(hashed,))
        finally:connection.close()
        try:
            api.enviar_acciones(int(row[0]),[api.msg(f'Archivos recibidos: {n} fotos'+(' y un video.' if has_video else '.')+' Volvé a Telegram para revisar y guardar.',
                [[{'texto':'Revisar archivos','data':'ed_fotos' if row[1]=='edicion' else 'continuar'}]])])
        except Exception:api.registrar_error('confirmacion_subida_telegram')
        return {'ok':True,'fotos':n,'video':has_video}
    size=int(handler.headers.get('Content-Length','0'))
    if not 0<size<=MAX_ARCHIVO:raise UploadError(413,'Cada archivo debe pesar hasta 100 MB.')
    if row[4]>=11:raise UploadError(429,'Este enlace ya recibió el máximo de archivos.')
    if not SLOT.acquire(blocking=False):raise UploadError(429,'Se está procesando otro archivo. Reintentá en unos segundos.')
    folder=api.MEDIA/'tmp'/row[0]/'subidas';folder.mkdir(parents=True,exist_ok=True)
    file=folder/(uuid.uuid4().hex+'.bin');retained=False
    try:
        hashed,row=validar_token(api,handler.headers.get('X-Oli-Upload',''))
        remaining=size
        digest=hashlib.sha256()
        with file.open('xb') as f:
            while remaining:
                chunk=handler.rfile.read(min(1024*1024,remaining))
                if not chunk:raise UploadError(400,'La transferencia quedó incompleta. Volvé a intentarlo.')
                f.write(chunk);digest.update(chunk);remaining-=len(chunk)
        kind=validar_archivo(file)
        with api.Bloqueo():
            sessions=api.leer_json(api.SESIONES_FILE,{})
            ses=sessions.get(row[0],{});target=destino(ses,row)
            hashed,row=validar_token(api,handler.headers.get('X-Oli-Upload',''))
            sha=digest.hexdigest()
            if any(e.get('sha256')==sha for e in target.get('fotos_tmp',[])+([target['video_tmp']] if target.get('video_tmp') else [])):
                return {'ok':True,'duplicado':True,'fotos':len(target.get('fotos_tmp',[])),'video':bool(target.get('video_tmp'))}
            entry={'archivo':file.relative_to(api.DATA).as_posix(),'file_id':None,'sha256':sha}
            if kind=='foto':
                photos=target.setdefault('fotos_tmp',[])
                if len(photos)>=10:raise UploadError(400,'El máximo es diez fotos. Quitá alguna antes de agregar otra.')
                photos.append(entry)
            else:target['video_tmp']=entry
            target['media_cambiada']=True
            api.escribir_json(api.SESIONES_FILE,sessions);retained=True
            n=len(target.get('fotos_tmp',[]));has_video=bool(target.get('video_tmp'))
        connection=db(api)
        try:
            with connection:connection.execute('UPDATE tokens SET cantidad=cantidad+1 WHERE hash=?',(hashed,))
        finally:connection.close()
        return {'ok':True,'tipo':kind,'fotos':n,'video':has_video}
    except MediaError as e:raise UploadError(400,str(e)) from None
    finally:
        if not retained:file.unlink(missing_ok=True)
        SLOT.release()
