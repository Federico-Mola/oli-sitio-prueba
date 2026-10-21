"""Instala las tareas del servidor después de preparar su clave pública y destino de avisos."""
from pathlib import Path
import os,shutil,subprocess
if os.name!='posix' or os.geteuid()!=0:raise SystemExit('Ejecutar como root en el VPS de Oli.')
source=Path(__file__).resolve().parent;target=Path('/opt/oli-operacion')
target.mkdir(mode=0o700,exist_ok=True);target.chmod(0o700)
assert (target/'respaldo-publica.pem').is_file() and (target/'alertas.json').is_file(),'Preparar primero la clave pública de respaldo y el destino privado de avisos.'
for name in ['oli_operacion.py','restaurar_prueba.py']:
 if (source/name).resolve()!=(target/name).resolve():shutil.copy2(source/name,target/name)
for path in (source/'units').glob('oli-*'):
 assert path.suffix in ('.service','.timer')
 shutil.copy2(path,Path('/etc/systemd/system')/path.name)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','--now','oli-respaldo.timer','oli-monitor.timer'],check=True,capture_output=True)
print('Respaldos y supervisión de Oli instalados.')
