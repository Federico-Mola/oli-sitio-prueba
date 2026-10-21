(() => {
  'use strict';
  if(document.getElementById('oli-chat-frame'))return;
  const frame=document.createElement('iframe');
  frame.id='oli-chat-frame';frame.title='Oli, asistente virtual de La Tiendita de Oli';
  frame.src='/oli-asistente/widget';frame.referrerPolicy='same-origin';
  frame.setAttribute('allow','');
  Object.assign(frame.style,{position:'fixed',right:'8px',bottom:'8px',border:'0',background:'transparent',zIndex:'1000',colorScheme:'normal'});
  let open=false;
  function fit(){
    const viewport=window.visualViewport;
    const width=Math.min(window.innerWidth,viewport?viewport.width:window.innerWidth);
    const height=viewport?viewport.height:window.innerHeight;
    frame.style.width=Math.min(open?418:244,Math.max(180,width-16))+'px';
    frame.style.height=Math.min(open?720:124,Math.max(180,height-16))+'px';
    frame.style.bottom=viewport?Math.max(8,window.innerHeight-viewport.height-viewport.offsetTop+8)+'px':'8px';
  }
  window.addEventListener('message',e=>{
    if(e.origin!==location.origin||e.source!==frame.contentWindow||!e.data||e.data.tipo!=='oli-widget'||typeof e.data.abierto!=='boolean')return;
    open=e.data.abierto;fit();
  });
  window.addEventListener('resize',fit);
  if(window.visualViewport){window.visualViewport.addEventListener('resize',fit);window.visualViewport.addEventListener('scroll',fit);}
  document.body.append(frame);fit();
})();
