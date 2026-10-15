'use strict';
window.MediaView=(()=>{
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function type(a){const name=String(a.filename||a.fileName||'').toLowerCase(),mime=a.content_type||'';
    if(/\.(mid|midi)$/.test(name)||mime.includes('midi'))return 'midi';
    if(/\.(png|jpe?g|gif|webp|avif|bmp)$/.test(name)||mime.startsWith('image/'))return 'image';
    if(/\.(mp4|webm|mov)$/.test(name)||mime.startsWith('video/'))return 'video';
    if(/\.(mp3|ogg|oga|m4a|wav|aac|flac|opus)$/.test(name)||mime.startsWith('audio/'))return 'audio';return 'file';}
  function html(a,url){
    if(!url||!url.startsWith('/'))return '';
    const kind=type(a),name=esc(a.filename||a.fileName||'Saved attachment'),source=esc(url),width=Math.max(1,Math.min(65535,Math.floor(Number(a.width)||320))),height=Math.max(1,Math.min(65535,Math.floor(Number(a.height)||180)));
    if(kind==='video'&&Number(a.size)>10000000)return '<span class="muted">Video exceeds 10 MB</span>';
    if(kind==='image')return `<div class="saved-media"><img data-media-src="${source}" width="${width}" height="${height}" alt="${name}" decoding="async" loading="lazy"><span class="media-fallback" hidden>Saved image could not be decoded. Use Open saved file.</span></div>`;
    if(kind==='video'||kind==='audio')return `<div class="saved-media"><${kind} controls preload="none" ${kind==='video'?`width="${width}" height="${height}"`:''} data-media-src="${source}" aria-label="${name}"></${kind}><span class="media-fallback" hidden>This browser cannot play the saved encoding. Use Open saved file.</span></div>`;
    if(kind==='midi')return `<div class="saved-media midi-player" data-midi-src="${source}"><button data-midi-play aria-label="Play ${name}">▶ Play MIDI</button><input data-midi-seek type="range" min="0" max="1" step="0.01" value="0" aria-label="MIDI playback position"><span data-midi-status>Local synthesizer</span></div>`;return '';
  }
  const observers=new Map(),observed=new WeakMap();
  let directEnabled=true;
  try{directEnabled=localStorage.getItem('studio.direct-images')!=='off';}catch{}
  const directStates=new Map(),directQueue=[];let directActive=0;
  function imageLinks(text){
    const found=new Set();
    for(const match of String(text||'').matchAll(/https?:\/\/[^\s<>"`]+/gi)){
      try{const raw=match[0].replace(/[),.;!?\]}]+$/g,''),url=new URL(raw);
        url.hash='';if(['http:','https:'].includes(url.protocol)&&!url.username&&!url.password&&/\.(jpe?g|png|gif)$/i.test(url.pathname))found.add(url.href);
      }catch{}
      if(found.size>=8)break;
    }
    return [...found];
  }
  function directHTML(text,assets={}){return imageLinks(text).map(url=>{
    const name=new URL(url).pathname.split('/').pop()||'Image';
    const saved=String(assets[url]||''),local=/^\/(linked|media)\/[a-f0-9]{64}$/.test(saved)?saved:/^[a-f0-9]{64}$/.test(saved)?(typeof assetURL==='function'?assetURL(saved):'/linked/'+saved):'';
    return `<div class="direct-media${directEnabled?'':' images-off'}" data-image-url="${esc(url)}"><div class="direct-image-frame"><img data-direct-src="${esc(local||url)}" width="480" height="270" loading="lazy" decoding="async" referrerpolicy="no-referrer" alt="${esc(name)}"><span class="direct-image-placeholder">${directEnabled?'Image loads as you approach':'Inline images are off'}</span></div><div class="direct-image-caption"><a href="${esc(local||url)}" target="_blank" rel="noopener noreferrer">${esc(name)} ↗</a><button type="button" data-direct-load>Load image</button><button type="button" data-save-linked ${local?'disabled':''}>${local?'Saved offline':'Save offline'}</button></div></div>`;
  }).join('');}
  function finishDirect(el,failed){
    const frame=el.closest('.direct-image-frame');if(!frame)return;
    const label=frame.querySelector('.direct-image-placeholder');
    frame.classList.toggle('image-failed',failed);frame.classList.toggle('image-loaded',!failed);
    label.textContent=failed?'Image unavailable. Open the original link or retry.':'';
    el.closest('.direct-media').querySelector('[data-direct-load]').textContent=failed?'Retry':'Load image';
  }
  function pumpDirect(){
    if(!navigator.onLine)return;
    while(directActive<4&&directQueue.length){
      const el=directQueue.shift(),url=el.dataset.directSrc;
      if(!el.isConnected||!url||!directEnabled&&!el.dataset.manualImage)continue;
      let entry=directStates.get(url);
      if(entry?.state==='failed'){finishDirect(el,true);continue;}
      if(entry?.state==='loading'){entry.waiting.add(el);continue;}
      directActive++;entry={state:'loading',waiting:new Set()};directStates.set(url,entry);let timeout;
      const done=failed=>{if(entry.state!=='loading')return;clearTimeout(timeout);entry.state=failed?'failed':'loaded';directActive--;finishDirect(el,failed);
        for(const other of entry.waiting)if(other.isConnected){if(failed)finishDirect(other,true);else{other.onload=()=>finishDirect(other,false);other.onerror=()=>finishDirect(other,true);other.src=url;}}
        entry.waiting.clear();while(directStates.size>500){const key=[...directStates].find(([,v])=>v.state!=='loading')?.[0];if(!key)break;directStates.delete(key);}pumpDirect();};
      el.hidden=false;el.onload=()=>done(false);el.onerror=()=>done(true);timeout=setTimeout(()=>{el.removeAttribute('src');done(true);},30000);el.src=url;
    }
  }
  const directObservers=new Map(),directObserved=new WeakMap();
  function useSaved(box,source){
    const el=box.querySelector('[data-direct-src]');if(!el||el.dataset.directSrc===source)return;
    if(el.getAttribute('src'))el.onerror?.();
    directObserved.get(el)?.unobserve(el);directObserved.delete(el);el.onload=el.onerror=null;el.removeAttribute('src');
    el.dataset.directSrc=source;delete el.dataset.directQueued;
    box.querySelector('.direct-image-frame').classList.remove('image-failed','image-loaded');
    box.querySelector('.direct-image-placeholder').textContent='Saved image loads as you approach';
    box.querySelector('[data-direct-load]').textContent='Load image';observeDirect(el);
  }
  function observeDirect(root=document){
    const elements=[...(root.matches?.('[data-direct-src]')?[root]:[]),...root.querySelectorAll('[data-direct-src]')];
    for(const el of elements){if(directObserved.has(el)||el.dataset.directQueued||el.getAttribute('src')||!directEnabled)continue;
      const scrollRoot=el.closest('#reader-timeline,#library-results,#mini-preview');let observer=directObservers.get(scrollRoot);
      if(!observer){observer=new IntersectionObserver(entries=>{for(const {target,isIntersecting} of entries)if(isIntersecting){observer.unobserve(target);directObserved.delete(target);target.dataset.directQueued='1';directQueue.push(target);}pumpDirect();},{root:scrollRoot,rootMargin:'400px'});directObservers.set(scrollRoot,observer);}
      directObserved.set(el,observer);observer.observe(el);
    }
  }
  function setDirect(enabled){directEnabled=!!enabled;try{localStorage.setItem('studio.direct-images',enabled?'on':'off');}catch{}
    for(const box of document.querySelectorAll('.direct-media'))box.classList.toggle('images-off',!enabled);
    if(enabled)observeDirect();else{directQueue.length=0;for(const [root,observer] of directObservers){observer.disconnect();directObservers.delete(root);}for(const el of document.querySelectorAll('[data-direct-src]')){directObserved.delete(el);delete el.dataset.directQueued;delete el.dataset.manualImage;if(el.getAttribute('src')&&!el.complete){el.removeAttribute('src');el.onerror?.();}}directStates.clear();}
  }
  document.addEventListener('click',event=>{const button=event.target.closest('[data-direct-load]');if(!button)return;const el=button.closest('.direct-media').querySelector('[data-direct-src]');directStates.delete(el.dataset.directSrc);el.dataset.manualImage='1';directObserved.get(el)?.unobserve(el);directObserved.delete(el);directQueue.push(el);pumpDirect();});
  window.addEventListener('storage',event=>{if(event.key==='studio.direct-images')setDirect(event.newValue!=='off');});
  window.addEventListener('online',pumpDirect);
  function observe(root=document){for(const el of root.querySelectorAll('[data-media-src]')){if(observed.has(el))continue;const scrollRoot=el.closest('#reader-timeline,#library-results,#mini-preview');let observer=observers.get(scrollRoot);if(!observer){observer=new IntersectionObserver(entries=>{for(const {target,isIntersecting} of entries){if(!isIntersecting)continue;observer.unobserve(target);observed.delete(target);if(target.dataset.mediaSrc){target.src=target.dataset.mediaSrc;delete target.dataset.mediaSrc;if(target.tagName!=='IMG')target.preload='metadata';}}},{root:scrollRoot,rootMargin:'350px'});observers.set(scrollRoot,observer);}el.dataset.mediaObserved='1';observed.set(el,observer);observer.observe(el);}}
  document.addEventListener('error',event=>{if(!event.target.closest?.('.saved-media'))return;const fallback=event.target.parentElement.querySelector('.media-fallback');if(fallback)fallback.hidden=false;},true);
  const mutation=new MutationObserver(records=>{for(const entry of records){for(const node of entry.addedNodes)if(node.nodeType===1)observe(node);for(const node of entry.removedNodes)if(node.nodeType===1&&!node.isConnected){for(const el of node.querySelectorAll('[data-media-src]')){observed.get(el)?.unobserve(el);observed.delete(el);}for(const media of node.querySelectorAll('audio,video')){media.pause();media.removeAttribute('src');media.load();}}}});
  const midiCleanup=new MutationObserver(records=>{for(const entry of records)for(const node of entry.removedNodes)if(node.nodeType===1&&!node.isConnected)window.MidiPlayer?.stop(node);});
  function decorateLinks(root){
    const contents=[...(root.matches?.('.message-content')?[root]:[]),...root.querySelectorAll('.message-content')];
    for(const content of contents){if(content.dataset.directScanned)continue;content.dataset.directScanned='1';let text='';const walker=document.createTreeWalker(content,NodeFilter.SHOW_TEXT);let node;
      while(node=walker.nextNode())if(!node.parentElement.closest('code,pre'))text+=node.data+' ';
      const row=content.closest('.message,.reader-message'),id=row?.dataset.messageId||row?.dataset.id;
      const message=typeof messages!=='undefined'&&Array.isArray(messages)?messages.find(m=>m.id===id):typeof results!=='undefined'?results.messages?.find(m=>m.id===id)||previewMessages?.get(id):null;
      const markup=directHTML(text,message?._linked_images);if(markup)content.insertAdjacentHTML('afterend',markup);
    }
    observeDirect(root.matches?.('.message-content')?root.parentElement:root);
  }
  const directMutation=new MutationObserver(records=>{for(const entry of records){for(const node of entry.addedNodes)if(node.nodeType===1&&node.isConnected)decorateLinks(node);for(const node of entry.removedNodes)if(node.nodeType===1&&!node.isConnected)for(const el of node.querySelectorAll('[data-direct-src]')){directObserved.get(el)?.unobserve(el);directObserved.delete(el);if(el.onload&&el.getAttribute('src')&&!el.complete)el.onerror?.();el.onload=el.onerror=null;}}});
  document.addEventListener('DOMContentLoaded',()=>{observe();decorateLinks(document);mutation.observe(document.body,{childList:true,subtree:true});midiCleanup.observe(document.body,{childList:true,subtree:true});directMutation.observe(document.body,{childList:true,subtree:true});});
  return {html,type,observe,imageLinks,directHTML,setDirect,useSaved,get directEnabled(){return directEnabled;}};
})();
