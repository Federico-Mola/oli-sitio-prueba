# Etapa 1: generar el sitio y optimizar imágenes, fuentes y video
FROM python:3.12-slim AS build
WORKDIR /build
RUN pip install --no-cache-dir pillow fonttools brotli
COPY build.py optimize.py ./
COPY data ./data
ADD https://cdn.prod.website-files.com/6a90d29afcc3908981f2b9b4/css/oli-sitio.webflow.shared.af3c6f3e2.css webflow.css
RUN python build.py && python optimize.py site

# Etapa 2: nginx + python para regenerar las páginas con los modelos guardados en /data
FROM nginx:1.27-alpine
RUN apk add --no-cache python3 py3-pillow
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/site /usr/share/nginx/html
COPY --from=build /build/build.py /build/webflow.css /app/
COPY oli_api.py /app/
COPY data /app/data
COPY 40-oli-build.sh /docker-entrypoint.d/40-oli-build.sh
COPY 45-oli-api.sh /docker-entrypoint.d/45-oli-api.sh
RUN chmod +x /docker-entrypoint.d/40-oli-build.sh /docker-entrypoint.d/45-oli-api.sh
ENV SITE_DIR=/usr/share/nginx/html MODELOS_FILE=/data/modelos.json DATA_DIR=/data
EXPOSE 80
