"""Se ejecuta dentro del build de Docker en el VPS: descarga imágenes, fuentes y video
de Webflow y los optimiza (imágenes a WebP redimensionadas, fuentes a WOFF2)."""
import io, pathlib, sys, urllib.request
from PIL import Image
from fontTools.ttLib import TTFont

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "site")
for line in open("assets.txt"):
    url, dest, maxw = line.split()
    maxw = int(maxw)
    target = OUT / dest
    target.parent.mkdir(parents=True, exist_ok=True)
    data = urllib.request.urlopen(url, timeout=60).read()
    if dest.endswith(".webp"):
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
        if im.width > maxw:
            im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
        im.save(target, "WEBP", quality=78, method=6)
    elif dest.endswith(".woff2"):
        f = TTFont(io.BytesIO(data)); f.flavor = "woff2"; f.save(target)
    else:
        target.write_bytes(data)
    print(f"{dest}: {len(data)//1024} KB -> {target.stat().st_size//1024} KB")
