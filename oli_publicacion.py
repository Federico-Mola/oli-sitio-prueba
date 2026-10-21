"""Publicación del catálogo con generación previa y cambio atómico del sitio."""
import copy
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import uuid

APP = pathlib.Path(__file__).parent
DATA = pathlib.Path(os.environ.get("DATA_DIR", "/data"))
SITE = pathlib.Path(os.environ.get("SITE_DIR", "/usr/share/nginx/html"))
SITE_URL = os.environ.get("SITE_URL", "https://www.latienditadeoli.com").rstrip("/")


class PublicacionError(Exception):
    pass


def ruta_modelo(m):
    nombre = unicodedata.normalize("NFKD", m["nombre"]).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", nombre).strip("-")[:60] or "modelo"
    return f"/modelos/{m['codigo'].lower()}-{slug}"


def escribir_json(path, data):
    """No dejar archivos parcialmente escritos ni temporales con nombres compartidos."""
    path = pathlib.Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".oli-json-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)


def validar(m):
    if not re.fullmatch(r"(?:ACC|COR|VEL|COL|NAV|PAS)-\d{4,}", m.get("codigo", "")):
        raise PublicacionError("El código del modelo no es válido.")
    if not isinstance(m.get("nombre"), str) or not m["nombre"].strip() or len(m["nombre"]) > 80:
        raise PublicacionError("Revisá el nombre del modelo.")
    if not isinstance(m.get("descripcion"), str) or not 3 <= len(m["descripcion"].strip()) <= 600:
        raise PublicacionError("Falta una descripción válida.")
    precio = m.get("precio")
    if isinstance(precio, bool) or not isinstance(precio, (int, float)) or precio <= 0 or precio != int(precio):
        raise PublicacionError("Falta un precio válido.")
    categorias = json.loads((APP / "data/catalogo.json").read_text())["categorias"]
    if m.get("linea"):
        cat = next((c for c in categorias if any(l["slug"] == m["linea"] for l in c["lineas"])), None)
        if not cat or m.get("categoria") not in (None, cat["slug"]):
            raise PublicacionError("La categoría y la línea no coinciden.")
        m["categoria"] = cat["slug"]
    elif not any(c["slug"] == m.get("categoria") and not c["lineas"] for c in categorias):
        raise PublicacionError("Falta elegir una línea válida.")
    fotos = m.get("fotos")
    if not isinstance(fotos, list) or not 1 <= len(fotos) <= 10:
        raise PublicacionError("Este borrador necesita al menos una foto antes de publicarlo.")
    for foto in fotos:
        if not isinstance(foto, str) or not foto.startswith("/media/modelos/"):
            raise PublicacionError("Las fotos de este borrador necesitan revisión.")
        path = (DATA / foto.lstrip("/")).resolve()
        if not path.is_relative_to((DATA / "media/modelos").resolve()) or not path.is_file():
            raise PublicacionError("Falta una foto guardada. El modelo sigue como borrador.")


def publicar(codigo, modelos):
    """El llamador mantiene el bloqueo del catálogo durante toda la operación."""
    coincidencias = [m for m in modelos if m.get("codigo") == codigo]
    if len(coincidencias) != 1:
        raise PublicacionError("No encontré un único modelo con ese código.")
    original = coincidencias[0]
    if original.get("estado") not in ("borrador", "publicado"):
        raise PublicacionError("Ese modelo no está disponible para publicar desde Borradores.")
    url = SITE_URL + ruta_modelo(original)
    if original.get("estado") == "publicado" and (SITE / ruta_modelo(original).lstrip("/") / "index.html").is_file():
        return original, url
    nuevo = copy.deepcopy(modelos)
    mod = next(m for m in nuevo if m.get("codigo") == codigo)
    validar(mod)
    mod["estado"] = "publicado"
    mod.setdefault("publicado", datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    if not SITE.is_symlink():
        raise PublicacionError("La publicación no está configurada. El borrador sigue guardado.")
    anterior = SITE.resolve()
    releases = SITE.parent / (SITE.name + ".releases")
    releases.mkdir(exist_ok=True)
    stage = pathlib.Path(tempfile.mkdtemp(prefix="publicacion-", dir=releases))
    fd, datos_tmp = tempfile.mkstemp(prefix=".oli-publicar-", suffix=".json", dir=DATA)
    enlace = SITE.with_name(".oli-current-" + uuid.uuid4().hex)
    activado = False
    guardado = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(nuevo, f, ensure_ascii=False)
        shutil.copytree(anterior, stage, dirs_exist_ok=True)
        env = dict(os.environ, SITE_DIR=str(stage), MODELOS_FILE=datos_tmp, SITE_URL=SITE_URL)
        resultado = subprocess.run([sys.executable, str(APP / "build.py")], env=env,
                                   capture_output=True, timeout=60)
        if resultado.returncode:
            raise PublicacionError("No pude preparar la página. Conservé el borrador; podés reintentar.")
        pagina = stage / ruta_modelo(mod).lstrip("/") / "index.html"
        if not pagina.is_file() or codigo not in pagina.read_text():
            raise PublicacionError("No pude verificar la página. El modelo sigue como borrador.")
        # El enlace y el JSON se reemplazan individualmente de forma atómica.
        # Si falla el cambio del enlace, restauramos el catálogo anterior.
        enlace.symlink_to(stage, target_is_directory=True)
        escribir_json(DATA / "modelos.json", nuevo)
        guardado = True
        os.replace(enlace, SITE)
        activado = True
    except Exception:
        if guardado and not activado:
            escribir_json(DATA / "modelos.json", modelos)
        raise
    finally:
        pathlib.Path(datos_tmp).unlink(missing_ok=True)
        enlace.unlink(missing_ok=True)
        if not activado:
            shutil.rmtree(stage, ignore_errors=True)
    # Conservar versión actual y anterior; la limpieza nunca invalida un éxito.
    for old in releases.glob("publicacion-*"):
        if old not in (stage, anterior) and old.is_dir() and not old.is_symlink():
            shutil.rmtree(old, ignore_errors=True)
    return mod, url
