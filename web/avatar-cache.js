'use strict';
// Only visible saved messages request pictures. The server resolves captured authors.
(() => {
  const visible=new Set(), observed=new Set(), known=new Map();
  let timer, busy=false;
  const selector='.reader-message[data-id],.message[data-message-id]';
  const context=()=>({archive:document.getElementById('reader-archive')?.value||'',channel:document.getElementById('reader-channel')?.value||''});
  const signature=c=>c.archive+':'+c.channel+':';
  const id=el=>el.dataset.messageId||el.dataset.id;
  function schedule(delay=150){clearTimeout(timer);timer=setTimeout(hydrate,delay);}
  function apply(el,picture){
    const box=el.querySelector('.reader-avatar,.avatar');
    if(!box||box.querySelector('img'))return;
    box.title=picture.status==='failed'?'Profile picture unavailable; retry from Library.':picture.status==='queued'||picture.status==='running'?'Profile picture queued; cached automatically during text rests.':'';
    if(!/^\/avatar\/[a-f0-9]{64}$/.test(picture.url||''))return;
    let initial=box.querySelector('span');
    if(!initial){initial=document.createElement('span');initial.textContent=box.textContent;box.replaceChildren(initial);}
    const image=document.createElement('img');image.width=image.height=40;image.alt='Profile picture';image.loading='lazy';
    image.onload=()=>{initial.hidden=true;};image.onerror=()=>{image.remove();initial.hidden=false;box.title='Cached profile picture could not be displayed.';};
    image.src=picture.url;box.append(image);
  }
  async function hydrate(){
    if(busy||document.hidden)return;
    const c=context(),prefix=signature(c),elements=[...visible].filter(el=>el.isConnected&&!el.querySelector('.reader-avatar img,.avatar img'));
    for(const el of elements){const value=known.get(prefix+id(el));if(value)apply(el,value);}
    const candidates=elements.filter(el=>{const value=known.get(prefix+id(el));return !value||['queued','running','deferred'].includes(value.status);});
    const ids=[...new Set(candidates.map(id))].slice(0,80);
    if(!ids.length)return;
    busy=true;
    try{
      const response=await fetch('/api/avatars/visible',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Action':'local'},body:JSON.stringify({...c,messages:ids})});
      const value=await response.json();if(!response.ok)throw new Error(value.error||'Unable to cache profile pictures.');
      if(signature(context())!==prefix)return;
      for(const mid of ids)known.set(prefix+mid,value.pictures[mid]||{status:'unavailable'});
      // Bound session metadata even when a reader traverses years of saved messages.
      while(known.size>2000)known.delete(known.keys().next().value);
      for(const el of candidates)if(el.isConnected)apply(el,known.get(prefix+id(el))||{status:'deferred'});
    }catch(error){console.warn('Profile-picture cache:',error.message);for(const el of candidates){const box=el.querySelector('.reader-avatar,.avatar');if(box)box.title=error.message;}}
    finally{busy=false;if([...visible].some(el=>el.isConnected))schedule(5000);}
  }
  const intersection=new IntersectionObserver(entries=>{for(const e of entries){if(e.isIntersecting)visible.add(e.target);else visible.delete(e.target);}schedule();});
  function observe(){
    for(const el of observed)if(!el.isConnected){intersection.unobserve(el);observed.delete(el);visible.delete(el);}
    for(const el of document.querySelectorAll(selector))if(!observed.has(el)){observed.add(el);intersection.observe(el);}
  }
  new MutationObserver(observe).observe(document.body,{childList:true,subtree:true});observe();
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)schedule();});
})();
