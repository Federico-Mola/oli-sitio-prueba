"""Pruebas aisladas: no usan Telegram, credenciales ni datos de producción."""
import copy
import json
import pathlib
import tempfile
import types
import unittest
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import oli_publicacion as pub
import oli_api as api


class PublicacionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.site = self.root / "html"
        initial = self.root / "html.releases/inicial"
        initial.mkdir(parents=True)
        (initial / "index.html").write_text("SITIO ANTERIOR")
        self.site.symlink_to(initial, target_is_directory=True)
        folder = self.data / "media/modelos/VEL-0004"
        folder.mkdir(parents=True)
        (folder / "1.webp").write_bytes(b"test-image")
        self.modelo = dict(codigo="VEL-0004", categoria="velas", linea="velas-numero",
                           nombre="Grande azul", descripcion="Vela pintada de prueba", precio=1200,
                           variantes=[], fotos=["/media/modelos/VEL-0004/1.webp"], estado="borrador")
        self.models = [copy.deepcopy(self.modelo)]
        self.file = self.data / "modelos.json"
        self.file.write_text(json.dumps(self.models))
        for obj, name, value in [(pub, "DATA", self.data), (pub, "SITE", self.site),
                                 (pub, "SITE_URL", "https://www.latienditadeoli.com"),
                                 (api, "DATA", self.data), (api, "MODELOS_FILE", self.file),
                                 (api, "SESIONES_FILE", self.data / "sesiones.json"),
                                 (api, "LOCK_FILE", self.data / ".lock"),
                                 (api, "USUARIOS_PERMITIDOS", {"123"})]:
            p = patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)

    def callback(self, data, user=123):
        return {"callback_query": {"id": "test", "from": {"id": user}, "data": data,
                                   "message": {"message_id": 1, "chat": {"id": user}}}}

    def test_publica_y_genera_modelo_y_linea(self):
        old = self.site.resolve()
        m, url = pub.publicar("VEL-0004", self.models)
        self.assertEqual(m["estado"], "publicado")
        self.assertEqual(json.loads(self.file.read_text())[0]["estado"], "publicado")
        self.assertNotEqual(self.site.resolve(), old)
        self.assertTrue((old / "index.html").exists())
        self.assertIn("VEL-0004", (self.site / "modelos/vel-0004-grande-azul/index.html").read_text())
        self.assertIn("VEL-0004", (self.site / "lineas-de-producto/velas-numero/index.html").read_text())
        self.assertEqual(url, "https://www.latienditadeoli.com/modelos/vel-0004-grande-azul")

    def test_segundo_click_no_duplica_ni_regenera(self):
        pub.publicar("VEL-0004", self.models)
        current = self.site.resolve()
        with patch.object(pub.subprocess, "run", side_effect=AssertionError("No debe regenerar")):
            pub.publicar("VEL-0004", json.loads(self.file.read_text()))
        self.assertEqual(self.site.resolve(), current)
        self.assertEqual(len(json.loads(self.file.read_text())), 1)

    def test_fallo_generador_conserva_borrador_y_sitio(self):
        with patch.object(pub.subprocess, "run", return_value=types.SimpleNamespace(returncode=1)):
            with self.assertRaises(pub.PublicacionError):
                pub.publicar("VEL-0004", self.models)
        self.assertEqual(json.loads(self.file.read_text()), self.models)
        self.assertEqual((self.site / "index.html").read_text(), "SITIO ANTERIOR")
        self.assertEqual(list(self.data.glob(".oli-publicar-*")), [])

    def test_fallo_activacion_restaura_json(self):
        replace = pub.os.replace
        def fail_link(src, dst):
            if pathlib.Path(dst) == self.site:
                raise OSError("simulated activation error")
            return replace(src, dst)
        with patch.object(pub.os, "replace", side_effect=fail_link):
            with self.assertRaises(OSError):
                pub.publicar("VEL-0004", self.models)
        self.assertEqual(json.loads(self.file.read_text()), self.models)
        self.assertEqual((self.site / "index.html").read_text(), "SITIO ANTERIOR")

    def test_foto_faltante_impide_publicar(self):
        (self.data / "media/modelos/VEL-0004/1.webp").unlink()
        with self.assertRaises(pub.PublicacionError):
            pub.publicar("VEL-0004", self.models)
        self.assertEqual(json.loads(self.file.read_text()), self.models)

    def test_usuario_no_autorizado_no_publica(self):
        actions = api.procesar(self.callback("publicar:VEL-0004", user=456))
        self.assertIn("privado", actions[0]["texto"])
        self.assertEqual(json.loads(self.file.read_text()), self.models)

    def test_sin_lista_explicita_no_publica(self):
        with patch.object(api, "USUARIOS_PERMITIDOS", set()):
            actions = api.procesar(self.callback("publicar:VEL-0004"))
        self.assertIn("permiso", actions[-1]["texto"])
        self.assertEqual(json.loads(self.file.read_text()), self.models)

    def test_borradores_y_vista_previa_no_borran_sesion(self):
        session = {"123": {"paso": "nombre", "modelo": {"categoria": "velas"}}}
        api.SESIONES_FILE.write_text(json.dumps(session))
        actions = api.procesar(self.callback("borradores:0"))
        self.assertEqual(actions[-1]["botones"][0][0]["data"], "ver_borrador:VEL-0004")
        preview = api.procesar(self.callback("ver_borrador:VEL-0004"))[-1]
        self.assertEqual(preview["botones"][0][0]["data"], "publicar:VEL-0004")
        self.assertEqual(json.loads(api.SESIONES_FILE.read_text()), session)

    def test_json_corrupto_no_se_sobrescribe(self):
        self.file.write_text("{incorrecto")
        actions = api.procesar(self.callback("publicar:VEL-0004"))
        self.assertTrue(any("No pude completar" in str(x) for x in actions))
        self.assertEqual(self.file.read_text(), "{incorrecto")

    def confirmar(self, callback):
        actions=api.procesar(self.callback(callback))
        token=actions[-1]['botones'][0][0]['data']
        self.assertTrue(token.startswith('ok:'))
        return api.procesar(self.callback(token))

    def test_callback_confirma_antes_de_publicar(self):
        actions=api.procesar(self.callback('publicar:VEL-0004'))
        self.assertEqual(json.loads(self.file.read_text())[0]['estado'],'borrador')
        result=api.procesar(self.callback(actions[-1]['botones'][0][0]['data']))
        self.assertEqual(json.loads(self.file.read_text())[0]['estado'],'publicado')
        self.assertTrue(any(b.get('url','').startswith('https://www.latienditadeoli.com/modelos/') for row in result[-1]['botones'] for b in row))

    def test_codigo_ajeno_no_publica(self):
        with self.assertRaises(pub.PublicacionError):
            pub.publicar("VEL-9999", self.models)
        self.assertEqual(json.loads(self.file.read_text()), self.models)

    def test_categoria_legacy_inferida_sin_perder_datos(self):
        self.models[0].pop("categoria")
        m, _ = pub.publicar("VEL-0004", self.models)
        self.assertEqual(m["categoria"], "velas")
        self.assertEqual(m["fotos"], self.modelo["fotos"])

    def test_dos_clicks_simultaneos_se_serializan(self):
        actions=api.procesar(self.callback('publicar:VEL-0004'))
        cb=actions[-1]['botones'][0][0]['data']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:api.procesar(self.callback(cb)),range(2)))
        self.assertEqual(json.loads(self.file.read_text())[0]['estado'],'publicado')
        self.assertEqual(sum('Cambio guardado' in str(r) for r in results),1)

    def test_http_rechaza_sin_clave_y_acepta_callback_autorizado(self):
        with patch.object(api, "API_KEY", "clave-de-prueba"), patch.object(api, "BOT_TOKEN", ""):
            server = api.ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/api/bot"
                body = json.dumps(self.callback("publicar:VEL-0004")).encode()
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(url, data=body))
                self.assertEqual(error.exception.code, 401)
                self.assertEqual(json.loads(self.file.read_text())[0]["estado"], "borrador")
                req = urllib.request.Request(url, data=body, headers={"X-Oli-Key": "clave-de-prueba"})
                with urllib.request.urlopen(req) as response:
                    result = json.load(response)
                self.assertFalse(result["enviado"])
                self.assertTrue(result["procesado"])
                self.assertEqual(json.loads(self.file.read_text())[0]["estado"],"borrador")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
