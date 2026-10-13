'use strict';
window.ChatBuffer=(()=>{
  function reconcile(container,items,html,id=m=>String(m.id),{empty='No saved messages.',limit=240}={}){
    const existing=new Map([...container.querySelectorAll(':scope > [data-chat-key]')].map(el=>[el.dataset.chatKey,el]));
    const visible=[...container.children].find(el=>el.getBoundingClientRect().bottom>=container.getBoundingClientRect().top);
    const anchorKey=visible?.dataset.chatKey,anchorTop=visible?.getBoundingClientRect().top;
    const keep=new Set();let previous=null;
    for(const item of items.slice(0,limit)){
      const key=id(item);if(keep.has(key))continue;keep.add(key);
      let node=existing.get(key);
      if(!node){const template=document.createElement('template');template.innerHTML=html(item);node=template.content.firstElementChild;if(!node)continue;node.dataset.chatKey=key;}
      const next=previous?previous.nextElementSibling:container.firstElementChild;
      if(node!==next)container.insertBefore(node,next);previous=node;
    }
    let pinned=0;
    for(const el of [...container.children])if(!keep.has(el.dataset.chatKey)){if(items.length&&active(el)&&pinned++<8)el.classList.add('chat-pinned');else{for(const media of el.querySelectorAll('audio,video'))media.pause();el.remove();}}else el.classList.remove('chat-pinned');
    if(!items.length){const el=document.createElement('div');el.className='empty';el.textContent=empty;container.replaceChildren(el);}
    if(anchorKey&&anchorTop!==undefined){const current=[...container.children].find(el=>el.dataset.chatKey===anchorKey);if(current)container.scrollTop+=current.getBoundingClientRect().top-anchorTop;}
    MediaView?.observe(container);
  }
  class Pages{
    constructor(fetchPage){this.fetchPage=fetchPage;this.reset();}
    reset(){this.epoch=(this.epoch||0)+1;for(const entry of this.entries?.values()||[])entry.controller.abort();this.entries=new Map();}
    async get(key,params){
      const tag=JSON.stringify([key,params]);let entry=this.entries.get(tag);
      if(!entry){const controller=new AbortController(),epoch=this.epoch;entry={controller,promise:this.fetchPage(params,controller.signal).then(value=>epoch===this.epoch?value:null).catch(error=>{if(this.entries.get(tag)===entry)this.entries.delete(tag);if(error.name==='AbortError')return null;throw error;})};this.entries.set(tag,entry);}
      while(this.entries.size>3){const first=this.entries.keys().next().value;this.entries.get(first).controller.abort();this.entries.delete(first);}
      return entry.promise;
    }
    retain(keys){for(const [key,entry] of this.entries)if(!keys.includes(key)){entry.controller.abort();this.entries.delete(key);}}
    drop(){this.reset();}
  }
  function active(container){return [...container.querySelectorAll('audio,video')].some(el=>!el.paused)||!!container.querySelector('[data-midi-playing="true"]');}
  function trimMetadata(map,keep,limit=600){for(const key of map.keys()){if(map.size<=Math.max(limit,keep.size))break;if(!keep.has(key))map.delete(key);}return map.size;}
  return {reconcile,Pages,active,trimMetadata};
})();
