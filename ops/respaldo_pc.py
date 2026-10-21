"""Copia externa cifrada. No muestra ni transmite la clave privada de recuperación."""
import base64, datetime, hashlib, io, json, os
from pathlib import Path
import re, shutil, subprocess, sys, tarfile, tempfile
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

home=Path.home();private=home/'.oli-secrets';out=home/'Documents/Respaldos Oli';out.mkdir(parents=True,exist_ok=True)
ssh=['ssh','-i',str(home/'.ssh/modo-autonomo-codex-ed25519'),'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','root@179.198.102.28']
def run(args,**kw):
    r=subprocess.run(args,capture_output=True,timeout=180,**kw)
    if r.returncode:raise RuntimeError('No se pudo completar la copia o verificación remota')
    return r.stdout
try:
    newest=json.loads(run(ssh+['cat /opt/oli-operacion/ultimo-respaldo.json']))
    name=newest['archivo']
    if not re.fullmatch(r'oli-\d{8}T\d{6}Z\.olibak',name):raise RuntimeError('Nombre no válido')
    if shutil.disk_usage(out).free<newest.get('bytes',0)*2+1024**3:raise RuntimeError('Falta espacio para copiar y verificar sin llenar el disco')
    dest=out/name
    if not dest.exists():
        tmp=out/('.'+name)
        run(['scp']+ssh[1:-1]+['root@179.198.102.28:/opt/oli-backups/automaticos/'+name,str(tmp)])
        os.replace(tmp,dest)
    with dest.open('rb') as source,tempfile.TemporaryFile(dir=private) as plain:
        magic=source.readline(4096);header=source.readline(4096)
        if magic!=b'OLI-BACKUP-1\n':raise RuntimeError('Formato no válido')
        h=json.loads(header);offset=source.tell();source.seek(-16,os.SEEK_END);tag=source.read(16);remaining=dest.stat().st_size-offset-16;source.seek(offset)
        key=serialization.load_pem_private_key((private/'respaldo-oli-privada.pem').read_bytes(),password=None)
        ephemeral=key.decrypt(base64.b64decode(h['clave']),padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        decryptor=Cipher(algorithms.AES(ephemeral),modes.GCM(base64.b64decode(h['nonce']),tag)).decryptor();decryptor.authenticate_additional_data(magic+header)
        while remaining:
            chunk=source.read(min(1024*1024,remaining))
            if not chunk:raise RuntimeError('Copia incompleta')
            remaining-=len(chunk);plain.write(decryptor.update(chunk))
        plain.write(decryptor.finalize());plain.seek(0)
        with tarfile.open(fileobj=plain,mode='r:gz') as f:
            manifest=json.load(f.extractfile('oli/MANIFIESTO.json'))
            for path,digest in manifest['archivos'].items():
                actual=hashlib.sha256()
                with f.extractfile('oli/'+path) as file:
                    for chunk in iter(lambda:file.read(1024*1024),b''):actual.update(chunk)
                if actual.hexdigest()!=digest:raise RuntimeError('Integridad no comprobada')
    report={'fecha':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),'archivo':name,'cifrado_verificado':True,'archivos':len(manifest['archivos']),'modelos':manifest['modelos']}
    if '--previo-rotacion' in sys.argv:
        if 'privado/n8n-previo/n8n-anterior.pgdump' not in manifest['archivos']:raise RuntimeError('Falta la base compartida en el respaldo previo')
        report['incluye_respaldo_n8n']=True
    if 'privado/n8n-previo/evolution-anterior.tgz' in manifest['archivos']:report['incluye_evolution']=True
    if '--restaurar-prueba' in sys.argv:
        # Solo una clave de este respaldo viaja cifrada por SSH, nunca la clave privada RSA.
        request=json.dumps({'archivo':name,'clave_efimera':base64.b64encode(ephemeral).decode()}).encode()
        report['prueba_restauracion']=json.loads(run(ssh+['python3 /opt/oli-operacion/restaurar_prueba.py'],input=request))
    (out/'ULTIMA-COPIA.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    notification=json.dumps(report).encode()
    code="import pathlib,json,sys; d=json.load(sys.stdin); pathlib.Path('/opt/oli-operacion/ultima-copia-externa.json').write_text(json.dumps(d)); pathlib.Path('/opt/oli-operacion/PRE-ROTACION-COPIA-EXTERNA.json').write_text(json.dumps(d)) if d.get('incluye_respaldo_n8n') else None; pathlib.Path('/opt/oli-operacion/EVOLUTION-COPIA-EXTERNA.json').write_text(json.dumps(d)) if d.get('incluye_evolution') else None"
    import shlex
    run(ssh+['python3 -c '+shlex.quote(code)],input=notification)
    print(json.dumps(report,ensure_ascii=False))
except Exception:
    (out/'ERROR-COPIA.txt').write_text('No se pudo completar el respaldo externo. Revisar conexión SSH, permisos y espacio en la PC. No borrar la clave de recuperación.',encoding='utf-8')
    print('No se pudo completar la copia externa o su verificación.',file=sys.stderr);sys.exit(1)
else:
    (out/'ERROR-COPIA.txt').unlink(missing_ok=True)
