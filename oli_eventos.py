"""Idempotencia por actualización y registro de resultado sin claves ni cuerpos en logs."""
import base64
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

LOCK=threading.RLock()
DESCARGAS=threading.BoundedSemaphore(3)


def contexto_media(ses):
    edit=ses.get('edicion') or {}
    if ses.get('foco')=='edicion' and edit.get('campo')=='media':return ('edicion',edit.get('id'))
    if ses.get('paso')=='fotos' and ses.get('foco','carga') in ('carga','menu') and not edit and not ses.get('buscando') and not ses.get('confirmacion'):
        return ('carga',ses.get('carga_id'))
    if ses.get('foco')=='menu' and not ses.get('paso') and edit.get('campo')=='media':return ('edicion',edit.get('id'))
    return None


def precargar(api,uid,message):
    """Descargar fuera del bloqueo global. Los archivos no se incorporan hasta validar la sesión."""
    if not getattr(api,'BOT_TOKEN','') or not hasattr(api,'DESCARGA_LOCAL'):return None,None
    obj=(message.get('photo') or [None])[-1] or message.get('video') or message.get('document') or message.get('animation')
    if not obj or not obj.get('file_id') or obj.get('file_size',0)>19*1024*1024:return None,None
    with api.Bloqueo():
        ses=api.leer_json(api.SESIONES_FILE,{}).get(uid,{})
        contexto=contexto_media(ses)
        target=ses.get('edicion',{}) if contexto and contexto[0]=='edicion' else ses.get('modelo',{})
        if target.get('reemplazar') is None:
            for entry in target.get('fotos_tmp',[]):
                if entry.get('file_id')==obj['file_id'] and entry.get('archivo'):
                    p=(api.DATA/entry['archivo']).resolve()
                    if p.is_relative_to(api.MEDIA.resolve()) and p.is_file():return None,contexto
    if not contexto:return None,None
    cache={'file_id':obj['file_id'],'archivo':api.MEDIA/'tmp'/uid/'precargas'/(uuid.uuid4().hex+'.bin')}
    if not DESCARGAS.acquire(timeout=120):
        cache['error']=api.DescargaTelegramError('Hay varias fotos en recepción. Reenviá las pendientes o usá Subir por la web; tu avance está guardado.','cola_descarga_telegram')
        return cache,contexto
    try:
        try:api.descargar_de_telegram(obj['file_id'],cache['archivo'])
        except api.DescargaTelegramError as error:cache['error']=error
        except Exception:
            cache['error']=api.DescargaTelegramError('No pude preparar esa foto. Reintentá o usá Subir por la web; tu avance está guardado.','preparar_archivo_telegram')
        return cache,contexto
    finally:DESCARGAS.release()


def _encode(value):
    if isinstance(value,bytes):return {'__bytes__':base64.b64encode(value).decode()}
    if isinstance(value,dict):return {k:_encode(v) for k,v in value.items()}
    if isinstance(value,list):return [_encode(v) for v in value]
    return value


def _decode(value):
    if isinstance(value,dict):
        if set(value)=={'__bytes__'}:return base64.b64decode(value['__bytes__'])
        return {k:_decode(v) for k,v in value.items()}
    if isinstance(value,list):return [_decode(v) for v in value]
    return value


def ejecutar(api, update, enviar=True):
    import oli_gestion
    message=update.get('message') or {}
    uid=str(message.get('from',{}).get('id',''))
    token=None
    if uid in api.USUARIOS_PERMITIDOS and any(message.get(k) for k in ('photo','video','document','animation')):
        token=oli_gestion.comenzar_media(uid)
    cache=None
    try:
        cache,contexto=precargar(api,uid,message) if token else (None,None)
        if cache:api.DESCARGA_LOCAL.valor=cache
        return _ejecutar(api,update,enviar,contexto)
    finally:
        if cache:
            api.DESCARGA_LOCAL.valor=None
            try:cache['archivo'].unlink(missing_ok=True)
            except OSError:api.registrar_error('limpiar_precarga')
        if token:oli_gestion.terminar_media(uid,token)


def _ejecutar(api, update, enviar=True, contexto=None):
    obj=update.get('message') or update.get('callback_query') or {}
    uid=str(obj.get('from',{}).get('id',''))
    if not api.USUARIOS_PERMITIDOS or uid not in api.USUARIOS_PERMITIDOS:
        return {'acciones':[],'enviado':False,'rechazado':True}
    event=update.get('update_id')
    if event is None:
        event='cb:'+str(obj.get('id')) if 'callback_query' in update else 'msg:'+str(obj.get('chat',{}).get('id'))+':'+str(obj.get('message_id'))
    key=uid+':'+str(event)
    file=api.DATA/'eventos.sqlite';api.DATA.mkdir(parents=True,exist_ok=True)
    with LOCK:
        db=sqlite3.connect(file,timeout=5)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS eventos(id TEXT PRIMARY KEY,estado TEXT,acciones TEXT,creado REAL)')
            db.execute('DELETE FROM eventos WHERE creado<?',(time.time()-7*86400,))
            old=db.execute('SELECT estado FROM eventos WHERE id=?',(key,)).fetchone()
            if old:
                return {'acciones':[],'enviado':False,'duplicado':True,'estado':old[0]}
            db.execute('INSERT INTO eventos VALUES(?,?,?,?)',(key,'procesando',None,time.time()));db.commit()
            try:
                with api.Bloqueo():
                    actual=api.leer_json(api.SESIONES_FILE,{}).get(uid,{}) if contexto else None
                if contexto and contexto_media(actual)!=contexto:
                    actions=[api.msg('La carga cambió mientras llegaba esa foto. No la mezclé con otro artículo. Abrí la carga correcta y reenviála.')]
                else:actions=api.procesar(update)
                db.execute('UPDATE eventos SET estado=?,acciones=? WHERE id=?',('listo',json.dumps(_encode(actions),ensure_ascii=False),key));db.commit()
            except Exception:
                db.execute('UPDATE eventos SET estado=? WHERE id=?',('error_proceso',key));db.commit()
                api.registrar_error('procesar_actualizacion')
                return {'acciones':[],'enviado':False,'error':'No pude completar la operación. Reabrí el menú para revisar su estado.'}
            # Si el envío falla no repetimos una escritura ni un mensaje cuyo resultado es incierto.
            try:
                if enviar and api.BOT_TOKEN and actions:
                    db.execute('UPDATE eventos SET estado=? WHERE id=?',('enviando',key));db.commit()
                    api.enviar_acciones(api.chat_de(update),actions)
                db.execute('UPDATE eventos SET estado=? WHERE id=?',('completo',key));db.commit()
            except Exception:
                db.execute('UPDATE eventos SET estado=? WHERE id=?',('envio_incierto',key));db.commit()
                api.registrar_error('envio_telegram')
                return {'acciones':[],'enviado':False,'error':'envio_incierto'}
            # Fotos/file_ids y enlaces temporales permanecen solo en la base privada; no vuelven a n8n.
            return {'acciones':[],'enviado':bool(enviar and api.BOT_TOKEN),'procesado':True}
        finally:db.close()
