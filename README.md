# Oli — sitio de prueba (home + Cordones)

Prueba para comparar velocidad y calidad contra el sitio en Webflow antes de decidir la migración.

- `build.py`: genera `site/` (HTML y CSS) a partir del CSS de Webflow.
- `optimize.py`: descarga imágenes, fuentes y video de Webflow y los optimiza (WebP / WOFF2).
- `Dockerfile`: corre los dos scripts en el VPS y sirve el sitio con nginx (puerto 80).
- Deploy: EasyPanel → App → fuente GitHub → build por Dockerfile.
