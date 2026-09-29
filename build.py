"""Genera el sitio estático de prueba de Oli (home + Cordones) a partir del CSS de Webflow.

Salida:
  site/css/oli.css, site/index.html, site/cordones/index.html
  assets.txt  -> lista "URL destino ancho_max" que el Dockerfile descarga y optimiza en el VPS
"""
import re, pathlib

ROOT = pathlib.Path(__file__).parent
SITE = ROOT / "site"
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
@media screen and (max-width:479px){.oli-float2{gap:8px;max-width:calc(100vw - 24px)}.oli-float2 img{width:48px;height:48px;flex:none}.oli-float2 .bubble{font-size:.78rem;padding:7px 12px;white-space:normal;max-width:62vw;line-height:1.3}}
"""
(SITE / "css").mkdir(parents=True, exist_ok=True)
(SITE / "css" / "oli.css").write_text(css)

# video (se carga recién cuando entra en pantalla)
assets.append(("https://cdn.prod.website-files.com/6a90d29afcc3908981f2b9b4/6a917d0f3c816267db826463_oli-video.mp4", "media/oli-video.mp4", 0))

(ROOT / "assets.txt").write_text("".join(f"{u} {d} {w}\n" for u, d, w in assets))

# ---------- HTML ----------
LOCAL = {"/", "/cordones"}

def link(path):
    return path if path in LOCAL else WF + path

NAV = [
    ("Accesorios", "/accesorios", [("Moñas Clásicas", "monas-clasicas"), ("Moñas Patas Largas", "monas-patas-largas"), ("Moñas Dobles", "monas-dobles"), ("Scrunchies", "scrunchies"), ("Sapitos", "sapitos"), ("Tiaras", "tiaras")]),
    ("Cordones", "/cordones", []),
    ("Velas", "/velas", [("Pintadas a Mano", "velas-pintadas-a-mano"), ("Velas c/ Dijes", "velas-con-dijes"), ("Velas Número", "velas-numero"), ("Casa Fósforos", "casa-fosforos")]),
    ("Oli Colegio", "/oli-colegio", [("Moñas Colegio", "monas-colegio"), ("Set Individuales", "set-individuales")]),
    ("Navidad", "/navidad", [("Calendario Adviento", "calendario-adviento"), ("Juego Notas para Manifestar", "juego-notas-manifestar")]),
    ("Pascuas", "/pascuas", [("Conejos", "conejos-pascua"), ("Velas", "velas-pascua"), ("Zanahorias", "zanahorias-pascua"), ("Bolsas", "bolsas-pascua")]),
]

def header(current):
    items = []
    for name, path, subs in NAV:
        cur = ' aria-current="page"' if path == current else ""
        if subs:
            menu = "".join(f'<a href="{link("/lineas-de-producto/" + s)}" class="oli-navdrop-item">{n}</a>' for n, s in subs)
            items.append(f'<div class="oli-navdrop"><a href="{link(path)}" class="oli-navlink oli-navdrop-toggle"{cur}>{name}</a><div class="oli-navdrop-menu">{menu}</div></div>')
        else:
            items.append(f'<a href="{link(path)}" class="oli-navlink{" w--current" if cur else ""}"{cur}>{name}</a>')
    return (f'<header class="oli-header"><div class="oli-nav-wrap"><div class="oli-logo"></div>'
            f'<nav class="oli-navlinks">{"".join(items)}</nav><a href="{WA}" class="oli-btn">Escribinos por WhatsApp</a></div></header>')

FOOTER = f'''<footer class="oli-footer"><div class="oli-footer-wrap"><div class="oli-footer-grid"><div><p class="oli-footer-logo"></p><p class="oli-footer-blurb">Accesorios y objetos hechos a mano, con amor, en Uruguay.</p></div><div><h3 class="oli-footer-h3">Contacto</h3><ul role="list" class="oli-footer-list"><li><a href="{WA}" class="oli-footer-link">WhatsApp</a></li><li><a href="https://www.instagram.com/olihandmadeaccesorios/" class="oli-footer-link">Instagram</a></li></ul></div></div><div class="oli-footer-bottom">La tiendita de Oli — Hecho a mano, con amor.<div class="oli-legal-links"><a href="{WF}/politica-de-privacidad" class="oli-legal-link">Política de Privacidad</a><a href="{WF}/terminos-y-condiciones" class="oli-legal-link">Términos y Condiciones</a><a href="{WF}/politica-de-cambios-y-devoluciones" class="oli-legal-link">Cambios y Devoluciones</a><a href="{WF}/politica-de-envios" class="oli-legal-link">Envíos</a></div></div></div></footer>'''

SCRIPTS = """<div class="oli-float2" id="oliFloat2"><img id="oliFloat2Img" src="/img/hola-soy-oli.webp" alt="Oli" width="64" height="64" loading="lazy"><span class="bubble" id="oliFloat2Text"></span></div>
<script>
(function(){
  var texts=['¡Hola! Soy Oli 👋','Que tengas un lindo día ✨','¡Qué lindo que me visites! 💛'];
  var corners=[{top:'18%',left:'6%'},{top:'30%',right:'6%',left:'auto'},{bottom:'14%',left:'8%'},{bottom:'22%',right:'8%',left:'auto'},{top:'55%',left:'4%'}];
  var el=document.getElementById('oliFloat2'),text=document.getElementById('oliFloat2Text');
  var reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function resetPos(){el.style.top=el.style.bottom=el.style.left=el.style.right='auto';}
  function playScene(){
    var pos=corners[Math.floor(Math.random()*corners.length)];
    resetPos();Object.keys(pos).forEach(function(k){el.style[k]=pos[k];});
    text.textContent=texts[Math.floor(Math.random()*texts.length)];
    requestAnimationFrame(function(){el.classList.add('show');});
    setTimeout(function(){el.classList.remove('show');setTimeout(playScene,4000+Math.random()*5000);},3200);
  }
  if(reduced){resetPos();el.style.bottom='20px';el.style.right='20px';text.textContent=texts[0];el.classList.add('show');}
  else setTimeout(playScene,1800);
  document.querySelectorAll('.oli-navdrop-toggle').forEach(function(t){
    t.addEventListener('click',function(e){if(window.innerWidth<=991){var p=t.closest('.oli-navdrop');if(p){e.preventDefault();p.classList.toggle('oli-navdrop-open');}}});
  });
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
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="preload" href="/fonts/Karla-Regular.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/fonts/Caveat-Bold.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/css/oli.css">
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

HOME_BODY = f'''<div><section class="oli-hero"><div class="oli-hero-wrap"><div class="oli-hero-copy"><p class="oli-eyebrow">Hecho a mano en Uruguay</p><h1 class="oli-h1">Hola, soy Oli y te doy la bienvenida a mi tiendita!</h1><p class="oli-lead">Oli es un producto 100% artesanal, de principio a fin, hecho con todo el amor que llevamos dentro — porque todo lo que podemos brindarte es todo lo que somos.</p><div class="oli-hero-actions"><a href="{WA}" class="oli-btn">Escribinos por WhatsApp</a><a href="#categorias" class="oli-btn-ghost">Ver categorías</a></div><p class="oli-slogan">“En Oli hacemos arte para el pelo, arte en tela, arte para tu hogar y tu vida! ❤️”</p></div><div class="oli-hero-portrait"></div></div></section><div class="oli-trust"><div class="oli-trust-wrap"><span class="oli-trust-item">🧵 100% artesanal</span><span class="oli-trust-item">🏡 Hecho en Uruguay</span><span class="oli-trust-item">📦 Envíos a todo el país</span></div></div></div>
<section class="oli-featured-section"><p class="oli-featured-eyebrow">Destacado del mes</p><h2 class="oli-featured-title">Moñas Clásicas</h2><p class="oli-featured-desc">Nuestro clásico de siempre — 4 tamaños y 5 tipos para elegir. El favorito de este mes, hecho a mano con todo el cariño de Oli.</p><a href="{WF}/lineas-de-producto/monas-clasicas" class="oli-btn">Ver este producto</a></section>
<section id="categorias" class="oli-cat-section"><div class="oli-section-wrap"><p class="oli-eyebrow oli-eyebrow-center">Nuestras categorías</p><h2 class="oli-h2-script">Cada tipo de magia, en su propio rincón</h2><div class="oli-cat-grid">
<a id="accesorios" href="{link('/accesorios')}" class="oli-cat-card oli-cat-mustard"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Accesorios</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="cordones" href="/cordones" class="oli-cat-card oli-cat-sage"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Cordones</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="velas" href="{link('/velas')}" class="oli-cat-card oli-cat-navy"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Velas</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="oli-colegio" href="{link('/oli-colegio')}" class="oli-cat-card oli-cat-sagedeep"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Oli Colegio</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="navidad" href="{link('/navidad')}" class="oli-cat-card oli-cat-rose-deep"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Navidad</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
<a id="cat-pascuas" href="{link('/pascuas')}" class="oli-cat-card oli-cat-rose"><span class="oli-cat-body"><span class="oli-cat-name oli-cat-name-light">Pascuas</span><span class="oli-cat-tag oli-cat-tag-light">Foto real</span></span></a>
</div></div></section>
<section class="oli-video-section"><div class="oli-video-wrap"><video controls playsinline loop muted autoplay preload="none" data-src="/media/oli-video.mp4" class="oli-video"></video></div></section>
<section class="oli-editorial-section"><div class="oli-editorial-wrap"><p class="oli-eyebrow">Detrás de cada pieza</p><p class="oli-pull">“Nuestros productos son más que accesorios: son historias, son emociones, son experiencias — y muchas pruebas y errores.”</p><p class="oli-editorial-p">Todo lo que vas a encontrar en esta página está hecho de forma artesanal, manualmente, pieza por pieza. Nada es al azar.</p><p class="oli-editorial-p">Imperfectos, como todo lo hecho a mano — pero esa imperfección se nos volvió esencia. Cada producto que te llevás es una representación del amor y la dedicación que le ponemos.</p><p class="oli-editorial-p">Somos producto artesanal, 100% hecho en Uruguay, y eso es un valor agregado. Espero que esta experiencia sea mágica — porque sí, en Oli creemos en la magia. ✨</p></div></section>
<section class="oli-wholesale-section"><div class="oli-wholesale-wrap"><h2 class="oli-wholesale-h2">¿Tenés una tienda y querés llenarla de magia?</h2><p class="oli-wholesale-p">También armamos pedidos al por mayor. Escribile a Euge y coordinamos juntas los precios y los tiempos de entrega — con el mismo cariño de siempre, pero a lo grande.</p><a href="{WA}" class="oli-btn oli-btn-mustard">Hablar con Euge por WhatsApp</a></div></section>'''

CORDONES_BODY = f'''<section class="oli-cat-section"><div class="oli-section-wrap"><p class="oli-eyebrow oli-eyebrow-center">Cordones</p><h1 class="oli-h2-script">Los famosos “cordoolis” de Oli</h1><p class="oli-lead">Cordones para no perder nunca más las moñas ni los chupetes. Arte en tela, hecho a mano.</p><a href="{WA}?text=Hola!%20Quiero%20consultar%20sobre%20los%20Cordones" class="oli-btn">Consultar por WhatsApp</a></div></section>'''

(SITE / "index.html").write_text(page(
    "La tiendita de Oli | Accesorios artesanales hechos a mano en Uruguay",
    "Moñas, accesorios, cordones, velas y más, hechos a mano con amor en Uruguay. Consultá por WhatsApp.",
    "/", HOME_BODY,
    '<link rel="preload" href="/img/hola-soy-oli.webp" as="image" fetchpriority="high">', wrap=True))
(SITE / "cordones").mkdir(exist_ok=True)
(SITE / "cordones" / "index.html").write_text(page(
    "Cordones Artesanales para Moñas y Chupetes | La tiendita de Oli",
    "Los famosos &quot;cordoolis&quot; de Oli — cordones artesanales hechos a mano en Uruguay para no perder nunca más las moñas ni los chupetes. Consultá por WhatsApp.",
    "/cordones", CORDONES_BODY))
print(f"OK: {len(assets)} assets, css {len(css)//1024} KB")
