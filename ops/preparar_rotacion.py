"""Preparación privada de migración de credenciales de n8n. No altera producción."""
import json, os, secrets, subprocess, sys, time, urllib.request, tempfile
from pathlib import Path

os.umask(0o077)
base=Path('/opt/oli-operacion/rotacion-privada');base.mkdir(mode=0o700,exist_ok=True)
req=json.load(sys.stdin);token=req['panel']
def run(args,**kw):
    r=subprocess.run(args,capture_output=True,timeout=180,**kw)
    if r.returncode:
        (base/'fallo-privado.log').write_bytes(r.stdout+r.stderr)
        raise RuntimeError('Fallo de preparación: '+args[0])
    return r.stdout
def api(op,name,kind='App'):
    u='https://4onmhx.easypanel.host/api/'+op+'?projectName=automatizaciones&serviceName='+name
    with urllib.request.urlopen(urllib.request.Request(u,headers={'Authorization':'Bearer '+token}),timeout=25) as r:return json.load(r)
def env(s):return dict(l.split('=',1) for l in s.splitlines() if '=' in l and not l.startswith('#'))
names=run(['docker','ps','--format','{{.Names}}']).decode().splitlines()
n8n=next(x for x in names if x.startswith('automatizaciones_n8n.'));db=next(x for x in names if x.startswith('automatizaciones_n8n-db.'))
main=json.loads(run(['docker','inspect',n8n]))[0];oldenv=env('\n'.join(main['Config']['Env']))
dbmeta=json.loads(run(['docker','inspect',db]))[0];dbenv=env('\n'.join(dbmeta['Config']['Env']))
services={}
for name,kind in [('n8n','App'),('n8n-runner','App'),('n8n-db','Postgres'),('evolution-api','App'),('evolution-api-db','Postgres'),('evolution-api-redis','Redis')]:services[name]=api('inspect'+kind+'Service',name)
(base/'panel-anterior.json').write_text(json.dumps(services))
(base/'entorno-anterior.json').write_text(json.dumps(oldenv))
if not (base/'n8n-anterior.pgdump').exists():
    (base/'n8n-anterior.pgdump').write_bytes(run(['docker','exec',db,'pg_dump','-U',dbenv['POSTGRES_USER'],'-d',dbenv['POSTGRES_DB'],'-Fc']))
transfer=base/'transfer';transfer.mkdir(mode=0o700,exist_ok=True)
remote='/tmp/oli-rotacion-'+secrets.token_hex(8)+'.json'
try:
    run(['docker','exec',n8n,'sh','-c','umask 077; n8n export:credentials --all --decrypted --output="$1"','oli',remote])
    credentials=json.loads(run(['docker','exec',n8n,'cat',remote]))
finally:run(['docker','exec',n8n,'rm','-f',remote])
(transfer/'originales.json').write_text(json.dumps(credentials))
os.chown(transfer/'originales.json',1000,1000)
new={'cifrado':secrets.token_hex(32),'db':secrets.token_urlsafe(36),'runner':secrets.token_hex(32),'oli_api':secrets.token_hex(32),'evolution_db':secrets.token_urlsafe(36),'evolution_redis':secrets.token_urlsafe(36),'evolution_api':secrets.token_hex(32)}
oldoli=env(Path('/opt/oli-api.env').read_text())
mapping={oldenv['DB_POSTGRESDB_PASSWORD']:new['db'],oldoli['OLI_API_KEY']:new['oli_api']}
evoenv=env(services['evolution-api'].get('env',''))
for old,value in [(services['evolution-api-db']['password'],new['evolution_db']),(services['evolution-api-redis']['password'],new['evolution_redis']),(evoenv.get('AUTHENTICATION_API_KEY'),new['evolution_api'])]:
    if old:mapping[old]=value
remote='/tmp/oli-workflow-'+secrets.token_hex(8)+'.json'
try:
    run(['docker','exec',n8n,'sh','-c','umask 077; n8n export:workflow --id=V3Jyq2JYKoicRVAO --output="$1"','oli',remote])
    workflow=json.loads(run(['docker','exec',n8n,'cat',remote]))
finally:run(['docker','exec',n8n,'rm','-f',remote])
(transfer/'workflow-original.json').write_text(json.dumps(workflow));os.chown(transfer/'workflow-original.json',1000,1000)
for node in workflow[0]['nodes']:
    if node['name']=='Oli API - procesar mensaje':
        node['parameters']['url']='https://www.latienditadeoli.com/api/bot'
        node['parameters'].setdefault('options',{})['timeout']=300000
(transfer/'workflow-oli.json').write_text(json.dumps(workflow));os.chown(transfer/'workflow-oli.json',1000,1000)
# Las credenciales compartidas que reutilizan estos valores se actualizarán juntas.
changed=[]
for c in credentials:
    raw=json.dumps(c['data'])
    for old,value in mapping.items():raw=raw.replace(old,value)
    if json.loads(raw)!=c['data']:changed.append(c['id'])
    c['data']=json.loads(raw)
    if c['name']=='Oli API' and c['type']=='httpHeaderAuth':
        assert c['data'].get('name','').lower()=='x-oli-key'
        c['data']['value']=new['oli_api']
        if c['id'] not in changed:changed.append(c['id'])
(transfer/'credenciales.json').write_text(json.dumps(credentials))
newenv={k:v for k,v in oldenv.items() if k.startswith('DB_')}
newenv.update(N8N_ENCRYPTION_KEY=new['cifrado'],N8N_USER_FOLDER='/tmp/oli-n8n-migracion',N8N_DIAGNOSTICS_ENABLED='false',N8N_RUNNERS_ENABLED='false',N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS='true')
# En la prueba aislada se usa una base restaurada, con otra contraseña.
testpass=secrets.token_hex(32)
(base/'postgres-prueba.env').write_text('POSTGRES_PASSWORD='+testpass+'\nPOSTGRES_DB='+dbenv['POSTGRES_DB']+'\n')
net='oli-rotacion-aislada'
r=subprocess.run(['docker','network','inspect',net],capture_output=True)
if r.returncode:run(['docker','network','create','--internal',net])
storage=tempfile.TemporaryDirectory(prefix='postgres-test-',dir=base)
Path(storage.name).chmod(0o755)  # El usuario postgres debe atravesar el punto de montaje dentro del contenedor.
run(['docker','run','-d','--name','oli-rotacion-db-prueba','--user','0:0','--network',net,'--memory','768m','--cpus','0.6','--env-file',str(base/'postgres-prueba.env'),'--mount','type=bind,src='+storage.name+',dst=/var/lib/postgresql',dbmeta['Image']])
try:
    for i in range(40):
        state=json.loads(run(['docker','inspect','oli-rotacion-db-prueba']))[0]['State']
        if not state['Running']:raise RuntimeError('PostgreSQL temporal no inició')
        r=subprocess.run(['docker','exec','oli-rotacion-db-prueba','pg_isready','-h','127.0.0.1','-U','postgres'],capture_output=True)
        if not r.returncode:break
        time.sleep(1)
    run(['docker','exec','-i','oli-rotacion-db-prueba','pg_restore','-U','postgres','-d',dbenv['POSTGRES_DB'],'--no-owner','--no-privileges'],input=(base/'n8n-anterior.pgdump').read_bytes())
    newenv.update(DB_POSTGRESDB_HOST='oli-rotacion-db-prueba',DB_POSTGRESDB_PASSWORD=testpass,DB_POSTGRESDB_USER='postgres')
    (base/'n8n-prueba.env').write_text('\n'.join(k+'='+v for k,v in newenv.items())+'\n')
    os.chown(transfer,1000,1000);os.chown(transfer/'credenciales.json',1000,1000)
    (transfer/'claves.json').write_text(json.dumps({'anterior':oldenv['N8N_ENCRYPTION_KEY'],'nueva':new['cifrado']}));os.chown(transfer/'claves.json',1000,1000)
    __import__('shutil').copy2('/opt/oli-operacion/migrar_cifrado.cjs',transfer/'migrar_cifrado.cjs');os.chown(transfer/'migrar_cifrado.cjs',1000,1000)
    migration=run(['docker','run','--rm','--network',net,'--memory','512m','--cpus','0.6','--env-file',str(base/'n8n-prueba.env'),'--mount','type=bind,src='+str(transfer)+',dst=/transfer','--entrypoint','node',main['Image'],'/transfer/migrar_cifrado.cjs'])
    (base/'MIGRACION-CIFRADO.json').write_bytes(migration)
    def cli(args):return run(['docker','run','--rm','--network',net,'--memory','512m','--cpus','0.6','--env-file',str(base/'n8n-prueba.env'),'--mount','type=bind,src='+str(transfer)+',dst=/transfer','--entrypoint','n8n',main['Image']]+args)
    cli(['import:credentials','--input=/transfer/credenciales.json'])
    cli(['export:credentials','--all','--decrypted','--output=/transfer/verificadas.json'])
    restored=json.loads((transfer/'verificadas.json').read_text())
    assert {c['id']:c['data'] for c in restored}=={c['id']:c['data'] for c in credentials},'La migración de cifrado no coincide'
    (transfer/'verificadas.json').unlink()
    # El arranque valida también firma JWT/JWE/OAuth, no solo credenciales.
    run(['docker','exec','oli-rotacion-db-prueba','psql','-U','postgres','-d',dbenv['POSTGRES_DB'],'-v','ON_ERROR_STOP=1','-c','UPDATE workflow_entity SET active=false, "activeVersionId"=NULL;'])
    statecopy=base/'estado-n8n-prueba'
    if statecopy.exists():__import__('shutil').rmtree(statecopy)
    live_state=next(m['Source'] for m in main['Mounts'] if m['Destination']=='/home/node/.n8n')
    __import__('shutil').copytree(live_state,statecopy,symlinks=True,ignore=__import__('shutil').ignore_patterns('binaryData','*.log','*.sqlite*','crash.journal'))
    for f in [statecopy,*statecopy.rglob('*')]:
        if not f.is_symlink():os.chown(f,1000,1000)
    runner_name=next(x for x in names if x.startswith('automatizaciones_n8n-runner.'))
    runner_meta=json.loads(run(['docker','inspect',runner_name]))[0];runner_original=env('\n'.join(runner_meta['Config']['Env']))
    runtime=dict(oldenv,DB_POSTGRESDB_HOST='oli-rotacion-db-prueba',DB_POSTGRESDB_PASSWORD=testpass,DB_POSTGRESDB_USER='postgres',N8N_ENCRYPTION_KEY=new['cifrado'],N8N_RUNNERS_AUTH_TOKEN=new['runner'],N8N_DIAGNOSTICS_ENABLED='false',N8N_VERSION_NOTIFICATIONS_ENABLED='false')
    runtime.pop('N8N_USER_FOLDER',None)
    def boot():
        name='oli-rotacion-n8n-prueba'
        try:
            key=env((base/'n8n-prueba.env').read_text())['N8N_ENCRYPTION_KEY']
            runtime['N8N_ENCRYPTION_KEY']=key;runtime['N8N_RUNNERS_AUTH_TOKEN']=new['runner'] if key==new['cifrado'] else oldenv['N8N_RUNNERS_AUTH_TOKEN']
            cfg=json.loads((statecopy/'config').read_text());cfg['encryptionKey']=key;(statecopy/'config').write_text(json.dumps(cfg));os.chown(statecopy/'config',1000,1000)
            (base/'n8n-arranque.env').write_text('\n'.join(k+'='+v for k,v in runtime.items())+'\n')
            renv=dict(runner_original,N8N_RUNNERS_AUTH_TOKEN=runtime['N8N_RUNNERS_AUTH_TOKEN'],N8N_RUNNERS_TASK_BROKER_URI='http://'+name+':5679')
            (base/'runner-arranque.env').write_text('\n'.join(k+'='+v for k,v in renv.items())+'\n')
            run(['docker','run','-d','--name',name,'--network',net,'--memory','768m','--cpus','0.7','--env-file',str(base/'n8n-arranque.env'),'--mount','type=bind,src='+str(statecopy)+',dst=/home/node/.n8n','--entrypoint','n8n',main['Image'],'start'])
            run(['docker','run','-d','--name','oli-rotacion-runner-prueba','--network',net,'--memory','384m','--cpus','0.3','--env-file',str(base/'runner-arranque.env'),runner_meta['Image']])
            for _ in range(80):
                state=json.loads(run(['docker','inspect',name]))[0]['State']
                if not state['Running']:raise RuntimeError('El arranque aislado de n8n falló')
                check="Promise.all(['/healthz/readiness','/rest/settings'].map(async p=>{const r=await fetch('http://127.0.0.1:5678'+p);if(!r.ok)process.exit(1);})).catch(()=>process.exit(1))"
                r=subprocess.run(['docker','exec',name,'node','-e',check],capture_output=True,timeout=10)
                if not r.returncode:return True
                time.sleep(2)
            raise RuntimeError('El arranque aislado de n8n no respondió')
        finally:
            r=subprocess.run(['docker','logs',name],capture_output=True);(base/'arranque-aislado-privado.log').write_bytes(r.stdout+r.stderr)
            subprocess.run(['docker','rm','-f',name],capture_output=True)
            subprocess.run(['docker','rm','-f','oli-rotacion-runner-prueba'],capture_output=True)
    boot()
    # La restauración del cifrado anterior también debe ser probada en esta copia.
    run(['docker','run','--rm','--network',net,'--memory','512m','--cpus','0.6','--env-file',str(base/'n8n-prueba.env'),'--mount','type=bind,src='+str(transfer)+',dst=/transfer','--entrypoint','node',main['Image'],'/transfer/migrar_cifrado.cjs','--restaurar'])
    oldtest=dict(newenv,N8N_ENCRYPTION_KEY=oldenv['N8N_ENCRYPTION_KEY']);(base/'n8n-prueba.env').write_text('\n'.join(k+'='+v for k,v in oldtest.items())+'\n')
    cli(['import:credentials','--input=/transfer/originales.json'])
    cli(['export:credentials','--all','--decrypted','--output=/transfer/restauradas.json'])
    assert {c['id']:c['data'] for c in json.loads((transfer/'restauradas.json').read_text())}=={c['id']:c['data'] for c in json.loads((transfer/'originales.json').read_text())}
    (transfer/'restauradas.json').unlink();(transfer/'cifrado-anterior.json').unlink()
    boot()
    new.update(credenciales=len(credentials),referencias_actualizadas=len(changed),imagen=main['Image'],red=main['NetworkSettings']['Networks'],n8n_container=n8n,db_container=db)
    (base/'nuevos.json').write_text(json.dumps(new))
    report={'migracion_cifrado_probada':True,'arranque_completo_probado':True,'arranque_restauracion_probado':True,'entorno_y_volumen_reales_copiados':True,'runner_externo_probado':True,'credenciales':len(credentials),'referencias_actualizadas':len(changed),'produccion_modificada':False}
    (base/'PREPARACION.json').write_text(json.dumps(report));print(json.dumps(report))
finally:
    (base/'postgres-prueba.log').write_bytes(subprocess.run(['docker','logs','oli-rotacion-db-prueba'],capture_output=True).stderr)
    subprocess.run(['docker','rm','-f','oli-rotacion-db-prueba'],capture_output=True)
    subprocess.run(['docker','network','rm',net],capture_output=True)
    storage.cleanup()
