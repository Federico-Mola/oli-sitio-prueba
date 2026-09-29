"""Genera el sitio estático de prueba de Oli (home + Cordones) a partir del CSS de Webflow.

Salida:
  site/css/oli.css, site/index.html, site/cordones/index.html
  assets.txt  -> lista "URL destino ancho_max" que el Dockerfile descarga y optimiza en el VPS
"""
import re, pathlib

ROOT = pathlib.Path(__file__).parent
import os
SITE = pathlib.Path(os.environ.get("SITE_DIR", ROOT / "site"))
MODELOS_FILE = pathlib.Path(os.environ.get("MODELOS_FILE", "/data/modelos.json"))
WF = "https://oli-sitio.webflow.io"
WA = "https://wa.me/59899383602"

# ---------- CSS ----------
css = (ROOT / "webflow.css").read_text()

# quitar la fuente de íconos de Webflow (no se usa en el sitio)
css = re.sub(r'@font-face\s*\{\s*font-family:\s*webflow-icons;[^}]*\}', '', css)

assets = []  # (url, destino, ancho_max)
MAXW = {"oli-logo": 240, "hola-soy-oli": 720}

def img_repl(m):
    url = m.group(1)
    name = url.rsplit("/", 1)[-1].split("_", 1)[-1].rsplit(".", 1)[0]
    dest = f"img/{name}.webp"
    if not any(a[1] == dest for a in assets):
        assets.append((url, dest, MAXW.get(name, 1000)))
    return f'url("/{dest}")'

css = re.sub(r'url\("(https://(?:cdn\.prod\.website-files\.com|s3\.amazonaws\.com)[^"]+\.(?:jpe?g|png))"\)', img_repl, css)

def font_repl(m):
    url = m.group(1)
    name = url.rsplit("/", 1)[-1].split("-", 1)[-1].rsplit(".", 1)[0]
    dest = f"fonts/{name}.woff2"
    assets.append((url, dest, 0))
    return f'url("/{dest}") format("woff2")'

css = re.sub(r'url\("(https://webflow-files-prod[^"]+\.woff)"\)\s*format\("woff"\)', font_repl, css)
# que el texto se vea mientras carga la fuente
css = re.sub(r'(@font-face\s*\{)', r'\1\n  font-display: swap;', css)

# estilos que Webflow inyectaba inline en el <head>
css += """
.oli-navdrop{position:relative}.oli-navdrop-toggle{cursor:pointer}
.oli-navdrop-menu{position:absolute;top:100%;left:0;background:#fff;border-radius:12px;box-shadow:rgba(0,0,0,.15) 0 10px 30px;padding:8px;min-width:210px;opacity:0;visibility:hidden;transform:translateY(6px);transition:opacity .2s,transform .2s,visibility .2s;z-index:100}
.oli-navdrop:hover .oli-navdrop-menu{opacity:1;visibility:visible;transform:translateY(0)}
.oli-navdrop-item{display:block;padding:8px 12px;border-radius:8px;color:#2c2620;font-family:Karla,sans-serif;font-size:.9rem;text-decoration:none;white-space:nowrap}
.oli-navdrop-item:hover{background:#f6f1e7}
@media screen and (max-width:991px){.oli-navdrop-menu{position:static;box-shadow:none;opacity:1;visibility:visible;transform:none;display:none;padding-left:12px;background:transparent}.oli-navdrop.oli-navdrop-open .oli-navdrop-menu{display:block}}
.oli-float2{position:fixed;z-index:90;display:flex;align-items:center;gap:10px;opacity:0;transform:translateY(10px) scale(.9);pointer-events:none;transition:opacity .6s,transform .6s}
.oli-float2.show{opacity:1;transform:translateY(0) scale(1)}
.oli-float2 img{width:64px;height:64px;border-radius:50%;object-fit:cover;object-position:50% 25%;box-shadow:rgba(0,0,0,.2) 0 6px 18px;border:3px solid #fff}
.oli-float2 .bubble{background:#fff;color:#2c2620;font-weight:700;font-size:.85rem;padding:8px 14px;border-radius:999px;box-shadow:rgba(0,0,0,.16) 0 4px 12px;white-space:nowrap;font-family:Karla,sans-serif}
@media (prefers-reduced-motion:reduce){.oli-float2{transition:none}}
.oli-burger{display:none;background:none;border:0;padding:8px;margin-left:4px;cursor:pointer;-webkit-tap-highlight-color:transparent}
.oli-burger span{display:block;width:24px;height:2px;background:#453f38;margin:5px 0;border-radius:2px;transition:transform .2s,opacity .2s}
.oli-only-mobile{display:none}
@media screen and (max-width:991px){.oli-only-mobile{display:block;font-weight:700}}
@media screen and (max-width:767px){
.oli-burger{display:block}
.oli-nav-wrap{flex-wrap:nowrap}
.oli-nav-wrap>.oli-btn{margin-left:auto;padding:10px 16px;font-size:.85rem}
.oli-header.menu-open .oli-navlinks{display:flex;flex-direction:column;flex-wrap:nowrap;gap:0;position:absolute;top:100%;left:0;right:0;background:#faf1e1;padding:6px 20px 16px;box-shadow:rgba(0,0,0,.1) 0 12px 20px;max-height:calc(100vh - 80px);overflow-y:auto;z-index:95}
.oli-header.menu-open .oli-navlink{display:block;padding:13px 0;font-size:1.05rem;border-bottom:1px solid rgba(69,63,56,.1)}
.oli-header.menu-open .oli-navdrop-toggle::after{content:" ▾";font-size:.8em}
.oli-header.menu-open .oli-navdrop-item{padding:10px 12px;font-size:.95rem;white-space:normal}
.oli-header.menu-open .oli-burger span:nth-child(1){transform:translateY(7px) rotate(45deg)}
.oli-header.menu-open .oli-burger span:nth-child(2){opacity:0}
.oli-header.menu-open .oli-burger span:nth-child(3){transform:translateY(-7px) rotate(-45deg)}
}
@media screen and (max-width:479px){.oli-float2{gap:8px;max-width:calc(100vw - 24px)}.oli-float2 img{width:48px;height:48px;flex:none}.oli-float2 .bubble{font-size:.78rem;padding:7px 12px;white-space:normal;max-width:62vw;line-height:1.3}}
"""
css += """
.oli-models-section{background:#faf1e1;padding:8px 0 64px}
.oli-models-wrap{max-width:1180px;margin:0 auto;padding:0 32px}
.oli-models-title{text-align:center;margin:0 0 24px}
.oli-model-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,280px));justify-content:center;gap:24px}
.oli-model-card{background:#fff;border-radius:18px;overflow:hidden;box-shadow:rgba(69,63,56,.08) 0 8px 24px;display:flex;flex-direction:column}
.oli-model-img{width:100%;aspect-ratio:4/5;object-fit:cover;display:block;background:#f3e7d3}
.oli-model-body{padding:16px 18px 20px;display:flex;flex-direction:column;gap:8px;flex:1}
.oli-model-name{margin:0;font-family:Fredoka,sans-serif;font-weight:600;font-size:1.15rem;color:#453f38}
.oli-model-code{font-size:.75rem;letter-spacing:.08em;color:#766c5f;text-transform:uppercase}
.oli-model-desc{margin:0;font-size:.92rem;line-height:1.55;color:#453f38}
.oli-model-price{font-family:Fredoka,sans-serif;font-weight:600;font-size:1.25rem;color:#c97c79}
.oli-model-vars{display:flex;flex-wrap:wrap;gap:6px}
.oli-model-var{font-size:.8rem;padding:4px 10px;border-radius:999px;background:#f6f1e7;color:#453f38}
.oli-model-card .oli-btn{margin-top:auto;text-align:center}
.oli-wholesale-note{text-align:center;margin:28px 0 0;color:#766c5f;font-size:.95rem}
.oli-wholesale-note a{color:#c97c79;font-weight:700;text-decoration:none}
@media screen and (max-width:479px){.oli-models-wrap{padding:0 16px}.oli-model-grid{grid-template-columns:1fr 1fr;gap:12px}.oli-model-body{padding:12px}.oli-model-name{font-size:1rem}.oli-model-desc{display:none}.oli-model-card .oli-btn{padding:10px 8px;font-size:.8rem;white-space:normal;line-height:1.25}}
.oli-only-phone{display:none}
@media screen and (max-width:479px){
.oli-cat-grid{grid-template-columns:1fr 1fr;grid-column-gap:12px;grid-row-gap:12px}
.oli-cat-card{padding:14px;border-radius:16px}
.oli-cat-name{font-size:1.15rem}
.oli-cat-tag{font-size:.6rem}
.oli-cat-section .oli-h2-script{font-size:1.85rem;line-height:1.15;margin-bottom:24px}
.oli-slogan{font-size:1.4rem;line-height:1.3}
.oli-slogan .oli-emoji{font-family:"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif;font-size:.75em;line-height:1;display:inline-block;vertical-align:middle}
.oli-subpage-img{height:200px;margin-bottom:16px}
.oli-only-phone{display:inline-block;margin-top:10px}
.oli-float2 img{width:44px;height:44px;border-width:2px}
}
@media screen and (max-width:400px){
.oli-nav-wrap{padding:12px 14px;gap:8px}
.oli-logo{width:46px;height:46px}
.oli-nav-wrap>.oli-btn{padding:9px 12px;font-size:.78rem}
.oli-burger{padding:6px;margin-left:0}
.oli-wholesale-wrap .oli-btn{white-space:normal;max-width:100%;text-align:center}
}
@media screen and (max-width:359px){.oli-wa-long{display:none}}
"""
(SITE / "css").mkdir(parents=True, exist_ok=True)
(SITE / "css" / "oli.css").write_text(css)
import hashlib
CSS_V = hashlib.md5(css.encode()).hexdigest()[:8]

# video (se carga recién cuando entra en pantalla)
assets.append(("https://cdn.prod.website-files.com/6a90d29afcc3908981f2b9b4/6a917d0f3c816267db826463_oli-video.mp4", "media/oli-video.mp4", 0))

(ROOT / "assets.txt").write_text("".join(f"{u} {d} {w}\n" for u, d, w in assets))

# ---------- HTML ----------
import json, html as _html, re as _re
from urllib.parse import quote

DATA = json.loads((ROOT / "data" / "catalogo.json").read_text())
CATS = DATA["categorias"]

def wa(text):
    return f"{WA}?text={quote(text)}"

def line_url(slug):
    return f"/lineas-de-producto/{slug}"

def header(current):
    items = []
    for c in CATS:
        path = "/" + c["slug"]
        cur = ' aria-current="page"' if current == path else ""
        if c["lineas"]:
            menu = f'<a href="{path}" class="oli-navdrop-item oli-only-mobile">Ver todo {c["nombre"]}</a>' + "".join(
                f'<a href="{line_url(l["slug"])}" class="oli-navdrop-item{" w--current" if current == line_url(l["slug"]) else ""}">{l.get("menu", l["nombre"])}</a>'
                for l in sorted(c["lineas"], key=lambda x: x["orden"]))
            items.append(f'<div class="oli-navdrop"><a href="{path}" class="oli-navlink oli-navdrop-toggle"{cur}>{c["nombre"]}</a><div class="oli-navdrop-menu">{menu}</div></div>')
        else:
            items.append(f'<a href="{path}" class="oli-navlink{" w--current" if cur else ""}"{cur}>{c["nombre"]}</a>')
    return (f'<header class="oli-header"><div class="oli-nav-wrap"><a href="/" class="oli-logo" aria-label="Inicio" style="display:block"></a>'
            f'<nav class="oli-navlinks">{"".join(items)}</nav><a href="{WA}" class="oli-btn"><span class="oli-wa-long">Escribinos por </span>WhatsApp</a>'
            f'<button class="oli-burger" type="button" aria-label="Abrir menú" aria-expanded="false"><span></span><span></span><span></span></button></div></header>')

FOOTER = f'''<footer class="oli-footer"><div class="oli-footer-wrap"><div class="oli-footer-grid"><div><p class="oli-footer-logo"></p><p class="oli-footer-blurb">Accesorios y objetos hechos a mano, con amor, en Uruguay.</p></div><div><h3 class="oli-footer-h3">Contacto</h3><ul role="list" class="oli-footer-list"><li><a href="{WA}" class="oli-footer-link">WhatsApp</a></li><li><a href="https://www.instagram.com/olihandmadeaccesorios/" class="oli-footer-link">Instagram</a></li></ul></div></div><div class="oli-footer-bottom">La tiendita de Oli — Hecho a mano, con amor.<div class="oli-legal-links"><a href="/politica-de-privacidad" class="oli-legal-link">Política de Privacidad</a><a href="/terminos-y-condiciones" class="oli-legal-link">Términos y Condiciones</a><a href="/politica-de-cambios-y-devoluciones" class="oli-legal-link">Cambios y Devoluciones</a><a href="/politica-de-envios" class="oli-legal-link">Envíos</a></div></div></div></footer>'''

SCRIPTS = """<div class="oli-float2" id="oliFloat2"><img id="oliFloat2Img" src="/img/hola-soy-oli.webp" alt="Oli" width="64" height="64" loading="lazy"><span class="bubble" id="oliFloat2Text"></span></div>
<script>
(function(){
  var texts=['¡Hola! Soy Oli 👋','Que tengas un lindo día ✨','¡Qué lindo que me visites! 💛'];
  var corners=[{top:'18%',left:'6%'},{top:'30%',right:'6%',left:'auto'},{bottom:'14%',left:'8%'},{bottom:'22%',right:'8%',left:'auto'},{top:'55%',left:'4%'}];
  var el=document.getElementById('oliFloat2'),text=document.getElementById('oliFloat2Text');
  var reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function resetPos(){el.style.top=el.style.bottom=el.style.left=el.style.right='auto';}
  var phone=window.innerWidth<=767;
  function playScene(){
    var pos=phone?{bottom:'16px',left:'12px'}:corners[Math.floor(Math.random()*corners.length)];
    resetPos();Object.keys(pos).forEach(function(k){el.style[k]=pos[k];});
    text.textContent=texts[Math.floor(Math.random()*texts.length)];
    requestAnimationFrame(function(){el.classList.add('show');});
    setTimeout(function(){el.classList.remove('show');setTimeout(playScene,phone?(20000+Math.random()*10000):(4000+Math.random()*5000));},phone?2000:3200);
  }
  if(reduced){resetPos();el.style.bottom='20px';el.style.right='20px';text.textContent=texts[0];el.classList.add('show');}
  else setTimeout(playScene,phone?6000:1800);
  document.querySelectorAll('.oli-navdrop-toggle').forEach(function(t){
    t.addEventListener('click',function(e){if(window.innerWidth<=991){var p=t.closest('.oli-navdrop');if(p){e.preventDefault();p.classList.toggle('oli-navdrop-open');}}});
  });
  var hd=document.querySelector('.oli-header'),bg=document.querySelector('.oli-burger');
  if(hd&&bg){bg.addEventListener('click',function(){var o=hd.classList.toggle('menu-open');bg.setAttribute('aria-expanded',o?'true':'false');bg.setAttribute('aria-label',o?'Cerrar menú':'Abrir menú');});}
  var v=document.querySelector('video[data-src]');
  if(v&&'IntersectionObserver' in window){
    new IntersectionObserver(function(es,o){es.forEach(function(e){if(e.isIntersecting){v.src=v.dataset.src;v.play&&v.play().catch(function(){});o.disconnect();}});},{rootMargin:'200px'}).observe(v);
  } else if(v){v.src=v.dataset.src;}
})();
</script>"""

def page(title, desc, current, body, extra_head="", wrap=False):
    open_w, close_w = ('<div class="oli-page">', '</div>') if wrap else ('', '')
    return f'''<!DOCTYPE html>
<html lang="es" class="w-mod-js">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)}</title>
<meta name="description" content="{_html.escape(desc)}">
<link rel="preload" href="/fonts/Karla-Regular.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/fonts/Caveat-Bold.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/css/oli.css?v={CSS_V}">
<link rel="icon" href="/img/oli-logo.webp">
{extra_head}
</head>
<body>
{open_w}{header(current)}
{body}
{FOOTER}{close_w}
{SCRIPTS}
</body>
</html>
'''

def write(path, content):
    out = SITE / path.strip("/") / "index.html" if path != "/" else SITE / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content)
    return path

pages = []

# --- Home ---
HOME_BODY = f'''<div><section class="oli-hero"><div class="oli-hero-wrap"><div class="oli-hero-copy"><p class="oli-eyebrow">Hecho a mano en Uruguay</p><h1 class="oli-h1">Hola, soy Oli y te doy la bienvenida a mi tiendita!</h1><p class="oli-lead">Oli es un producto 100% artesanal, de principio a fin, hecho con todo el amor que llevamos dentro — porque todo lo que podemos brindarte es todo lo que somos.</p><div class="oli-hero-actions"><a href="{WA}" class="oli-btn">Escribinos por WhatsApp</a><a href="#categorias" class="oli-btn-ghost">Ver categorías</a></div><p class="oli-slogan">“En Oli hacemos arte para el pelo, arte en tela, arte para tu hogar y tu vida! <span class="oli-emoji">❤️</span>”</p></div><div class="oli-hero-portrait"></div></div></section><div class="oli-trust"><div class="oli-trust-wrap"><span class="oli-trust-item">🧵 100% artesanal</span><span class="oli-trust-item">🏡 Hecho en Uruguay</span><span class="oli-trust-item">📦 Envíos a todo el país</span></div></div></div>
<section class="oli-featured-section"><p class="oli-featured-eyebrow">Destacado del mes</p><h2 class="oli-featured-title">Moñas Clásicas</h2><p class="oli-featured-desc">Nuestro clásico de siempre — 4 tamaños y 5 tipos para elegir. El favorito de este mes, hecho a mano con todo el cariño de Oli.</p><a href="/lineas-de-producto/monas-clasicas" class="oli-btn">Ver este producto</a></section>
<section id="categorias" class="oli-cat-section"><div class="oli-section-wrap"><p class="oli-eyebrow oli-eyebrow-center">Nuestras categorías</p><h2 class="oli-h2-script">Cada tipo de magia, en su propio rincón</h2><div class="oli-cat-grid">
<a id="accesorios" href="/accesorios" class="oli-cat-card oli-cat-mustard"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Accesorios</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="cordones" href="/cordones" class="oli-cat-card oli-cat-sage"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Cordones</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="velas" href="/velas" class="oli-cat-card oli-cat-navy"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Velas</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="oli-colegio" href="/oli-colegio" class="oli-cat-card oli-cat-sagedeep"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Oli Colegio</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="navidad" href="/navidad" class="oli-cat-card oli-cat-rose-deep"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Navidad</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="cat-pascuas" href="/pascuas" class="oli-cat-card oli-cat-rose"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Pascuas</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
</div></div></section>
<section class="oli-video-section"><div class="oli-video-wrap"><video controls playsinline loop muted autoplay preload="none" data-src="/media/oli-video.mp4" class="oli-video"></video></div></section>
<section class="oli-editorial-section"><div class="oli-editorial-wrap"><p class="oli-eyebrow">Detrás de cada pieza</p><p class="oli-pull">“Nuestros productos son más que accesorios: son historias, son emociones, son experiencias — y muchas pruebas y errores.”</p><p class="oli-editorial-p">Todo lo que vas a encontrar en esta página está hecho de forma artesanal, manualmente, pieza por pieza. Nada es al azar.</p><p class="oli-editorial-p">Imperfectos, como todo lo hecho a mano — pero esa imperfección se nos volvió esencia. Cada producto que te llevás es una representación del amor y la dedicación que le ponemos.</p><p class="oli-editorial-p">Somos producto artesanal, 100% hecho en Uruguay, y eso es un valor agregado. Espero que esta experiencia sea mágica — porque sí, en Oli creemos en la magia. ✨</p></div></section>
<section class="oli-wholesale-section"><div class="oli-wholesale-wrap"><h2 class="oli-wholesale-h2">¿Tenés una tienda y querés llenarla de magia?</h2><p class="oli-wholesale-p">También armamos pedidos al por mayor. Escribile a Euge y coordinamos juntas los precios y los tiempos de entrega — con el mismo cariño de siempre, pero a lo grande.</p><a href="{WA}" class="oli-btn oli-btn-mustard">Hablar con Euge por WhatsApp</a></div></section>'''


pages.append(write("/", page(
    "La tiendita de Oli | Accesorios artesanales hechos a mano en Uruguay",
    "Moñas, accesorios, cordones, velas y más, hechos a mano con amor en Uruguay. Consultá por WhatsApp.",
    "/", HOME_BODY,
    '<link rel="preload" href="/img/hola-soy-oli.webp" as="image" fetchpriority="high">', wrap=True)))

# --- Categorías ---
for c in CATS:
    chips = "".join(f'<a href="{line_url(l["slug"])}" class="oli-prod-chip">{l.get("menu", l["nombre"])}</a>' for l in sorted(c["lineas"], key=lambda x: x["orden"]))
    body = (f'<section class="oli-cat-section"><div class="oli-section-wrap"><p class="oli-eyebrow oli-eyebrow-center">{c["nombre"]}</p>'
            f'<h1 class="oli-h2-script">{c["h1"]}</h1><p class="oli-lead">{c["lead"]}</p>'
            + (f'<div class="oli-prod-list">{chips}</div>' if chips else "")
            + f'<a href="{wa(c["wa_texto"])}" class="oli-btn">Consultar por WhatsApp</a></div></section>')
    pages.append(write("/" + c["slug"], page(c["title"], c["meta"], "/" + c["slug"], body)))

# --- Modelos ---
try:
    MODELOS = json.loads(MODELOS_FILE.read_text()) if MODELOS_FILE.exists() else []
except Exception as e:
    print("Aviso: no se pudo leer", MODELOS_FILE, e)
    MODELOS = []

def precio_fmt(p):
    return "$ " + f"{int(p):,}".replace(",", ".")

def models_section(slug):
    items = [m for m in MODELOS if m.get("linea") == slug and m.get("estado") == "publicado"]
    cards = ""
    for m in items:
        nombre = _html.escape(m["nombre"])
        fotos = m.get("fotos") or []
        img = f'<img src="{fotos[0]}" alt="{nombre}" class="oli-model-img" loading="lazy" width="400" height="500">' if fotos else ""
        vars_ = "".join(f'<span class="oli-model-var">{_html.escape(v)}</span>' for v in m.get("variantes") or [])
        msg = f'Hola! Quiero consultar por el modelo {m["nombre"]} (código {m["codigo"]})'
        cards += (f'<article class="oli-model-card" id="{m["codigo"]}">{img}<div class="oli-model-body">'
                  f'<span class="oli-model-code">Código {m["codigo"]}</span><h3 class="oli-model-name">{nombre}</h3>'
                  f'<p class="oli-model-desc">{_html.escape(m["descripcion"])}</p>'
                  f'<span class="oli-model-price">{precio_fmt(m["precio"])}</span>'
                  + (f'<div class="oli-model-vars">{vars_}</div>' if vars_ else "")
                  + f'<a href="{wa(msg)}" class="oli-btn">Consultar por WhatsApp</a></div></article>')
    grid = (f'<h2 class="oli-h2-script oli-models-title">Modelos</h2><div class="oli-model-grid">{cards}</div>') if cards else ""
    return (f'<section class="oli-models-section" id="modelos"><div class="oli-models-wrap">{grid}'
            f'<p class="oli-wholesale-note">Precios por mayor: a acordar con Euge por <a href="{WA}">WhatsApp</a></p></div></section>')

# --- Líneas ---
for c in CATS:
    for l in c["lineas"]:
        extra = f'<p class="oli-lead">{l["info_extra"]}</p>' if l.get("info_extra") else ""
        body = (f'<section class="oli-cat-section"><div class="oli-section-wrap oli-subpage-wrap">'
                f'<img src="/img/{c["imagen"]}.webp" alt="{_html.escape(l["nombre"])}" class="oli-subpage-img" width="1000" height="1000" loading="eager">'
                f'<p class="oli-eyebrow oli-eyebrow-center">{c["nombre"]}</p><h1 class="oli-h2-script">{l["nombre"]}</h1>{extra}'
                f'<div class="oli-editorial-p"><p>{l["descripcion"]}</p></div>'
                f'<a href="{wa(l["wa_texto"])}" class="oli-btn">Consultar por WhatsApp</a>'
                + (f'<a href="#modelos" class="oli-btn-ghost oli-only-phone">Ver modelos</a>' if any(m.get("linea") == l["slug"] and m.get("estado") == "publicado" for m in MODELOS) else "")
                + '</div></section>'
                + models_section(l["slug"]))
        title = f'{l["nombre"]} | {c["nombre"]} | La tiendita de Oli'
        pages.append(write(line_url(l["slug"]), page(title, l["descripcion"], line_url(l["slug"]), body)))

# --- Legales ---
def md_to_html(md):
    out, lst = [], False
    link = lambda t: _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" class="oli-legal-wa-link">\1</a>', _html.escape(t, quote=False))
    for block in md.strip().split("\n\n"):
        lines = block.strip().split("\n")
        if lines[0].startswith("## "):
            out.append(f'<h2 class="oli-legal-h2">{link(lines[0][3:])}</h2>')
        elif all(x.startswith("- ") for x in lines):
            out.append('<ul class="oli-legal-list">' + "".join(f'<li class="oli-legal-li">{link(x[2:])}</li>' for x in lines) + "</ul>")
        else:
            out.append(f'<p class="oli-legal-p">{link(" ".join(lines))}</p>')
    return "".join(out)

for f in sorted((ROOT / "data" / "legal").glob("*.md")):
    meta_txt, md = f.read_text().split("\n---\n", 1)
    meta = dict(x.split(": ", 1) for x in meta_txt.strip().split("\n"))
    body = (f'<section class="oli-legal-section"><div class="oli-legal-wrap"><p class="oli-eyebrow">Legal</p>'
            f'<h1 class="oli-legal-h1">{meta["h1"]}</h1><p class="oli-legal-updated">{meta["updated"]}</p>'
            + md_to_html(md) +
            f'<p class="oli-legal-p oli-legal-wa"><a href="{WA}" class="oli-legal-wa-link">wa.me/59899383602</a></p></div></section>')
    pages.append(write("/" + f.stem, page(meta["title"], meta["meta"], "/" + f.stem, body)))

# 404
(SITE / "404.html").write_text(page("Página no encontrada | La tiendita de Oli", "", "",
    '<section class="oli-cat-section"><div class="oli-section-wrap"><h1 class="oli-h2-script">Esta página no existe</h1><p class="oli-lead">Volvé al inicio o escribinos por WhatsApp.</p><a href="/" class="oli-btn">Ir al inicio</a></div></section>'))

(SITE / "sitemap.txt").write_text("".join(p + "\n" for p in pages))
print(f"OK: {len(pages)} páginas, {len(assets)} assets, css {len(css)//1024} KB")
