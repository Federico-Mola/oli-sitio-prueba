#!/bin/sh
set -eu
# Regenera las páginas con los modelos de /data/modelos.json al iniciar el contenedor.
# El enlace permite activar una publicación completa sin borrar el sitio servido.
if [ ! -L "$SITE_DIR" ]; then
    mkdir -p "${SITE_DIR}.releases"
    mv "$SITE_DIR" "${SITE_DIR}.releases/inicial"
    ln -s "${SITE_DIR}.releases/inicial" "$SITE_DIR"
fi
python3 /app/build.py
