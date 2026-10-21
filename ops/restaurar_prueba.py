"""Recibe una clave efímera por stdin SSH; restaura solo en un directorio temporal privado."""
import base64, hashlib, io, json, os
from pathlib import Path
import sqlite3, subprocess, sys, tarfile, tempfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

os.umask(0o077)
request=json.load(sys.stdin)
name=request['archivo']
if Path(name).name!=name or not name.startswith('oli-') or not name.endswith('.olibak'):raise SystemExit('Nombre no válido')
backup=Path('/opt/oli-backups/automaticos')/name
key=base64.b64decode(request['clave_efimera'])
with tempfile.TemporaryDirectory(prefix='restauracion-probada-',dir='/opt/oli-operacion') as temp:
    root=Path(temp)
    plain=root/'contenido.tgz'
    with backup.open('rb') as source,plain.open('xb') as output:
        magic=source.readline(4096);header=source.readline(4096);assert magic==b'OLI-BACKUP-1\n'
        info=json.loads(header);offset=source.tell();source.seek(-16,os.SEEK_END);tag=source.read(16);remaining=backup.stat().st_size-offset-16;source.seek(offset)
        decryptor=Cipher(algorithms.AES(key),modes.GCM(base64.b64decode(info['nonce']),tag)).decryptor();decryptor.authenticate_additional_data(magic+header)
        while remaining:
            chunk=source.read(min(1024*1024,remaining));assert chunk;remaining-=len(chunk);output.write(decryptor.update(chunk))
        output.write(decryptor.finalize())
    with tarfile.open(plain,mode='r:gz') as f:f.extractall(root,filter='data')
    root=root/'oli';manifest=json.loads((root/'MANIFIESTO.json').read_text())
    for name,digest in manifest['archivos'].items():
        file=(root/name).resolve();assert file.is_relative_to(root.resolve())
        sha=hashlib.sha256()
        with file.open('rb') as content:
            for chunk in iter(lambda:content.read(1024*1024),b''):sha.update(chunk)
        assert sha.hexdigest()==digest,'Archivo distinto al respaldo'
    dbs=0
    for file in root.rglob('*.sqlite'):
        with sqlite3.connect('file:'+str(file)+'?mode=ro',uri=True) as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        dbs+=1
    code="""import pathlib,shutil,subprocess,sys,json
sys.path.insert(0,'/app')
shutil.copytree('/restaurada','/tmp/restaurada')
r=subprocess.run([sys.executable,'/app/build.py'],capture_output=True);assert r.returncode==0
models=json.loads(pathlib.Path('/data/modelos.json').read_text())
assert len(models)>0
for m in models:
 if m['estado']=='publicado':
  import oli_publicacion as p
  assert (pathlib.Path('/tmp/restaurada')/p.ruta_modelo(m).lstrip('/')/'index.html').is_file()
print('Sitio reconstruido desde respaldo sin red')
"""
    cmd=['docker','run','--rm','--network','none','--memory','512m','--cpus','0.7','--mount','type=bind,src='+str(root/'datos')+',dst=/data,readonly','--mount','type=bind,src='+str(root/'publica')+',dst=/restaurada,readonly','-e','SITE_DIR=/tmp/restaurada','-e','SITE_URL=https://www.latienditadeoli.com','--entrypoint','python3','oli-sitio-prueba:gestion-v2','-c',code]
    r=subprocess.run(cmd,capture_output=True,timeout=90)
    assert r.returncode==0,'La reconstrucción aislada no pasó'
    report={'fecha':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='seconds'),'archivo':request['archivo'],'archivos':len(manifest['archivos']),'modelos':manifest['modelos'],'sqlite_integras':dbs,'sitio_reconstruido':True,'produccion_modificada':False}
    Path('/opt/oli-operacion/ultima-restauracion.json').write_text(json.dumps(report))
    print(json.dumps(report))
