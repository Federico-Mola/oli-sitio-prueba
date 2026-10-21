"""Activa imágenes ya probadas. Conserva configuración previa y revierte si falla la verificación."""
from pathlib import Path
import hashlib,json,subprocess,time,urllib.request

def run(args,timeout=120):
    r=subprocess.run(args,capture_output=True,timeout=timeout)
    if r.returncode:raise RuntimeError('Falló '+args[0])
    return r.stdout
root=Path('/opt/oli-operacion');current=Path('/opt/oli-despliegue/compose.yaml')
assert '\nOK\n' in Path('/opt/oli-gestion-tests-final.log').read_text(),'Las pruebas finales deben pasar'
old=current.read_bytes();(root/'compose-anterior-gestion.json').write_bytes(old)
before=hashlib.sha256(Path('/opt/oli-data/modelos.json').read_bytes()).hexdigest()
candidate=json.loads(Path('/opt/oli-gestion-v2/deploy/compose.yaml').read_text())
# El puerto directo se cerrará al completar la migración del nodo n8n a HTTPS.
candidate['services']['sitio']['ports']=['8088:80']
current.write_text(json.dumps(candidate,indent=2))
try:
    run(['docker','compose','-f',str(current),'config','-q'])
    run(['docker','compose','-f',str(current),'up','-d','--wait','--wait-timeout','90'])
    for url in ['https://www.latienditadeoli.com/','https://www.latienditadeoli.com/api/salud','https://www.latienditadeoli.com/carga-oli/','https://www.latienditadeoli.com/oli-asistente/api/salud']:
        with urllib.request.urlopen(url,timeout=15) as response:assert response.status==200
    with urllib.request.urlopen('https://www.latienditadeoli.com/api/salud',timeout=10) as r:assert json.load(r)['version']=='gestion-v2'
    assert hashlib.sha256(Path('/opt/oli-data/modelos.json').read_bytes()).hexdigest()==before,'El catálogo cambió durante el despliegue'
except Exception:
    current.write_bytes(old)
    run(['docker','compose','-f',str(current),'up','-d','--wait','--wait-timeout','90'])
    raise
report={'gestion_telegram':'desplegada','sitio':200,'subida_privada':200,'catalogo_conservado':True,'modelos':len(json.loads(Path('/opt/oli-data/modelos.json').read_text())),'transporte_n8n':'pendiente_rotacion_coordinada'}
(root/'DESPLIEGUE-GESTION.json').write_text(json.dumps(report));print(json.dumps(report))
