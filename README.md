# Oli — sitio de prueba (home + Cordones)

Prueba para comparar velocidad y calidad contra el sitio en Webflow antes de decidir la migración.

- `build.py`: genera `site/` (HTML y CSS) a partir del CSS de Webflow.
- `optimize.py`: descarga imágenes, fuentes y video de Webflow y los optimiza (WebP / WOFF2).
- `Dockerfile`: corre los dos scripts en el VPS y sirve el sitio con nginx (puerto 80).
- Deploy: EasyPanel → App → fuente GitHub → build por Dockerfile.

## Servicio del bot (oli_api.py)
- Corre dentro del mismo contenedor (puerto interno 8091) y nginx lo publica en `/api/`.
- n8n le manda cada mensaje autorizado del bot de Telegram a `POST /api/bot` y el servicio devuelve las respuestas ("acciones") que n8n envía.
- Guarda los modelos en `/data/modelos.json` y la carga en curso de cada persona en `/data/sesiones.json`.
- Pide el encabezado `X-Oli-Key` igual a la variable `OLI_API_KEY` (en el VPS: `/opt/oli-api.env`, fuera del repo). `GET /api/salud` no pide clave.
