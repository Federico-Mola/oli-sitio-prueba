"""Entradas del bot y subida privada; no se registran URL con claves ni mensajes."""
import hmac
import json
from http.server import BaseHTTPRequestHandler
import oli_eventos
import oli_upload


def crear_handler(api):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(120)

        def _json(self,code,value):
            body=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers();self.wfile.write(body)

        def _autorizado(self):
            return bool(api.API_KEY) and hmac.compare_digest(self.headers.get('X-Oli-Key',''),api.API_KEY)

        def do_GET(self):
            if self.path=='/api/salud':return self._json(200,{'ok':True,'version':'gestion-v2'})
            return self._json(404,{'error':'no encontrado'})

        def do_POST(self):
            if self.path in ('/api/subida','/api/subida/finalizar'):
                try:return self._json(200,oli_upload.manejar(self,api,self.path))
                except oli_upload.UploadError as e:return self._json(e.status,{'error':e.message})
                except Exception:
                    api.registrar_error('subida_archivo')
                    return self._json(400,{'error':'No pude recibir ese archivo. Pedí un enlace nuevo desde Telegram.'})
            if not self._autorizado():return self._json(401,{'error':'no autorizado'})
            if self.path!='/api/bot':return self._json(404,{'error':'no encontrado'})
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=1024*1024 or self.headers.get('Transfer-Encoding'):
                    return self._json(413,{'error':'solicitud demasiado grande'})
                body=json.loads(self.rfile.read(n));update=body.get('update',body)
                if not isinstance(update,dict):return self._json(400,{'error':'formato no válido'})
                return self._json(200,oli_eventos.ejecutar(api,update))
            except Exception:
                api.registrar_error('solicitud_bot')
                return self._json(400,{'error':'solicitud no válida'})

        def log_message(self,*args):pass
    return Handler
