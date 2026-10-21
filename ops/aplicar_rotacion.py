"""Rotación coordinada, con restauración de credenciales si una comprobación falla.
Requiere prueba de cifrado aprobada y respaldo previo cifrado copiado fuera del VPS.
La clave de EasyPanel llega por stdin SSH y no se guarda.
"""
import base64,copy,hashlib,hmac,http.client,json,os,secrets,socket,subprocess,sys,time,urllib.error,urllib.parse,urllib.request
from pathlib import Path

os.umask(0o077)
ROOT=Path('/opt/oli-operacion');BASE=ROOT/'rotacion-privada';TRANSFER=BASE/'transfer'
token=json.load(sys.stdin)['panel']
assert json.loads((BASE/'PREPARACION.json').read_text())['migracion_cifrado_probada']
assert json.loads((BASE/'PREPARACION.json').read_text()).get('arranque_completo_probado')
assert json.loads((BASE/'PREPARACION.json').read_text()).get('arranque_restauracion_probado')
assert json.loads((BASE/'PREPARACION.json').read_text()).get('entorno_y_volumen_reales_copiados')
assert (ROOT/'PRE-ROTACION-COPIA-EXTERNA.json').is_file(),'Falta copia externa del respaldo compartido'
new=json.loads((BASE/'nuevos.json').read_text());old=json.loads((BASE/'entorno-anterior.json').read_text());services=json.loads((BASE/'panel-anterior.json').read_text())


def run(args,timeout=180,**kwargs):
    r=subprocess.run(args,capture_output=True,timeout=timeout,**kwargs)
    if r.returncode:
        (BASE/'fallo-aplicacion-privado.log').write_bytes(r.stdout+r.stderr)
        raise RuntimeError('operacion_externa')
    return r.stdout


def api(op,name,changes=None,kind='App'):
    params={'projectName':'automatizaciones','serviceName':name}
    if changes is None:
        url='https://4onmhx.easypanel.host/api/'+op+'?'+urllib.parse.urlencode(params);data=None
    else:
        params.update(changes);url='https://4onmhx.easypanel.host/api/'+op;data=json.dumps(params).encode()
    req=urllib.request.Request(url,data=data,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=90) as r:raw=r.read()
    return json.loads(raw) if raw else None


def phase(s):
    (ROOT/'ROTACION-ESTADO.json').write_text(json.dumps({'fase':s,'fecha':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='seconds')}))
    print('Fase:',s,flush=True)


def containers():return run(['docker','ps','--format','{{.Names}}']).decode().splitlines()


class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(30);self.sock.connect('/var/run/docker.sock')


def engine(method,path,body=None):
    con=DockerConnection('localhost',timeout=30)
    try:
        con.request(method,path,body=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        response=con.getresponse();raw=response.read()
        if response.status>=300:raise RuntimeError('docker_actualizacion_no_confirmada')
        return json.loads(raw) if raw else None
    finally:con.close()


def service(name,replicas,changes=None):
    # Cambio controlado de la tarea actual; conserva imagen, montajes, permisos y redes.
    data=engine('GET','/services/'+name);spec=copy.deepcopy(data['Spec']);spec['Mode']['Replicated']['Replicas']=replicas
    if changes:
        values=dict(x.split('=',1) for x in spec['TaskTemplate']['ContainerSpec']['Env']);values.update(changes)
        spec['TaskTemplate']['ContainerSpec']['Env']=[k+'='+v for k,v in values.items()]
    engine('POST','/services/'+data['ID']+'/update?version='+str(data['Version']['Index']),spec)


def db_ready(previous=None,password=None):
    started=time.monotonic()
    for _ in range(90):
        names=containers();db=next((x for x in names if x.startswith('automatizaciones_n8n-db.')),None)
        if db and (db!=previous or time.monotonic()-started>15):
            state=json.loads(run(['docker','inspect',db]))[0]['State']
            age=time.time()-__import__('datetime').datetime.fromisoformat(state['StartedAt'].replace('Z','+00:00')).timestamp()
            service=json.loads(run(['docker','service','inspect','automatizaciones_n8n-db']))[0]
            changing=service.get('UpdateStatus',{}).get('State') in ('updating','rollback_started')
            if age>10 and not changing and subprocess.run(['docker','exec',db,'pg_isready','-h','127.0.0.1','-U','postgres'],capture_output=True).returncode==0:
                if password:
                    raw=run(['docker','exec',db,'psql','-U','postgres','-d',old['DB_POSTGRESDB_DATABASE'],'-At','-c',"SELECT rolpassword FROM pg_authid WHERE rolname='postgres'"]).decode().strip()
                    method,iteration_salt,stored_server=raw.split('$');iterations,salt=iteration_salt.split(':');assert method=='SCRAM-SHA-256'
                    salted=hashlib.pbkdf2_hmac('sha256',password.encode(),base64.b64decode(salt),int(iterations));client=hmac.new(salted,b'Client Key','sha256').digest()
                    if not hmac.compare_digest(hashlib.sha256(client).digest(),base64.b64decode(stored_server.split(':')[0])):raise RuntimeError('password_no_coincide')
                return db
        time.sleep(1)
    raise RuntimeError('base_no_disponible')


def variables(text,changes):
    lines=text.splitlines();seen=set();out=[]
    for line in lines:
        key=line.split('=',1)[0]
        if key in changes:out.append(key+'='+changes[key]);seen.add(key)
        else:out.append(line)
    out.extend(k+'='+v for k,v in changes.items() if k not in seen)
    return '\n'.join(out)+'\n'


network='easypanel-automatizaciones' if 'easypanel-automatizaciones' in new['red'] else next(k for k in new['red'] if k!='ingress')
current_n8n=next(x for x in containers() if x.startswith('automatizaciones_n8n.'))
configdir=next(m['Source'] for m in json.loads(run(['docker','inspect',current_n8n]))[0]['Mounts'] if m['Destination']=='/home/node/.n8n')
config=Path(configdir)/'config';oldconfig=config.read_bytes();(BASE/'n8n-config-anterior.json').write_bytes(oldconfig)
siteenv=Path('/opt/oli-api.env');oldsiteenv=siteenv.read_bytes();(BASE/'oli-env-anterior').write_bytes(oldsiteenv)
compose=Path('/opt/oli-despliegue/compose.yaml');oldcompose=compose.read_bytes();(BASE/'compose-anterior.json').write_bytes(oldcompose)
catalog_hash=hashlib.sha256(Path('/opt/oli-data/modelos.json').read_bytes()).hexdigest()


def cli(args,key,password,program='n8n'):
    environment={k:v for k,v in old.items() if k.startswith('DB_')}
    environment.update(DB_POSTGRESDB_PASSWORD=password,N8N_ENCRYPTION_KEY=key,N8N_USER_FOLDER='/tmp/oli-cli',N8N_DIAGNOSTICS_ENABLED='false',N8N_RUNNERS_ENABLED='false')
    envfile=BASE/'cli-produccion.env';envfile.write_text('\n'.join(k+'='+v for k,v in environment.items())+'\n')
    return run(['docker','run','--rm','--network',network,'--memory','640m','--cpus','0.7','--env-file',str(envfile),'--mount','type=bind,src='+str(TRANSFER)+',dst=/transfer','--entrypoint',program,new['imagen']]+args)


def config_key(key):
    obj=json.loads(oldconfig);obj['encryptionKey']=key
    # Con las tareas detenidas, conservar el inode que utiliza el volumen persistente.
    with config.open('w') as f:json.dump(obj,f);f.flush();os.fsync(f.fileno())
    config.chmod(0o600);os.chown(config,1000,1000)
    assert json.loads(config.read_text())['encryptionKey']==key


def update_env(name,content):
    payload={'env':content}
    if services[name].get('dotEnvPath'):payload['dotEnvPath']=services[name]['dotEnvPath']
    api('updateAppEnv',name,payload)


stopped=False;db_changed=False;credentials_changed=False;cipher_changed=False;workflow_changed=False;success=False
with urllib.request.urlopen('https://n8n.molavariedades.uy/healthz/readiness',timeout=10) as baseline:assert baseline.status==200
assert all(api('inspectAppService',name).get('enabled') for name in ['n8n','n8n-runner'])
run(['systemctl','stop','oli-monitor.timer'])
try:
    phase('pausa_controlada_n8n')
    service('automatizaciones_n8n',0);service('automatizaciones_n8n-runner',0);stopped=True
    for _ in range(40):
        if not any(x.startswith(('automatizaciones_n8n.','automatizaciones_n8n-runner.')) for x in containers()):break
        time.sleep(1)
    else:raise RuntimeError('n8n_no_se_detuvo')
    # Capturar credenciales con los procesos detenidos para no pisar renovaciones OAuth recientes.
    cli(['export:credentials','--all','--decrypted','--output=/transfer/originales.json'],old['N8N_ENCRYPTION_KEY'],old['DB_POSTGRESDB_PASSWORD'])
    fresh=json.loads((TRANSFER/'originales.json').read_text());changes={old['DB_POSTGRESDB_PASSWORD']:new['db']}
    for previous,value in [(services['evolution-api-db']['password'],new['evolution_db']),(services['evolution-api-redis']['password'],new['evolution_redis'])]:
        if previous:changes[previous]=value
    candidate=copy.deepcopy(fresh)
    for credential in candidate:
        raw=json.dumps(credential['data'])
        for previous,value in changes.items():raw=raw.replace(previous,value)
        credential['data']=json.loads(raw)
        if credential['name']=='Oli API':
            assert credential['type']=='httpHeaderAuth' and credential['data'].get('name','').lower()=='x-oli-key'
            credential['data']['value']=new['oli_api']
    (TRANSFER/'credenciales.json').write_text(json.dumps(candidate));os.chown(TRANSFER/'credenciales.json',1000,1000)
    phase('rotar_base_y_cifrado')
    previous=db_ready();db_changed=True;api('updatePostgresCredentials','n8n-db',{'password':new['db']});db_ready(previous,new['db'])
    cipher_changed=True;cli(['/transfer/migrar_cifrado.cjs'],new['cifrado'],new['db'],program='node')
    credentials_changed=True;cli(['import:credentials','--input=/transfer/credenciales.json'],new['cifrado'],new['db'])
    cli(['export:credentials','--all','--decrypted','--output=/transfer/verificacion-produccion.json'],new['cifrado'],new['db'])
    expected=json.loads((TRANSFER/'credenciales.json').read_text());actual=json.loads((TRANSFER/'verificacion-produccion.json').read_text())
    assert {c['id']:c['data'] for c in actual}=={c['id']:c['data'] for c in expected},'Credenciales no conservadas'
    (TRANSFER/'verificacion-produccion.json').unlink()
    phase('publicar_workflow_https')
    workflow_changed=True
    cli(['import:workflow','--input=/transfer/workflow-oli.json'],new['cifrado'],new['db'])
    cli(['publish:workflow','--id=V3Jyq2JYKoicRVAO'],new['cifrado'],new['db'])
    config_key(new['cifrado'])
    phase('rotar_conexion_oli_y_cerrar_puerto')
    siteenv.write_text(variables(oldsiteenv.decode(),{'OLI_API_KEY':new['oli_api']}));siteenv.chmod(0o600)
    spec=json.loads(oldcompose);spec['services']['sitio']['ports']=['172.18.0.1:8088:80'];compose.write_text(json.dumps(spec,indent=2))
    run(['docker','compose','-f',str(compose),'up','-d','--no-deps','--wait','--wait-timeout','75','sitio'])
    phase('actualizar_entornos_compartidos')
    update_env('n8n',variables(services['n8n']['env'],{'DB_POSTGRESDB_PASSWORD':new['db'],'N8N_ENCRYPTION_KEY':new['cifrado'],'N8N_RUNNERS_AUTH_TOKEN':new['runner']}))
    update_env('n8n-runner',variables(services['n8n-runner']['env'],{'N8N_RUNNERS_AUTH_TOKEN':new['runner']}))
    config_key(new['cifrado'])
    service('automatizaciones_n8n',1,{'DB_POSTGRESDB_PASSWORD':new['db'],'N8N_ENCRYPTION_KEY':new['cifrado'],'N8N_RUNNERS_AUTH_TOKEN':new['runner']})
    service('automatizaciones_n8n-runner',1,{'N8N_RUNNERS_AUTH_TOKEN':new['runner']})
    phase('verificar_servicios')
    reconciled=False
    for _ in range(70):
        if json.loads(config.read_text()).get('encryptionKey')!=new['cifrado']:
            if reconciled:raise RuntimeError('archivo_de_clave_revertido_por_otro_proceso')
            config_key(new['cifrado']);run(['docker','service','update','--force','--detach','automatizaciones_n8n']);reconciled=True
        try:
            with urllib.request.urlopen('https://n8n.molavariedades.uy/healthz/readiness',timeout=5) as r:
                if r.status==200:break
        except Exception:pass
        time.sleep(2)
    else:raise RuntimeError('n8n_no_responde')
    with urllib.request.urlopen('https://www.latienditadeoli.com/api/salud',timeout=10) as r:assert json.load(r)['version']=='gestion-v2'
    # Solicitud autenticada sin mensaje: verifica la clave y el transporte sin enviar mensajes ni mutar productos.
    req=urllib.request.Request('https://www.latienditadeoli.com/api/bot',data=b'{}',headers={'X-Oli-Key':new['oli_api'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r:assert r.status==200
    try:
        req=urllib.request.Request('https://www.latienditadeoli.com/api/bot',data=b'{}',headers={'X-Oli-Key':dict(l.split('=',1) for l in oldsiteenv.decode().splitlines() if '=' in l)['OLI_API_KEY']})
        urllib.request.urlopen(req,timeout=10);raise RuntimeError('clave_anterior_aun_valida')
    except urllib.error.HTTPError as e:assert e.code==401
    assert hashlib.sha256(Path('/opt/oli-data/modelos.json').read_bytes()).hexdigest()==catalog_hash
    success=True;phase('rotacion_n8n_y_oli_completada')
except Exception as error:
    (ROOT/'ROTACION-FALLO.json').write_text(json.dumps({'tipo':type(error).__name__,'codigo':str(error) if isinstance(error,RuntimeError) else getattr(error,'code',None)}))
    phase('restaurando_configuracion_anterior')
    # Mantener las aplicaciones detenidas hasta que clave, datos cifrados y base vuelvan a coincidir.
    try:
        service('automatizaciones_n8n',0);service('automatizaciones_n8n-runner',0)
        for _ in range(30):
            if not any(x.startswith(('automatizaciones_n8n.','automatizaciones_n8n-runner.')) for x in containers()):break
            time.sleep(1)
        if db_changed:
            previous=db_ready();api('updatePostgresCredentials','n8n-db',{'password':old['DB_POSTGRESDB_PASSWORD']});db_ready(previous,old['DB_POSTGRESDB_PASSWORD'])
        if cipher_changed and (TRANSFER/'cifrado-anterior.json').exists():cli(['/transfer/migrar_cifrado.cjs','--restaurar'],old['N8N_ENCRYPTION_KEY'],old['DB_POSTGRESDB_PASSWORD'],program='node')
        if credentials_changed:cli(['import:credentials','--input=/transfer/originales.json'],old['N8N_ENCRYPTION_KEY'],old['DB_POSTGRESDB_PASSWORD'])
        if workflow_changed:
            cli(['import:workflow','--input=/transfer/workflow-original.json'],old['N8N_ENCRYPTION_KEY'],old['DB_POSTGRESDB_PASSWORD'])
            cli(['publish:workflow','--id=V3Jyq2JYKoicRVAO'],old['N8N_ENCRYPTION_KEY'],old['DB_POSTGRESDB_PASSWORD'])
        config.write_bytes(oldconfig);config.chmod(0o600);os.chown(config,1000,1000)
        siteenv.write_bytes(oldsiteenv);compose.write_bytes(oldcompose)
        run(['docker','compose','-f',str(compose),'up','-d','--no-deps','--wait','--wait-timeout','75','sitio'])
        update_env('n8n',services['n8n']['env']);update_env('n8n-runner',services['n8n-runner']['env'])
        service('automatizaciones_n8n',1,{'DB_POSTGRESDB_PASSWORD':old['DB_POSTGRESDB_PASSWORD'],'N8N_ENCRYPTION_KEY':old['N8N_ENCRYPTION_KEY'],'N8N_RUNNERS_AUTH_TOKEN':old['N8N_RUNNERS_AUTH_TOKEN']})
        service('automatizaciones_n8n-runner',1,{'N8N_RUNNERS_AUTH_TOKEN':old['N8N_RUNNERS_AUTH_TOKEN']})
        phase('configuracion_anterior_restaurada')
    except Exception:phase('requiere_recuperacion_asistida')
    raise SystemExit('La rotación no se completó; revisar el estado de recuperación.')
finally:
    run(['systemctl','start','oli-monitor.timer'])
if success:
    report={'n8n_cifrado_rotado':True,'n8n_base_rotada':True,'runner_rotado':True,'oli_api_rotada':True,'workflow_https':True,'puerto_solo_red_privada':True,'credenciales_conservadas':len(expected),'catalogo_conservado':True,'evolution_y_tokens_despliegue':'pendientes_de_intervencion_separada'}
    (ROOT/'ROTACION-RESULTADO.json').write_text(json.dumps(report));print(json.dumps(report))
