"""Pruebas de fallos e integración completa sin datos, cuentas ni mensajes reales."""
import copy,io,json,threading,time,types,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image
import oli_api as api
import oli_eventos as eventos
import oli_gestion as gestion
import oli_upload as upload
import test_gestion
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
import urllib.request


class SolidezTests(test_gestion.GestionTests):
    def test_http_album_concurrente_reintento_resumen_guardar_y_publicar(self):
        photos={};sent=[];tries={};mutex=threading.Lock()
        for i in range(10):
            out=io.BytesIO();Image.new('RGB',(100,120),(i*20,70,110)).save(out,'JPEG');photos[str(i)]=out.getvalue()
        class TelegramFixture(BaseHTTPRequestHandler):
            def reply(self,status,body,kind='application/json'):
                self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):
                method=self.path.rsplit('/',1)[-1];raw=self.rfile.read(int(self.headers['Content-Length']))
                if method=='getFile':
                    fid=json.loads(raw)['file_id']
                    with mutex:tries[fid]=tries.get(fid,0)+1;attempt=tries[fid]
                    if fid=='0' and attempt==1:return self.reply(503,b'{"ok":false}')
                    body={'ok':True,'result':{'file_path':'photos/file_'+fid+'.jpg'}}
                else:
                    with mutex:sent.append(method)
                    body={'ok':True,'result':{'message_id':1}}
                self.reply(200,json.dumps(body).encode())
            def do_GET(self):
                fid=self.path.rsplit('file_',1)[-1].split('.')[0];time.sleep(.05)
                self.reply(200,photos[fid],'image/jpeg')
            def log_message(self,*args):pass
        fake=ThreadingHTTPServer(('127.0.0.1',0),TelegramFixture)
        backend=ThreadingHTTPServer(('127.0.0.1',0),api.Handler)
        threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in [fake,backend]]
        for t in threads:t.start()
        seq=iter(range(2000,2100))
        def post(update):
            request=urllib.request.Request('http://127.0.0.1:'+str(backend.server_port)+'/api/bot',data=json.dumps(update).encode(),headers={'X-Oli-Key':'fixture-api','Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=10) as r:return json.load(r)
        def cb(data):
            update=self.callback(data);update['update_id']=next(seq);return post(update)
        def text(value):
            return post({'update_id':next(seq),'message':{'from':{'id':123},'chat':{'id':123},'message_id':next(seq),'text':value}})
        try:
            with patch.object(api,'BOT_TOKEN','fixture'),patch.object(api,'API_KEY','fixture-api'),patch.object(api,'TELEGRAM_URL','http://127.0.0.1:'+str(fake.server_port)),patch.object(api,'ESPERA_ALBUM',.04):
                cb('cargar');cb('cat:velas');cb('lin:velas-numero')
                for value in ['Producto HTTP','Descripción HTTP','350','Sin variantes']:text(value)
                with ThreadPoolExecutor(max_workers=10) as pool:
                    updates=[{'update_id':3000+i,'message':{'from':{'id':123},'chat':{'id':123},'photo':[{'file_id':str(i)}],'message_id':3100+i,'media_group_id':'fixture-album'}} for i in range(10)]
                    results=list(pool.map(post,updates))
                self.assertTrue(all(r.get('procesado') for r in results));self.assertEqual(len(self.sessions()['modelo']['fotos_tmp']),10)
                limit=time.monotonic()+3
                while sent.count('sendPhoto')<1 and time.monotonic()<limit:time.sleep(.01)
                self.assertEqual(sent.count('sendPhoto'),1);self.assertEqual(tries['0'],2)
                self.assertTrue(post(updates[0])['duplicado']);self.assertEqual(len(self.sessions()['modelo']['fotos_tmp']),10)
                ses=self.sessions();view=gestion.pregunta(api,ses)
                button=next(b['data'] for row in view['botones'] for b in row if b.get('data','').startswith('fotos_listo~'))
                cb(button);model=self.catalogo_guardado()[-1];self.assertEqual(model['estado'],'borrador')
                self.assertEqual(model['fotos_tg'],[str(i) for i in range(10)])
                cb('publicar:'+model['codigo']);cb('ok:'+self.sessions()['confirmacion']['token'])
                self.assertEqual(self.catalogo_guardado()[-1]['estado'],'publicado')
        finally:
            for server in [backend,fake]:server.shutdown();server.server_close()
            for t in threads:t.join(2)
    def carga(self,n=1):
        self.cb('cargar');self.cb('cat:velas');self.cb('lin:velas-numero')
        for text in ['Artículo único','Descripción válida','350','Sin variantes']:self.text(text)
        def receive(fid,dest):
            dest.parent.mkdir(parents=True,exist_ok=True)
            Image.new('RGB',(80,90),(int(fid)*25,50,90)).save(dest,'JPEG')
        with patch.object(api,'descargar_de_telegram',side_effect=receive):
            for i in range(n):api.procesar({'message':{'from':{'id':123},'chat':{'id':123},'photo':[{'file_id':str(i)}],'message_id':50+i}})

    def raw(self,data):return api.procesar(self.callback(data))
    def button(self,data):
        ses=self.sessions();target=ses.get('edicion',{}) if data.startswith('ed_') else ses.get('modelo',{})
        gen=target.get('id') if data.startswith('ed_') else ses.get('carga_id')
        return data+'~'+gestion.firma_fotos(target,gen)

    def test_boton_de_otra_carga_no_guarda_la_actual(self):
        self.carga();old=self.button('fotos_listo');self.cb('cargar');self.accept()
        self.cb('cat:velas');self.cb('lin:velas-numero')
        for text in ['Artículo nuevo','Descripción nueva','500','Sin variantes']:self.text(text)
        before=self.sessions();result=self.raw(old)
        self.assertIn('vista anterior',str(result));self.assertEqual(before,self.sessions());self.assertEqual(len(self.catalogo_guardado()),1)

    def test_boton_de_orden_anterior_no_quita_foto_equivocada(self):
        self.cb('media:VEL-0004');old=self.button('ed_quitar:0')
        ses=self.sessions();ses['edicion']['fotos_tmp'].append(copy.deepcopy(ses['edicion']['fotos_tmp'][0]));api.escribir_json(api.SESIONES_FILE,{'123':ses})
        result=self.raw(old);self.assertIn('vista anterior',str(result));self.assertEqual(len(self.sessions()['edicion']['fotos_tmp']),2)

    def test_fallo_despues_de_guardar_no_duplica_borrador_al_reintentar(self):
        self.carga();real=api.escribir_json;failed=[]
        def write(path,data):
            if Path(path)==api.SESIONES_FILE and 'paso' not in data.get('123',{}) and not failed:
                failed.append(True);raise OSError('fallo de disco simulado')
            return real(path,data)
        with patch.object(api,'escribir_json',side_effect=write):self.cb('fotos_listo')
        self.assertEqual(len(self.catalogo_guardado()),2);self.assertEqual(self.sessions()['paso'],'fotos')
        self.cb('fotos_listo');self.assertEqual(len(self.catalogo_guardado()),2);self.assertNotIn('paso',self.sessions())

    def test_recorrido_carga_album_publicacion_edicion_y_ocultar(self):
        self.carga(10);self.cb('portada:4');self.cb('fotos_listo')
        model=self.catalogo_guardado()[-1];code=model['codigo'];self.assertEqual(model['estado'],'borrador');self.assertEqual(len(model['fotos']),10)
        self.confirmar('publicar:'+code);self.cb('editar:'+code);self.cb('edcampo:precio');self.text('450');self.cb('ed_guardar');self.accept()
        self.assertEqual(self.catalogo_guardado()[-1]['precio'],450)
        self.confirmar('ocultar:'+code);self.assertEqual(self.catalogo_guardado()[-1]['estado'],'oculto')
        self.confirmar('publicar:'+code);self.assertEqual(self.catalogo_guardado()[-1]['estado'],'publicado')

    def test_recupera_edicion_si_falla_cerrar_sesion_despues_de_guardar(self):
        self.cb('editar:VEL-0004');self.cb('edcampo:precio');self.text('800');self.cb('ed_guardar')
        real=api.escribir_json;failed=[]
        def write(path,data):
            if Path(path)==api.SESIONES_FILE and 'edicion' not in data.get('123',{}) and not failed:
                failed.append(True);raise OSError('fallo de cierre simulado')
            return real(path,data)
        with patch.object(api,'escribir_json',side_effect=write):self.accept()
        self.assertEqual(self.catalogo_guardado()[0]['precio'],800);self.assertIn('edicion',self.sessions())
        result=self.accept();self.assertIn('ya estaba guardado',str(result));self.assertNotIn('edicion',self.sessions())

    def upload_handler(self,data,token):return types.SimpleNamespace(headers={'Origin':api.SITE_URL,'X-Oli-Upload':token,'Content-Length':str(len(data))},rfile=io.BytesIO(data))
    def enlace(self):
        self.cb('media:VEL-0004');edit=self.sessions()['edicion'];return upload.crear(api,'123','edicion',edit['id']).split('#')[1]

    def test_subida_web_libera_turno_si_falla_crear_carpeta(self):
        token=self.enlace();handler=self.upload_handler(b'fixture',token);original=Path.mkdir
        def fail(path,*args,**kwargs):
            if path.name=='subidas':raise OSError('sin espacio simulado')
            return original(path,*args,**kwargs)
        with patch.object(Path,'mkdir',new=fail):
            with self.assertRaises(OSError):upload.manejar(handler,api,'/api/subida')
        self.assertTrue(upload.SLOT.acquire(blocking=False));upload.SLOT.release();self.assertNotIn('123',gestion._MEDIA_PENDIENTE)

    def test_subida_web_reemplaza_foto_elegida_en_lugar_de_agregar(self):
        token=self.enlace();self.cb('ed_reemplazar:0');out=io.BytesIO();Image.new('RGB',(60,80),'orange').save(out,'JPEG')
        result=upload.manejar(self.upload_handler(out.getvalue(),token),api,'/api/subida')
        self.assertEqual(result['fotos'],1);self.assertNotIn('reemplazar',self.sessions()['edicion'])

    def test_finalizar_web_espera_las_transferencias(self):
        token=self.enlace();pending=gestion.comenzar_media('123')
        try:
            with self.assertRaises(upload.UploadError) as caught:upload.manejar(self.upload_handler(b'',token),api,'/api/subida/finalizar')
            self.assertEqual(caught.exception.status,409)
        finally:gestion.terminar_media('123',pending)

    def test_descarga_lenta_no_bloquea_menu_y_no_contamina_otra_carga(self):
        self.carga();started=threading.Event();finish=threading.Event();result=[]
        def download(fid,dest):
            started.set();self.assertTrue(finish.wait(3));dest.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(40,40),'green').save(dest,'JPEG')
        update={'update_id':991,'message':{'from':{'id':123},'chat':{'id':123},'photo':[{'file_id':'fixture-lento'}],'message_id':992}}
        with patch.object(api,'BOT_TOKEN','fixture'),patch.object(api,'descargar_de_telegram',side_effect=download),patch.object(api,'enviar_acciones'):
            thread=threading.Thread(target=lambda:result.append(eventos.ejecutar(api,update,enviar=False)));thread.start()
            self.assertTrue(started.wait(1))
            # Se usa el circuito completo, que adquiere el mismo bloqueo que cualquier mensaje real.
            menu=self.callback('menu');menu['update_id']=993
            before=time.monotonic();eventos.ejecutar(api,menu,enviar=False)
            self.assertLess(time.monotonic()-before,1)
            self.cb('cargar');self.accept();other=self.sessions()['carga_id'];finish.set();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(self.sessions()['carga_id'],other);self.assertEqual(self.sessions()['paso'],'categoria');self.assertEqual(len(self.catalogo_guardado()),1)

    def test_precarga_se_consume_una_vez_y_respeta_el_articulo(self):
        self.carga();photo=io.BytesIO();Image.new('RGB',(50,60),'yellow').save(photo,'JPEG')
        update={'update_id':994,'message':{'from':{'id':123},'chat':{'id':123},'photo':[{'file_id':'fixture-nueva'}],'message_id':995}}
        with patch.object(api,'BOT_TOKEN','fixture'),patch.object(api,'telegram',return_value={'ok':True,'result':{'file_path':'photos/file_1.jpg'}}) as get,patch.object(api.urllib.request,'urlopen',return_value=io.BytesIO(photo.getvalue())),patch.object(gestion,'resumen_album'):
            result=eventos.ejecutar(api,update,enviar=False)
        self.assertTrue(result['procesado']);self.assertEqual(get.call_count,1)
        self.assertEqual(len(self.sessions()['modelo']['fotos_tmp']),2)
        self.assertFalse(list((api.MEDIA/'tmp/123/precargas').glob('*.bin')))


if __name__=='__main__':unittest.main()
