# Agente Oli: atención web publicada

Publicado el 21/10/2026 por autorización del propietario en https://www.latienditadeoli.com.

Servicio Python propio, GLM-5.3-FlashX de Z.AI, memoria por sesión en SQLite y widget aislado en iframe del mismo origen. El personaje es el dibujo original entregado por el propietario. No se modificaron los workflows de Telegram, Lola o Martina y no se conectaron Instagram/Facebook.

## Uso y privacidad

- El agente se abre con Hablá con Oli, sin apertura automática.
- Consulta de catálogo de solo lectura: solo publicados con código comercial aprobado. La lista está vacía hasta revisión de Euge.
- No confirma pedidos, pagos, disponibilidad, descuentos o soluciones de reclamos.
- Contacto por WhatsApp con texto editable y envío por acción de la persona.
- Cookie HttpOnly/Secure/SameSite=Strict, Host y Origin verificados y proxy interno autorizado.
- Contexto de ocho intercambios, caducidad por 24 horas de inactividad y limpieza cada cinco minutos.
- No hay tope monetario ni máximo total de llamadas; se mantiene contabilidad técnica. El propietario retiró expresamente el límite de USD 2 y pidió ajustar luego según uso.
- Se mantienen controles por longitud, IP seudonimizada, frecuencia y concurrencia contra abuso.

## Despliegue

Contenedores oli-sitio-prueba y oli-agente. Configuración persistente en deploy/compose.yaml, red externa oli-atencion (172.19.0.0/16), IP del sitio 172.19.0.3 y del agente 172.19.0.2. nginx publica /oli-asistente/ sobre HTTPS; el puerto directo 8094 permanece en 127.0.0.1.

Construir desde la raíz del repositorio:

```sh
docker build -t oli-sitio-prueba:agente-v1 .
docker build -t oli-agente:produccion-v2 agente
docker compose -f deploy/compose.yaml up -d
```

Las rutas de estado y conexión /opt/oli-agent-preview/state y /opt/oli-agent-preview/private/provider.json se conservan por continuidad de la primera instalación; su nombre histórico no indica que el servicio actual sea privado. El archivo de conexión y /opt/oli-api.env nunca van al repositorio. El entorno no configura OLI_BUDGET_USD. Si en el futuro se define, el servicio vuelve a aplicar ese tope explícito.

La red debe existir con el rango indicado antes de recuperar en un VPS nuevo. /opt/oli-data contiene el catálogo y las fotos fuera del repositorio. El modelo requiere saldo y acceso válido en Z.AI; el retiro del tope de software no otorga consumo gratuito.

## Pruebas y reversión

21 pruebas automáticas técnicas, más conversaciones reales privadas y públicas. Ejecutar pruebas técnicas con python -m unittest discover -s agente/tests -q desde la raíz. No consumen API. Los casos pagados están documentados fuera del repositorio, no se ejecutan al correr unittest.

Respaldo privado anterior a la publicación: /opt/oli-backups/agente-web-20261021T131948Z. Se preservan contenedores detenidos del sitio y agente anteriores. Para una reversión completa, detener los servicios nuevos y restaurar los contenedores anteriores según la documentación operativa, conservando estado y catálogo. No iniciar dos versiones del agente sobre la misma base.

La matriz de navegadores/dispositivos continúa abierta a ajustes con uso real. El chequeo visible se hizo en el navegador del propietario, incluida apertura, respuesta, cierre y navegación. El catálogo comercial requiere confirmación con Euge.
