'use strict';
const $ = id => document.getElementById(id);
const avatarSetting=document.createElement('label');avatarSetting.className='switch-row';avatarSetting.innerHTML='<span>Cache and include profile pictures <small class="hint">Optional · after text · 1 MB each</small></span><input id="include-avatars" type="checkbox">';$('download-media').closest('label').after(avatarSetting);
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
  theme=['midnight','light','contrast','system','graphite','ocean','forest','rose','sepia'].includes(value)?value:'midnight';
  document.documentElement.dataset.theme=theme==='system'?(systemTheme.matches?'light':'midnight'):theme;
  localStorage.setItem('studio.theme',theme);
  $('theme-select').value=theme;
}
systemTheme.addEventListener('change',()=>{if(theme==='system')applyTheme(theme);});
window.addEventListener('storage',event=>{if(event.key==='studio.theme')applyTheme(event.newValue);});
const pending = new Set();
const messageMap = new Map();
let metadataPruneQueued=false;
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
  if(page==='people'&&typeof loadPeople==='function')loadPeople();
  if(page==='archives'&&typeof loadArchiveCatalogue==='function')loadArchiveCatalogue();
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
  if(typeof renderServerPickers==='function')renderServerPickers();
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
    const channelHTML=html || '<div class="empty small">No channels here yet.<br>Refresh your current accessible inventory.</div>';
    if(typeof StudioRender!=='undefined')StudioRender.markup($('channel-list'),channelHTML);else $('channel-list').innerHTML=channelHTML;
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
    include_avatars:$('include-avatars').checked,include_attachments:$('include-attachments').checked,download_media:$('download-media').checked,reactions:$('include-reactions').checked,
    edits:$('include-edits').checked,role_colors:$('role-colors').checked,exclude_bots:$('exclude-bots').checked,
    split_count:Number($('split-count').value),split_mb:Number($('split-mb').value),max_media_mb:Number($('max-media').value),
    batch_messages:Number($('batch-messages').value),cooldown_minutes:Number($('batch-cooldown').value),page_delay:Number($('page-delay').value),timing_variation:Number($('timing-variation').value),
    start:$('date-start').value,end:$('date-end').value,people:$('people-filter').value.split(',').map(x=>x.trim()).filter(Boolean),
    archived_threads:$('include-archived').checked,full_rescan:$('full-rescan').checked,recheck_edits:$('recheck-edits').checked,_use_queue_defaults:$('use-future-defaults')?.checked!==false};
}
function loadOptions(opts) {
  const mappings={include_avatars:'include-avatars',include_attachments:'include-attachments',download_media:'download-media',reactions:'include-reactions',edits:'include-edits',
    role_colors:'role-colors',exclude_bots:'exclude-bots',split_count:'split-count',split_mb:'split-mb',max_media_mb:'max-media',
    batch_messages:'batch-messages',cooldown_minutes:'batch-cooldown',page_delay:'page-delay',timing_variation:'timing-variation',start:'date-start',end:'date-end',full_rescan:'full-rescan',recheck_edits:'recheck-edits'};
  for(const [key,id] of Object.entries(mappings)) { if(opts[key]===undefined)continue;const el=$(id);if(el.tagName==='SELECT'&&!Array.from(el.options).some(o=>o.value===String(opts[key]))){const o=document.createElement('option');o.value=String(opts[key]);o.textContent=key==='cooldown_minutes'?duration(Number(opts[key]))+' · custom':number(opts[key])+' · custom';el.add(o);}if(el.type==='checkbox')el.checked=opts[key];else el.value=opts[key]; }
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
  const controls=history ? `<button data-saved-channel="${esc(job.channel_id)}" title="Read locally saved messages">Read messages</button>`+(job.status==='failed'?`<button data-job="${esc(job.id)}" data-action="apply" title="Apply the current export form settings">Use settings</button><button data-job="${esc(job.id)}" data-action="resume">Retry</button>`:'') :
    (allowedPause?`<button data-job="${esc(job.id)}" data-action="pause" title="Pause">Ⅱ</button>`:'')+
    (allowedResume?`<button data-job="${esc(job.id)}" data-action="resume" title="Recheck access and resume">▷</button>`:'')+
    (['queued','waiting','paused','blocked'].includes(job.status)?`<button data-queue-settings="${esc(job.id)}" ${job.owner_id===state.settings_owner&&job.id!==state.processing_job?'':'disabled'} title="Edit this task’s full export settings">Settings</button>`:'')+
    (['queued','paused','waiting','blocked'].includes(job.status)?`<button data-job="${esc(job.id)}" data-action="up" title="Move earlier">↑</button><button data-job="${esc(job.id)}" data-action="down" title="Move later">↓</button>`:'')+
    `<button data-job="${esc(job.id)}" data-action="cancel" title="Remove task; keep captured messages">×</button>`;
  const movable=!history&&job.id!==state.processing_job&&['queued','paused','waiting','blocked'].includes(job.status);
  return `<div class="job-row ${esc(job.status)}" ${history?'':`data-queue-job="${esc(job.id)}" data-movable="${movable}"`}><div class="job-label">${movable?'<span class="drag-handle" role="button" tabindex="0" draggable="false" title="Drag to reorder; arrows also move this task" aria-label="Drag task">⠿</span>':''}${history?'':`<input class="queue-select" type="checkbox" data-select-queue="${esc(job.id)}" aria-label="Select ${esc(job.channel_name)}" ${movable&&job.owner_id===state.settings_owner?'':'disabled'} ${typeof queueSelection!=='undefined'&&queueSelection.has(job.id)?'checked':''}>`}<strong>${esc(job.server_name)} <span class="muted"># ${esc(job.channel_name)}</span></strong><small>${job.options.formats.map(x=>x.toUpperCase()).join(' · ')} · ${number(job.options.batch_messages)} per batch · ${duration(job.options.cooldown_minutes)} rest</small></div><div class="job-progress"><div class="progress-track"><div class="progress-fill"></div></div><div class="job-state"><span class="job-detail" title="${esc(job.detail)}"><span class="status-label">${esc(job.status)}</span> · ${esc(job.detail||'Ready to begin')}</span><span>${number(job.progress)} scanned</span></div></div><div class="job-controls">${controls}</div></div>`;
}
function renderQueue() {
  const signature=JSON.stringify([state.queue,state.history,state.schedules,state.publications,state.processing_job]);
  if(signature!==queueSignature&&!(typeof draggedJob!=='undefined'&&draggedJob)){
    const scrolls=[$('tray-jobs'),$('queue-detail')].map(e=>e.scrollTop);
    $('tray-jobs').innerHTML=state.queue.map(j=>jobHTML(j)).join('');
    $('queue-detail').innerHTML=state.queue.length?state.queue.map(j=>jobHTML(j)).join(''):'<div class="empty panel">Nothing waiting.<br>Select channels and add an export.</div>';
    $('history-list').innerHTML=state.history.length?state.history.map(j=>jobHTML(j,true)).join(''):'<div class="empty panel">Completed exports will appear here.</div>';
    $('schedule-list').innerHTML=state.schedules.length?state.schedules.map(s=>{
      const id=s.scope.split(':')[1], name=s.scope.startsWith('server:')?state.servers.find(x=>x.id===id)?.name:state.channels.find(x=>x.id===id)?.name;
      return `<div class="schedule-item"><div><strong>${s.scope.startsWith('channel:')?'# ':''}${esc(name||id)}</strong><small>${s.mode==='adaptive'?'Adaptive · seven-day sample':duration(s.minutes)}${s.options.inherited?' · server default':''}</small></div><div>${s.enabled?'Enabled':'Disabled'}<small>${s.enabled?'Next: '+esc(new Date(s.next_run*1000).toLocaleString()):'Paused'}</small></div></div>`;
    }).join(''):'<p class="hint">No schedules enabled. Configure one per server or per selected channel.</p>';
    $('publication-list').innerHTML=state.publications.length?state.publications.map(p=>`<div class="publication-item"><div><strong>${esc(state.servers.find(s=>s.id===p.server_id)?.name||p.server_id)}</strong><small>${esc(p.path)}</small><a href="/reader.html?archive=${esc(p.reader_id)}" target="_blank" rel="noopener">Read ZIP ↗</a></div><div>${(p.size/1048576).toFixed(1)} MB<small>${esc(new Date(p.updated*1000).toLocaleString())}</small></div></div>`).join(''):'<p class="hint">No current ZIPs have been published yet.</p>';
    queueSignature=signature;
    [$('tray-jobs'),$('queue-detail')].forEach((e,i)=>e.scrollTop=scrolls[i]);
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
let historySignature='', scheduleManagerSignature='', scheduleDraft=null, scheduleSelection=new Set();
function scheduleName(s) {
  const id=s.scope.split(':')[1], channel=state.channels.find(c=>c.id===id);
  const server=state.servers.find(v=>v.id===(s.scope.startsWith('server:')?id:channel?.server_id));
  return s.scope.startsWith('server:')?(server?.name||id)+ ' · server default':(server?.name?server.name+' · ':'')+'# '+(channel?.name||id);
}
function renderSavedHistory() {
  if(!state)return;
  const signature=JSON.stringify([state.stats.messages,state.channels,state.queue.map(j=>[j.channel_id,j.status])]);
  if(signature===historySignature)return;historySignature=signature;
  const channels=state.channels.filter(c=>c.count>0).sort((a,b)=>b.count-a.count);
  $('history-summary').textContent=`${number(state.stats.messages)} messages saved locally across ${number(channels.length)} conversations. Partial batches are included; ${number(state.queue.length)} tasks remain in the queue.`;
  const box=$('history-saved'),scroll=box.scrollTop;
  const savedHTML=channels.map(c=>{const job=state.queue.find(j=>j.channel_id===c.id),server=state.servers.find(s=>s.id===c.server_id);return `<div class="saved-row"><div><strong>${esc(server?.name||c.server_id)} · # ${esc(c.name)}</strong><small>${number(c.count)} saved messages · ${job?esc(job.status):c.history_done?'History captured':'Saved checkpoint'}</small></div><button data-saved-channel="${esc(c.id)}">Read messages →</button></div>`;}).join('')||'<div class="empty">Saved batches will appear here as messages arrive.</div>';if(typeof StudioRender!=='undefined')StudioRender.markup(box,savedHTML);else box.innerHTML=savedHTML;
  box.scrollTop=scroll;
}
function renderScheduleManager() {
  if(!state)return;
  const q=$('schedule-search').value.trim().toLowerCase(),owner=state.connection.account?.id;
  const entries=state.schedules.filter(s=>(scheduleName(s)+' '+s.scope).toLowerCase().includes(q));
  scheduleSelection=new Set([...scheduleSelection].filter(scope=>state.schedules.some(s=>s.scope===scope&&s.owner_id===owner)));
  const signature=JSON.stringify([q,entries,state.servers,state.channels.map(c=>[c.id,c.name]),owner,[...scheduleSelection],state.schedule_recovery]);
  if(signature===scheduleManagerSignature)return;scheduleManagerSignature=signature;
  $('schedule-count').textContent=`${entries.length} of ${state.schedules.length} schedules · ${scheduleSelection.size} selected`;
  document.querySelectorAll('[data-schedule-bulk]').forEach(b=>b.disabled=!scheduleSelection.size||pending.has('schedule-bulk'));
  $('clear-all-schedules').disabled=!owner||!state.schedules.some(s=>s.owner_id===owner)||pending.has('schedule-bulk');
  $('undo-schedule-removal').hidden=!state.schedule_recovery;
  const box=$('schedule-manager'),scroll=box.scrollTop;
  const savedHTML=entries.map(s=>{const allowed=owner===s.owner_id;return `<div class="saved-row ${s.enabled?'':'schedule-paused'}"><input type="checkbox" data-select-schedule="${esc(s.scope)}" aria-label="Select ${esc(scheduleName(s))}" ${scheduleSelection.has(s.scope)?'checked':''} ${allowed?'':'disabled'}><div><strong>${esc(scheduleName(s))}</strong><small>${s.mode==='adaptive'?'Adaptive · current '+duration(s.minutes):'Every '+duration(s.minutes)}${s.options.inherited?' · inherited':' · independent'}<br>${s.enabled?'Next: '+esc(new Date(s.next_run*1000).toLocaleString()):'Paused'}${allowed?'':' · connect the original account to manage'}</small></div><div class="saved-actions"><button data-edit-schedule="${esc(s.scope)}" ${allowed?'':'disabled'}>Edit</button><button data-toggle-schedule="${esc(s.scope)}" ${allowed?'':'disabled'}>${s.enabled?'Pause':'Enable'}</button></div></div>`;}).join('')||'<div class="empty">'+(q?'No matching schedules.':'No schedules yet. Choose a server or channels in Export, then enable a schedule.')+'</div>';if(typeof StudioRender!=='undefined')StudioRender.markup(box,savedHTML);else box.innerHTML=savedHTML;
  box.scrollTop=scroll;
}
function readSavedChannel(id) {
  const channel=state.channels.find(c=>c.id===id);showPage('library');
  ['library-search','library-person','library-start','library-end'].forEach(key=>$(key).value='');
  $('library-server').value=channel?.server_id||'';updateLibraryChannels();$('library-channel').value=id;offset=0;searchLibrary();
}
function editSchedule(scope) {
  const s=state.schedules.find(v=>v.scope===scope);if(!s)return;
  scheduleDraft=JSON.parse(JSON.stringify(s));
  $('schedule-title').textContent=scheduleName(s);
  $('schedule-context').textContent=scope.startsWith('channel:')?'Saving creates an independent channel override.':'Changes also apply to inherited channel schedules.';
  $('schedule-edit-mode').value=s.mode;$('schedule-edit-minutes').value=s.minutes;$('schedule-edit-enabled').checked=!!s.enabled;
  $('schedule-edit-minutes').disabled=s.mode==='adaptive';if(!$('schedule-dialog').open)$('schedule-dialog').showModal();
}
async function changeSavedSchedule(s,changes) {
  if(state.connection.account?.id!==s.owner_id)throw new Error('Connect the original account before changing this schedule.');
  const opts={...s.options};if(s.scope.startsWith('channel:'))opts.inherited=false;
  await api('schedule',{scope:s.scope,enabled:!!s.enabled,mode:s.mode,minutes:s.minutes,options:opts,...changes});
  applyState(await api('state'));
}
async function manageScheduleBatch(action) {
  if(pending.has('schedule-bulk'))return;
  pending.add('schedule-bulk');scheduleManagerSignature='';renderScheduleManager();
  try{const result=await api('schedules/manage',{action,scopes:[...scheduleSelection]});if(['remove','clear','restore'].includes(action))scheduleSelection.clear();applyState(await api('state'));toast(`${number(result.changed)} schedules ${action==='restore'?'restored':action==='pause'?'paused':action==='enable'?'enabled':'removed'}. Saved messages and queue retained.`);}
  catch(error){toast(error.message,true);}finally{pending.delete('schedule-bulk');scheduleManagerSignature='';renderScheduleManager();}
}
function safeLink(url) { try { const p=new URL(url,location.origin);return ['http:','https:'].includes(p.protocol)?p.href:''; } catch{return '';} }
function contentHTML(text) {
  return StudioEmoji.html(text).replace(/```([^]*?)```/g,'<pre><code>$1</code></pre>').replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>').replace(/~~([^~\n]+)~~/g,'<del>$1</del>');
}
function attachmentHTML(a, local, messageId) {
  const path=local?.[String(a.id)]; const original=safeLink(a.url);const image=path&&((a.content_type||'').startsWith('image/')||/\.(png|jpe?g|gif|webp)$/i.test(a.filename||''));
  const video=(a.content_type||'').startsWith('video/')||/\.(mp4|webm|mov|m4v|avi|mkv|mpeg|mpg|wmv|3gp)$/i.test(a.filename||'');
  const oversized=video&&Number(a.size)>10000000;
  return `<div class="attachment"><label>${!path&&a.id&&original?`<input type="checkbox" data-media-id="${esc(a.id)}" data-media-message="${esc(messageId)}" ${selectedMedia.has(String(a.id))?'checked':''} ${oversized?'disabled':''}> `:''}📎 ${esc(a.filename||a.fileName||'Attachment')} <small class="muted">${a.size?(Number(a.size)/1000000).toFixed(2)+' MB':'size unknown'}</small></label>${path?MediaView.html(a,path):''}${path?` <a href="${esc(path)}" target="_blank" rel="noopener">Open saved file ↗</a>`:` <span class="muted">${esc(oversized?'Skipped: video exceeds 10 MB':a.download_status||'Manual download only')}</span>`}</div>`;
}
function previewMediaHTML(m){
  return (m.attachments||[]).map(a=>`<div class="preview-attachment">📎 ${esc(a.filename||a.fileName||'Attachment')}${a.size?` <span class="muted">${(Number(a.size)/1000000).toFixed(2)} MB</span>`:''}</div>`).join('')+(m.embeds||[]).map(e=>`<div class="preview-attachment">${StudioEmoji.html(String(e.title||e.description||'Embedded content').slice(0,500))}</div>`).join('');
}
function messageHTML(m, local, small=false) {
  messageMap.set(String(m.id),m);
  if(messageMap.size>600&&!metadataPruneQueued){metadataPruneQueued=true;queueMicrotask(()=>{metadataPruneQueued=false;ChatBuffer.trimMetadata(messageMap,new Set([...document.querySelectorAll('[data-message-id]')].map(el=>el.dataset.messageId)));});}
  const author=m.author?.global_name||m.author?.nickname||m.author?.username||m.author?.name||'Unknown';
  const initial=Array.from(author).slice(0,2).join('').toUpperCase();
  const avatar=/^\/avatar\/[a-f0-9]{64}$/.test(m._avatar_url||'')?`<img src="${esc(m._avatar_url)}" alt="${esc(initial)}" loading="lazy" width="40" height="40">`:esc(initial);
  return `<article class="message" data-message-id="${esc(m.id)}"><div class="avatar">${avatar}</div><div class="message-body"><div class="message-header"><span class="message-author">${esc(author)}</span><time class="message-time">${esc(new Date(m.timestamp).toLocaleString())}${m.edited_timestamp?' · edited':''}</time>${m.channel_name?`<span class="message-channel"># ${esc(m.channel_name)}</span>`:''}</div>${m.message_reference?.message_id?`<button class="message-reply subtle" data-reply="${esc(m.message_reference.message_id)}">↩ Reply to message ${esc(m.message_reference.message_id)}</button>`:''}<div class="message-content">${contentHTML(m.content||'')}</div>${(m.attachments||[]).map(a=>attachmentHTML(a,local,m.id)).join('')}${small?'':(m.embeds||[]).map(e=>`<div class="embed"><strong>${StudioEmoji.html(e.title||'')}</strong><div>${StudioEmoji.html(e.description||'')}</div></div>`).join('')}${m.reactions?.length?`<div class="reactions">${m.reactions.map(r=>`<span class="reaction">${StudioEmoji.reaction(r.emoji)} ${number(r.count)}</span>`).join('')}</div>`:''}<div class="message-actions"><button data-copy-message="${esc(m.id)}">Copy text</button><button data-details="${esc(m.id)}">Details · ${esc(m.author?.id)}</button></div></div></article>`;
}
async function searchLibrary() {
  if(!state)return;
  searchAbort?.abort();searchAbort=new AbortController();
  const query=new URLSearchParams({q:$('library-search').value,server:$('library-server').value,channel:$('library-channel').value,person:$('library-person').value,attachment:$('library-attachment').value,type:$('library-type').value,phrase:$('library-phrase').checked?'1':'',start:$('library-start').value,end:$('library-end').value,offset,limit:80});
  try {results=await api('search?'+query.toString(),undefined,searchAbort.signal);renderResults();$('library-updates').hidden=true;}
  catch(error){if(error.name!=='AbortError')toast(error.message,true);}
}
function renderResults() {
  $('library-results').classList.toggle('transcript',libraryTab==='messages');
  $('result-count').textContent=`${number(results.total)} matching messages`;
  $('page-label').textContent=results.total?`Page ${Math.floor(offset/80)+1} · ${number(offset+1)}–${number(Math.min(offset+80,results.total))}`:'No results';
  $('previous-page').disabled=offset===0;$('next-page').disabled=offset+80>=results.total;
  if(libraryTab==='messages') $('library-results').innerHTML=results.messages.map(m=>messageHTML(m,results.media)).join('')||'<div class="empty panel">No matching messages.<br>Try a different search, or import an existing export.</div>';
  if(libraryTab==='attachments') $('library-results').innerHTML=results.messages.flatMap(m=>(m.attachments||[]).map(a=>`<div class="panel"><div class="panel-title">${esc(m.channel_name)} · ${esc(m.author?.username||m.author?.name||'Unknown')}</div>${attachmentHTML(a,results.media,m.id)}</div>`)).join('')||'<div class="empty panel">No attachments on this result page.</div>';
  if(libraryTab==='statistics') $('library-results').innerHTML=`<div class="stats-grid">${[['Matching messages',results.total],['All saved messages',state.stats.messages],['People in library',state.stats.people],['Archived channels',state.stats.channels],['Downloaded attachments',state.stats.attachments],['Captured prior versions',state.stats.revisions]].map(([k,v])=>`<div class="stat-card"><span>${k}</span><strong>${number(v)}</strong></div>`).join('')}</div><p class="hint">Library totals cover all saved data. The matching-message count follows your search and filters.</p>`;
}
let previewChannel='',previewMessages=new Map(),previewCursor=null,previewMore=false,previewVersion=0;
async function preview(older=false) {
  const channel=Array.from(selected)[0];
  if(!channel){previewVersion++;previewChannel='';previewMessages.clear();previewCursor=null;$('mini-preview').innerHTML='<div class="empty small">Select a channel to preview saved messages.</div>';return;}
  const container=$('mini-preview'),changed=channel!==previewChannel,version=++previewVersion;
  if(changed){previewChannel=channel;previewMessages.clear();previewCursor=null;older=false;}
  const oldHeight=container.scrollHeight,oldTop=container.scrollTop,atEnd=oldHeight-oldTop-container.clientHeight<35;
  try{
    const value=await api('preview?'+new URLSearchParams({channel,limit:50,...(older&&previewCursor?{before:previewCursor}:{})}));if(version!==previewVersion)return;
    for(const m of value.messages)previewMessages.set(m.id,m);
    if(older||changed||!previewCursor){previewCursor=value.next_cursor;previewMore=value.has_more;}
    const messages=[...previewMessages.values()].sort((a,b)=>Date.parse(a.timestamp)-Date.parse(b.timestamp)||a.id.length-b.id.length||a.id.localeCompare(b.id));
    container.innerHTML=(previewMore?'<button id="preview-older" class="subtle">↑ Load older saved messages</button>':'')+messages.map(m=>messageHTML(m,{},true)).join('')||'<div class="empty small">Preview appears after the first saved batch.</div>';
    if($('preview-older'))$('preview-older').onclick=()=>busy($('preview-older'),()=>preview(true));
    container.scrollTop=older?oldTop+container.scrollHeight-oldHeight:(changed||atEnd?container.scrollHeight:oldTop);
  }catch(error){if(version===previewVersion)toast('Saved preview: '+error.message,true);}
}
async function loadUsers() {
  try {const users=await api('users');replaceSelect($('alias-user'),users.map(u=>({id:u.id,name:`${u.name} · ${u.id}`})),$('alias-user').value,'Choose an archived person…');replaceSelect($('alias-target'),users.map(u=>({id:u.id,name:`${u.name} · ${u.id}`})),$('alias-target').value,'Choose an archived person…');$('alias-list').textContent=users.filter(u=>u.person_id).map(u=>`${u.name} (${u.id}) → ${u.person_id}`).join('\n')||'No cross-account links.';}catch(e){toast(e.message,true);}
}
function applyState(value) {
  const was=state;state=value;StudioSounds.update(value,was);
  if(was&&currentPage==='library'&&JSON.stringify(was.channels.map(c=>[c.id,c.generation]))!==JSON.stringify(value.channels.map(c=>[c.id,c.generation])))$('library-updates').hidden=false;
  if(!was){$('destination').value=value.destination;setIntervalMinutes(1440);}
  renderConnection();renderCatalog();renderQueue();renderSavedHistory();renderScheduleManager();
  if(!was&&currentPage==='library')searchLibrary();
  $('auto-connect').checked=state.auto_connect;
  $('app-address').textContent=location.origin;$('app-address').href=location.origin+'/';
  const mediaHTML=(state.media_tasks||[]).map(t=>`<div class="schedule-item" data-media-task="${esc(t.attachment_id)}"><div><strong># ${esc(t.channel_name)} · ${esc(t.attachment_id)}</strong><small>${esc(t.status)} · ${(t.received/1000000).toFixed(2)} MB · ${esc(t.detail)}</small></div>${['queued','running','paused'].includes(t.status)?`<button data-cancel-media="${esc(t.attachment_id)}">Cancel</button>`:''}</div>`).join('')||'<p class="hint">No attachments selected. Text exports never start media downloads.</p>';if(typeof StudioRender!=='undefined')StudioRender.markup($('media-task-list'),mediaHTML);else $('media-task-list').innerHTML=mediaHTML;
  replaceSelect($('preset-select'),state.presets.map(p=>({id:p.name,name:p.name})),$('preset-select').value,'Load a preset…');
  if(value.stats.messages!==knownMessageCount){if(currentPage==='library'&&was)$('library-updates').hidden=false;knownMessageCount=value.stats.messages;if(currentPage==='export'&&mode!=='dock')preview();}
  if(value.worker_error&&value.worker_error!==was?.worker_error)toast(value.worker_error,true);
  if(typeof updatePeopleAccount==='function')updatePeopleAccount();
  if(typeof updateQueueSettingsState==='function')updateQueueSettingsState();
}
function connectEvents() {
  stream?.close();stream=new EventSource('/api/events');
  stream.onmessage=event=>{try{const value=JSON.parse(event.data);if(typeof scheduleState==='function')scheduleState(value);else applyState(value);$('offline-banner').hidden=true;}catch(e){console.error('Unable to render archive update',e);}};
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
  if(button.dataset.savedChannel)readSavedChannel(button.dataset.savedChannel);
  if(button.dataset.editSchedule)editSchedule(button.dataset.editSchedule);
  if(button.dataset.toggleSchedule)busy(button,async()=>{const s=state.schedules.find(v=>v.scope===button.dataset.toggleSchedule);if(s){await changeSavedSchedule(s,{enabled:!s.enabled});toast(s.enabled?'Schedule paused.':'Schedule enabled.');}});
  if(button.dataset.removeChannel){selected.delete(button.dataset.removeChannel);renderCatalog();preview();}
  if(button.dataset.job)busy(button,()=>api('control',{id:button.dataset.job,action:button.dataset.action,...(button.dataset.action==='apply'?{options:readOptions()}:{})}));
  if(button.dataset.cancelMedia)busy(button,()=>api('media/cancel',{id:button.dataset.cancelMedia}));
  if(button.dataset.libraryTab){libraryTab=button.dataset.libraryTab;document.querySelectorAll('[data-library-tab]').forEach(x=>x.classList.toggle('active',x===button));renderResults();}
  if(button.dataset.copyMessage)busy(button,async()=>{await navigator.clipboard.writeText(messageMap.get(button.dataset.copyMessage)?.content||'');toast('Message text copied.');});
  if(button.dataset.details||button.dataset.reply)busy(button,async()=>{const value=await api('message?'+new URLSearchParams({id:button.dataset.details||button.dataset.reply}));$('message-details').innerHTML=messageHTML(value.message,value.media)+`<pre>${esc(JSON.stringify(value.message,null,2))}</pre>`+(value.revisions.length?`<details><summary>${value.revisions.length} captured prior versions</summary>${value.revisions.map(m=>`<pre>${esc(JSON.stringify(m,null,2))}</pre>`).join('')}</details>`:'');if(!$('message-dialog').open)$('message-dialog').showModal();});
});
document.addEventListener('change',event=>{
  const input=event.target;
  if(input.dataset.selectSchedule){input.checked?scheduleSelection.add(input.dataset.selectSchedule):scheduleSelection.delete(input.dataset.selectSchedule);renderScheduleManager();}
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
['library-search','library-person','library-attachment','library-type','library-phrase','library-start','library-end'].forEach(id=>$(id).addEventListener('input',()=>{offset=0;clearTimeout(searchTimer);searchTimer=setTimeout(searchLibrary,180);}));
$('library-server').onchange=()=>{updateLibraryChannels();offset=0;searchLibrary();};$('library-channel').onchange=()=>{offset=0;searchLibrary();};
$('clear-library').onclick=()=>{['library-search','library-person','library-attachment','library-type','library-start','library-end','library-server','library-channel'].forEach(id=>$(id).value='');$('library-phrase').checked=false;updateLibraryChannels();offset=0;searchLibrary();};
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
$('schedule-search').oninput=renderScheduleManager;
$('select-filtered-schedules').onclick=()=>{const q=$('schedule-search').value.trim().toLowerCase();state.schedules.filter(s=>s.owner_id===state.connection.account?.id&&(scheduleName(s)+' '+s.scope).toLowerCase().includes(q)).forEach(s=>scheduleSelection.add(s.scope));renderScheduleManager();};
$('clear-schedule-selection').onclick=()=>{scheduleSelection.clear();renderScheduleManager();};
document.querySelectorAll('[data-schedule-bulk]').forEach(b=>b.onclick=()=>manageScheduleBatch(b.dataset.scheduleBulk));
$('clear-all-schedules').onclick=()=>{if(!$('clear-schedules-dialog').open)$('clear-schedules-dialog').showModal();};
$('cancel-clear-schedules').onclick=()=>$('clear-schedules-dialog').close();
$('confirm-clear-schedules').onclick=()=>{$('clear-schedules-dialog').close();manageScheduleBatch('clear');};
$('undo-schedule-removal').onclick=()=>manageScheduleBatch('restore');
$('close-schedule').onclick=()=>$('schedule-dialog').close();
$('schedule-edit-mode').onchange=()=>$('schedule-edit-minutes').disabled=$('schedule-edit-mode').value==='adaptive';
$('schedule-form').onsubmit=event=>{event.preventDefault();busy($('save-schedule-edit'),async()=>{if(!scheduleDraft)return;const minutes=Number($('schedule-edit-minutes').value);if(!Number.isFinite(minutes)||minutes<10||minutes>10080)throw new Error('Choose an interval from 10 to 10,080 minutes.');await changeSavedSchedule(scheduleDraft,{enabled:$('schedule-edit-enabled').checked,mode:$('schedule-edit-mode').value,minutes});$('schedule-dialog').close();toast('Schedule saved; export settings and checkpoints preserved.');});};
viewMode(mode);showPage(currentPage);intervalLabel();api('state').then(applyState).then(connectEvents).catch(e=>{toast(e.message,true);$('offline-banner').hidden=false;});
