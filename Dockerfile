# Etapa 1: generar el sitio y optimizar imágenes, fuentes y video
FROM python:3.12-slim AS build
WORKDIR /build
RUN pip install --no-cache-dir pillow fonttools brotli
COPY build.py optimize.py ./
COPY data ./data
ADD https://cdn.prod.website-files.com/6a90d29afcc3908981f2b9b4/css/oli-sitio.webflow.shared.af3c6f3e2.css webflow.css
RUN python build.py && python optimize.py site

# Etapa 2: servir el sitio estático con nginx
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/site /usr/share/nginx/html
EXPOSE 80
