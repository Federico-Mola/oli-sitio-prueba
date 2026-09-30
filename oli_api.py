"""Servicio interno de Oli: lleva la conversación del bot de carga y guarda los modelos.

n8n recibe los mensajes de Telegram, controla quién está autorizado y le pasa cada
mensaje a este servicio (POST /api/bot). El servicio responde con la lista de cosas
que el bot tiene que contestar ("acciones"), y n8n las manda por Telegram.

Solo usa la biblioteca estándar de Python. Datos:
  /data/modelos.json   -> modelos (los mismos que usa build.py)
  /data/sesiones.json  -> carga en curso de cada persona
Seguridad: todas las rutas /api/ (menos /api/salud) piden el encabezado X-Oli-Key
igual a la variable de entorno OLI_API_KEY. Sin esa variable, el servicio rechaza todo.
"""
import datetime
import fcntl
import hmac
import json
import os
import pathlib
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = pathlib.Path(__file__).parent
DATA = pathlib.Path(os.environ.get("DATA_DIR", "/data"))
CATALOGO_FILE = pathlib.Path(os.environ.get("CATALOGO_FILE", APP / "data" / "catalogo.json"))
MODELOS_FILE = DATA / "modelos.json"
SESIONES_FILE = DATA / "sesiones.json"
LOCK_FILE = DATA / ".oli.lock"
API_KEY = os.environ.get("OLI_API_KEY", "")
PORT = int(os.environ.get("OLI_API_PORT", "8091"))

MAX_NOMBRE = 80
MAX_DESCRIPCION = 600


# ---------- datos ----------
def catalogo():
    return json.loads(CATALOGO_FILE.read_text())["categorias"]


def buscar_categoria(slug):
    return next((c for c in catalogo() if c["slug"] == slug), None)


def buscar_linea(slug):
    for c in catalogo():
        for l in c["lineas"]:
            if l["slug"] == slug:
                return c, l
    return None, None


def leer_json(path, vacio):
    try:
        return json.loads(path.read_text()) if path.exists() else vacio
    except Exception:
        return vacio


def escribir_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


class Bloqueo:
    """Evita que dos mensajes a la vez pisen los archivos."""
    def __enter__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        self.f = open(LOCK_FILE, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def siguiente_codigo(modelos, prefijo):
    nums = [int(m["codigo"].split("-")[1]) for m in modelos
            if str(m.get("codigo", "")).startswith(prefijo + "-") and m["codigo"].split("-")[1].isdigit()]
    return f"{prefijo}-{(max(nums) + 1 if nums else 1):04d}"


def precio_fmt(p):
    return "$ " + f"{int(p):,}".replace(",", ".")


def leer_precio(texto):
    t = texto.strip().replace("$", "").replace(" ", "").replace("U", "").replace("u", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):  # 1.200 / 12.500
        t = t.replace(".", "")
    t = t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    if v <= 0 or v != int(v):
        return None
    return int(v)


# ---------- respuestas ----------
def msg(texto, botones=None):
    return {"tipo": "mensaje", "texto": texto, "botones": botones or []}


def menu(nombre=""):
    saludo = f"Hola {nombre} 👋 " if nombre else ""
    return msg(f"{saludo}¿Qué querés hacer?",
               [[{"texto": "📷 Cargar modelo", "data": "cargar"}, {"texto": "🔎 Buscar modelo", "data": "buscar"}]])


def en_filas(botones, por_fila=2):
    return [botones[i:i + por_fila] for i in range(0, len(botones), por_fila)]


def pedir_categoria():
    bs = [{"texto": c["nombre"], "data": "cat:" + c["slug"]} for c in catalogo()]
    return msg("¿De qué categoría es el modelo?", en_filas(bs))


def pedir_linea(cat):
    lineas = sorted(cat["lineas"], key=lambda l: l.get("orden", 0))
    bs = [{"texto": l["nombre"], "data": "lin:" + l["slug"]} for l in lineas]
    return msg(f"¿De qué línea de {cat['nombre']}?", en_filas(bs))


PREGUNTAS = {
    "nombre": "¿Cómo se llama el modelo? (por ejemplo: Moña Liberty Rosa)",
    "descripcion": "Escribí una descripción corta del modelo.",
    "precio": "¿Cuál es el precio al público? Escribí solo el número, por ejemplo: 1200",
    "variantes": "Si tiene variantes (tamaños, tipos o colores), escribilas separadas por coma.\n"
                 "Por ejemplo: Chica, Mediana, Grande\nSi no tiene, tocá Saltear.",
}


def preguntar(paso):
    botones = [[{"texto": "Saltear", "data": "saltar_variantes"}]] if paso == "variantes" else []
    return msg(PREGUNTAS[paso], botones)


def vista_previa(m):
    cat, lin = buscar_linea(m["linea"])
    lineas = [
        "👀 Vista previa del modelo", "",
        f"Código: {m['codigo']}",
        f"Categoría: {cat['nombre'] if cat else '-'}",
        f"Línea: {lin['nombre'] if lin else m['linea']}",
        f"Nombre: {m['nombre']}",
        f"Descripción: {m['descripcion']}",
        f"Precio: {precio_fmt(m['precio'])}",
    ]
    if m["variantes"]:
        lineas.append("Variantes:")
        lineas += [f"• {v}" for v in m["variantes"]]
    else:
        lineas.append("Variantes: no tiene")
    lineas += ["", "Quedó guardado como borrador: todavía no se ve en el sitio.",
               "Las fotos y el botón Publicar se suman en las próximas etapas."]
    return msg("\n".join(lineas))


# ---------- conversación ----------
def procesar(update):
    """Recibe un update de Telegram y devuelve la lista de acciones para contestar."""
    m = update.get("message")
    cb = update.get("callback_query")
    if not m and not cb:
        return []
    frm = (m or cb)["from"]
    uid = str(frm["id"])
    nombre = frm.get("first_name", "")
    acciones = []
    if cb:
        acciones.append({"tipo": "responder_boton", "callback_id": cb["id"], "texto": ""})

    with Bloqueo():
        sesiones = leer_json(SESIONES_FILE, {})
        ses = sesiones.get(uid)

        def guardar(s):
            if s is None:
                sesiones.pop(uid, None)
            else:
                s["actualizado"] = datetime.datetime.now().isoformat(timespec="seconds")
                sesiones[uid] = s
            escribir_json(SESIONES_FILE, sesiones)

        # --- botones ---
        if cb:
            data = cb.get("data", "")
            if data == "cargar":
                guardar({"paso": "categoria", "modelo": {}})
                acciones.append(pedir_categoria())
            elif data == "buscar":
                acciones[0]["texto"] = "Esta opción se habilita en una próxima etapa."
                acciones[0]["alerta"] = True
            elif data.startswith("cat:") and ses and ses["paso"] == "categoria":
                cat = buscar_categoria(data[4:])
                if not cat:
                    acciones.append(pedir_categoria())
                else:
                    ses["modelo"]["categoria"] = cat["slug"]
                    ses["paso"] = "linea"
                    guardar(ses)
                    acciones.append(pedir_linea(cat))
            elif data.startswith("lin:") and ses and ses["paso"] == "linea":
                cat, lin = buscar_linea(data[4:])
                if not lin or cat["slug"] != ses["modelo"].get("categoria"):
                    acciones.append(pedir_linea(buscar_categoria(ses["modelo"]["categoria"])))
                else:
                    ses["modelo"]["linea"] = lin["slug"]
                    ses["paso"] = "nombre"
                    guardar(ses)
                    acciones.append(msg(f"Línea: {lin['nombre']} ✅"))
                    acciones.append(preguntar("nombre"))
            elif data == "saltar_variantes" and ses and ses["paso"] == "variantes":
                ses["modelo"]["variantes"] = []
                acciones += terminar(ses, guardar)
            else:
                acciones[0]["texto"] = "Ese botón ya no está activo."
                acciones.append(continuar(ses, nombre))
            return acciones

        # --- mensajes ---
        texto = (m.get("text") or "").strip()
        if texto.startswith("/start") or texto.startswith("/menu"):
            guardar(None)
            acciones.append(menu(nombre))
            return acciones
        if not ses:
            acciones.append(menu(nombre))
            return acciones
        paso = ses["paso"]
        if paso in ("categoria", "linea"):
            acciones.append(msg("Elegí una opción con los botones de arriba."))
            acciones.append(pedir_categoria() if paso == "categoria"
                            else pedir_linea(buscar_categoria(ses["modelo"]["categoria"])))
            return acciones
        if not texto:
            acciones.append(msg("Necesito que me lo escribas como texto."))
            acciones.append(preguntar(paso))
            return acciones
        mod = ses["modelo"]
        if paso == "nombre":
            if len(texto) > MAX_NOMBRE:
                acciones.append(msg(f"El nombre es muy largo (máximo {MAX_NOMBRE} letras). Probá con uno más corto."))
                return acciones
            mod["nombre"] = texto
            ses["paso"] = "descripcion"
        elif paso == "descripcion":
            if len(texto) < 3:
                acciones.append(msg("La descripción es obligatoria."))
                acciones.append(preguntar("descripcion"))
                return acciones
            if len(texto) > MAX_DESCRIPCION:
                acciones.append(msg(f"La descripción es muy larga (máximo {MAX_DESCRIPCION} letras). Probá acortarla."))
                return acciones
            mod["descripcion"] = texto
            ses["paso"] = "precio"
        elif paso == "precio":
            p = leer_precio(texto)
            if p is None:
                acciones.append(msg("No entendí el precio. Escribí solo el número, sin centavos. Por ejemplo: 1200"))
                return acciones
            mod["precio"] = p
            ses["paso"] = "variantes"
        elif paso == "variantes":
            vs = [v.strip() for v in texto.split(",") if v.strip()]
            mod["variantes"] = vs
            acciones += terminar(ses, guardar)
            return acciones
        guardar(ses)
        acciones.append(preguntar(ses["paso"]))
        return acciones


def continuar(ses, nombre):
    """Qué mostrar si tocan un botón viejo."""
    if not ses:
        return menu(nombre)
    if ses["paso"] == "categoria":
        return pedir_categoria()
    if ses["paso"] == "linea":
        return pedir_linea(buscar_categoria(ses["modelo"]["categoria"]))
    return preguntar(ses["paso"])


def terminar(ses, guardar):
    """Guarda el modelo como borrador con su código y muestra la vista previa."""
    mod = ses["modelo"]
    cat = buscar_categoria(mod["categoria"])
    modelos = leer_json(MODELOS_FILE, [])
    nuevo = {
        "codigo": siguiente_codigo(modelos, cat["codigo"]),
        "linea": mod["linea"],
        "nombre": mod["nombre"],
        "descripcion": mod["descripcion"],
        "precio": mod["precio"],
        "variantes": mod.get("variantes", []),
        "fotos": [],
        "video": None,
        "estado": "borrador",
        "creado": datetime.date.today().isoformat(),
    }
    modelos.append(nuevo)
    escribir_json(MODELOS_FILE, modelos)
    guardar(None)
    return [vista_previa(nuevo), menu()]


# ---------- servidor ----------
class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _autorizado(self):
        k = self.headers.get("X-Oli-Key", "")
        return bool(API_KEY) and hmac.compare_digest(k, API_KEY)

    def do_GET(self):
        if self.path == "/api/salud":
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "no encontrado"})

    def do_POST(self):
        if not self._autorizado():
            return self._json(401, {"error": "no autorizado"})
        if self.path != "/api/bot":
            return self._json(404, {"error": "no encontrado"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or b"{}")
            update = body.get("update", body)
            acciones = procesar(update)
        except Exception as e:
            print("Error procesando mensaje:", repr(e), file=sys.stderr, flush=True)
            return self._json(500, {"error": "error interno", "detalle": repr(e)})
        return self._json(200, {"acciones": acciones})

    def log_message(self, fmt, *args):
        print("oli-api:", fmt % args, flush=True)


if __name__ == "__main__":
    if not API_KEY:
        print("Aviso: falta OLI_API_KEY; el servicio va a rechazar todos los pedidos.", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
