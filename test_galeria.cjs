// Ejecutar con Playwright instalado y OLI_GALLERY_FIXTURE apuntando al sitio de prueba.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true});
  const root = process.env.OLI_GALLERY_FIXTURE;
  const checks=[];
  async function context(mobile) {
    const c=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1280,height:900},hasTouch:mobile,isMobile:mobile});
    await c.route('**/*',async r=>{
      const u=new URL(r.request().url());
      if(u.hostname!=='galeria.test')return r.abort();
      let file=path.join(root,decodeURIComponent(u.pathname));
      if(!path.extname(file))file=path.join(file,'index.html');
      if(!fs.existsSync(file))return r.fulfill({status:404,body:''});
      return r.fulfill({status:200,contentType:file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(file)});
    });
    return c;
  }
  try {
    for(const mobile of [false,true]){
      const c=await context(mobile),p=await c.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));
      await p.goto('http://galeria.test/modelos/acc-0099-galeria');
      const gallery=p.locator('.oli-mp-gallery'),count=p.locator('.oli-mp-count');
      const expectCount=async text=>{await p.waitForFunction(t=>document.querySelector('.oli-mp-count').textContent===t,text);};
      const aligned=async()=>{try{await p.waitForFunction(()=>{const g=document.querySelector('.oli-mp-gallery'),i=Number(document.querySelector('.oli-mp-count').textContent.split('/')[0])-1;return Math.abs(g.scrollLeft-g.clientWidth*i)<2;},null,{timeout:5000});}catch(e){console.error(await gallery.evaluate(g=>({width:g.clientWidth,left:g.scrollLeft,scrollWidth:g.scrollWidth,count:document.querySelector('.oli-mp-count').textContent,slides:Array.from(g.children).map(e=>({width:e.getBoundingClientRect().width,offset:e.offsetLeft,snap:getComputedStyle(e).scrollSnapAlign}))})));throw e;}};
      await expectCount('1 / 3');assert(await p.locator('.prev').isDisabled());
      await p.locator('.next').click();await expectCount('2 / 3');await aligned();
      await p.locator('.oli-mp-thumbs a').nth(2).click();await expectCount('3 / 3');await aligned();assert(await p.locator('.next').isDisabled());
      assert.equal(new URL(p.url()).hash,'');checks.push((mobile?'móvil':'escritorio')+': flechas, miniaturas, límites y sin saltos de página');
      await gallery.focus();await p.keyboard.press('Home');await expectCount('1 / 3');await aligned();await p.keyboard.press('ArrowRight');await expectCount('2 / 3');await aligned();
      assert.equal(await p.locator('.oli-mp-thumbs a[aria-current=true]').count(),1);checks.push((mobile?'móvil':'escritorio')+': teclado y foto activa');
      if(mobile){
        await gallery.focus();await p.keyboard.press('Home');await expectCount('1 / 3');await aligned();
        await gallery.scrollIntoViewIfNeeded();
        const session=await c.newCDPSession(p),box=await gallery.boundingBox();const x=box.x+box.width*.8,y=box.y+box.height*.35;
        await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
        for(let n=1;n<=12;n++){await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x-box.width*.7*n/12,y}]});await p.waitForTimeout(20);}
        await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
        try{await p.waitForFunction(()=>document.querySelector('.oli-mp-gallery').scrollLeft>100,null,{timeout:5000});}catch(e){console.error(await gallery.evaluate(g=>({width:g.clientWidth,scrollWidth:g.scrollWidth,left:g.scrollLeft,rect:g.getBoundingClientRect().toJSON(),ancestors:Array.from((function*(e){while(e){yield e;e=e.parentElement}})(g)).map(e=>({tag:e.tagName,cls:e.className,touch:getComputedStyle(e).touchAction}))})));throw e;}await aligned();
        const current=await count.textContent();assert.notEqual(current,'1 / 3');checks.push('móvil: gesto táctil real sobre imagen grande');
        assert.equal(await gallery.evaluate(g=>getComputedStyle(g).touchAction),'auto');
        assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));checks.push('móvil: sin desborde horizontal ni bloqueo de gestos verticales/zoom');
      }else{
        await gallery.focus();await p.keyboard.press('Home');await expectCount('1 / 3');await aligned();
        const box=await gallery.boundingBox();await p.mouse.move(box.x+box.width*.8,box.y+box.height*.5);await p.mouse.down();await p.mouse.move(box.x+box.width*.15,box.y+box.height*.5,{steps:15});await p.mouse.up();await expectCount('2 / 3');await aligned();checks.push('escritorio: arrastre con mouse');
        await p.setViewportSize({width:950,height:900});await aligned();await expectCount('2 / 3');checks.push('escritorio: conserva foto al redimensionar');
      }
      await p.goto('http://galeria.test/modelos/acc-0098-una-foto');assert.equal(await p.locator('.oli-mp-arrow').count(),0);assert.equal(await p.locator('.oli-mp-count').count(),0);assert.deepEqual(errors,[]);checks.push((mobile?'móvil':'escritorio')+': una foto sin controles innecesarios ni errores JS');
      await c.close();
    }
    console.log(JSON.stringify({pruebas:checks.length,correcto:true,comprobaciones:checks},null,2));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
