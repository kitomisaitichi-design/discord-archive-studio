'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => Number(value || 0).toLocaleString();
let state = null, currentPage = localStorage.getItem('studio.page') || 'export';
let selected = new Set(JSON.parse(localStorage.getItem('studio.selected') || '[]')), selectedServer = localStorage.getItem('studio.server') || '', mode = localStorage.getItem('studio.mode') || 'full';
let stream = null, searchAbort = null, searchTimer, offset = 0, libraryTab = 'messages', results = {messages:[],total:0,media:{}};
let queueSignature = '', autoAccount = null, knownMessageCount = 0, toastTimer, closing = false;
let cooldownTimer;
let theme=localStorage.getItem('studio.theme')||'midnight';
const systemTheme=matchMedia('(prefers-color-scheme: light)');
function applyTheme(value){
  theme=['midnight','light','contrast','system'].includes(value)?value:'midnight';
  document.documentElement.dataset.theme=theme==='system'?(systemTheme.matches?'light':'midnight'):theme;
  localStorage.setItem('studio.theme',theme);
  $('theme-select').value=theme;
}
systemTheme.addEventListener('change',()=>{if(theme==='system')applyTheme(theme);});
const pending = new Set();
const messageMap = new Map();
const selectedMedia = new Map();
applyTheme(theme);
$('theme-select').onchange=()=>applyTheme($('theme-select').value);

async function api(path, data, signal) {
  const init = data === undefined ? {signal} : {method:'POST',headers:{'Content-Type':'application/json','X-Studio-Action':'local'},body:JSON.stringify(data),signal};
  const response = await fetch('/api/'+path, init);
  let value;
  try { value = await response.json(); } catch { throw new Error('The archive service is unavailable. Reopen the launcher.'); }
  if (!response.ok) throw new Error(value.error || 'The request failed.');
  return value;
}
function toast(message, error=false) {
  clearTimeout(toastTimer); $('toast').textContent=message; $('toast').classList.toggle('error',error); $('toast').hidden=false;
  toastTimer=setTimeout(()=>$('toast').hidden=true,error?9000:4500);
}
async function busy(button, task) {
  const key=button.id || button;
  if (pending.has(key)) return;
  pending.add(key); const old=button.textContent; button.disabled=true;
  try { return await task(); } catch(error) { if(error.name!=='AbortError') toast(error.message,true); }
  finally { pending.delete(key); button.disabled=false; button.textContent=old; }
}
function duration(minutes) {
  if(minutes>=1440) return minutes%1440===0 ? `${minutes/1440} ${minutes===1440?'day':'days'}` : `${(minutes/1440).toFixed(1)} days`;
  if(minutes>=60) return minutes%60===0 ? `${minutes/60} ${minutes===60?'hour':'hours'}` : `${(minutes/60).toFixed(1)} hours`;
  return `${minutes} min`;
}
function interval() { const raw=Math.min(10080,Math.max(10,Math.round(10*Math.pow(1008,Number($('interval-slider').value)/100))));return [10,30,60,180,360,720,1440,2880,10080].find(n=>Math.abs(raw-n)/n<.04)||raw; }
function intervalLabel() { $('interval-label').textContent=duration(interval()); }
function setIntervalMinutes(minutes) { $('interval-slider').value=Math.round(Math.log(minutes/10)/Math.log(1008)*100); intervalLabel(); }
function viewMode(value) {
  document.title='Discord Archive Studio · '+location.port;
  mode=value; localStorage.setItem('studio.mode',value);
  document.body.classList.toggle('mode-compact',value==='compact'); document.body.classList.toggle('mode-dock',value==='dock'); $('dock').hidden=value!=='dock';
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('selected',b.dataset.mode===value));
  api('window-mode',{mode:value}).catch(error=>toast('Window layout: '+error.message,true));
}
function showPage(page) {
  currentPage=page; localStorage.setItem('studio.page',page);
  document.body.classList.toggle('library-view',page==='library');
  document.body.classList.toggle('secondary-view',page!=='export');
  $('queue-tray').classList.toggle('collapsed',page!=='export');
  document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-'+page));
  document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
  if(page==='library') searchLibrary();
  if(page==='settings') loadUsers();
}
function currentChannels() { return state?.channels.filter(c=>c.server_id===selectedServer) || []; }
function replaceSelect(element, choices, value, empty) {
  const signature=JSON.stringify(choices);
  if(element.dataset.signature!==signature) {
    element.innerHTML=(empty?`<option value="">${esc(empty)}</option>`:'')+choices.map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    element.dataset.signature=signature;
  }
  element.value=value;
}
function renderCatalog() {
  if(!state) return;
  replaceSelect($('server-select'),state.servers,selectedServer,'Choose a server');
  replaceSelect($('compact-server'),state.servers,selectedServer,'Choose a server');
  replaceSelect($('compact-channel'),currentChannels().filter(c=>![4,15,16].includes(c.type)),Array.from(selected)[0]||'','Choose a channel');
  if(selectedServer && !state.servers.some(s=>s.id===selectedServer)) selectedServer='';
  const current=state.servers.find(s=>s.id===selectedServer);
  $('server-caption').textContent=current ? `${number(current.channels)} channels catalogued · ${number(current.messages)} messages saved` : 'Connect to browse, or import saved exports.';
  const q=$('channel-search').value.toLowerCase();
  const channels=currentChannels().filter(c=>c.name.toLowerCase().includes(q));
  const signature=JSON.stringify([channels,Array.from(selected)]);
  if($('channel-list').dataset.signature!==signature) {
    let html='',group='';
    for(const channel of channels) {
      const thread=[10,11,12].includes(channel.type);
      const next=thread?'THREADS':[2,13].includes(channel.type)?'VOICE CHANNEL CHAT':'TEXT CHANNELS';
      if([4,15,16].includes(channel.type)) continue;
      if(next!==group){html+=`<div class="channel-group">${next}</div>`;group=next;}
      html+=`<label class="channel-row"><input type="checkbox" data-channel="${esc(channel.id)}" ${selected.has(channel.id)?'checked':''} ${state.connection.connected&&!channel.accessible?'disabled':''}><span class="channel-type">${thread?'↳':[2,13].includes(channel.type)?'◖':'#'}</span><span class="channel-name">${esc(channel.name)}</span><small>${state.connection.connected&&!channel.accessible?'saved':channel.count?number(channel.count):''}</small></label>`;
    }
    $('channel-list').innerHTML=html || '<div class="empty small">No channels here yet.<br>Refresh your current accessible inventory.</div>';
    $('channel-list').dataset.signature=signature;
  }
  replaceSelect($('library-server'),state.servers,$('library-server').value,'Every server');
  updateLibraryChannels(); updateSummary();
}
function updateLibraryChannels() {
  const server=$('library-server').value;
  replaceSelect($('library-channel'),state?.channels.filter(c=>(!server||c.server_id===server)&&![4,15,16].includes(c.type))||[],$('library-channel').value,'Every channel');
}
function readOptions() {
  return {formats:Array.from(document.querySelectorAll('input[name=format]:checked'),x=>x.value),
    include_attachments:$('include-attachments').checked,download_media:$('download-media').checked,reactions:$('include-reactions').checked,
    edits:$('include-edits').checked,role_colors:$('role-colors').checked,exclude_bots:$('exclude-bots').checked,
    split_count:Number($('split-count').value),split_mb:Number($('split-mb').value),max_media_mb:Number($('max-media').value),
    batch_messages:Number($('batch-messages').value),cooldown_minutes:Number($('batch-cooldown').value),page_delay:Number($('page-delay').value),timing_variation:Number($('timing-variation').value),
    start:$('date-start').value,end:$('date-end').value,people:$('people-filter').value.split(',').map(x=>x.trim()).filter(Boolean),
    archived_threads:$('include-archived').checked,full_rescan:$('full-rescan').checked,recheck_edits:$('recheck-edits').checked};
}
function loadOptions(opts) {
  const mappings={include_attachments:'include-attachments',download_media:'download-media',reactions:'include-reactions',edits:'include-edits',
    role_colors:'role-colors',exclude_bots:'exclude-bots',split_count:'split-count',split_mb:'split-mb',max_media_mb:'max-media',
    batch_messages:'batch-messages',cooldown_minutes:'batch-cooldown',page_delay:'page-delay',timing_variation:'timing-variation',start:'date-start',end:'date-end',full_rescan:'full-rescan',recheck_edits:'recheck-edits'};
  for(const [key,id] of Object.entries(mappings)) { if(opts[key]===undefined)continue; if($(id).type==='checkbox')$(id).checked=opts[key];else $(id).value=opts[key]; }
  document.querySelectorAll('input[name=format]').forEach(x=>x.checked=opts.formats.includes(x.value));
  $('people-filter').value=(opts.people||[]).join(', '); updateSummary();
}
function updateSummary() {
  localStorage.setItem('studio.selected',JSON.stringify(Array.from(selected)));
  const channels=currentChannels().filter(c=>selected.has(c.id));
  const server=state?.servers.find(s=>s.id===selectedServer);
  $('selection-count').textContent=`${selected.size} channels selected`; $('summary-channels').textContent=number(selected.size);
  $('selected-summary').textContent=server?`${server.name} · ${selected.size} selected`:'Choose channels from the sidebar.';
  $('selected-chips').innerHTML=channels.slice(0,10).map(c=>`<span class="chip"># ${esc(c.name)}<button data-remove-channel="${esc(c.id)}" aria-label="Remove ${esc(c.name)}">×</button></span>`).join('')+(channels.length>10?`<span class="chip">+${channels.length-10} more</span>`:'');
  $('summary-messages').textContent=number(channels.reduce((a,c)=>a+c.count,0));
  const opts=readOptions(); $('summary-formats').textContent=opts.formats.map(x=>x==='md'?'MD':x.toUpperCase()).join(' · ')||'None selected';
  $('summary-batch').textContent=number(opts.batch_messages); $('summary-rest').textContent=duration(opts.cooldown_minutes)+(opts.timing_variation?` +0–${opts.timing_variation}%`:'');
  $('start-export').disabled=!selected.size || !state?.connection.connected || !opts.formats.length || channels.some(c=>!c.accessible);
  $('rebuild-zip').disabled=!selectedServer || !state?.channels.some(c=>c.server_id===selectedServer&&(c.generation||c.history_done));
}
function renderConnection() {
  const c=state.connection;
  $('connection-pill').classList.toggle('connected',c.connected);
  $('connection-text').textContent=state.demo?'Demo library · no Discord requests':c.busy?'Connecting desktop login…':c.connected?`${c.account.name} · ${c.source}`:'Open Discord to connect';
  $('connection-description').textContent=c.connected?`Connected as ${c.account.name} (${c.account.id}) through ${c.source}.`:c.error || 'Open logged-in Discord to connect automatically, or pair the browser connector.';
  $('summary-status').textContent=state.demo?'Demonstration data only':c.connected?'Connected · exports are read-only':'Offline library available';
  if(c.connected && autoAccount!==c.account.id) {
    autoAccount=c.account.id;
    api('servers',{}).then(()=>{if(selectedServer)return api('catalog',{server:selectedServer,archived:$('include-archived').checked});}).catch(e=>toast(e.message,true));
  }
}
function jobHTML(job, history=false) {
  const allowedPause=['running','waiting','queued'].includes(job.status), allowedResume=['paused','failed','blocked'].includes(job.status);
  const controls=history ? (job.status==='failed'?`<button data-job="${esc(job.id)}" data-action="apply" title="Apply the current export form settings">Use settings</button><button data-job="${esc(job.id)}" data-action="resume">Retry</button>`:'') :
    (allowedPause?`<button data-job="${esc(job.id)}" data-action="pause" title="Pause">Ⅱ</button>`:'')+
    (allowedResume?`<button data-job="${esc(job.id)}" data-action="resume" title="Recheck access and resume">▷</button>`:'')+
    (['queued','paused','blocked'].includes(job.status)?`<button data-job="${esc(job.id)}" data-action="apply" title="Apply the current export form settings">☷</button>`:'')+
    (['queued','paused'].includes(job.status)?`<button data-job="${esc(job.id)}" data-action="up" title="Move earlier">↑</button><button data-job="${esc(job.id)}" data-action="down" title="Move later">↓</button>`:'')+
    `<button data-job="${esc(job.id)}" data-action="cancel" title="Remove task; keep captured messages">×</button>`;
  return `<div class="job-row ${esc(job.status)}"><div class="job-label"><strong>${esc(job.server_name)} <span class="muted"># ${esc(job.channel_name)}</span></strong><small>${job.options.formats.map(x=>x.toUpperCase()).join(' · ')} · ${number(job.options.batch_messages)} per batch</small></div><div class="job-progress"><div class="progress-track"><div class="progress-fill"></div></div><div class="job-state"><span class="job-detail" title="${esc(job.detail)}"><span class="status-label">${esc(job.status)}</span> · ${esc(job.detail||'Ready to begin')}</span><span>${number(job.progress)} scanned</span></div></div><div class="job-controls">${controls}</div></div>`;
}
function renderQueue() {
  const signature=JSON.stringify([state.queue,state.history,state.schedules,state.publications]);
  if(signature!==queueSignature){
    $('tray-jobs').innerHTML=state.queue.slice(0,3).map(j=>jobHTML(j)).join('');
    $('queue-detail').innerHTML=state.queue.length?state.queue.map(j=>jobHTML(j)).join(''):'<div class="empty panel">Nothing waiting.<br>Select channels and add an export.</div>';
    $('history-list').innerHTML=state.history.length?state.history.map(j=>jobHTML(j,true)).join(''):'<div class="empty panel">Completed exports will appear here.</div>';
    $('schedule-list').innerHTML=state.schedules.length?state.schedules.map(s=>{
      const id=s.scope.split(':')[1], name=s.scope.startsWith('server:')?state.servers.find(x=>x.id===id)?.name:state.channels.find(x=>x.id===id)?.name;
      return `<div class="schedule-item"><div><strong>${s.scope.startsWith('channel:')?'# ':''}${esc(name||id)}</strong><small>${s.mode==='adaptive'?'Adaptive · seven-day sample':duration(s.minutes)}${s.options.inherited?' · server default':''}</small></div><div>${s.enabled?'Enabled':'Disabled'}<small>${s.enabled?'Next: '+esc(new Date(s.next_run*1000).toLocaleString()):'Paused'}</small></div></div>`;
    }).join(''):'<p class="hint">No schedules enabled. Configure one per server or per selected channel.</p>';
    $('publication-list').innerHTML=state.publications.length?state.publications.map(p=>`<div class="publication-item"><div><strong>${esc(state.servers.find(s=>s.id===p.server_id)?.name||p.server_id)}</strong><small>${esc(p.path)}</small></div><div>${(p.size/1048576).toFixed(1)} MB<small>${esc(new Date(p.updated*1000).toLocaleString())}</small></div></div>`).join(''):'<p class="hint">No current ZIPs have been published yet.</p>';
    queueSignature=signature;
  }
  $('queue-badge').textContent=state.queue.length; $('tray-count').textContent=state.queue.length;
  const active=state.queue.find(j=>['running','waiting'].includes(j.status));
  $('tray-status').textContent=active?`${active.status==='waiting'?'Cooling down':'Exporting'} · #${active.channel_name}`:state.queue.length?`${state.queue.length} tasks waiting`:'Ready when you are';
  $('dock-status').textContent=active?`#${active.channel_name} · ${number(active.progress)} scanned · ${active.status}`:state.queue.length?`${state.queue.length} tasks waiting`:`${number(state.stats.messages)} messages saved`;
  $('dock').classList.toggle('running',active?.status==='running'); $('dock-pause').disabled=!active;
  renderCooldown();
}
function renderCooldown(){
  clearTimeout(cooldownTimer);if(!state)return;
  const seconds=Math.max(0,Math.ceil(state.cooldown_until-Date.now()/1000));
  if(seconds&&state.queue.length){const text=`Batch rest · ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')} remaining`;$('tray-status').textContent=text;$('dock-status').textContent=text;cooldownTimer=setTimeout(renderCooldown,1000);}
}
function safeLink(url) { try { const p=new URL(url,location.origin);return ['http:','https:'].includes(p.protocol)?p.href:''; } catch{return '';} }
function contentHTML(text) {
  return esc(text).replace(/```([^]*?)```/g,'<pre><code>$1</code></pre>').replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>').replace(/~~([^~\n]+)~~/g,'<del>$1</del>');
}
function attachmentHTML(a, local, messageId) {
  const path=local?.[String(a.id)]; const original=safeLink(a.url);const image=path&&((a.content_type||'').startsWith('image/')||/\.(png|jpe?g|gif|webp)$/i.test(a.filename||''));
  const video=(a.content_type||'').startsWith('video/')||/\.(mp4|webm|mov|m4v|avi|mkv|mpeg|mpg|wmv|3gp)$/i.test(a.filename||'');
  const oversized=video&&Number(a.size)>10000000;
  return `<div class="attachment"><label>${!path&&a.id&&original?`<input type="checkbox" data-media-id="${esc(a.id)}" data-media-message="${esc(messageId)}" ${selectedMedia.has(String(a.id))?'checked':''} ${oversized?'disabled':''}> `:''}📎 ${esc(a.filename||a.fileName||'Attachment')} <small class="muted">${a.size?(Number(a.size)/1000000).toFixed(2)+' MB':'size unknown'}</small></label>${image?`<img src="${esc(path)}" alt="${esc(a.filename)}" loading="lazy">`:''}${path?` <a href="${esc(path)}" target="_blank" rel="noopener">Open saved file ↗</a>`:` <span class="muted">${esc(oversized?'Skipped: video exceeds 10 MB':a.download_status||'Manual download only')}</span>`}</div>`;
}
function messageHTML(m, local, small=false) {
  messageMap.set(m.id,m);
  const author=m.author?.global_name||m.author?.nickname||m.author?.username||m.author?.name||'Unknown';
  const initial=Array.from(author).slice(0,2).join('').toUpperCase();
  return `<article class="message" data-message-id="${esc(m.id)}"><div class="avatar">${esc(initial)}</div><div class="message-body"><div class="message-header"><span class="message-author">${esc(author)}</span><time class="message-time">${esc(new Date(m.timestamp).toLocaleString())}${m.edited_timestamp?' · edited':''}</time>${m.channel_name?`<span class="message-channel"># ${esc(m.channel_name)}</span>`:''}</div>${m.message_reference?.message_id?`<button class="message-reply subtle" data-reply="${esc(m.message_reference.message_id)}">↩ Reply to message ${esc(m.message_reference.message_id)}</button>`:''}<div class="message-content">${contentHTML(m.content||'')}</div>${small?'':(m.attachments||[]).map(a=>attachmentHTML(a,local,m.id)).join('')}${small?'':(m.embeds||[]).map(e=>`<div class="embed"><strong>${esc(e.title||'')}</strong><div>${esc(e.description||'')}</div></div>`).join('')}${m.reactions?.length?`<div class="reactions">${m.reactions.map(r=>`<span class="reaction">${esc(r.emoji?.name||'?')} ${number(r.count)}</span>`).join('')}</div>`:''}<div class="message-actions"><button data-copy-message="${esc(m.id)}">Copy text</button><button data-details="${esc(m.id)}">Details · ${esc(m.author?.id)}</button></div></div></article>`;
}
async function searchLibrary() {
  if(!state)return;
  searchAbort?.abort();searchAbort=new AbortController();
  const query=new URLSearchParams({q:$('library-search').value,server:$('library-server').value,channel:$('library-channel').value,person:$('library-person').value,start:$('library-start').value,end:$('library-end').value,offset,limit:80});
  try {results=await api('search?'+query.toString(),undefined,searchAbort.signal);renderResults();$('library-updates').hidden=true;}
  catch(error){if(error.name!=='AbortError')toast(error.message,true);}
}
function renderResults() {
  $('result-count').textContent=`${number(results.total)} matching messages`;
  $('page-label').textContent=results.total?`Page ${Math.floor(offset/80)+1} · ${number(offset+1)}–${number(Math.min(offset+80,results.total))}`:'No results';
  $('previous-page').disabled=offset===0;$('next-page').disabled=offset+80>=results.total;
  if(libraryTab==='messages') $('library-results').innerHTML=results.messages.map(m=>messageHTML(m,results.media)).join('')||'<div class="empty panel">No matching messages.<br>Try a different search, or import an existing export.</div>';
  if(libraryTab==='attachments') $('library-results').innerHTML=results.messages.flatMap(m=>(m.attachments||[]).map(a=>`<div class="panel"><div class="panel-title">${esc(m.channel_name)} · ${esc(m.author?.username||m.author?.name||'Unknown')}</div>${attachmentHTML(a,results.media,m.id)}</div>`)).join('')||'<div class="empty panel">No attachments on this result page.</div>';
  if(libraryTab==='statistics') $('library-results').innerHTML=`<div class="stats-grid">${[['Matching messages',results.total],['All saved messages',state.stats.messages],['People in library',state.stats.people],['Archived channels',state.stats.channels],['Downloaded attachments',state.stats.attachments],['Captured prior versions',state.stats.revisions]].map(([k,v])=>`<div class="stat-card"><span>${k}</span><strong>${number(v)}</strong></div>`).join('')}</div><p class="hint">Library totals cover all saved data. The matching-message count follows your search and filters.</p>`;
}
async function preview() {
  const channel=Array.from(selected)[0];
  if(!channel){$('mini-preview').innerHTML='<div class="empty small">Select a channel to preview saved messages.</div>';return;}
  try{const value=await api('search?'+new URLSearchParams({channel,limit:3}));$('mini-preview').innerHTML=value.messages.map(m=>messageHTML(m,value.media,true)).join('')||'<div class="empty small">Preview appears after the first saved batch.</div>';}catch(error){$('mini-preview').innerHTML=`<div class="empty small">${esc(error.message)}</div>`;}
}
async function loadUsers() {
  try {const users=await api('users');replaceSelect($('alias-user'),users.map(u=>({id:u.id,name:`${u.name} · ${u.id}`})),$('alias-user').value,'Choose an archived person…');replaceSelect($('alias-target'),users.map(u=>({id:u.id,name:`${u.name} · ${u.id}`})),$('alias-target').value,'Choose an archived person…');$('alias-list').textContent=users.filter(u=>u.person_id).map(u=>`${u.name} (${u.id}) → ${u.person_id}`).join('\n')||'No cross-account links.';}catch(e){toast(e.message,true);}
}
function applyState(value) {
  const was=state;state=value;
  if(was&&currentPage==='library'&&JSON.stringify(was.channels.map(c=>[c.id,c.generation]))!==JSON.stringify(value.channels.map(c=>[c.id,c.generation])))$('library-updates').hidden=false;
  if(!was){$('destination').value=value.destination;setIntervalMinutes(1440);}
  if(!was&&currentPage==='library')searchLibrary();
  renderConnection();renderCatalog();renderQueue();
  $('auto-connect').checked=state.auto_connect;
  $('app-address').textContent=location.origin;$('app-address').href=location.origin+'/';
  $('media-task-list').innerHTML=(state.media_tasks||[]).map(t=>`<div class="schedule-item"><div><strong># ${esc(t.channel_name)} · ${esc(t.attachment_id)}</strong><small>${esc(t.status)} · ${(t.received/1000000).toFixed(2)} MB · ${esc(t.detail)}</small></div>${['queued','running','paused'].includes(t.status)?`<button data-cancel-media="${esc(t.attachment_id)}">Cancel</button>`:''}</div>`).join('')||'<p class="hint">No attachments selected. Text exports never start media downloads.</p>';
  replaceSelect($('preset-select'),state.presets.map(p=>({id:p.name,name:p.name})),$('preset-select').value,'Load a preset…');
  if(value.stats.messages!==knownMessageCount){if(currentPage==='library'&&was)$('library-updates').hidden=false;knownMessageCount=value.stats.messages;preview();}
  if(value.worker_error&&value.worker_error!==was?.worker_error)toast(value.worker_error,true);
}
function connectEvents() {
  stream?.close();stream=new EventSource('/api/events');
  stream.onmessage=event=>{try{applyState(JSON.parse(event.data));$('offline-banner').hidden=true;}catch(e){console.error('Unable to render archive update',e);}};
  stream.onerror=()=>{if(!closing)$('offline-banner').hidden=false;};
}
async function saveSchedule(enabled) {
  if(!selectedServer)throw new Error('Choose a server first.');
  const scope=$('schedule-scope').value;
  const ids=scope==='server'?[`server:${selectedServer}`]:Array.from(selected,id=>`channel:${id}`);
  if(!ids.length)throw new Error('Select channels to give them independent schedules.');
  for(const id of ids)await api('schedule',{scope:id,enabled,mode:document.querySelector('input[name=schedule-mode]:checked').value,minutes:interval(),options:readOptions()});
  toast(enabled?`Schedule saved for ${ids.length} ${scope==='server'?'server':'channels'}.`:'Schedule disabled.');
}
async function importFiles(files) {
  if(pending.has('import'))return;pending.add('import');$('import-button').disabled=true;
  try {for(const file of files){toast(`Importing ${file.name}…`);const response=await fetch('/api/import?'+new URLSearchParams({name:file.name}),{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Studio-Action':'local'},body:file});const result=await response.json();if(!response.ok)throw new Error(result.error);toast(`${file.name}: ${number(result.added)} new, ${number(result.edited)} updated.${result.warnings.length?' '+result.warnings.join(' '):''}`);}
    showPage('library');offset=0;await searchLibrary();}
  catch(e){toast(e.message,true);}finally{pending.delete('import');$('import-button').disabled=false;$('import-files').value='';}
}

document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.page)showPage(button.dataset.page);
  if(button.dataset.mode)viewMode(button.dataset.mode);
  if(button.dataset.removeChannel){selected.delete(button.dataset.removeChannel);renderCatalog();preview();}
  if(button.dataset.job)busy(button,()=>api('control',{id:button.dataset.job,action:button.dataset.action,...(button.dataset.action==='apply'?{options:readOptions()}:{})}));
  if(button.dataset.cancelMedia)busy(button,()=>api('media/cancel',{id:button.dataset.cancelMedia}));
  if(button.dataset.libraryTab){libraryTab=button.dataset.libraryTab;document.querySelectorAll('[data-library-tab]').forEach(x=>x.classList.toggle('active',x===button));renderResults();}
  if(button.dataset.copyMessage)busy(button,async()=>{await navigator.clipboard.writeText(messageMap.get(button.dataset.copyMessage)?.content||'');toast('Message text copied.');});
  if(button.dataset.details||button.dataset.reply)busy(button,async()=>{const value=await api('message?'+new URLSearchParams({id:button.dataset.details||button.dataset.reply}));$('message-details').innerHTML=messageHTML(value.message,results.media)+`<pre>${esc(JSON.stringify(value.message,null,2))}</pre>`+(value.revisions.length?`<details><summary>${value.revisions.length} captured prior versions</summary>${value.revisions.map(m=>`<pre>${esc(JSON.stringify(m,null,2))}</pre>`).join('')}</details>`:'');if(!$('message-dialog').open)$('message-dialog').showModal();});
});
document.addEventListener('change',event=>{
  const input=event.target;
  if(input.dataset.mediaId){input.checked?selectedMedia.set(input.dataset.mediaId,{attachment_id:input.dataset.mediaId,message_id:input.dataset.mediaMessage}):selectedMedia.delete(input.dataset.mediaId);$('selected-media-count').textContent=selectedMedia.size;}
});
$('download-selected').onclick=()=>busy($('download-selected'),async()=>{const result=await api('media/select',{selections:Array.from(selectedMedia.values()),cap_mb:Number($('media-cap').value)});selectedMedia.clear();$('selected-media-count').textContent='0';await searchLibrary();toast(`${result.tasks} manual downloads queued; ${result.skipped} skipped by size cap. Text exports run first.`);});
$('clear-media-selection').onclick=()=>{selectedMedia.clear();$('selected-media-count').textContent='0';renderResults();};
$('server-select').addEventListener('change',()=>{selectedServer=$('server-select').value;localStorage.setItem('studio.server',selectedServer);selected.clear();renderCatalog();preview();if(state.connection.connected&&selectedServer)busy($('refresh-channels'),()=>api('catalog',{server:selectedServer,archived:$('include-archived').checked}));});
$('compact-server').onchange=()=>{$('server-select').value=$('compact-server').value;$('server-select').dispatchEvent(new Event('change'));};
$('compact-channel').onchange=()=>{selected=new Set($('compact-channel').value?[$('compact-channel').value]:[]);renderCatalog();preview();};
$('channel-search').addEventListener('input',renderCatalog);
$('channel-list').addEventListener('change',event=>{const id=event.target.dataset.channel;if(id){event.target.checked?selected.add(id):selected.delete(id);renderCatalog();preview();}});
$('select-all').onclick=()=>{currentChannels().filter(c=>![4,15,16].includes(c.type)&&(!state.connection.connected||c.accessible)).forEach(c=>selected.add(c.id));renderCatalog();preview();};
$('clear-selection').onclick=()=>{selected.clear();renderCatalog();preview();};
$('refresh-servers').onclick=()=>busy($('refresh-servers'),()=>api('servers',{}));
$('refresh-channels').onclick=()=>busy($('refresh-channels'),async()=>{if(!selectedServer)throw new Error('Choose a server first.');return api('catalog',{server:selectedServer,archived:$('include-archived').checked});});
$('include-archived').onchange=()=>{if(selectedServer&&state.connection.connected)$('refresh-channels').click();};
document.querySelectorAll('#page-export input,#page-export select').forEach(input=>input.addEventListener('change',updateSummary));
$('interval-slider').oninput=intervalLabel;$('seven-day').onclick=()=>setIntervalMinutes(10080);
$('save-schedule').onclick=()=>busy($('save-schedule'),()=>saveSchedule(true));$('disable-schedule').onclick=()=>busy($('disable-schedule'),()=>saveSchedule(false));
$('start-export').onclick=()=>busy($('start-export'),async()=>{const opts=readOptions();if(opts.start&&opts.end&&opts.start>opts.end)throw new Error('End date must be on or after start date.');const result=await api('enqueue',{channels:Array.from(selected),options:opts});toast(`${result.tasks} export tasks added or already queued.`);});
$('save-destination').onclick=()=>busy($('save-destination'),async()=>{await api('settings',{destination:$('destination').value});toast('Destination saved.');});
$('browse-folder').onclick=()=>busy($('browse-folder'),async()=>{const result=await api('folder',{});if(result.path){$('destination').value=result.path;await api('settings',{destination:result.path});toast('Destination selected.');}});
$('open-folder').onclick=()=>busy($('open-folder'),()=>api('open-folder',{}));
$('rebuild-zip').onclick=()=>busy($('rebuild-zip'),async()=>{const r=await api('publish',{server:selectedServer,channels:Array.from(selected),options:readOptions()});toast(r.unchanged?'Current ZIP already matches the library.':'Current server ZIP updated.');});
$('preset-select').onchange=()=>{const p=state.presets.find(p=>p.name===$('preset-select').value);if(p){loadOptions(p.options);$('preset-name').value=p.name;}};
$('save-preset').onclick=()=>busy($('save-preset'),async()=>{await api('preset',{name:$('preset-name').value,options:readOptions()});toast('Preset saved.');});
$('remove-preset').onclick=()=>busy($('remove-preset'),async()=>{await api('preset',{name:$('preset-select').value,remove:true});toast('Preset removed.');});
function openLibrary(){showPage('library');$('library-server').value=selectedServer;updateLibraryChannels();$('library-channel').value=Array.from(selected)[0]||'';offset=0;searchLibrary();}
['server-library','selected-preview','open-preview-library'].forEach(id=>$(id).onclick=openLibrary);
['settings-top','connection-pill'].forEach(id=>$(id).onclick=()=>showPage('settings'));
$('connect-desktop').onclick=()=>busy($('connect-desktop'),async()=>{await api('connect',{});toast('Checking your local Discord login…');});
$('disconnect').onclick=()=>busy($('disconnect'),()=>api('disconnect',{}));
$('auto-connect').onchange=()=>api('settings',{auto_connect:$('auto-connect').checked}).catch(e=>toast(e.message,true));
$('pair-browser').onclick=()=>busy($('pair-browser'),async()=>{const result=await api('pair-code',{});$('pair-code').textContent=result.code;toast('Code expires in 10 minutes. Paste it in the connector popup.');});
$('link-person').onclick=()=>busy($('link-person'),async()=>{await api('alias',{user_id:$('alias-user').value,person_id:$('alias-target').value});await loadUsers();toast('Accounts linked. Search either ID to see the person’s messages.');});
$('unlink-person').onclick=()=>busy($('unlink-person'),async()=>{await api('alias',{user_id:$('alias-user').value});await loadUsers();toast('Account link removed.');});
['library-search','library-person','library-start','library-end'].forEach(id=>$(id).addEventListener('input',()=>{offset=0;clearTimeout(searchTimer);searchTimer=setTimeout(searchLibrary,180);}));
$('library-server').onchange=()=>{updateLibraryChannels();offset=0;searchLibrary();};$('library-channel').onchange=()=>{offset=0;searchLibrary();};
$('clear-library').onclick=()=>{['library-search','library-person','library-start','library-end','library-server','library-channel'].forEach(id=>$(id).value='');updateLibraryChannels();offset=0;searchLibrary();};
$('next-page').onclick=()=>{offset+=80;searchLibrary();};$('previous-page').onclick=()=>{offset=Math.max(0,offset-80);searchLibrary();};$('library-updates').onclick=searchLibrary;
$('import-button').onclick=()=>$('import-files').click();$('import-files').onchange=()=>importFiles(Array.from($('import-files').files));
document.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();document.body.classList.add('drop-active');}});
document.addEventListener('dragleave',e=>{if(!e.relatedTarget)document.body.classList.remove('drop-active');});
document.addEventListener('drop',e=>{if(e.dataTransfer.files.length){e.preventDefault();document.body.classList.remove('drop-active');importFiles(Array.from(e.dataTransfer.files));}});
$('expand-queue').onclick=()=>{showPage('queue');$('queue-tray').classList.remove('collapsed');};$('collapse-tray').onclick=()=>$('queue-tray').classList.toggle('collapsed');
$('dock-expand').onclick=()=>viewMode('compact');$('dock-pause').onclick=()=>{const active=state.queue.find(j=>['running','waiting'].includes(j.status));if(active)api('control',{id:active.id,action:'pause'}).catch(e=>toast(e.message,true));};
$('close-message').onclick=()=>$('message-dialog').close();
$('shutdown').onclick=()=>busy($('shutdown'),async()=>{closing=true;stream?.close();await api('shutdown',{});toast('Archive service closed. Reopen the launcher to continue.');});
$('retry-app').onclick=()=>{connectEvents();api('state').then(applyState).catch(e=>toast(e.message,true));};
document.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){e.preventDefault();showPage('library');$('library-search').focus();}});
viewMode(mode);showPage(currentPage);intervalLabel();api('state').then(applyState).then(connectEvents).catch(e=>{toast(e.message,true);$('offline-banner').hidden=false;});
