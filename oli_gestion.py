"""Administración privada del catálogo. Cambios visibles solo después de confirmar."""
import copy
import datetime
import hashlib
import json
import re
import threading
import time
import unicodedata
import uuid
from oli_media import materializar, validar_archivo, MediaError
from oli_publicacion import aplicar_modelo, publicar, revision, validar, PublicacionError
import oli_upload

_ALBUMS={}
_ALBUM_LOCK=threading.Lock()


def resumen_album(a,uid,chat_id,modo):
    """Agrupa la previsualización; los archivos ya están persistidos antes de esperar."""
    nonce=uuid.uuid4().hex
    with _ALBUM_LOCK:_ALBUMS[uid]=nonce
    def worker():
        time.sleep(a.ESPERA_ALBUM)
        with _ALBUM_LOCK:
            if _ALBUMS.get(uid)!=nonce:return
            _ALBUMS.pop(uid,None)
        try:
            with a.Bloqueo():
                ses=a.leer_json(a.SESIONES_FILE,{}).get(uid,{})
                if ses.get('foco')!=modo:return
                if modo=='edicion' and ses.get('edicion',{}).get('campo')=='media':result=editar_fotos(a,copy.deepcopy(ses['edicion']))
                elif modo=='carga' and ses.get('paso')=='fotos':result=pregunta(a,ses)
                else:return
            if a.BOT_TOKEN:a.enviar_acciones(chat_id,[result])
        except Exception:a.registrar_error('resumen_album')
    threading.Thread(target=worker,daemon=True).start()


def boton(texto,data):return {'texto':texto,'data':data}


def con_mosaico(a,result,target):
    photos=target.get('fotos_tmp',[])
    if not photos:return result
    from oli_publicacion import SITE
    paths=[((SITE if f.get('publica','').startswith('/img/') else a.DATA)/(f.get('archivo') or f.get('publica','').lstrip('/'))).resolve() for f in photos]
    if not all((p.is_relative_to(a.MEDIA.resolve()) or p.is_relative_to((SITE/'img').resolve())) and p.is_file() for p in paths):return result
    return dict(result,tipo='foto',bytes=a.armar_mosaico(paths,target.get('portada',0)))


def menu(a,ses=None,nombre=''):
    ses=ses or {};rows=[[boton('📷 Cargar modelo','cargar'),boton('🔎 Buscar modelo','buscar')]]
    if ses.get('paso'):rows.append([boton('▶️ Continuar carga','continuar')])
    if ses.get('edicion'):rows.append([boton('✏️ Continuar edición','ed_volver')])
    rows += [[boton('📝 Borradores','borradores:0'),boton('🛍 Publicados','lista:publicado:0')],
             [boton('🙈 Ocultos','lista:oculto:0'),boton('🗃 Archivados','lista:descartado:0')],
             [boton('❔ Ayuda','ayuda')]]
    return a.msg((f'Hola {nombre}. ' if nombre else '')+'¿Qué querés hacer? Tu avance se conserva al abrir este menú.',rows)


def lista(a,estado,pagina=0,consulta=None):
    models=a.leer_json(a.MODELOS_FILE,[])
    if consulta:
        def norm(t):return ''.join(c for c in unicodedata.normalize('NFD',t.lower()) if unicodedata.category(c)!='Mn')
        terms=norm(consulta).split()
        models=[m for m in models if all(t in norm(m['codigo']+' '+m['nombre']) for t in terms)]
    else:models=[m for m in models if m.get('estado')==estado]
    models=list(reversed(models));page=max(0,min(pagina,(len(models)-1)//8)) if models else 0
    rows=[[boton(f"{m['codigo']} · {m['nombre'][:35]} · {m['estado']}",('ver_borrador:' if m['estado']=='borrador' else 'ver:')+m['codigo'])] for m in models[page*8:page*8+8]]
    nav=[]
    if page:nav.append(boton('← Anteriores',f'lista:{estado}:{page-1}'))
    if (page+1)*8<len(models):nav.append(boton('Más →',f'lista:{estado}:{page+1}'))
    if nav and not consulta:rows.append(nav)
    if consulta and len(models)>8:rows.append([boton('Afinar búsqueda','buscar')])
    rows.append([boton('Menú','menu')])
    return a.msg(('Elegí un modelo:' if models else 'No encontré modelos con ese criterio.')+(' Mostré los primeros ocho; podés afinar la búsqueda.' if consulta and len(models)>8 else ''),rows)


def ficha(a,m):
    estado=m.get('estado','borrador');code=m['codigo'];rows=[]
    if estado in ('borrador','oculto'):rows.append([boton('✅ Publicar' if estado=='borrador' else '👁 Volver a mostrar','publicar:'+code)])
    if estado=='publicado':rows.append([{'texto':'👀 Ver en la tienda','url':a.SITE_URL+a.ruta_modelo(m)},boton('🙈 Ocultar','ocultar:'+code)])
    if estado!='descartado':
        rows += [[boton('✏️ Editar datos','editar:'+code),boton('📷 Fotos y video','media:'+code)],
                 [boton('🤖 Quitar aprobación IA' if m.get('aprobado_comercialmente') else '🤖 Aprobar para Oli','aprobar:'+code)]]
    if estado=='borrador':rows.append([boton('🗃 Descartar borrador','descartar:'+code)])
    if estado=='descartado':rows.append([boton('↩️ Recuperar borrador','recuperar:'+code)])
    rows.append([boton('Menú','menu')])
    cat=a.buscar_categoria(m.get('categoria'))
    text=f"{code} · {m['nombre']}\nEstado: {estado}\nCategoría: {cat['nombre'] if cat else m.get('categoria','')}\nLínea: {m.get('linea') or '—'}\n\n{m.get('descripcion','')}\n\nPrecio orientativo: {a.precio_fmt(m['precio'])}\nVariantes: {', '.join(m.get('variantes',[])) or 'sin variantes'}\nFotos: {len(m.get('fotos',[]))} · Video: {'sí' if m.get('video') else 'no'}\nAprobado para recomendaciones: {'sí' if m.get('aprobado_comercialmente') else 'no'}"
    return a.msg(text[:3500],rows)


def pregunta(a,ses):
    step=ses.get('paso')
    if step=='categoria':result=a.pedir_categoria()
    elif step=='linea':result=a.pedir_linea(a.buscar_categoria(ses['modelo']['categoria']))
    else:result=a.preguntar(step)
    if step=='fotos':
        result['texto']='Mandame hasta diez fotos y, si querés, un video de hasta 3 minutos. Elegí la portada y tocá Listo. Para archivos que Telegram no pueda entregar, usá Subir por la web.'
        n=len(ses['modelo'].get('fotos_tmp',[]))
        result['texto']+=f'\nGuardadas: {n} fotos'+(' y un video.' if ses['modelo'].get('video_tmp') else '.')
        result['botones']=a.en_filas([boton(('⭐ ' if i==ses['modelo'].get('portada',0) else '')+str(i+1),f'portada:{i}') for i in range(n)],5)
        result['botones'] += [[boton('✅ Listo','fotos_listo'),boton('🌐 Subir por la web','subir:carga')]]
        if n:result['botones'].append([boton('Quitar última foto','carga_quitar_foto')])
        if ses['modelo'].get('video_tmp'):result['botones'].append([boton('Quitar video','carga_quitar_video')])
    result['botones'] += [[boton('↩️ Volver','atras'),boton('💾 Guardar y salir','menu')]]
    return con_mosaico(a,result,ses['modelo']) if step=='fotos' else result


def editar_menu(a,edit):
    m=edit['propuesta']
    text=f"Editando {edit['codigo']} · {m['nombre']}\n\nLos cambios no se aplican a la tienda hasta Guardar cambios.\nPrecio: {a.precio_fmt(m['precio'])}\nDescripción: {m.get('descripcion','')}\nVariantes: {', '.join(m.get('variantes',[])) or 'sin variantes'}"
    return a.msg(text[:3000],[[boton('Nombre','edcampo:nombre'),boton('Descripción','edcampo:descripcion')],
        [boton('Precio','edcampo:precio'),boton('Variantes','edcampo:variantes')],
        [boton('Categoría y línea','edcampo:categoria'),boton('Fotos y video','ed_fotos')],
        [boton('💾 Guardar cambios','ed_guardar'),boton('Descartar cambios','ed_descartar')],
        [boton('Menú','menu')]])


def editar_fotos(a,edit):
    edit['campo']='media'
    photos=edit['fotos_tmp'];rows=[]
    for i in range(len(photos)):
        rows.append([boton(('⭐ ' if i==edit.get('portada',0) else '')+f'Portada {i+1}',f'ed_portada:{i}'),
                     boton(f'Quitar {i+1}',f'ed_quitar:{i}'),boton(f'Reemplazar {i+1}',f'ed_reemplazar:{i}')])
    rows += [[boton('Ordenar fotos','ed_orden'),boton('🌐 Subir archivos','subir:edicion')]]
    if edit.get('video_tmp'):rows.append([boton('Quitar video','ed_quitar_video')])
    rows += [[boton('Volver a datos','ed_volver'),boton('💾 Guardar cambios','ed_guardar')]]
    return con_mosaico(a,a.msg(f"{edit['codigo']}: {len(photos)} fotos y {'un video' if edit.get('video_tmp') else 'sin video'}.\nMandame más fotos o un video, elegí portada, reemplazá o reordená. Los cambios se aplican al guardar.",rows),edit)


def valid_texto(a,campo,text):
    if campo=='nombre':
        if not 1<=len(text)<=80:raise PublicacionError('El nombre debe tener entre 1 y 80 caracteres.')
        return text
    if campo=='descripcion':
        if not 3<=len(text)<=600:raise PublicacionError('La descripción debe tener entre 3 y 600 caracteres.')
        return text
    if campo=='precio':
        value=a.leer_precio(text)
        if value is None:raise PublicacionError('Escribí un precio entero mayor que cero, por ejemplo 1200.')
        return value
    if campo=='variantes':
        if text.lower() in ('ninguna','sin variantes','-'):return []
        values=[v.strip() for v in text.split(',') if v.strip()]
        if len(text)>1000 or len(values)>30 or any(len(v)>100 for v in values):raise PublicacionError('Acortá las variantes: hasta 30 opciones separadas por coma.')
        return values
    raise PublicacionError('Ese campo no se puede modificar aquí.')


def recibir_media(a,uid,message,target):
    obj=(message.get('photo') or [None])[-1] or message.get('video') or message.get('document') or message.get('animation')
    if not obj:return None
    if obj.get('file_size',0)>19*1024*1024:
        return 'grande'
    if not obj.get('file_id'):raise MediaError('No pude identificar el archivo. Usá Subir por la web.')
    dest=a.MEDIA/'tmp'/uid/'archivos'/(uuid.uuid4().hex+'.bin')
    try:
        a.descargar_de_telegram(obj['file_id'],dest)
        kind=validar_archivo(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise MediaError('No pude recibir ese archivo. Probá JPG/PNG/WebP, MP4/MOV/WebM o Subir por la web.') from None
    entry={'archivo':dest.relative_to(a.DATA).as_posix(),'file_id':obj['file_id'],'msg':message.get('message_id',0)}
    if kind=='foto':
        replace=target.pop('reemplazar',None)
        if replace is not None:
            if not 0<=replace<len(target['fotos_tmp']):raise MediaError('Esa foto cambió. Volvé a abrir Fotos.')
            target['fotos_tmp'][replace]=entry
        else:
            if len(target.setdefault('fotos_tmp',[]))>=10:
                dest.unlink(missing_ok=True);raise MediaError('El máximo es diez fotos. Quitá alguna antes de agregar más.')
            target['fotos_tmp'].append(entry)
    else:
        if target.get('reemplazar') is not None:raise MediaError('Para reemplazar una foto enviá una imagen.')
        target['video_tmp']=entry
    target['media_cambiada']=True
    return kind


def procesar(update,a):
    message=update.get('message');cb=update.get('callback_query');obj=message or cb
    if not obj:return []
    uid=str(obj.get('from',{}).get('id',''))
    if not a.USUARIOS_PERMITIDOS or uid not in a.USUARIOS_PERMITIDOS:
        return [a.msg('No tenés permiso para usar este bot privado.')]
    chat=message.get('chat',{}) if message else cb.get('message',{}).get('chat',{})
    if chat.get('type','private')!='private':return [a.msg('Usá este bot por mensaje privado.')]
    actions=[{'tipo':'responder_boton','callback_id':cb['id'],'texto':''}] if cb else []
    data=cb.get('data','') if cb else ''
    text=((message or {}).get('text') or '').strip()
    if len(text)>3000:return actions+[a.msg('El texto es demasiado largo. Mandame hasta 3000 caracteres.')]
    with a.Bloqueo():
        sessions=a.leer_json(a.SESIONES_FILE,{})
        ses=sessions.get(uid,{})
        def save():
            ses['actualizado']=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
            sessions[uid]=ses;a.escribir_json(a.SESIONES_FILE,sessions)
        def model(code):
            return next((m for m in a.leer_json(a.MODELOS_FILE,[]) if m.get('codigo')==code),None)
        def cargar_nuevo():
            for key in ('paso','modelo','carga_id','buscando','confirmacion'):ses.pop(key,None)
            ses.update({'paso':'categoria','foco':'carga','modelo':{},'carga_id':uuid.uuid4().hex,'chat_id':chat.get('id',int(uid))});save()
            return pregunta(a,ses)
        def confirm(action,code=None,rev=None):
            token=uuid.uuid4().hex[:12];ses['confirmacion']={'token':token,'accion':action,'codigo':code,'revision':rev};save()
            labels={'nuevo':'¿Descartar el avance de esta carga e iniciar otra?','ed_guardar':'¿Guardar estos cambios? Si está publicado, la ficha web se actualizará.',
                    'ed_descartar':'¿Descartar los cambios de esta edición? El producto guardado se conserva.',
                    'ocultar':'¿Ocultar este producto? Dejará de verse y de recomendarse, pero lo podés recuperar.',
                    'publicar':'¿Mostrar este producto en la tienda? Revisá antes sus datos y archivos.',
                    'descartar':'¿Archivar este borrador? Sus datos y fotos se conservan para poder recuperarlo.',
                    'recuperar':'¿Recuperar este modelo como borrador?',
                    'aprobar':'¿Confirmás que es un producto real, con datos comerciales revisados, para que Oli pueda recomendarlo cuando esté publicado?',
                    'desaprobar':'¿Quitar la aprobación para recomendaciones de Oli?'}
            return a.msg(labels[action]+(f'\nModelo: {code}' if code else ''),[[boton('✅ Confirmar','ok:'+token),boton('Cancelar','cancelar_confirmacion')]])
        def abrir_edicion(code,media=False):
            current=model(code)
            if not current or current.get('estado')=='descartado':return a.msg('Ese modelo no está disponible para editar.')
            if ses.get('edicion') and ses['edicion']['codigo']!=code:return a.msg('Tenés otra edición en curso. Guardala o descartala antes de abrir este modelo.',[[boton('Continuar edición','ed_volver')]])
            if not ses.get('edicion'):
                tg=current.get('fotos_tg',[])
                ses['edicion']={'id':uuid.uuid4().hex,'codigo':code,'revision':revision(current),'propuesta':copy.deepcopy(current),
                    'fotos_tmp':[{'publica':f,'file_id':tg[i] if i<len(tg) else None} for i,f in enumerate(current.get('fotos',[]))],
                    'video_tmp':{'publica':current['video']} if current.get('video') else None,'portada':0,'media_cambiada':False}
            ses.pop('buscando',None);ses['foco']='edicion'
            result=editar_fotos(a,ses['edicion']) if media else editar_menu(a,ses['edicion']);save();return result
        def subir(modo):
            if modo=='edicion':
                if not ses.get('edicion'):return a.msg('Primero abrí un modelo para editar.')
                nonce=ses['edicion']['id']
            else:
                if ses.get('paso')!='fotos':return a.msg('Primero completá los datos de la carga hasta llegar a Fotos.')
                ses.setdefault('carga_id',uuid.uuid4().hex);nonce=ses['carga_id'];save()
            url=oli_upload.crear(a,uid,modo,nonce)
            return a.msg('Abrí este enlace privado dentro de los próximos 15 minutos. Fotos hasta 50 MB, videos hasta 100 MB y 3 minutos. Al terminar, volvé a Telegram para revisar y guardar.',[[{'texto':'🌐 Subir fotos o video','url':url}]])

        try:
            command=text.split('@',1)[0]
            if data=='menu' or command in ('/menu','/start','/cancelar'):
                ses.pop('buscando',None);ses.pop('confirmacion',None);ses['foco']='menu';save();return actions+[menu(a,ses,obj.get('from',{}).get('first_name',''))]
            if data=='ayuda' or command=='/ayuda':
                return actions+[a.msg('Cargar modelo crea un borrador. Menú conserva el avance; Continuar carga lo retoma. Buscar permite editar datos, fotos y video. Guardar cambios pide confirmación. Publicar muestra la ficha; Ocultar la retira sin borrarla. Aprobar para Oli habilita recomendaciones solo si el modelo está publicado. Para archivos grandes usá el enlace privado del bot. No compartas ese enlace.',[[boton('Menú','menu')]])]
            if data=='cargar' or command=='/nuevo':
                if ses.get('edicion'):return actions+[a.msg('Terminá o descartá tu edición antes de iniciar otra carga.',[[boton('Continuar edición','ed_volver')]])]
                return actions+[confirm('nuevo') if ses.get('paso') else cargar_nuevo()]
            if data=='continuar' or command=='/continuar':
                ses.pop('buscando',None);ses['foco']='carga'
                if ses.get('paso'):
                    ses.setdefault('carga_id',uuid.uuid4().hex);save();return actions+[pregunta(a,ses)]
                return actions+[a.msg('No tenés una carga pendiente.'),menu(a,ses)]
            if data=='cancelar_confirmacion':
                ses.pop('confirmacion',None);save();return actions+[editar_menu(a,ses['edicion']) if ses.get('edicion') else menu(a,ses)]
            if data.startswith('ok:'):
                pending=ses.get('confirmacion',{})
                if pending.get('token')!=data[3:]:return actions+[a.msg('Esa confirmación ya no está activa. Reabrí la opción.')]
                action=pending['accion'];code=pending.get('codigo')
                if action=='nuevo':return actions+[cargar_nuevo()]
                if action=='ed_descartar':
                    ses.pop('edicion',None);ses.pop('confirmacion',None);save();return actions+[a.msg('Cambios descartados; el producto guardado se conserva.'),menu(a,ses)]
                models=a.leer_json(a.MODELOS_FILE,[]);current=model(code)
                if not current:raise PublicacionError('Ese modelo ya no está disponible.')
                if action=='ed_guardar':
                    edit=ses.get('edicion')
                    if not edit or edit['codigo']!=code or edit['id']!=pending.get('edicion_id'):raise PublicacionError('La edición cambió. Volvé a revisarla.')
                    if revision(current)!=edit['revision']:raise PublicacionError('Otra persona modificó el modelo. Descartá esta edición y volvé a abrirlo para ver los datos actuales.')
                    changes={k:edit['propuesta'].get(k) for k in ('nombre','descripcion','precio','variantes','categoria','linea')}
                    if edit.get('media_cambiada'):changes.update(materializar(a,code,edit['fotos_tmp'],edit.get('portada',0),edit.get('video_tmp')))
                    saved,_=aplicar_modelo(code,changes,models,edit['revision']);ses.pop('edicion',None)
                else:
                    changes={'publicar':{'estado':'publicado'},'ocultar':{'estado':'oculto'},'descartar':{'estado':'descartado'},'recuperar':{'estado':'borrador'},'aprobar':{'aprobado_comercialmente':True},'desaprobar':{'aprobado_comercialmente':False}}[action]
                    if action=='descartar' and current['estado']!='borrador':raise PublicacionError('Solo se pueden archivar borradores. Para un publicado usá Ocultar.')
                    if action=='recuperar' and current['estado']!='descartado':raise PublicacionError('Ese modelo no está archivado.')
                    saved,_=aplicar_modelo(code,changes,models,pending.get('revision'))
                ses.pop('confirmacion',None);save();return actions+[a.msg('✅ Cambio guardado.'),ficha(a,saved)]
            if data.startswith(('publicar:','ocultar:','descartar:','recuperar:','aprobar:')):
                action,code=data.split(':',1);current=model(code)
                if not current:return actions+[a.msg('No encontré ese modelo.')]
                if action=='aprobar' and current.get('aprobado_comercialmente'):action='desaprobar'
                return actions+[confirm(action,code,revision(current))]
            if data.startswith('borradores:') or command=='/borradores':
                page=int(data.split(':')[1]) if data.startswith('borradores:') and data.split(':')[1].isdigit() else 0
                return actions+[lista(a,'borrador',page)]
            if data.startswith('lista:'):
                _,state,page=data.split(':');return actions+[lista(a,state,int(page))]
            if data.startswith(('ver:','ver_borrador:')):
                current=model(data.split(':',1)[1]);return actions+[ficha(a,current) if current else a.msg('No encontré ese modelo.')]
            if data=='buscar' or command=='/buscar':
                ses['buscando']=True;save();return actions+[a.msg('Escribí el código o parte del nombre del modelo. La carga y la edición en curso se conservan.',[[boton('Menú','menu')]])]
            if ses.get('buscando') and message:
                ses.pop('buscando',None);ses['foco']='menu';save();return actions+[lista(a,'',consulta=text[:80])]
            if data.startswith(('editar:','media:')):return actions+[abrir_edicion(data.split(':')[1],data.startswith('media:'))]
            if data=='ed_volver' or data=='ed_fotos':
                if not ses.get('edicion'):return actions+[a.msg('No hay una edición en curso.')]
                ses['edicion'].pop('campo',None);ses['foco']='edicion'
                result=editar_fotos(a,ses['edicion']) if data=='ed_fotos' else editar_menu(a,ses['edicion']);save();return actions+[result]
            if data.startswith('subir:'):return actions+[subir(data.split(':')[1])]
            edit=ses.get('edicion')
            if edit and data in ('ed_guardar','ed_descartar'):
                result=confirm(data,edit['codigo'],edit['revision'])
                ses['confirmacion']['edicion_id']=edit['id'];save();return actions+[result]
            if edit and data.startswith('edcampo:'):
                field=data.split(':')[1];edit['campo']=field;save()
                if field=='categoria':
                    result=a.pedir_categoria()
                    for row in result['botones']:
                        for b in row:b['data']='ed_'+b['data']
                else:result=a.msg('Escribí el nuevo '+field+('. Para quitar variantes escribí ninguna.' if field=='variantes' else '.'))
                result['botones'].append([boton('Volver a la edición','ed_volver')]);return actions+[result]
            if edit and data.startswith('ed_cat:'):
                cat=a.buscar_categoria(data[7:])
                if not cat:raise PublicacionError('Elegí una categoría válida.')
                edit['propuesta']['categoria']=cat['slug'];edit['propuesta']['linea']=None
                if cat['lineas']:
                    edit['campo']='linea';result=a.pedir_linea(cat)
                    for row in result['botones']:
                        for b in row:b['data']='ed_'+b['data']
                else:edit.pop('campo',None);result=editar_menu(a,edit)
                save();return actions+[result]
            if edit and data.startswith('ed_lin:'):
                cat,line=a.buscar_linea(data[7:])
                if not line or cat['slug']!=edit['propuesta']['categoria']:raise PublicacionError('Elegí una línea de esa categoría.')
                edit['propuesta']['linea']=line['slug'];edit.pop('campo',None);save();return actions+[editar_menu(a,edit)]
            if edit and data.startswith(('ed_portada:','ed_quitar:','ed_reemplazar:')):
                op,index=data.split(':');i=int(index)
                if not 0<=i<len(edit['fotos_tmp']):raise PublicacionError('Esa foto ya no está. Volvé a abrir Fotos.')
                if op=='ed_portada':edit['portada']=i;edit['media_cambiada']=True
                elif op=='ed_quitar':
                    if len(edit['fotos_tmp'])==1:raise PublicacionError('El modelo necesita al menos una foto. Reemplazala antes de quitarla.')
                    edit['fotos_tmp'].pop(i);edit['portada']=0;edit['media_cambiada']=True
                else:
                    edit['reemplazar']=i;edit['campo']='media';save();return actions+[a.msg(f'Mandame la foto que reemplaza a la {i+1}.')]
                result=editar_fotos(a,edit);save();return actions+[result]
            if edit and data=='ed_orden':
                edit['campo']='orden';save();return actions+[a.msg('Escribí todos los números en el orden deseado, separados por coma. Por ejemplo: 3,1,2. La primera quedará de portada.')]
            if edit and data=='ed_quitar_video':
                edit['video_tmp']=None;edit['media_cambiada']=True;result=editar_fotos(a,edit);save();return actions+[result]
            if edit and message and edit.get('campo') and ses.get('foco','edicion')=='edicion':
                field=edit['campo']
                if field=='media':
                    kind=recibir_media(a,uid,message,edit)
                    if kind=='grande':return actions+[subir('edicion')]
                    if not kind:return actions+[a.msg('Mandame fotos/video o elegí una opción de Fotos.')]
                    save()
                    if message.get('media_group_id'):
                        resumen_album(a,uid,chat.get('id',int(uid)),'edicion');return actions
                    return actions+[editar_fotos(a,edit)]
                if field=='orden':
                    order=[int(x.strip())-1 for x in text.split(',')]
                    if sorted(order)!=list(range(len(edit['fotos_tmp']))):raise PublicacionError('Incluí cada número de foto una sola vez.')
                    edit['fotos_tmp']=[edit['fotos_tmp'][i] for i in order];edit['portada']=0;edit['media_cambiada']=True;result=editar_fotos(a,edit);save();return actions+[result]
                if field in ('categoria','linea'):return actions+[a.msg('Elegí la categoría o línea con los botones.')]
                edit['propuesta'][field]=valid_texto(a,field,text);edit.pop('campo',None);save();return actions+[editar_menu(a,edit)]
            if data=='atras' and ses.get('paso'):
                steps=['categoria']+(['linea'] if a.buscar_categoria(ses['modelo'].get('categoria','')) and a.buscar_categoria(ses['modelo']['categoria'])['lineas'] else [])+['nombre','descripcion','precio','variantes','fotos']
                ses['paso']=steps[max(0,steps.index(ses['paso'])-1)];save();return actions+[pregunta(a,ses)]
            if data.startswith('cat:') and ses.get('paso')=='categoria':
                cat=a.buscar_categoria(data[4:])
                if not cat:raise PublicacionError('Elegí una categoría válida.')
                ses['modelo']['categoria']=cat['slug'];ses['modelo']['linea']=None;ses['paso']='linea' if cat['lineas'] else 'nombre';save();return actions+[pregunta(a,ses)]
            if data.startswith('lin:') and ses.get('paso')=='linea':
                cat,line=a.buscar_linea(data[4:])
                if not line or cat['slug']!=ses['modelo']['categoria']:raise PublicacionError('Elegí una línea de esa categoría.')
                ses['modelo']['linea']=line['slug'];ses['paso']='nombre';save();return actions+[pregunta(a,ses)]
            if data=='saltar_variantes' and ses.get('paso')=='variantes':
                ses['modelo']['variantes']=[];ses['paso']='fotos';save();return actions+[pregunta(a,ses)]
            if data.startswith('portada:') and ses.get('paso')=='fotos':
                i=int(data.split(':')[1])
                if not 0<=i<len(ses['modelo'].get('fotos_tmp',[])):raise PublicacionError('Esa foto no está disponible.')
                ses['modelo']['portada']=i;save();return actions+[pregunta(a,ses)]
            if data in ('carga_quitar_foto','carga_quitar_video') and ses.get('paso')=='fotos':
                if data=='carga_quitar_video':ses['modelo'].pop('video_tmp',None)
                elif ses['modelo'].get('fotos_tmp'):ses['modelo']['fotos_tmp'].pop();ses['modelo']['portada']=0
                save();return actions+[pregunta(a,ses)]
            if data=='fotos_listo' and ses.get('paso')=='fotos':
                mod=ses['modelo'];photos=mod.get('fotos_tmp',[])
                if not photos:return actions+[a.msg('Falta al menos una foto.'),pregunta(a,ses)]
                models=a.leer_json(a.MODELOS_FILE,[]);cat=a.buscar_categoria(mod['categoria']);code=a.siguiente_codigo(models,cat['codigo'])
                nuevo={k:mod.get(k) for k in ('categoria','linea','nombre','descripcion','precio','variantes')}
                nuevo.update(materializar(a,code,photos,mod.get('portada',0),mod.get('video_tmp')))
                nuevo.update({'codigo':code,'estado':'borrador','aprobado_comercialmente':False,'creado':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')})
                validar(nuevo)
                models.append(nuevo);a.escribir_json(a.MODELOS_FILE,models)
                for key in ('paso','modelo','carga_id'):ses.pop(key,None)
                save();return actions+[a.msg('✅ Borrador guardado. Revisalo antes de publicarlo.'),ficha(a,nuevo),menu(a,ses)]
            if ses.get('paso')=='fotos' and message and ses.get('foco','carga')=='carga':
                kind=recibir_media(a,uid,message,ses['modelo'])
                if kind=='grande':return actions+[subir('carga')]
                if not kind:return actions+[pregunta(a,ses)]
                save()
                if message.get('media_group_id'):
                    resumen_album(a,uid,chat.get('id',int(uid)),'carga');return actions
                return actions+[pregunta(a,ses)]
            if ses.get('paso') in ('nombre','descripcion','precio','variantes') and message and ses.get('foco','carga')=='carga':
                field=ses['paso'];ses['modelo'][field]=valid_texto(a,field,text)
                ses['paso']={'nombre':'descripcion','descripcion':'precio','precio':'variantes','variantes':'fotos'}[field];save();return actions+[pregunta(a,ses)]
            if ses.get('paso') in ('categoria','linea'):return actions+[pregunta(a,ses)]
            return actions+[menu(a,ses,obj.get('from',{}).get('first_name',''))]
        except (PublicacionError,MediaError) as error:
            return actions+[a.msg(str(error),[[boton('Menú','menu')]])]
        except (ValueError,IndexError,KeyError):
            return actions+[a.msg('Esa opción cambió o el dato no es válido. Volvé a abrir el menú; tu avance se conserva.',[[boton('Menú','menu')]])]
