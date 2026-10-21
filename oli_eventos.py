"""Idempotencia por actualización y registro de resultado sin claves ni cuerpos en logs."""
import base64
import json
from pathlib import Path
import sqlite3
import threading
import time

LOCK=threading.RLock()


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
                actions=api.procesar(update)
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
