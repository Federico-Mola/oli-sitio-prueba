"""Recepción de fotos: sin Telegram real, mensajes, claves o datos de producción."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile
from PIL import Image
import oli_api as api
import oli_gestion as gestion
from oli_media import MediaError


class RecepcionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.dest=self.data/'foto.bin'
        for name,value in [('DATA',self.data),('MEDIA',self.data/'media')]:
            p=patch.object(api,name,value);p.start();self.addCleanup(p.stop)
        self.payload=io.BytesIO();Image.new('RGB',(90,120),'pink').save(self.payload,'JPEG');self.photo=self.payload.getvalue()
        p=patch.object(api.time,'sleep');self.sleep=p.start();self.addCleanup(p.stop)

    def response(self,body=None):return io.BytesIO(self.photo if body is None else body)
    def info(self):return {'ok':True,'result':{'file_path':'photos/file_1.jpg'}}
    def message(self,fid='fixture',unique='unique'):
        return {'message_id':1,'photo':[{'file_id':fid,'file_unique_id':unique,'file_size':len(self.photo)}]}

    def test_reintenta_getfile_timeout_y_descarga(self):
        with patch.object(api,'telegram',side_effect=[TimeoutError('no mostrar URL'),self.info()]) as get,patch.object(api.urllib.request,'urlopen',return_value=self.response()):
            api.descargar_de_telegram('fixture',self.dest)
        self.assertEqual(self.dest.read_bytes(),self.photo);self.assertEqual(get.call_count,2)
        self.assertEqual(get.call_args.kwargs['timeout'],7)

    def test_reintenta_transferencia_cortada(self):
        with patch.object(api,'telegram',return_value=self.info()),patch.object(api.urllib.request,'urlopen',side_effect=[ConnectionResetError(),self.response()]):
            api.descargar_de_telegram('fixture',self.dest)
        self.assertEqual(self.dest.read_bytes(),self.photo)

    def test_agota_reintentos_sin_filtrar_claves_ni_archivo_parcial(self):
        with patch.object(api,'telegram',side_effect=urllib.error.URLError('https://secreto.invalid/botCLAVE_PRIVADA')) as get:
            with self.assertRaises(api.DescargaTelegramError) as caught:api.descargar_de_telegram('fixture',self.dest)
        self.assertEqual(get.call_count,3);self.assertNotIn('CLAVE_PRIVADA',str(caught.exception));self.assertNotIn('JPG',str(caught.exception));self.assertFalse(self.dest.exists())

    def test_respeta_429_y_rechaza_400_sin_reintentar(self):
        error=urllib.error.HTTPError('https://privada.invalid',429,'limit',{},io.BytesIO(json.dumps({'parameters':{'retry_after':1}}).encode()))
        with patch.object(api,'telegram',side_effect=[error,self.info()]),patch.object(api.urllib.request,'urlopen',return_value=self.response()):api.descargar_de_telegram('fixture',self.dest)
        self.sleep.assert_called_with(1)
        error=urllib.error.HTTPError('https://privada.invalid',400,'bad',{},io.BytesIO(b'{}'))
        with patch.object(api,'telegram',side_effect=error) as get:
            with self.assertRaises(api.DescargaTelegramError):api.descargar_de_telegram('fixture',self.dest)
        self.assertEqual(get.call_count,1)

    def test_archivo_supera_descarga_ofrece_web(self):
        error=urllib.error.HTTPError('https://privada.invalid',400,'bad',{},io.BytesIO(b'{"description":"Bad Request: file is too big"}'))
        with patch.object(api,'telegram',side_effect=error):
            with self.assertRaises(api.DescargaTelegramError) as caught:api.descargar_de_telegram('fixture',self.dest)
        self.assertTrue(caught.exception.grande)
        with patch.object(api,'descargar_de_telegram',side_effect=caught.exception),patch.object(api,'registrar_error'):
            self.assertEqual(gestion.recibir_media(api,'fixture',self.message(),{}),'grande')

    def test_error_de_red_conserva_carga_y_no_culpa_formato(self):
        target={'fotos_tmp':[],'nombre':'Mi producto'};before=copy.deepcopy(target)
        error=api.DescargaTelegramError('Telegram demoró. Tu avance está guardado.','descarga_telegram_temporal')
        with patch.object(api,'descargar_de_telegram',side_effect=error),patch.object(api,'registrar_error') as log:
            with self.assertRaises(MediaError) as caught:gestion.recibir_media(api,'fixture',self.message(),target)
        self.assertEqual(target,before);self.assertNotIn('JPG',str(caught.exception));log.assert_called_once_with('descarga_telegram_temporal')

    def receive(self,fid,dest):dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(self.photo)

    def test_reenvio_no_duplica_por_id_ni_contenido(self):
        target={}
        with patch.object(api,'descargar_de_telegram',side_effect=self.receive) as download:
            gestion.recibir_media(api,'fixture',self.message(),target)
            gestion.recibir_media(api,'fixture',self.message(),target)
            gestion.recibir_media(api,'fixture',self.message('otro','otro'),target)
        self.assertEqual(len(target['fotos_tmp']),1);self.assertEqual(download.call_count,2)
        self.assertEqual(len(list((api.MEDIA/'tmp/fixture/archivos').glob('*.bin'))),1)

    def test_formato_invalido_se_distingue_de_error_red(self):
        def bad(fid,dest):dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b'invalid')
        with patch.object(api,'descargar_de_telegram',side_effect=bad),patch.object(api,'registrar_error') as log:
            with self.assertRaises(MediaError) as caught:gestion.recibir_media(api,'fixture',self.message(),{})
        log.assert_called_once_with('formato_archivo_telegram');self.assertIn('JPG',str(caught.exception))

    def test_reenvio_album_completa_diez_sin_perder_las_tres_previas(self):
        payloads={}
        for i in range(10):
            out=io.BytesIO();Image.new('RGB',(90,120),(i*20,30,90)).save(out,'JPEG');payloads[str(i)]=out.getvalue()
        def receive(fid,dest):dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payloads[fid])
        target={}
        with patch.object(api,'descargar_de_telegram',side_effect=receive):
            for i in range(3):gestion.recibir_media(api,'fixture',self.message(str(i),str(i)),target)
            first=copy.deepcopy(target['fotos_tmp'])
            for i in range(10):gestion.recibir_media(api,'fixture',self.message(str(i),str(i)),target)
        self.assertEqual(len(target['fotos_tmp']),10);self.assertEqual(target['fotos_tmp'][:3],first)

    @unittest.skipUnless(os.environ.get('OLI_FOTOS_ZIP'),'ZIP de diagnóstico opcional, nunca incluido en el repositorio')
    def test_diez_fotos_aportadas_por_propietario(self):
        with zipfile.ZipFile(os.environ['OLI_FOTOS_ZIP']) as archive:
            files={str(i):archive.read(info) for i,info in enumerate(archive.infolist()) if not info.is_dir()}
        self.assertEqual(len(files),10)
        def receive(fid,dest):dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(files[fid])
        target={}
        with patch.object(api,'descargar_de_telegram',side_effect=receive):
            for fid in files:gestion.recibir_media(api,'fixture',self.message(fid,fid),target)
        self.assertEqual(len(target['fotos_tmp']),10)


if __name__=='__main__':unittest.main()
