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
  function observe(root=document){for(const el of root.querySelectorAll('[data-media-src]')){if(observed.has(el))continue;const scrollRoot=el.closest('#reader-timeline,#library-results,#mini-preview');let observer=observers.get(scrollRoot);if(!observer){observer=new IntersectionObserver(entries=>{for(const {target,isIntersecting} of entries){if(!isIntersecting)continue;observer.unobserve(target);observed.delete(target);if(target.dataset.mediaSrc){target.src=target.dataset.mediaSrc;delete target.dataset.mediaSrc;if(target.tagName!=='IMG')target.preload='metadata';}}},{root:scrollRoot,rootMargin:'350px'});observers.set(scrollRoot,observer);}el.dataset.mediaObserved='1';observed.set(el,observer);observer.observe(el);}}
  document.addEventListener('error',event=>{if(!event.target.closest?.('.saved-media'))return;const fallback=event.target.parentElement.querySelector('.media-fallback');if(fallback)fallback.hidden=false;},true);
  const mutation=new MutationObserver(records=>{for(const entry of records){for(const node of entry.addedNodes)if(node.nodeType===1)observe(node);for(const node of entry.removedNodes)if(node.nodeType===1&&!node.isConnected){for(const el of node.querySelectorAll('[data-media-src]')){observed.get(el)?.unobserve(el);observed.delete(el);}for(const media of node.querySelectorAll('audio,video')){media.pause();media.removeAttribute('src');media.load();}}}});
  const midiCleanup=new MutationObserver(records=>{for(const entry of records)for(const node of entry.removedNodes)if(node.nodeType===1&&!node.isConnected)window.MidiPlayer?.stop(node);});
  document.addEventListener('DOMContentLoaded',()=>{observe();mutation.observe(document.body,{childList:true,subtree:true});midiCleanup.observe(document.body,{childList:true,subtree:true});});
  return {html,type,observe};
})();
