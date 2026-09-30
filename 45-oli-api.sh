#!/bin/sh
# Arranca el servicio interno del bot (oli_api.py) en segundo plano, antes de nginx.
# La clave llega por la variable OLI_API_KEY (docker run --env-file /opt/oli-api.env).
nohup python3 /app/oli_api.py >> /proc/1/fd/1 2>&1 &
