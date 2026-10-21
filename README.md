# Oli — sitio de prueba (home + Cordones)

Prueba para comparar velocidad y calidad contra el sitio en Webflow antes de decidir la migración.

- `build.py`: genera `site/` (HTML y CSS) a partir del CSS de Webflow.
- `optimize.py`: descarga imágenes, fuentes y video de Webflow y los optimiza (WebP / WOFF2).
- `Dockerfile`: corre los dos scripts en el VPS y sirve el sitio con nginx (puerto 80).
- Deploy: EasyPanel → App → fuente GitHub → build por Dockerfile.

## Servicio del bot (oli_api.py)

### Publicación desde Telegram

- Al terminar una carga, la vista previa ofrece **Publicar**. `/borradores` o el botón **Borradores** del menú permiten recuperar los modelos guardados anteriormente.
- Publicar requiere `OLI_ALLOWED_USER_IDS` (IDs separados por coma), además de la clave entre n8n y la API. Debe coincidir con la lista autorizada del workflow; sin esta variable se rechaza la publicación.
- Valida datos y fotos, genera una copia del sitio y cambia un enlace simbólico para activarla completa. Un fallo de generación conserva el borrador y la web anterior. Un clic repetido devuelve el mismo enlace.
- `40-oli-build.sh` prepara `/usr/share/nginx/html` como enlace a una versión del sitio. No ejecutar el generador manualmente contra el sitio en servicio durante una publicación.
- Pruebas aisladas en Linux: `python3 -m unittest -v test_publicacion` (requiere los archivos de aplicación y `webflow.css`, como la imagen Docker). No usa Telegram ni datos reales.

- Corre dentro del mismo contenedor (puerto interno 8091) y nginx lo publica en `/api/`.
- n8n le manda cada mensaje autorizado del bot de Telegram a `POST /api/bot`. El servicio arma las respuestas y las manda directo a Telegram (así puede usar botones que cambian según el caso).
- Guarda los modelos en `/data/modelos.json` y la carga en curso de cada persona en `/data/sesiones.json`.
- Pide el encabezado `X-Oli-Key` igual a la variable `OLI_API_KEY`. Usa el token del bot en `OLI_BOT_TOKEN`. Las dos están en el VPS en `/opt/oli-api.env` (solo root, fuera del repo). `GET /api/salud` no pide clave.


## Agente Oli publicado

Desde el 21/10/2026 la tienda incluye atención con IA en /oli-asistente/. El servicio propio usa Z.AI y memoria separada del bot de carga. Despliegue persistente de ambos servicios: deploy/compose.yaml. Ver agente/README.md para construcción, controles, privacidad y reversión. El propietario retiró el tope monetario de las pruebas. Mantener las claves y las bases de estado fuera del repositorio.
