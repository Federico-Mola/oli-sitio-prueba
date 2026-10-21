"""Servicio interno de Oli: lleva la conversación del bot de carga y guarda los modelos.

n8n recibe los mensajes de Telegram, controla quién está autorizado y le pasa cada
mensaje a este servicio (POST /api/bot). El servicio arma las respuestas ("acciones")
y las manda directo a Telegram con el token del bot (variable OLI_BOT_TOKEN), porque
el nodo de Telegram de n8n no puede armar botones que cambian según el caso.

Solo usa la biblioteca estándar de Python y Pillow (para las fotos). Datos:
  /data/modelos.json          -> modelos (los mismos que usa build.py)
  /data/sesiones.json         -> carga en curso de cada persona
  /data/media/tmp/<persona>/  -> fotos recibidas durante una carga
  /data/media/modelos/<cod>/  -> fotos de cada modelo (1.webp, 1-600.webp, ..., og.jpg)
Seguridad: todas las rutas /api/ (menos /api/salud) piden el encabezado X-Oli-Key
igual a la variable de entorno OLI_API_KEY. Sin esa variable, el servicio rechaza todo.
"""
import datetime
import fcntl
import hmac
import io
import json
import math
import os
import pathlib
import re
import shutil
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from oli_publicacion import PublicacionError, publicar, escribir_json, SITE_URL, ruta_modelo

APP = pathlib.Path(__file__).parent
DATA = pathlib.Path(os.environ.get("DATA_DIR", "/data"))
CATALOGO_FILE = pathlib.Path(os.environ.get("CATALOGO_FILE", APP / "data" / "catalogo.json"))
MODELOS_FILE = DATA / "modelos.json"
SESIONES_FILE = DATA / "sesiones.json"
LOCK_FILE = DATA / ".oli.lock"
MEDIA = DATA / "media"
API_KEY = os.environ.get("OLI_API_KEY", "")
PORT = int(os.environ.get("OLI_API_PORT", "8091"))
BOT_TOKEN = os.environ.get("OLI_BOT_TOKEN", "")
TELEGRAM_URL = os.environ.get("OLI_TELEGRAM_URL", "https://api.telegram.org")
ESPERA_ALBUM = float(os.environ.get("OLI_ESPERA_ALBUM", "2.5"))  # segundos para juntar las fotos de un álbum
USUARIOS_PERMITIDOS = {x.strip() for x in os.environ.get("OLI_ALLOWED_USER_IDS", "").split(",") if x.strip()}

MAX_NOMBRE = 80
MAX_DESCRIPCION = 600
MAX_FOTOS = 10


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
    # Un JSON corrupto debe detener la operación, nunca convertirse en catálogo vacío.
    try:
        return json.loads(path.read_text()) if path.exists() else vacio
    except (json.JSONDecodeError, UnicodeError):
        raise RuntimeError("Datos no disponibles; se conserva el archivo original") from None


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
    if not math.isfinite(v) or v <= 0 or v != int(v):
        return None
    return int(v)


def carpeta_tmp(uid):
    return MEDIA / "tmp" / uid


def limpiar_tmp(uid):
    shutil.rmtree(carpeta_tmp(uid), ignore_errors=True)


# ---------- respuestas ----------
def msg(texto, botones=None):
    return {"tipo": "mensaje", "texto": texto, "botones": botones or []}


def menu(nombre=""):
    saludo = f"Hola {nombre} 👋 " if nombre else ""
    return msg(f"{saludo}¿Qué querés hacer?",
               [[{"texto": "📷 Cargar modelo", "data": "cargar"}, {"texto": "🔎 Buscar modelo", "data": "buscar"}],
                [{"texto": "📝 Borradores", "data": "borradores:0"}]])


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
    "fotos": f"📷 Ahora mandame las fotos del modelo (hasta {MAX_FOTOS}).\n"
             "Tocá el clip 📎 que está al lado de donde escribís, elegí las fotos de la galería y tocá Enviar. "
             "Podés mandarlas todas juntas.\n"
             "Cuando termines, tocá ✅ Listo.",
}

BOTON_LISTO = {"texto": "✅ Listo", "data": "fotos_listo"}


def preguntar(paso):
    if paso == "variantes":
        botones = [[{"texto": "Saltear", "data": "saltar_variantes"}]]
    elif paso == "fotos":
        botones = [[BOTON_LISTO]]
    else:
        botones = []
    return msg(PREGUNTAS[paso], botones)


def botones_portada(n, portada):
    nums = [{"texto": ("⭐ " if i == portada else "") + str(i + 1), "data": f"portada:{i}"} for i in range(n)]
    return en_filas(nums, 5) + [[BOTON_LISTO]]


def texto_vista_previa(m):
    cat, lin = buscar_linea(m["linea"]) if m.get("linea") else (buscar_categoria(m.get("categoria", "")), None)
    lineas = [
        "👀 Vista previa del modelo", "",
        f"Código: {m['codigo']}",
        f"Categoría: {cat['nombre'] if cat else '-'}",
        f"Línea: {lin['nombre'] if lin else '— (va en la página de la categoría)'}",
        f"Nombre: {m['nombre']}",
        f"Descripción: {m['descripcion']}",
        f"Precio: {precio_fmt(m['precio'])}",
    ]
    if m["variantes"]:
        lineas.append("Variantes:")
        lineas += [f"• {v}" for v in m["variantes"]]
    else:
        lineas.append("Variantes: no tiene")
    n = len(m.get("fotos") or [])
    if n:
        lineas.append(f"Fotos: {n} (la de arriba es la portada)")
    lineas += ["", "Quedó guardado como borrador: todavía no se ve en el sitio.",
               "Tocá ✅ Publicar cuando quieras mostrarlo en la tienda."]
    return "\n".join(lineas)


def vista_previa(m, portada_tg=None):
    texto = texto_vista_previa(m)
    botones = [[{"texto": "✅ Publicar", "data": "publicar:" + m["codigo"]}],
               [{"texto": "📝 Borradores", "data": "borradores:0"}]]
    if portada_tg:
        return {"tipo": "foto", "file_id": portada_tg, "texto": texto, "botones": botones}
    return msg(texto, botones)


def borradores(pagina=0):
    modelos = [m for m in reversed(leer_json(MODELOS_FILE, [])) if m.get("estado") == "borrador"]
    if not modelos:
        return msg("No tenés modelos pendientes de publicar.")
    pagina = max(0, min(pagina, (len(modelos) - 1) // 8))
    bs = [[{"texto": f"{m['codigo']} · {m['nombre'][:45]}", "data": "ver_borrador:" + m["codigo"]}]
          for m in modelos[pagina * 8:(pagina + 1) * 8]]
    nav = []
    if pagina:
        nav.append({"texto": "← Anteriores", "data": f"borradores:{pagina - 1}"})
    if (pagina + 1) * 8 < len(modelos):
        nav.append({"texto": "Más →", "data": f"borradores:{pagina + 1}"})
    if nav:
        bs.append(nav)
    return msg("📝 Elegí el borrador que querés revisar y publicar:", bs)


# ---------- fotos ----------
def foto_de_mensaje(m):
    """Devuelve (file_id, tipo) de lo que mandaron: 'foto', 'video', 'otro' o None si es texto."""
    if m.get("photo"):
        return m["photo"][-1]["file_id"], "foto"  # la última es la de mayor tamaño
    doc = m.get("document")
    if doc:
        if str(doc.get("mime_type", "")).startswith("image/"):
            return doc["file_id"], "foto"
        if str(doc.get("mime_type", "")).startswith("video/"):
            return None, "video"
        return None, "otro"
    if m.get("video") or m.get("video_note") or m.get("animation"):
        return None, "video"
    if any(m.get(k) for k in ("sticker", "audio", "voice", "contact", "location", "poll", "dice")):
        return None, "otro"
    return None, None


def descargar_de_telegram(file_id, destino):
    info = telegram("getFile", {"file_id": file_id})
    ruta = info["result"]["file_path"]
    with urllib.request.urlopen(f"{TELEGRAM_URL}/file/bot{BOT_TOKEN}/{ruta}", timeout=60) as r:
        datos = r.read(20 * 1024 * 1024 + 1)
    if len(datos) > 20 * 1024 * 1024:
        raise ValueError("Archivo demasiado grande; usar enlace de subida")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)


def abrir_imagen(path):
    from PIL import Image, ImageOps
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    return im.convert("RGB")


def armar_mosaico(archivos, portada):
    """Una sola imagen con todas las fotos numeradas, para mostrarlas en el chat."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    n = len(archivos)
    cols = 1 if n == 1 else 2 if n <= 4 else 3
    filas = (n + cols - 1) // cols
    lado = 360
    lienzo = Image.new("RGB", (cols * lado + (cols + 1) * 8, filas * lado + (filas + 1) * 8), (250, 241, 225))
    try:
        fuente = ImageFont.load_default(size=44)
    except TypeError:
        fuente = ImageFont.load_default()
    for i, a in enumerate(archivos):
        im = ImageOps.fit(abrir_imagen(a), (lado, lado))
        x, y = 8 + (i % cols) * (lado + 8), 8 + (i // cols) * (lado + 8)
        lienzo.paste(im, (x, y))
        d = ImageDraw.Draw(lienzo)
        color = (201, 124, 121) if i == portada else (69, 63, 56)
        d.ellipse((x + 12, y + 12, x + 84, y + 84), fill=color, outline=(255, 255, 255), width=4)
        d.text((x + 48, y + 48), str(i + 1), fill=(255, 255, 255), font=fuente, anchor="mm")
    buf = io.BytesIO()
    lienzo.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def guardar_fotos_modelo(codigo, archivos):
    """Guarda las fotos finales del modelo (portada primero) y devuelve sus rutas públicas."""
    carpeta = MEDIA / "modelos" / codigo
    shutil.rmtree(carpeta, ignore_errors=True)
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = []
    for i, a in enumerate(archivos, start=1):
        im = abrir_imagen(a)
        grande = im.copy()
        grande.thumbnail((1200, 1200))
        grande.save(carpeta / f"{i}.webp", "WEBP", quality=80)
        chica = im.copy()
        chica.thumbnail((600, 600))
        chica.save(carpeta / f"{i}-600.webp", "WEBP", quality=78)
        if i == 1:  # imagen para la vista previa al compartir el link (WhatsApp pide JPG)
            grande.save(carpeta / "og.jpg", "JPEG", quality=82)
        rutas.append(f"/media/modelos/{codigo}/{i}.webp")
    return rutas


def resumen_fotos(uid, token):
    """Se llama unos segundos después de la última foto: si no llegaron más, manda el resumen."""
    time.sleep(ESPERA_ALBUM)
    with Bloqueo():
        ses = leer_json(SESIONES_FILE, {}).get(uid)
        if not ses or ses.get("paso") != "fotos" or ses.get("fotos_token") != token:
            return
        fotos = ses["modelo"].get("fotos_tmp", [])
        portada = ses["modelo"].get("portada", 0)
        excedidas = ses.pop("fotos_excedidas", 0)
        chat_id = ses.get("chat_id")
        sesiones = leer_json(SESIONES_FILE, {})
        sesiones[uid] = ses
        escribir_json(SESIONES_FILE, sesiones)
    if not fotos or not chat_id:
        return
    texto = f"Recibí {len(fotos)} foto{'s' if len(fotos) != 1 else ''}."
    if excedidas:
        texto += f"\nNo guardé {excedidas} porque el máximo es {MAX_FOTOS}."
    texto += "\nTocá el número de la foto que va de portada (⭐). Si querés, mandá más. Cuando termines, tocá ✅ Listo."
    try:
        imagen = armar_mosaico([DATA / f["archivo"] for f in fotos], portada)
        enviar_acciones(chat_id, [{"tipo": "foto", "bytes": imagen, "texto": texto,
                                   "botones": botones_portada(len(fotos), portada)}])
    except Exception as e:
        registrar_error("resumen_fotos")


# ---------- administración actual y errores seguros ----------
_ERROR_LOCK = threading.Lock()


def registrar_error(codigo):
    codigo = codigo if re.fullmatch(r"[a-z0-9_]{1,64}", codigo) else "error_interno"
    with _ERROR_LOCK:
        folder = DATA / "operacion"
        folder.mkdir(parents=True, exist_ok=True)
        escribir_json(folder / "ultimo-error.json", {"codigo": codigo, "fecha": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})
    print("oli-error:", codigo, file=sys.stderr, flush=True)


def procesar(update):
    import oli_gestion
    try:
        return oli_gestion.procesar(update, sys.modules[__name__])
    except Exception:
        registrar_error("gestion_modelo")
        return [msg("No pude completar la operación. Conservé los datos anteriores; reabrí el menú para revisar.", [[{"texto": "Menú", "data": "menu"}]])]


# ---------- envío a Telegram ----------
def telegram(metodo, datos):
    req = urllib.request.Request(
        f"{TELEGRAM_URL}/bot{BOT_TOKEN}/{metodo}",
        data=json.dumps(datos).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def telegram_archivo(metodo, campos, nombre_campo, nombre_archivo, contenido):
    """Manda un archivo (multipart/form-data)."""
    limite = "----oli" + uuid.uuid4().hex
    partes = []
    for k, v in campos.items():
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{nombre_campo}"; filename="{nombre_archivo}"\r\n'
                  f"Content-Type: image/jpeg\r\n\r\n".encode() + contenido + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    req = urllib.request.Request(f"{TELEGRAM_URL}/bot{BOT_TOKEN}/{metodo}", data=b"".join(partes),
                                 headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def teclado(botones):
    return {"inline_keyboard": [[dict(text=b["texto"], **({"url": b["url"]} if "url" in b
                                  else {"callback_data": b["data"]})) for b in fila] for fila in botones]}


def enviar_acciones(chat_id, acciones):
    """Manda las acciones a Telegram, en orden."""
    for a in acciones:
        if a["tipo"] == "responder_boton":
            datos = {"callback_query_id": a["callback_id"]}
            if a.get("texto"):
                datos["text"] = a["texto"]
                datos["show_alert"] = bool(a.get("alerta"))
            try:
                telegram("answerCallbackQuery", datos)
            except Exception:
                # Los botones caducan pronto; no perder la confirmación de una operación ya guardada.
                registrar_error("respuesta_boton_caducada")
        elif a["tipo"] == "editar_botones":
            telegram("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": a["message_id"],
                                                "reply_markup": teclado(a["botones"])})
        elif a["tipo"] == "foto":
            texto = a.get("texto", "")
            leyenda, resto = (texto, "") if len(texto) <= 1024 else ("", texto)
            if a.get("bytes"):
                campos = {"chat_id": chat_id, "caption": leyenda}
                if a.get("botones") and not resto:
                    campos["reply_markup"] = json.dumps(teclado(a["botones"]))
                telegram_archivo("sendPhoto", campos, "photo", "fotos.jpg", a["bytes"])
            else:
                datos = {"chat_id": chat_id, "photo": a["file_id"], "caption": leyenda}
                if a.get("botones") and not resto:
                    datos["reply_markup"] = teclado(a["botones"])
                telegram("sendPhoto", datos)
            if resto:
                datos = {"chat_id": chat_id, "text": resto}
                if a.get("botones"):
                    datos["reply_markup"] = teclado(a["botones"])
                telegram("sendMessage", datos)
        else:
            datos = {"chat_id": chat_id, "text": a["texto"]}
            if a.get("botones"):
                datos["reply_markup"] = teclado(a["botones"])
            telegram("sendMessage", datos)


def chat_de(update):
    m = update.get("message")
    cb = update.get("callback_query")
    return m["chat"]["id"] if m else cb["message"]["chat"]["id"]


# ---------- servidor ----------
from oli_http import crear_handler
Handler = crear_handler(sys.modules[__name__])

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
