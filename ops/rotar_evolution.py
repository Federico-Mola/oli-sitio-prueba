"""Rotación de las credenciales expuestas de Evolution, conservando su estado previo.
La aplicación se pausa mientras su base deshabilitada se levanta para cambiar la contraseña.
"""
import base64,hashlib,hmac,json,os,subprocess,sys,tarfile,time,urllib.parse,urllib.request
from pathlib import Path
os.umask(0o077)
ROOT=Path('/opt/oli-operacion');BASE=ROOT/'rotacion-privada'
request=json.load(sys.stdin);token=request['panel'];mode=request.get('accion','aplicar')
old=json.loads((BASE/'panel-anterior.json').read_text());new=json.loads((BASE/'nuevos.json').read_text())
def run(args,**kwargs):
 r=subprocess.run(args,capture_output=True,timeout=120,**kwargs)
 if r.returncode:raise RuntimeError('operacion_externa')
 return r.stdout
def api(op,name,changes=None):
 params={'projectName':'automatizaciones','serviceName':name}
 if changes is None:url='https://4onmhx.easypanel.host/api/'+op+'?'+urllib.parse.urlencode(params);body=None
 else:params.update(changes);url='https://4onmhx.easypanel.host/api/'+op;body=json.dumps(params).encode()
 with urllib.request.urlopen(urllib.request.Request(url,data=body,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}),timeout=90) as r:b=r.read()
 return json.loads(b) if b else None
def names():return run(['docker','ps','--format','{{.Names}}']).decode().splitlines()
def wait_db(previous=None):
 since=time.monotonic()
 for _ in range(90):
  n=next((x for x in names() if x.startswith('automatizaciones_evolution-api-db.')),None)
  if n:
   d=json.loads(run(['docker','inspect',n]))[0];age=time.time()-__import__('datetime').datetime.fromisoformat(d['State']['StartedAt'].replace('Z','+00:00')).timestamp()
   state=json.loads(run(['docker','service','inspect','automatizaciones_evolution-api-db']))[0].get('UpdateStatus',{}).get('State')
   if age>10 and (n!=previous or time.monotonic()-since>15) and state not in ('updating','rollback_started') and subprocess.run(['docker','exec',n,'pg_isready','-U','postgres'],capture_output=True).returncode==0:return n
  time.sleep(1)
 raise RuntimeError('base_evolution_no_disponible')
if mode=='preparar':
 assert not old['evolution-api-db']['enabled'] and not old['evolution-api-redis']['enabled'],'Las bases no están en el estado inactivo esperado'
 assert not any(x.startswith(('automatizaciones_evolution-api-db.','automatizaciones_evolution-api-redis.')) for x in names())
 with tarfile.open(BASE/'evolution-anterior.tgz','w:gz') as t:
  for name in ['evolution-api-db','evolution-api-redis']:t.add(Path('/etc/easypanel/projects/automatizaciones')/name/'data',arcname=name)
 print(json.dumps({'respaldo_frio_preparado':True,'produccion_modificada':False}));sys.exit(0)
assert json.loads((ROOT/'ROTACION-RESULTADO.json').read_text())['n8n_cifrado_rotado']
assert json.loads((ROOT/'EVOLUTION-COPIA-EXTERNA.json').read_text())['incluye_evolution']
assert not any(x.startswith(('automatizaciones_evolution-api-db.','automatizaciones_evolution-api-redis.')) for x in names())
def env(text):return dict(l.split('=',1) for l in text.splitlines() if '=' in l and not l.startswith('#'))
before=old['evolution-api']['env'];oldvalues=env(before)
assert oldvalues.get('AUTHENTICATION_API_KEY') and old['evolution-api-db']['user']=='postgres'
mapping={old['evolution-api-db']['password']:new['evolution_db'],old['evolution-api-redis']['password']:new['evolution_redis']}
if oldvalues.get('AUTHENTICATION_API_KEY'):mapping[oldvalues['AUTHENTICATION_API_KEY']]=new['evolution_api']
updated=before
for a,b in mapping.items():updated=updated.replace(a,b)
dbchanged=False;success=False
try:
 api('stopAppService','evolution-api',{})
 for _ in range(30):
  if not any(x.startswith('automatizaciones_evolution-api.') for x in names()):break
  time.sleep(1)
 api('enablePostgresService','evolution-api-db',{});db=wait_db()
 dbchanged=True;api('updatePostgresCredentials','evolution-api-db',{'password':new['evolution_db']});db=wait_db(db)
 row=run(['docker','exec',db,'psql','-U','postgres','-At','-c',"SELECT rolpassword FROM pg_authid WHERE rolname='postgres'"]).decode().strip()
 method,iteration_salt,stored_server=row.split('$');iterations,salt=iteration_salt.split(':');assert method=='SCRAM-SHA-256'
 salted=hashlib.pbkdf2_hmac('sha256',new['evolution_db'].encode(),base64.b64decode(salt),int(iterations));ck=hmac.new(salted,b'Client Key','sha256').digest();assert hmac.compare_digest(hashlib.sha256(ck).digest(),base64.b64decode(stored_server.split(':')[0]))
 api('updateRedisCredentials','evolution-api-redis',{'password':new['evolution_redis']})
 payload={'env':updated}
 if old['evolution-api'].get('dotEnvPath'):payload['dotEnvPath']=old['evolution-api']['dotEnvPath']
 api('updateAppEnv','evolution-api',payload)
 success=True
finally:
 if not success:
  try:
   wait_db();api('updatePostgresCredentials','evolution-api-db',{'password':old['evolution-api-db']['password']});wait_db()
   api('updateRedisCredentials','evolution-api-redis',{'password':old['evolution-api-redis']['password']})
   api('updateAppEnv','evolution-api',{'env':before})
  except Exception:pass
 api('disablePostgresService','evolution-api-db',{})
 api('disableRedisService','evolution-api-redis',{})
 if old['evolution-api']['enabled']:api('startAppService','evolution-api',{})
if success:
 persisted=api('inspectAppService','evolution-api');assert env(persisted['env'])['AUTHENTICATION_API_KEY']==new['evolution_api']
 for name,kind,value in [('evolution-api-db','Postgres',new['evolution_db']),('evolution-api-redis','Redis',new['evolution_redis'])]:
  current=api('inspect'+kind+'Service',name);assert current['password']==value and not current['enabled']
 tokens=[]
 for name in ['n8n','n8n-runner','evolution-api']:
  api('refreshAppDeployToken',name,{});tokens.append(name)
 report={'evolution_base_rotada':True,'evolution_redis_rotado':True,'evolution_api_rotada':True,'tokens_despliegue_rotados':tokens,'bases_desactivadas_como_antes':True}
 (ROOT/'ROTACION-EVOLUTION.json').write_text(json.dumps(report));print(json.dumps(report))
