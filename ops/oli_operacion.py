"""Ejecutar como root en el VPS. Respaldos cifrados y avisos privados sin secretos en logs."""
import base64, datetime, fcntl, hashlib, io, json, os
from pathlib import Path
import shutil, sqlite3, subprocess, sys, tarfile, tempfile, time, urllib.request
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

BASE=Path('/opt/oli-operacion')
BACKUPS=Path('/opt/oli-backups/automaticos')
MAGIC=b'OLI-BACKUP-1\n'


def command(args,timeout=90):
    r=subprocess.run(args,capture_output=True,timeout=timeout)
    if r.returncode:raise RuntimeError('operacion_externa')
    return r.stdout


def now():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def sha256_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def values():
    return dict(l.split('=',1) for l in Path('/opt/oli-api.env').read_text().splitlines() if l and not l.startswith('#') and '=' in l)


def avisar(text):
    target=json.loads((BASE/'alertas.json').read_text())['chat_id'];env=values()
    if target not in env.get('OLI_ALLOWED_USER_IDS','').split(','):raise RuntimeError('destinatario_no_autorizado')
    req=urllib.request.Request('https://api.telegram.org/bot'+env['OLI_BOT_TOKEN']+'/sendMessage',data=json.dumps({'chat_id':target,'text':text}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=20) as r:
        if not json.load(r).get('ok'):raise RuntimeError('aviso_no_confirmado')


def sqlite_copy(source,dest):
    if not source.exists():return
    dest.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as src,sqlite3.connect(dest) as out:
        src.backup(out)
        if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('base_no_integra')


def snapshot(dest):
    with open('/opt/oli-data/.oli.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        shutil.copytree('/opt/oli-data',dest/'datos',ignore=shutil.ignore_patterns('*.sqlite','*.sqlite-wal','*.sqlite-shm','*.sqlite-journal','.oli.lock','.oli-json-*','.oli-publicar-*'))
        for src in Path('/opt/oli-data').rglob('*.sqlite'):sqlite_copy(src,dest/'datos'/src.relative_to('/opt/oli-data'))
    sqlite_copy(Path('/opt/oli-agent-preview/state/oli.sqlite'),dest/'agente/oli.sqlite')
    (dest/'publica').mkdir()
    command(['docker','cp','-L','oli-sitio-prueba:/usr/share/nginx/html/.',str(dest/'publica')])
    # El nombre real de la base se descubre sin copiar un SQLite en escritura.
    for src in Path('/opt/oli-agent-preview/state').glob('*.sqlite*'):
        if src.suffix in ('.sqlite','.sqlite3','.db'):sqlite_copy(src,dest/'agente'/src.name)
    config=dest/'privado';config.mkdir(mode=0o700)
    for src in [Path('/opt/oli-api.env'),Path('/opt/oli-agent-preview/private/provider.json'),Path('/opt/oli-despliegue/compose.yaml'),BASE/'alertas.json']:
        shutil.copy2(src,config/src.name)
    names=command(['docker','ps','--format','{{.Names}}']).decode().splitlines()
    n8n=next(x for x in names if x.startswith('automatizaciones_n8n.'))
    db=next(x for x in names if x.startswith('automatizaciones_n8n-db.'))
    meta=json.loads(command(['docker','inspect',n8n]))[0];env=dict(x.split('=',1) for x in meta['Config']['Env'])
    (config/'n8n-recuperacion.json').write_text(json.dumps({'N8N_ENCRYPTION_KEY':env['N8N_ENCRYPTION_KEY']}))
    dbmeta=json.loads(command(['docker','inspect',db]))[0];dbenv=dict(x.split('=',1) for x in dbmeta['Config']['Env'])
    def sql(q):return command(['docker','exec',db,'psql','-U',dbenv.get('POSTGRES_USER','postgres'),'-d',dbenv.get('POSTGRES_DB','n8n'),'-At','-c',q])
    q="SELECT row_to_json(w) FROM workflow_entity w WHERE id='V3Jyq2JYKoicRVAO'"
    workflow=json.loads(sql(q));(config/'workflow-oli.json').write_text(json.dumps(workflow))
    creds=json.loads(sql("SELECT coalesce(json_agg(c),'[]'::json) FROM credentials_entity c WHERE name IN ('Oli API','oli_carga_bot')"))
    if len(creds)!=2:raise RuntimeError('credenciales_no_identificadas')
    (config/'credenciales-oli-cifradas-n8n.json').write_text(json.dumps(creds))
    (config/'n8n-claves-secundarias.json').write_bytes(sql("SELECT coalesce(json_agg(k),'[]'::json) FROM deployment_key k"))
    # Fuente exacta y configuración de operación permiten reconstruir las imágenes.
    deployed=Path('/opt/oli-sitio-prueba')
    if not (deployed/'oli_gestion.py').exists():deployed=Path('/opt/oli-gestion-v2')
    shutil.copytree(deployed,dest/'fuente',ignore=shutil.ignore_patterns('.git','__pycache__','site','node_modules','*.bundle'))
    command(['docker','cp','oli-sitio-prueba:/app/webflow.css',str(dest/'fuente/webflow.css')])
    def ignore_operation(folder,names):
        ignored=set(shutil.ignore_patterns('rotacion-privada','*.log','estado*','*.lock','ultimo*','alertas.json','__pycache__')(folder,names))
        ignored.update(name for name in names if name.startswith(('respaldo-','restauracion-probada-','postgres-test-')) and (Path(folder)/name).is_dir())
        return ignored
    shutil.copytree(BASE,dest/'operacion',ignore=ignore_operation)
    if os.environ.get('OLI_RESPALDO_ROTACION')=='1':
        extra=config/'n8n-previo';extra.mkdir()
        for name in ['n8n-anterior.pgdump','panel-anterior.json','entorno-anterior.json','evolution-anterior.tgz']:
            source=BASE/'rotacion-privada'/name
            if source.exists():shutil.copy2(source,extra/name)
    models=json.loads((dest/'datos/modelos.json').read_text())
    for m in models:
        for f in list(m.get('fotos',[]))+([m['video']] if m.get('video') else []):
            base=dest/'publica' if f.startswith('/img/') else dest/'datos'
            p=(base/f.lstrip('/')).resolve()
            if not p.is_relative_to(base.resolve()) or not p.is_file():raise RuntimeError('medio_ausente')
    files={p.relative_to(dest).as_posix():sha256_file(p) for p in dest.rglob('*') if p.is_file()}
    info={'fecha':now(),'modelos':len(models),'archivos':files,'version':1}
    (dest/'MANIFIESTO.json').write_text(json.dumps(info,ensure_ascii=False))
    return info


def backup():
    BACKUPS.mkdir(parents=True,exist_ok=True,mode=0o700)
    estimate=sum(p.stat().st_size for p in Path('/opt/oli-data').rglob('*') if p.is_file())+100*1024**2
    if os.environ.get('OLI_RESPALDO_ROTACION')=='1':estimate+=sum(p.stat().st_size for p in (BASE/'rotacion-privada').glob('*') if p.is_file())
    if shutil.disk_usage('/opt').free<estimate*3+2*1024**3:raise RuntimeError('espacio_insuficiente_para_respaldo_seguro')
    with tempfile.TemporaryDirectory(prefix='respaldo-',dir=BASE) as folder:
        root=Path(folder)/'restauracion';root.mkdir();info=snapshot(root)
        payload=Path(folder)/'contenido.tgz'
        with tarfile.open(payload,mode='w:gz') as t:t.add(root,arcname='oli')
        key=AESGCM.generate_key(bit_length=256);nonce=os.urandom(12)
        public=serialization.load_pem_public_key((BASE/'respaldo-publica.pem').read_bytes())
        wrapped=public.encrypt(key,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        header=json.dumps({'clave':base64.b64encode(wrapped).decode(),'nonce':base64.b64encode(nonce).decode()}).encode()
        aad=MAGIC+header+b'\n'
        name=datetime.datetime.now(datetime.timezone.utc).strftime('oli-%Y%m%dT%H%M%SZ.olibak')
        tmp=BACKUPS/('.'+name)
        encryptor=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor();encryptor.authenticate_additional_data(aad)
        try:
            with payload.open('rb') as source,tmp.open('xb') as target:
                target.write(aad)
                for chunk in iter(lambda:source.read(1024*1024),b''):target.write(encryptor.update(chunk))
                target.write(encryptor.finalize());target.write(encryptor.tag);target.flush();os.fsync(target.fileno())
            # Autenticar también el archivo ya escrito, con memoria acotada.
            decryptor=Cipher(algorithms.AES(key),modes.GCM(nonce,encryptor.tag)).decryptor();decryptor.authenticate_additional_data(aad)
            digest=hashlib.sha256();remaining=tmp.stat().st_size-len(aad)-16
            with tmp.open('rb') as source:
                source.seek(len(aad))
                while remaining:
                    chunk=source.read(min(1024*1024,remaining));remaining-=len(chunk);digest.update(decryptor.update(chunk))
            digest.update(decryptor.finalize());assert digest.hexdigest()==sha256_file(payload)
            tmp.chmod(0o600);os.replace(tmp,BACKUPS/name)
        finally:tmp.unlink(missing_ok=True)
        (BASE/'ultimo-respaldo.json').write_text(json.dumps({'fecha':info['fecha'],'archivo':name,'modelos':info['modelos'],'archivos':len(info['archivos']),'bytes':(BACKUPS/name).stat().st_size}))
    allfiles=sorted(BACKUPS.glob('oli-*.olibak'),reverse=True)
    days={};weeks={}
    for f in allfiles:
        date=datetime.datetime.strptime(f.name[4:12],'%Y%m%d');iso=date.isocalendar()
        days.setdefault(date.date(),f);weeks.setdefault((iso.year,iso.week),f)
    keep=set(list(days.values())[:14])
    keep.update(list(weeks.values())[:8])
    for marker in ['PRE-ROTACION-COPIA-EXTERNA.json','EVOLUTION-COPIA-EXTERNA.json']:
        try:
            protected=BACKUPS/json.loads((BASE/marker).read_text())['archivo']
            if protected.is_file() and protected.parent==BACKUPS:keep.add(protected)
        except Exception:pass
    for f in allfiles:
        if f not in keep:f.unlink()
    print('Respaldo cifrado verificado',name)


def monitor(test=False):
    if test:
        avisar('Oli · Prueba de avisos técnicos completada. Este bot avisará si falla la tienda, Telegram o los respaldos. No se modificó ningún producto.');print('Aviso técnico confirmado');return
    issues=[]
    for name,url in [('tienda','https://www.latienditadeoli.com/'),('bot','https://www.latienditadeoli.com/api/salud'),('agente','https://www.latienditadeoli.com/oli-asistente/api/salud'),('n8n','https://n8n.molavariedades.uy/healthz/readiness')]:
        try:
            with urllib.request.urlopen(url,timeout=12) as r:
                if r.status!=200:raise ValueError()
                if name=='agente' and not json.load(r).get('modelo_configurado'):raise ValueError()
        except Exception:issues.append(name)
    try:
        names=command(['docker','ps','--format','{{.Names}}'],timeout=15).decode().splitlines()
        if not any(x.startswith('automatizaciones_n8n-runner.') for x in names):issues.append('ejecutor n8n no disponible')
        db=next(x for x in names if x.startswith('automatizaciones_n8n-db.'))
        meta=json.loads(command(['docker','inspect',db],timeout=15))[0];env=dict(x.split('=',1) for x in meta['Config']['Env'])
        query="SELECT active FROM workflow_entity WHERE id='V3Jyq2JYKoicRVAO'; SELECT EXISTS(SELECT 1 FROM execution_entity WHERE \"workflowId\"='V3Jyq2JYKoicRVAO' AND status='error' AND \"startedAt\">now()-interval '10 minutes');"
        result=command(['docker','exec',db,'psql','-U',env['POSTGRES_USER'],'-d',env['POSTGRES_DB'],'-At','-c',query],timeout=15).decode().strip().splitlines()
        if len(result)!=2 or result[0]!='t':issues.append('flujo Telegram desactivado')
        if len(result)==2 and result[1]=='t':issues.append('ejecución Telegram con error reciente')
    except Exception:issues.append('estado del flujo Telegram no comprobado')
    try:
        with sqlite3.connect('file:/opt/oli-agent-preview/state/oli.sqlite?mode=ro',uri=True,timeout=3) as db:
            failures=db.execute("SELECT count(*) FROM usage WHERE status='fallo' AND created>?",(time.time()-600,)).fetchone()[0]
        if failures:issues.append('respuesta de IA para revisar')
    except Exception:issues.append('registro del agente no comprobado')
    if shutil.disk_usage('/opt').free<3*1024**3:issues.append('espacio en disco')
    try:
        latest=json.loads((BASE/'ultimo-respaldo.json').read_text())
        if time.time()-datetime.datetime.fromisoformat(latest['fecha']).timestamp()>30*3600:issues.append('respaldo atrasado')
    except Exception:issues.append('respaldo no comprobado')
    try:
        offsite=json.loads((BASE/'ultima-copia-externa.json').read_text())
        if time.time()-datetime.datetime.fromisoformat(offsite['fecha']).timestamp()>72*3600:issues.append('copia externa atrasada; encender la PC')
    except Exception:issues.append('copia externa no comprobada')
    try:
        err=json.loads(Path('/opt/oli-data/operacion/ultimo-error.json').read_text())
        # Fallos de operación recientes; no mostrar mensajes, identificadores ni excepciones.
        if err.get('codigo')!='respuesta_boton_caducada' and time.time()-datetime.datetime.fromisoformat(err['fecha']).timestamp()<600:issues.append('operación Telegram: '+err.get('codigo','error'))
    except FileNotFoundError:pass
    except Exception:issues.append('registro del bot no comprobado')
    statefile=BASE/'estado-monitor.json'
    try:old=json.loads(statefile.read_text()) if statefile.exists() else {}
    except Exception:old={};issues.append('registro del monitor no comprobado')
    current=', '.join(sorted(issues))
    if current and (current!=old.get('incidencias') or time.time()-old.get('aviso',0)>6*3600):
        avisar('Oli · Hay que revisar: '+current+'. La tienda conserva sus datos; consultar el registro técnico.');old['aviso']=time.time()
    elif not current and old.get('incidencias'):
        avisar('Oli · Los servicios y respaldos vuelven a responder correctamente.');old['aviso']=time.time()
    old.update(incidencias=current,comprobado=now());statefile.write_text(json.dumps(old))
    print('Comprobación terminada:',len(issues),'incidencias')


if __name__=='__main__':
    os.umask(0o077);BASE.mkdir(mode=0o700,exist_ok=True)
    with open(BASE/'operacion.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            if sys.argv[1]=='backup':backup()
            elif sys.argv[1]=='prueba-aviso':monitor(True)
            else:monitor()
        except Exception:
            # La excepción original podría contener rutas con tokens; no registrarla.
            print('Falló la operación de continuidad de Oli',file=sys.stderr)
            try:avisar('Oli · Falló una tarea de continuidad. Revisar el servicio de respaldos o monitorización en el VPS.')
            except Exception:pass
            sys.exit(1)
