"""Resúmenes de álbum: colas, respuestas únicas y continuidad del mismo artículo."""
import copy,json,tempfile,threading,time,types,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import oli_eventos as eventos
import oli_gestion as gestion
import oli_api as api
import test_gestion


class AlbumTests(unittest.TestCase):
    def setUp(self):
        self.sent=Mock();self.state={'foco':'carga','paso':'fotos','carga_id':'carga-fixture','modelo':{'fotos_tmp':[]}}
        self.api=types.SimpleNamespace(BOT_TOKEN='fixture',ESPERA_ALBUM=.025,SESIONES_FILE=Path('/fixture'),Bloqueo=threading.RLock,leer_json=lambda *args:{'fixture':copy.deepcopy(self.state)},enviar_acciones=self.sent,registrar_error=Mock())
        self.threads=[];real=threading.Thread
        def factory(*args,**kwargs):
            t=real(*args,**kwargs);self.threads.append(t);return t
        self.patches=[patch.object(gestion.threading,'Thread',side_effect=factory),patch.object(gestion,'pregunta',side_effect=lambda a,s:{'fotos':len(s['modelo']['fotos_tmp'])})]
        for p in self.patches:p.start()

    def tearDown(self):
        with gestion._ALBUM_LOCK:
            gestion._ALBUMS.clear();gestion._MEDIA_PENDIENTE.clear();gestion._MEDIA_ACTIVIDAD.clear()
        for t in self.threads:t.join(timeout=1)
        for p in reversed(self.patches):p.stop()

    def schedule(self):gestion.resumen_album(self.api,'fixture',123,'carga','carga-fixture')
    def wait_summary(self):
        limit=time.monotonic()+2
        while not self.sent.call_count and time.monotonic()<limit:time.sleep(.01)
        self.assertEqual(self.sent.call_count,1)

    def test_album_lento_no_responde_hasta_terminar_todas_las_entradas(self):
        tokens=[gestion.comenzar_media('fixture') for _ in range(10)]
        for i,token in enumerate(tokens):
            self.state['modelo']['fotos_tmp'].append({'fixture':i});self.schedule();gestion.terminar_media('fixture',token)
            if i<9:
                time.sleep(.04);self.sent.assert_not_called()
        self.wait_summary();self.assertEqual(self.sent.call_args.args[1],[{'fotos':10}])

    def test_worker_revalida_nonce_despues_del_bloqueo(self):
        with eventos.LOCK:
            self.state['modelo']['fotos_tmp']=[{}];self.schedule();time.sleep(.06)
            self.state['modelo']['fotos_tmp']=[{},{}];self.schedule();time.sleep(.06)
        self.wait_summary();self.assertEqual(self.sent.call_args.args[1],[{'fotos':2}])
        time.sleep(.05);self.assertEqual(self.sent.call_count,1)

    def test_no_envia_resumen_de_una_carga_anterior(self):
        with eventos.LOCK:
            self.schedule();time.sleep(.06);self.state['carga_id']='otra-carga'
        for t in self.threads:t.join(timeout=1)
        self.sent.assert_not_called()

    def test_otra_persona_no_reinicia_el_album(self):
        token=gestion.comenzar_media('otra-persona');self.schedule();self.wait_summary()
        gestion.terminar_media('otra-persona',token)

    def test_se_libera_pendiente_en_actualizacion_repetida(self):
        fake=types.SimpleNamespace(USUARIOS_PERMITIDOS={'fixture'})
        update={'message':{'from':{'id':'fixture'},'photo':[{'file_id':'fixture'}]}}
        with patch.object(eventos,'_ejecutar',return_value={'duplicado':True}):
            result=eventos.ejecutar(fake,update)
        self.assertTrue(result['duplicado']);self.assertNotIn('fixture',gestion._MEDIA_PENDIENTE)


class ContinuidadFotosTests(test_gestion.GestionTests):
    def test_no_guarda_un_articulo_mientras_hay_fotos_en_cola(self):
        self.cb('cargar');self.cb('cat:velas');self.cb('lin:velas-numero')
        for text in ['Artículo único','Descripción del artículo','250','Sin variantes']:self.text(text)
        token=gestion.comenzar_media('123')
        try:
            result=self.cb('fotos_listo')
            self.assertIn('Todavía estoy recibiendo',str(result))
            self.assertEqual(self.sessions()['paso'],'fotos')
            self.assertEqual(self.catalogo_guardado(),self.models_original())
        finally:gestion.terminar_media('123',token)

    def test_fotos_reanudan_carga_desde_menu_y_no_responden_por_imagen(self):
        self.cb('cargar');self.cb('cat:velas');self.cb('lin:velas-numero')
        for text in ['Artículo único','Descripción del artículo','250','Sin variantes']:self.text(text)
        self.assertEqual(self.sessions()['paso'],'fotos');nonce=self.sessions()['carga_id'];self.cb('menu')
        payload={}
        from PIL import Image
        import io
        for i in range(3):
            f=io.BytesIO();Image.new('RGB',(80,90),(i*60,40,80)).save(f,'JPEG');payload[str(i)]=f.getvalue()
        def receive(fid,dest):dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload[fid])
        with patch.object(api,'descargar_de_telegram',side_effect=receive),patch.object(gestion,'resumen_album') as summary:
            for i in range(3):
                result=api.procesar({'message':{'from':{'id':123},'chat':{'id':123},'message_id':50+i,'photo':[{'file_id':str(i)}]}})
                self.assertEqual(result,[])
        self.assertEqual(self.sessions()['foco'],'carga');self.assertEqual(self.sessions()['carga_id'],nonce)
        self.assertEqual(len(self.sessions()['modelo']['fotos_tmp']),3);self.assertEqual(summary.call_count,3)


if __name__=='__main__':unittest.main()
