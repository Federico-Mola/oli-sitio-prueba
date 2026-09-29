#!/bin/sh
# Regenera las páginas con los modelos de /data/modelos.json al iniciar el contenedor.
python3 /app/build.py || echo "Aviso: no se pudieron regenerar las páginas"
