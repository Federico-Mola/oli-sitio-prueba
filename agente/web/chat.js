(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const launcher=$('oli-launcher'), panel=$('oli-panel'), messages=$('oli-messages'), input=$('oli-input');
  const apiBase=location.pathname.startsWith('/oli-asistente/')?'/oli-asistente':'';
  const embedded=location.pathname.endsWith('/widget');
  function notify(open){if(embedded&&parent!==window)parent.postMessage({tipo:'oli-widget',abierto:open},location.origin);}
  let busy=false, ready=false, lastTurn=null;
  const userMessages=[];
  function add(role,text,products=[]) {
    const box=document.createElement('div'); box.className='message '+role;
    const content=document.createElement('p'); content.textContent=text; box.append(content);
    if(products.length) {
      const list=document.createElement('div'); list.className='products';
      for(const p of products) {
        const url=new URL(p.url);
        if(url.origin!=='https://www.latienditadeoli.com'||!/^\/modelos\/[a-z0-9-]+$/.test(url.pathname)) continue;
        const a=document.createElement('a'); a.className='product'; a.href=url.href; a.target='_blank'; a.rel='noopener noreferrer';
        a.textContent=p.nombre;
        const detail=document.createElement('span'); detail.textContent=p.codigo+(typeof p.precio_orientativo_UYU==='number'?' · $ '+p.precio_orientativo_UYU.toLocaleString('es-UY')+' UYU · orientativo':'');
        a.append(detail); list.append(a);
      }
      box.append(list);
    }
    messages.append(box); messages.scrollTop=messages.scrollHeight;
  }
  async function post(path,body) {
    const response=await fetch(apiBase+path,{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(body),signal:AbortSignal.timeout(45000)});
    const result=await response.json();
    if(!response.ok) { const e=new Error('request'); e.code=result.error; throw e; }
    return result;
  }
  async function session() {
    const data=await post('/api/sesion',{});
    if(data.nueva && ready) {messages.replaceChildren();userMessages.length=0;lastTurn=null;add('assistant','Comenzamos una nueva conversación. ¿En qué te puedo ayudar?');}
    ready=true;
  }
  launcher.addEventListener('click',async()=>{
    panel.hidden=false; launcher.hidden=true; launcher.setAttribute('aria-expanded','true'); notify(true); input.focus();
    if(!messages.children.length) add('assistant','Soy Oli, la asistente virtual de La Tiendita de Oli. ¿Qué te gustaría consultar?');
    if(!ready) try {await session();} catch { $('oli-status').textContent='No pude conectar. Podés reintentar o hablar con Euge.'; }
  });
  function close(){panel.hidden=true;launcher.hidden=false;launcher.setAttribute('aria-expanded','false');notify(false);launcher.focus();}
  $('oli-close').addEventListener('click',close);
  panel.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('oli-form').requestSubmit();}});
  $('oli-form').addEventListener('submit',async e=>{
    e.preventDefault();const text=input.value.trim();if(!text||busy)return;
    busy=true;$('oli-send').disabled=true;$('oli-status').textContent='Oli está preparando tu respuesta…';
    try {
      if(!ready)await session();
      const retry=lastTurn&&lastTurn.text===text&&lastTurn.failed;
      if(!retry){lastTurn={id:crypto.randomUUID(),text,failed:false};add('user',text);userMessages.push(text);}
      input.value='';
      const r=await post('/api/chat',{evento:lastTurn.id,mensaje:text});
      add('assistant',r.texto,r.productos);lastTurn.failed=false;
      $('oli-status').textContent=r.estado==='ok'?'':'Podés reintentar o hablar con Euge.';
    } catch(err) {
      if(lastTurn)lastTurn.failed=true;
      if(err.code==='sesion_caducada'){ready=false;lastTurn=null;userMessages.length=0;messages.replaceChildren();}
      input.value=text;
      const labels={limite_pruebas:'Se alcanzó el límite de estas pruebas.',esperar:'Esperá un momento antes de volver a enviar.',ocupado:'Oli está atendiendo otra consulta. Reintentá en unos segundos.',modelo_no_configurado:'La conexión de IA todavía no está habilitada.',sesion_caducada:'La sesión venció. Reenviá tu mensaje para empezar otra conversación.',en_proceso:'Tu mensaje sigue en proceso. Esperá un momento y reintentá.'};
      $('oli-status').textContent=labels[err.code]||'No pude completar la respuesta. Tu mensaje quedó para reintentar; también podés hablar con Euge.';
    } finally {busy=false;$('oli-send').disabled=false;input.focus();}
  });
  function updateLink(){
    const text=$('oli-summary').value.slice(0,700);
    $('oli-wa').href='https://wa.me/59899383602?text='+encodeURIComponent(text);
  }
  $('oli-contact').addEventListener('click',()=>{
    $('oli-handoff').hidden=false;
    // Resumen de mensajes expresados por la persona, sin agregar datos inferidos ni respuesta del modelo.
    $('oli-summary').value=('Hola Euge, te consulto desde la web de Oli.\n'+userMessages.slice(-3).join('\n')).slice(0,700);
    updateLink();$('oli-summary').focus();
  });
  $('oli-summary').addEventListener('input',updateLink);
  $('oli-cancel').addEventListener('click',()=>{$('oli-handoff').hidden=true;input.focus();});
  notify(false);
})();
