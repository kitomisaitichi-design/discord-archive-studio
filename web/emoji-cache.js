'use strict';
(() => {
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const token=/<(a?):([A-Za-z0-9_]{1,100}):(\d{1,22})>/g,code=/```[\s\S]*?(?:```|$)|`[^`\n]*(?:`|$)/g;
  const brokenImages=new Set();
  const safe=url=>(/^\/emoji\/[a-f0-9]{64}$/.test(url||'')||/^\/api\/reader\/asset\?/.test(url||''))&&!brokenImages.has(url);
  document.addEventListener('error',event=>{const img=event.target;if(img.tagName==='IMG'&&img.parentElement?.classList.contains('custom-emoji')){brokenImages.add(img.getAttribute('src'));img.hidden=true;img.parentElement.append(document.createTextNode(img.alt||':emoji:'));img.parentElement.title='Saved emoji could not be displayed; readable name retained.';}},true);
  function normal(text,assets){let out='',position=0;for(const m of text.matchAll(token)){const label=':'+m[2]+':',url=assets[m[3]];out+=esc(text.slice(position,m.index))+`<span class="custom-emoji" data-emoji-id="${m[3]}" title="${esc(label)}">${safe(url)?`<img src="${esc(url)}" alt="${esc(label)}" loading="lazy">`:esc(label)}</span>`;position=m.index+m[0].length;}return out+esc(text.slice(position));}
  function html(text,assets={}){text=String(text||'');let out='',position=0;for(const m of text.matchAll(code)){out+=normal(text.slice(position,m.index),assets)+esc(m[0]);position=m.index+m[0].length;}return out+normal(text.slice(position),assets);}
  function reaction(e,assets={}){return e?.id?html(`<${e.animated?'a':''}:${/^[A-Za-z0-9_]{1,100}$/.test(e.name||'')?e.name:'emoji'}:${e.id}>`,assets):esc(e?.name||'?');}
  window.StudioEmoji={html,reaction};
  const visible=new Set(),observed=new Set(),known=new Map();let timer,busy=false;
  const context=()=>({archive:document.getElementById('reader-archive')?.value||'',channel:document.getElementById('reader-channel')?.value||''});
  function schedule(delay=150){clearTimeout(timer);timer=setTimeout(hydrate,delay);}
  function apply(el,value){if(!el.isConnected||el.querySelector('img')||!safe(value?.url))return;const label=el.textContent,img=document.createElement('img');img.alt=label;img.loading='lazy';img.onload=()=>{for(const n of [...el.childNodes])if(n!==img)n.remove();};img.onerror=()=>{img.remove();el.title=label+' · cached image could not be displayed';};img.src=value.url;el.append(img);}
  async function hydrate(){
    if(busy||document.hidden)return;
    const c=context(),items=[...visible].filter(el=>el.isConnected&&!el.querySelector('img'));
    for(const el of items)apply(el,known.get(el.dataset.emojiId));
    const candidates=items.filter(el=>{const v=known.get(el.dataset.emojiId);return !v||['queued','running','deferred'].includes(v.status);});
    const ids=[...new Set(candidates.map(el=>{const row=el.closest('[data-message-id],.reader-message[data-id]');return row?.dataset.messageId||row?.dataset.id;}).filter(Boolean))].slice(0,80);
    if(!ids.length)return;busy=true;
    try{
      const response=await fetch('/api/emojis/visible',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Action':'local'},body:JSON.stringify({...c,messages:ids})});
      const value=await response.json();if(!response.ok)throw new Error(value.error||'Unable to cache emojis.');
      for(const [eid,e] of Object.entries(value.emojis))known.set(eid,e);
      while(known.size>2000)known.delete(known.keys().next().value);
      for(const el of candidates){if(!value.emojis[el.dataset.emojiId]&&!known.has(el.dataset.emojiId))known.set(el.dataset.emojiId,{status:'unavailable'});apply(el,known.get(el.dataset.emojiId));}
      document.dispatchEvent(new Event('studio-emojis-updated'));
    }catch(error){console.warn('Emoji cache:',error.message);for(const el of candidates)el.title=error.message;}
    finally{busy=false;if([...visible].some(el=>el.isConnected))schedule(5000);}
  }
  const intersection=new IntersectionObserver(entries=>{for(const e of entries){if(e.isIntersecting)visible.add(e.target);else visible.delete(e.target);}schedule();});
  function observe(){for(const el of observed)if(!el.isConnected){intersection.unobserve(el);observed.delete(el);visible.delete(el);}for(const el of document.querySelectorAll('.custom-emoji[data-emoji-id]'))if(!observed.has(el)){observed.add(el);intersection.observe(el);}}
  new MutationObserver(observe).observe(document.body,{childList:true,subtree:true});observe();
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)schedule();});
  document.addEventListener('studio-emojis-retry',()=>{known.clear();schedule();});
})();
