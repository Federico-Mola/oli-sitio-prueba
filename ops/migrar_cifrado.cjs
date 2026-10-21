/* Adaptador de migración para el modo legacy de la versión instalada de n8n.
 * Usa sus implementaciones de Cipher. Solo recibe secretos mediante archivos privados.
 * Primero se debe comprobar sobre una base restaurada, nunca activar flags experimentales.
 */
'use strict';
const fs=require('node:fs');
const {createRequire}=require('node:module');
const req=createRequire('/usr/local/lib/node_modules/n8n/package.json');
const {Cipher}=req('n8n-core');
let pg;try{pg=req('pg');}catch{pg=createRequire(req.resolve('@n8n/db'))('pg');}
const folder='/transfer';
const ident=s=>'"'+s.replaceAll('"','""')+'"';
const client=new pg.Client({host:process.env.DB_POSTGRESDB_HOST,port:Number(process.env.DB_POSTGRESDB_PORT||5432),database:process.env.DB_POSTGRESDB_DATABASE,user:process.env.DB_POSTGRESDB_USER,password:process.env.DB_POSTGRESDB_PASSWORD,connectionTimeoutMillis:15000});
let etapa='conexion';

async function main(){
 await client.connect();await client.query('BEGIN');
 try{
  if(process.argv.includes('--restaurar')){
   const rows=JSON.parse(fs.readFileSync(folder+'/cifrado-anterior.json','utf8'));
   for(const row of rows){const keys=Object.keys(row.pk);const where=keys.map((k,i)=>ident(k)+'=$'+(i+2)).join(' AND ');const r=await client.query('UPDATE '+ident(row.table)+' SET '+ident(row.column)+'=$1 WHERE '+where,[row.value,...keys.map(k=>row.pk[k])]);if(r.rowCount!==1)throw Error('Fila no identificada al restaurar');}
   await client.query('COMMIT');console.log(JSON.stringify({cifrado_restaurado:true,campos:rows.length}));return;
  }
  if(['true','1'].includes(process.env.N8N_ENV_FEAT_ENCRYPTION_KEY_ROTATION||''))throw Error('Este adaptador requiere modo legacy');
  const keys=JSON.parse(fs.readFileSync(folder+'/claves.json','utf8'));
  const old=new Cipher({encryptionKey:keys.anterior},null),fresh=new Cipher({encryptionKey:keys.nueva},null);
  etapa='esquema';const schema=(await client.query("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")).rows;
  const pkRows=(await client.query("SELECT tc.table_name,kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema WHERE tc.table_schema='public' AND tc.constraint_type='PRIMARY KEY' ORDER BY tc.table_name,kcu.ordinal_position")).rows;
  const pks={};for(const p of pkRows)(pks[p.table_name]??=[]).push(p.column_name);
  const keyTable=schema.find(r=>r.table_name.endsWith('deployment_key'))?.table_name;
  if(!keyTable)throw Error('No se encontró el almacén de claves de esta versión');
  const deks=(await client.query('SELECT * FROM '+ident(keyTable))).rows.filter(r=>r.type!=='instance.id');
  const recovered=[];
  for(const row of deks){let raw;
   if(row.type==='data_encryption'&&(row.value===keys.anterior||/^[0-9a-f]{64}$/i.test(row.value)))raw=row.value;
   else if(row.value.startsWith('U2FsdGVk'))raw=old.decryptWithInstanceKey(row.value);
   else raw=old.decryptDEKWithInstanceKey(row.value);
   recovered.push({row,raw});
  }
  const legacy=recovered.find(x=>x.row.type==='data_encryption'&&x.row.algorithm==='aes-256-cbc');
  if(!legacy||legacy.raw!==keys.anterior)throw Error('La clave legacy requiere otro procedimiento');
  const undo=[],changes=[];
  function add(table,column,row,value){const pk={};for(const key of pks[table]||[])pk[key]=row[key];if(!Object.keys(pk).length)throw Error('Falta clave primaria');undo.push({table,column,pk,value:row[column]});changes.push({table,column,pk,value});}
  for(const col of schema){
   if(!['text','character varying','character'].includes(col.data_type)||col.table_name===keyTable)continue;
   etapa=col.table_name+'.'+col.column_name;const selected=[...new Set([...(pks[col.table_name]||[]),col.column_name])].map(ident).join(',');
   const rows=(await client.query('SELECT '+selected+' FROM '+ident(col.table_name)+' WHERE '+ident(col.column_name)+" LIKE 'U2FsdGVk%'")).rows;
   for(const row of rows){let plain;
    try{plain=old.decryptWithInstanceKey(row[col.column_name]);}catch{throw Error('Se encontró cifrado legacy que no se puede migrar');}
    const encrypted=fresh.encryptWithInstanceKey(plain);if(fresh.decryptWithInstanceKey(encrypted)!==plain)throw Error('Verificación de cifrado fallida');
    add(col.table_name,col.column_name,row,encrypted);
   }
  }
  for(const {row,raw} of recovered){const value=fresh.encryptDEKWithInstanceKey(row.type==='data_encryption'&&row.algorithm==='aes-256-cbc'?keys.nueva:raw);if(fresh.decryptDEKWithInstanceKey(value)!==(row.type==='data_encryption'&&row.algorithm==='aes-256-cbc'?keys.nueva:raw))throw Error('Verificación de clave secundaria fallida');add(keyTable,'value',row,value);}
  if(process.argv.includes('--comprobar')){await client.query('ROLLBACK');console.log(JSON.stringify({comprobado:true,campos:changes.length,claves_secundarias:recovered.length,produccion_modificada:false}));return;}
  fs.writeFileSync(folder+'/cifrado-anterior.json',JSON.stringify(undo),{mode:0o600});
  for(const row of changes){const keys=Object.keys(row.pk),where=keys.map((k,i)=>ident(k)+'=$'+(i+2)).join(' AND ');const r=await client.query('UPDATE '+ident(row.table)+' SET '+ident(row.column)+'=$1 WHERE '+where,[row.value,...keys.map(k=>row.pk[k])]);if(r.rowCount!==1)throw Error('Fila no identificada');}
  await client.query('COMMIT');console.log(JSON.stringify({cifrado_migrado:true,campos:changes.length,claves_secundarias:recovered.length}));
 }catch(e){await client.query('ROLLBACK');throw e;}finally{await client.end();}
}
main().catch(e=>{const allowed=['Este adaptador requiere modo legacy','No se encontró el almacén de claves de esta versión','La clave legacy requiere otro procedimiento','Falta clave primaria','Se encontró cifrado legacy que no se puede migrar','Verificación de cifrado fallida','Verificación de clave secundaria fallida','Fila no identificada'];console.error('No se completó la migración de cifrado; la transacción se revirtió.',etapa,allowed.some(x=>e.message.startsWith(x))?e.message:(e.code||e.name));process.exitCode=1;});
