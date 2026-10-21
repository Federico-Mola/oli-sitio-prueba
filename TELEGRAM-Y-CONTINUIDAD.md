# Telegram y continuidad de Oli

La administración se usa desde el chat privado de `@oli_carga_bot`. Solo acceden los usuarios autorizados en el servicio y en n8n. `/menu` conserva el avance; `/continuar` retoma una carga. La tienda pública es https://www.latienditadeoli.com.

## Operación diaria

- **Cargar modelo:** categoría/línea, nombre, descripción, precio orientativo, variantes y archivos. Guardar crea un borrador; Publicar pide confirmación.
- **Buscar modelo:** por nombre o código. Editar datos, fotos, portada, orden y video; Guardar cambios pide confirmación y detecta si otra persona cambió el producto.
- **Ocultar / volver a mostrar:** conserva código y archivos. Los borradores se pueden archivar y recuperar.
- **Aprobar para Oli:** habilita recomendaciones solo si el producto está publicado. No convierte por sí sola un modelo en publicación. Los productos de prueba requieren revisión comercial de Euge.
- **Archivos grandes:** el enlace privado del bot dura quince minutos y se vincula a la carga o edición. Fotos JPG/PNG/WebP de hasta 50 MB y 40 megapíxeles; un video MP4/MOV/WebM de hasta 100 MB y tres minutos. Revisar y guardar desde Telegram después de subir.

Los precios distintos por variante no se deducen de las etiquetas: la ficha tiene un precio orientativo y la consulta se deriva a Euge. Ocultar retira la ficha y las recomendaciones; no elimina copias que una persona ya haya descargado.

## Despliegue

El sitio y el agente siguen en Docker Compose, fuera de la gestión de aplicaciones de EasyPanel. `deploy/compose.yaml` conserva datos y estado. El puerto del sitio se enlaza solo a la dirección privada del puente que usa Traefik; el acceso público es por el dominio HTTPS.

Los secretos se preparan exclusivamente en el VPS: `/opt/oli-api.env` y el archivo privado del proveedor del agente. Nunca copiarlos al repositorio o a la documentación. La conexión de n8n usa HTTPS y la credencial `Oli API`, con encabezado `X-Oli-Key`. Se conserva un único trigger por bot.

Compilar la imagen del sitio con el Dockerfile de la raíz y la del agente con `agente/Dockerfile`. Verificar pruebas, conservar la configuración anterior y activar con Compose. La base y las fotos se respaldan antes de intervenir. No publicar modelos reales como prueba automática de despliegue.

## Respaldos y avisos

`ops/oli_operacion.py` genera archivos `.olibak` autenticados con AES-256-GCM y una clave de archivo envuelta con RSA-OAEP. El VPS guarda únicamente la clave pública. La clave privada de recuperación permanece en la carpeta privada del propietario en su PC; no incluirla en este repositorio, en capturas ni en documentos compartidos.

La tarea del VPS respalda diariamente datos, fotos, sesiones, bases SQLite consistentes, fuente, recursos web, configuración privada y workflow de Oli. Se conservan catorce copias diarias y hasta ocho semanales, además de los respaldos de intervención protegidos. La copia externa de Windows se verifica al copiar; necesita la PC encendida y la sesión del propietario disponible.

El monitor comprueba tienda, bot, agente, n8n, workflow activo, errores recientes, espacio y antigüedad de las copias. Envía avisos técnicos al propietario, con supresión de avisos repetidos y aviso de recuperación. No hace llamadas pagas al modelo para supervisar.

`ops/instalar_operacion.py` instala las unidades del servidor cuando están preparados su certificado público y el destino privado de avisos. La tarea de Windows ejecuta `ops/respaldo_pc.py` desde la carpeta privada del propietario. No borrar la clave privada de recuperación.

## Restauración

La prueba independiente descifra una copia con una clave efímera enviada por SSH, verifica el manifiesto, comprueba SQLite y reconstruye las páginas en un contenedor aislado. No restaura sobre producción.

Para recuperar el sistema, usar los componentes de una misma copia: datos, configuración y claves de cifrado deben corresponderse. El archivo incluye recursos optimizados para no depender del CDN del diseño. `ops/Dockerfile.restauracion` se compila desde la raíz `oli/` del archivo descifrado y usa `fuente/` y `publica/`.

Las copias de intervención también incluyen la base compartida de n8n y las bases de Evolution, con sus configuraciones de fecha correspondiente. Una restauración completa de n8n debe preservar la clave principal y las claves secundarias que cifran sus credenciales.

Los scripts de rotación son herramientas de mantenimiento para la versión de n8n comprobada. Exigen prueba previa con copia del entorno y respaldo externo; no forman parte de las tareas diarias. El adaptador de cifrado usa las clases de la instalación y mantiene deshabilitadas las funciones experimentales que no estaban activas.

## Validación de uso

Las pruebas automáticas se ejecutan sin Telegram real ni consumo del proveedor. La aceptación final de operación consiste en que Euge cargue un modelo real desde su teléfono, lo corrija, revise fotos/video, publique, cambie sus datos, oculte y recupere. VEL-0004 no se publica automáticamente.
