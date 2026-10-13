'use strict';
// Extend the existing Library controls without changing queue or export state.
const libraryContainer=$('library-results');
let libraryEpoch=0,libraryBusy=false,libraryHasMore=false,libraryPrefsLoaded=false,libraryRestore=null;
const libraryPages=new ChatBuffer.Pages((query,signal)=>api('search?'+new URLSearchParams(query),undefined,signal));
function libraryQuery(extra={}){return {q:$('library-search').value,server:$('library-server').value,channel:$('library-channel').value,person:$('library-person').value,attachment:$('library-attachment').value,type:$('library-type').value,phrase:$('library-phrase').checked?'1':'',start:$('library-start').value,end:$('library-end').value,limit:80,...extra};}
const originalRenderResults=renderResults;
renderResults=function(){
  libraryContainer.classList.toggle('transcript',libraryTab==='messages');libraryContainer.classList.toggle('media-results',libraryTab==='attachments');
  if(libraryTab==='statistics'){originalRenderResults();return;}
  $('result-count').textContent=number(results.total)+' matching messages';$('page-label').textContent=results.total?`${number(offset+1)}–${number(offset+results.messages.length)} · scroll for older`:'No results';
  $('previous-page').disabled=offset===0;$('next-page').disabled=!libraryHasMore||libraryBusy;
  if(libraryTab==='messages')ChatBuffer.reconcile(libraryContainer,results.messages,m=>messageHTML(m,results.media),m=>m.id,{empty:'No matching messages. Try another text, person, file or date filter.'});
  else{const rows=results.messages.flatMap(m=>(m.attachments||[]).map(a=>({id:m.id+':'+a.id,m,a})));ChatBuffer.reconcile(libraryContainer,rows,x=>`<article class="panel" data-message-id="${esc(x.m.id)}"><div class="panel-title">${esc(x.m.channel_name)} · ${esc(x.m.author?.username||x.m.author?.name||'Unknown')}</div>${attachmentHTML(x.a,results.media,x.m.id)}</article>`,x=>x.id,{limit:480,empty:'No attachments in these matching messages.'});}
};
searchLibrary=async function(){
  if(!state)return;
  if(!libraryPrefsLoaded){libraryPrefsLoaded=true;try{const prefs=JSON.parse(localStorage.getItem('studio.library-search')||'{}');for(const name of ['server','channel','search','person','attachment','type','start','end']){if(prefs[name])$('library-'+name).value=prefs[name];if(name==='server')updateLibraryChannels();}$('library-phrase').checked=!!prefs.phrase;}catch{}}
  if(libraryEpoch===0){try{libraryRestore=JSON.parse(localStorage.getItem('studio.library-position')||'null');}catch{}}
  const epoch=++libraryEpoch;libraryPages.reset();searchAbort?.abort();libraryBusy=true;
  const query=libraryQuery({offset}),restore=libraryRestore;libraryRestore=null;
  if(restore?.signature===JSON.stringify(libraryQuery())){query.cursor=restore.cursor;query.inclusive='1';delete query.offset;offset=restore.index||0;}
  localStorage.setItem('studio.library-search',JSON.stringify(Object.fromEntries(['server','channel','search','person','attachment','type','start','end','phrase'].map(name=>[name,name==='phrase'?$('library-phrase').checked:$('library-'+name).value]))));
  try{const value=await libraryPages.get('initial',query);if(!value||epoch!==libraryEpoch)return;results=value;libraryContainer.replaceChildren();libraryHasMore=offset+value.messages.length<value.total;libraryBusy=false;renderResults();libraryContainer.scrollTop=0;if(query.inclusive&&restore){const row=libraryContainer.querySelector('[data-message-id="'+CSS.escape(restore.message)+'"]');if(row)libraryContainer.scrollTop+=row.getBoundingClientRect().top-libraryContainer.getBoundingClientRect().top-(restore.top||0);}$('library-updates').hidden=true;warmLibrary();}
  catch(error){if(epoch===libraryEpoch&&error.name!=='AbortError')toast(error.message,true);}
  finally{if(epoch===libraryEpoch)libraryBusy=false;}
};
function nextLibraryQuery(){const last=results.messages.at(-1);return libraryQuery(last?._cursor?{cursor:last._cursor}:{offset:offset+results.messages.length});}
function warmLibrary(){if(!libraryBusy&&libraryHasMore&&results.messages.length&&libraryContainer.scrollHeight-libraryContainer.scrollTop-libraryContainer.clientHeight<libraryContainer.clientHeight*1.5)libraryPages.get('older',nextLibraryQuery()).catch(error=>toast(error.message,true));}
async function olderLibrary(){if(libraryBusy||!libraryHasMore)return;libraryBusy=true;const epoch=libraryEpoch;try{const value=await libraryPages.get('older',nextLibraryQuery());if(!value||epoch!==libraryEpoch)return;const ids=new Set(results.messages.map(m=>m.id));results.messages.push(...value.messages.filter(m=>!ids.has(m.id)));Object.assign(results.media,value.media);const excess=Math.max(0,results.messages.length-240);if(excess){results.messages.splice(0,excess);offset+=excess;}const savedIds=new Set(results.messages.flatMap(m=>(m.attachments||[]).map(a=>String(a.id))));results.media=Object.fromEntries(Object.entries(results.media).filter(([id])=>savedIds.has(id)));libraryHasMore=value.messages.length===80&&offset+results.messages.length<value.total;libraryBusy=false;renderResults();libraryPages.reset();warmLibrary();}catch(error){if(epoch===libraryEpoch&&error.name!=='AbortError')toast(error.message,true);}finally{if(epoch===libraryEpoch)libraryBusy=false;}}
libraryContainer.addEventListener('scroll',()=>{if(libraryTab==='statistics')return;warmLibrary();if(libraryContainer.scrollHeight-libraryContainer.scrollTop-libraryContainer.clientHeight<120)olderLibrary();},{passive:true});
$('next-page').onclick=olderLibrary;

let previewBusy=false,previewBuffer=null,previewAbort=null;
const originalPreview=preview;
preview=async function(older=false){
  const channel=Array.from(selected)[0],container=$('mini-preview');
  if(!channel){previewAbort?.abort();previewBuffer=null;return originalPreview();}
  const changed=channel!==previewChannel;if(older&&previewBusy)return;
  if(changed){previewVersion++;previewAbort?.abort();previewMessages.clear();previewCursor=null;previewBuffer=null;container.replaceChildren();}
  previewChannel=channel;const version=++previewVersion,oldTop=container.scrollTop,atEnd=container.scrollHeight-oldTop-container.clientHeight<35;
  if(!older)previewAbort?.abort();previewBusy=true;
  try{let value;if(older&&previewBuffer?.cursor===previewCursor)value=await previewBuffer.promise;else{previewAbort=new AbortController();value=await api('preview?'+new URLSearchParams({channel,limit:50,...(older&&previewCursor?{before:previewCursor}:{})}),undefined,previewAbort.signal);}if(version!==previewVersion||channel!==previewChannel)return;
    for(const message of value.messages)previewMessages.set(message.id,message);
    if(older||changed||!previewCursor){previewCursor=value.next_cursor;previewMore=value.has_more;previewBuffer=null;}
    let rows=[...previewMessages.values()].sort((a,b)=>Date.parse(a.timestamp)-Date.parse(b.timestamp)||a.id.length-b.id.length||a.id.localeCompare(b.id));
    if(rows.length>240){rows=older?rows.slice(0,240):rows.slice(-240);previewMessages=new Map(rows.map(m=>[m.id,m]));if(!older){previewCursor=rows[0]?.id;previewMore=true;}}
    ChatBuffer.reconcile(container,rows,m=>messageHTML(m,value.media,true),m=>m.id,{empty:'Preview appears after the first saved batch.'});
    if(changed||(!older&&atEnd))container.scrollTop=container.scrollHeight;
    previewBusy=false;warmPreview();
  }catch(error){if(version===previewVersion&&error.name!=='AbortError')toast('Saved preview: '+error.message,true);}finally{if(version===previewVersion)previewBusy=false;}
};
function warmPreview(){const container=$('mini-preview');if(previewBusy||!previewMore||!previewCursor||container.scrollTop>container.clientHeight*1.5)return;if(!previewBuffer||previewBuffer.cursor!==previewCursor){previewAbort=new AbortController();const cursor=previewCursor;previewBuffer={cursor,promise:api('preview?'+new URLSearchParams({channel:previewChannel,limit:50,before:cursor}),undefined,previewAbort.signal)};previewBuffer.promise.catch(error=>{if(error.name!=='AbortError')toast(error.message,true);if(previewBuffer?.cursor===cursor)previewBuffer=null;});}}
$('mini-preview').addEventListener('scroll',()=>{warmPreview();if($('mini-preview').scrollTop<80&&previewMore&&!previewBusy)preview(true);},{passive:true});
