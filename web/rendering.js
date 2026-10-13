'use strict';
// Retain row identity, focus and scroll during progress updates. No network work here.
const StudioRender=(()=>{
  const signatures=new WeakMap();
  function morph(old,fresh){
    if(old.nodeType!==fresh.nodeType||old.nodeName!==fresh.nodeName){old.replaceWith(fresh);return;}
    if(old.nodeType===3){if(old.data!==fresh.data)old.data=fresh.data;return;}
    for(const attr of [...old.attributes])if(!fresh.hasAttribute(attr.name))old.removeAttribute(attr.name);
    for(const attr of [...fresh.attributes])if(old.getAttribute(attr.name)!==attr.value)old.setAttribute(attr.name,attr.value);
    if(old instanceof HTMLInputElement){old.disabled=fresh.disabled;if(old.type==='checkbox')old.checked=fresh.checked;}
    const children=[...fresh.childNodes];for(let i=0;i<children.length;i++){if(old.childNodes[i])morph(old.childNodes[i],children[i]);else old.append(children[i]);}
    while(old.childNodes.length>children.length)old.lastChild.remove();
  }
  function list(box,items,key,html,signature,empty=''){
    const nodes=new Map([...box.children].filter(n=>n.dataset.renderKey).map(n=>[n.dataset.renderKey,n]));let next=box.firstElementChild;
    for(const item of items){const id=String(key(item)),stamp=signature(item);let row=nodes.get(id);nodes.delete(id);
      if(!row||signatures.get(row)!==stamp){const template=document.createElement('template');template.innerHTML=html(item);const fresh=template.content.firstElementChild;
        if(row)morph(row,fresh);else row=fresh;row.dataset.renderKey=id;signatures.set(row,stamp);}
      const entering=!row.isConnected;if(row!==next)box.insertBefore(row,next);next=row.nextElementSibling;
      if(entering&&row.classList.contains('job-row')&&document.documentElement.dataset.motion==='full'&&!document.hidden)row.animate([{opacity:0},{opacity:1}],{duration:140});
    }
    for(const row of nodes.values()){
      if(row.classList.contains('job-row')&&document.documentElement.dataset.motion==='full'&&!document.hidden){row.removeAttribute('data-render-key');row.removeAttribute('data-queue-job');row.inert=true;row.classList.add('render-leaving');row.animate([{opacity:1},{opacity:0}],{duration:120}).finished.catch(()=>{}).finally(()=>row.remove());}
      else row.remove();
    }
    for(const row of [...box.children])if(!row.dataset.renderKey&&!row.classList.contains('render-leaving'))row.remove();
    if(!items.length&&empty){const template=document.createElement('template');template.innerHTML=empty;box.append(template.content);}
  }
  function markup(box,html){const template=document.createElement('template');template.innerHTML=html;list(box,[...template.content.children],n=>{const control=n.querySelector('[data-channel],[data-saved-channel],[data-select-schedule],a[href]');return n.dataset.mediaTask||control?.dataset.channel||control?.dataset.savedChannel||control?.dataset.selectSchedule||control?.getAttribute('href')||n.textContent;},n=>n.outerHTML,n=>n.outerHTML);}
  return {list,morph,markup};
})();
const oldRenderQueue=renderQueue;
let auxiliarySignature='';
renderQueue=function(){
  if(!state)return;
  let dragging=typeof draggedJob!=='undefined'&&draggedJob;
  if(dragging&&typeof movable==='function'&&!movable(draggedJob)){queueAnnouncement.textContent='Task started exporting. Reorder cancelled.';clearQueueGesture(false);dragging=false;}
  const signature=job=>JSON.stringify([job,state.processing_job,state.settings_owner,typeof queueSelection!=='undefined'&&queueSelection.has(job.id)]);
  if(!dragging){
    if(!$('queue-tray').classList.contains('collapsed'))StudioRender.list($('tray-jobs'),state.queue,j=>j.id,j=>jobHTML(j),signature);
    if(currentPage==='queue')StudioRender.list($('queue-detail'),state.queue,j=>j.id,j=>jobHTML(j),signature,'<div class="empty panel">Nothing waiting. Select channels and add an export.</div>');
    if(currentPage==='history')StudioRender.list($('history-list'),state.history,j=>j.id,j=>jobHTML(j,true),j=>JSON.stringify(j),'<div class="empty panel">Completed exports will appear here.</div>');
  }
  // Legacy auxiliary markup remains scoped to its visible page and own data changes.
  const auxiliary=JSON.stringify([currentPage,state.history,state.schedules,state.publications,state.servers.map(s=>[s.id,s.name]),state.channels.map(c=>[c.id,c.name])]);
  if(auxiliary!==auxiliarySignature){
    auxiliarySignature=auxiliary;
    if(currentPage==='queue')$('schedule-list').innerHTML=state.schedules.map(s=>`<div class="schedule-item"><div><strong>${esc(scheduleName(s))}</strong><small>${s.mode==='adaptive'?'Adaptive · seven-day sample':duration(s.minutes)}</small></div><div>${s.enabled?'Enabled':'Paused'}<small>${s.enabled?'Next: '+esc(new Date(s.next_run*1000).toLocaleString()):''}</small></div></div>`).join('')||'<p class="hint">No schedules enabled.</p>';
    if(currentPage==='history')$('publication-list').innerHTML=state.publications.map(p=>`<div class="publication-item"><div><strong>${esc(state.servers.find(s=>s.id===p.server_id)?.name||p.server_id)}</strong><small>${esc(p.path)}</small><a href="/reader.html?archive=${esc(p.reader_id)}" target="_blank" rel="noopener">Read ZIP ↗</a></div><div>${(p.size/1048576).toFixed(1)} MB<small>${esc(new Date(p.updated*1000).toLocaleString())}</small></div></div>`).join('')||'<p class="hint">No ZIPs published yet.</p>';
  }
  const active=state.queue.find(j=>['running','waiting'].includes(j.status));
  for(const id of ['queue-badge','tray-count'])if($(id).textContent!==String(state.queue.length))$(id).textContent=state.queue.length;
  $('tray-status').textContent=active?`${active.status==='waiting'?'Cooling down':'Exporting'} · #${active.channel_name}`:state.queue.length?`${state.queue.length} tasks waiting`:'Ready when you are';
  $('dock-status').textContent=active?`#${active.channel_name} · ${number(active.progress)} scanned · ${active.status}`:`${number(state.stats.messages)} messages saved`;
  $('dock').classList.toggle('running',active?.status==='running');$('dock-pause').disabled=!active;renderCooldown();
};
const oldRenderCatalog=renderCatalog,oldRenderConnection=renderConnection,oldRenderSavedHistory=renderSavedHistory,oldRenderScheduleManager=renderScheduleManager;
let catalogStamp='',connectionStamp='';
renderCatalog=function(){const stamp=JSON.stringify([state.servers,state.channels,selectedServer,[...selected],$('channel-search').value,state.connection.connected]);if(stamp!==catalogStamp){catalogStamp=stamp;oldRenderCatalog();}};
renderConnection=function(){const stamp=JSON.stringify([state.connection,state.demo]);if(stamp!==connectionStamp){connectionStamp=stamp;oldRenderConnection();}};
renderSavedHistory=function(){if(currentPage==='history')oldRenderSavedHistory();};
renderScheduleManager=function(){if(currentPage==='schedules')oldRenderScheduleManager();};
const oldShowPage=showPage;
showPage=function(page){oldShowPage(page);if(state){renderQueue();renderSavedHistory();renderScheduleManager();if(page==='export')preview();}document.dispatchEvent(new CustomEvent('studio-page',{detail:page}));};
let scheduledState=null,stateFrame=0;
function scheduleState(value){scheduledState=value;if(document.hidden||stateFrame)return;stateFrame=requestAnimationFrame(()=>{stateFrame=0;const next=scheduledState;scheduledState=null;if(next)applyState(next);});}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&scheduledState)scheduleState(scheduledState);});
