"""Flujos de gestión y límites, siempre con datos efímeros y sin Telegram real."""
import copy, io, json, sqlite3, subprocess, types
from unittest.mock import patch
from PIL import Image
import test_publicacion
import oli_api as api
import oli_publicacion as pub
import oli_eventos as eventos
import oli_upload as upload
import oli_media as media


class GestionTests(test_publicacion.PublicacionTests):
    def setUp(self):
        super().setUp()
        p=patch.object(api,'MEDIA',self.data/'media');p.start();self.addCleanup(p.stop)
        Image.new('RGB',(64,80),'pink').save(self.data/'media/modelos/VEL-0004/1.webp','WEBP')

    def text(self,t):
        return api.procesar({'message':{'from':{'id':123},'chat':{'id':123,'type':'private'},'message_id':99,'text':t}})

    def cb(self,s):return api.procesar(self.callback(s))
    def sessions(self):return json.loads(api.SESIONES_FILE.read_text())['123']
    def catalogo_guardado(self):return json.loads(self.file.read_text())
    def accept(self):return self.cb(self.sessions()['confirmacion']['token'].join(['ok:','']))

    def test_carga_se_conserva_y_nueva_requiere_confirmar(self):
        self.cb('cargar');self.cb('cat:velas');self.cb('lin:velas-numero');self.text('Mi vela')
        before=self.sessions()['modelo'];self.cb('menu');self.text('No modificar')
        self.assertEqual(self.sessions()['modelo'],before)
        self.cb('continuar');self.assertEqual(self.sessions()['paso'],'descripcion')
        self.cb('cargar');self.assertEqual(self.sessions()['modelo'],before)
        self.accept();self.assertEqual(self.sessions()['paso'],'categoria')

    def test_edicion_aislada_conflicto_y_cancelacion(self):
        self.cb('editar:VEL-0004');self.cb('edcampo:nombre');self.text('Otro nombre')
        self.assertEqual(self.catalogo_guardado(),self.models_original())
        self.cb('ed_guardar');self.accept();self.assertEqual(self.catalogo_guardado()[0]['nombre'],'Otro nombre')
        self.cb('editar:VEL-0004');self.cb('edcampo:precio');self.text('2400')
        changed=self.catalogo_guardado();changed[0]['descripcion']='Cambio de otra persona';pub.escribir_json(self.file,changed)
        self.cb('ed_guardar');result=self.accept();self.assertIn('Otra persona',str(result))
        self.assertEqual(self.catalogo_guardado()[0]['precio'],1200)
        self.cb('ed_descartar');self.accept();self.assertNotIn('edicion',self.sessions())

    def models_original(self):return [self.modelo]

    def test_ocultar_republicar_y_redireccion_nombre(self):
        self.confirmar('publicar:VEL-0004')
        self.confirmar('ocultar:VEL-0004');self.assertFalse((self.site/'modelos/vel-0004-grande-azul/index.html').exists())
        self.confirmar('publicar:VEL-0004');self.assertTrue((self.site/'modelos/vel-0004-grande-azul/index.html').exists())
        self.cb('editar:VEL-0004');self.cb('edcampo:nombre');self.text('Vela nueva');self.cb('ed_guardar');self.accept()
        self.assertIn('/modelos/vel-0004-vela-nueva',(self.site/'modelos/vel-0004-grande-azul/index.html').read_text())
        self.assertTrue((self.site/'modelos/vel-0004-vela-nueva/index.html').exists())

    def test_archivar_y_recuperar_sin_borrar_archivos(self):
        self.confirmar('descartar:VEL-0004');self.assertEqual(self.catalogo_guardado()[0]['estado'],'descartado')
        self.confirmar('recuperar:VEL-0004');self.assertEqual(self.catalogo_guardado()[0]['estado'],'borrador')
        self.assertTrue((self.data/'media/modelos/VEL-0004/1.webp').exists())

    def test_fotos_portada_orden_reemplazo_y_version(self):
        self.cb('media:VEL-0004')
        photo=self.data/'segunda.png';Image.new('RGB',(80,60),'blue').save(photo)
        def receive(fid,dest):dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(photo.read_bytes())
        with patch.object(api,'descargar_de_telegram',side_effect=receive):
            update={'message':{'from':{'id':123},'chat':{'id':123},'photo':[{'file_id':'fixture','file_size':200}],'message_id':11}}
            api.procesar(update);self.cb('ed_reemplazar:0');api.procesar(update)
        self.assertEqual(len(self.sessions()['edicion']['fotos_tmp']),2)
        self.cb('ed_orden');self.text('2,1');self.cb('ed_guardar');self.accept()
        saved=self.catalogo_guardado()[0];self.assertEqual(len(saved['fotos']),2);self.assertIn('/v-',saved['fotos'][0])
        self.assertTrue((self.data/'media/modelos/VEL-0004/1.webp').exists())
        self.cb('media:VEL-0004');self.cb('ed_quitar:0');self.cb('ed_quitar:0')
        self.assertEqual(len(self.sessions()['edicion']['fotos_tmp']),1)

    def test_duplicado_y_envio_incierto_no_repite_mutacion(self):
        update=self.callback('cargar');update['update_id']=1
        with patch.object(api,'BOT_TOKEN','fixture'),patch.object(api,'enviar_acciones',side_effect=RuntimeError('simulado')):
            first=eventos.ejecutar(api,update);nonce=self.sessions()['carga_id'];second=eventos.ejecutar(api,update)
        self.assertEqual(first['error'],'envio_incierto');self.assertTrue(second['duplicado']);self.assertEqual(self.sessions()['carga_id'],nonce)

    def test_precio_no_finito_y_medio_falso(self):
        for v in ['nan','inf','-1','0','1.5']:self.assertIsNone(api.leer_precio(v))
        file=self.data/'falso.mp4';file.write_bytes(b'not a photo or video')
        with self.assertRaises(media.MediaError):media.validar_archivo(file)

    def test_ruta_de_foto_no_puede_saltar_a_otro_modelo(self):
        other=self.data/'media/modelos/ACC-9999';other.mkdir();Image.new('RGB',(32,32),'blue').save(other/'1.webp')
        model=copy.deepcopy(self.modelo);model['fotos']=['/media/modelos/VEL-0004/../ACC-9999/1.webp']
        with self.assertRaises(pub.PublicacionError):pub.validar(model)

    def test_fallo_al_ocultar_conserva_ficha_publicada(self):
        self.confirmar('publicar:VEL-0004');before=self.file.read_bytes();release=self.site.resolve()
        with patch.object(pub.subprocess,'run',return_value=types.SimpleNamespace(returncode=1)):
            with self.assertRaises(pub.PublicacionError):pub.aplicar_modelo('VEL-0004',{'estado':'oculto'},self.catalogo_guardado())
        self.assertEqual(self.file.read_bytes(),before);self.assertEqual(self.site.resolve(),release)
        self.assertTrue((self.site/'modelos/vel-0004-grande-azul/index.html').exists())

    def test_subida_vinculada_a_sesion_origen_y_expiracion(self):
        self.cb('media:VEL-0004');nonce=self.sessions()['edicion']['id']
        token=upload.crear(api,'123','edicion',nonce).split('#')[1]
        b=io.BytesIO();Image.new('RGB',(64,64),'pink').save(b,'PNG');body=b.getvalue()
        handler=types.SimpleNamespace(headers={'Origin':api.SITE_URL,'X-Oli-Upload':token,'Content-Length':str(len(body))},rfile=io.BytesIO(body))
        self.assertEqual(upload.manejar(handler,api,'/api/subida')['fotos'],2)
        handler.rfile=io.BytesIO(body)
        self.assertTrue(upload.manejar(handler,api,'/api/subida')['duplicado'])
        self.assertEqual(len(self.sessions()['edicion']['fotos_tmp']),2)
        handler.headers['Origin']='https://evil.invalid'
        with self.assertRaises(upload.UploadError):upload.manejar(handler,api,'/api/subida')
        handler.headers['Origin']=api.SITE_URL
        self.cb('ed_descartar');self.accept()
        with self.assertRaises(upload.UploadError):upload.manejar(handler,api,'/api/subida')
        with patch.object(upload.time,'time',return_value=9999999999):
            with self.assertRaises(upload.UploadError):upload.validar_token(api,token)

    def test_video_normalizado_y_renderizado(self):
        video=self.data/'media/tmp/video.mp4';video.parent.mkdir(parents=True,exist_ok=True)
        r=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=pink:s=160x120:d=1','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-metadata','title=Fixture privado',str(video)],capture_output=True)
        self.assertEqual(r.returncode,0)
        files=media.materializar(api,'VEL-0004',[{'publica':self.modelo['fotos'][0]}],video={'archivo':'media/tmp/video.mp4'})
        self.assertTrue((self.data/files['video'].lstrip('/')).exists())
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format_tags=title','-of','json',str(self.data/files['video'].lstrip('/'))],capture_output=True)
        self.assertNotIn('Fixture privado',probe.stdout.decode())
        pub.aplicar_modelo('VEL-0004',dict(files,estado='publicado'),self.catalogo_guardado())
        html=(self.site/'modelos/vel-0004-grande-azul/index.html').read_text()
        self.assertIn('<video controls playsinline preload="metadata"',html)
        self.assertIn(files['imagen_social'],html)
