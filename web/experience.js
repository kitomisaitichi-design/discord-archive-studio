'use strict';
// Shared reading controls. All preferences, bookmarks and searches stay on this device.
const StudioExperience=(()=>{
  const reader=document.body.classList.contains('reader-body'),byId=id=>document.getElementById(id);
  const html=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const read=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}};
  const put=(key,value)=>localStorage.setItem(key,JSON.stringify(value));
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let preferences=read('studio.reading',{motion:'subtle',density:'comfortable',scale:100,sidebar:260,calendar:300});
  function apply(){
    const root=document.documentElement;root.dataset.motion=reduced.matches?'off':(['off','subtle','full'].includes(preferences.motion)?preferences.motion:'subtle');
    root.dataset.density=preferences.density==='dense'?'dense':'comfortable';root.style.setProperty('--reading-scale',Math.min(140,Math.max(90,Number(preferences.scale)||100))/100);
    root.style.setProperty('--sidebar-width',Math.min(400,Math.max(190,Number(preferences.sidebar)||260))+'px');root.style.setProperty('--calendar-width',Math.min(440,Math.max(220,Number(preferences.calendar)||300))+'px');
    document.body.classList.toggle('pane-collapsed',!!preferences[reader?'calendarCollapsed':'sidebarCollapsed']);
  }
  function savePreferences(){put('studio.reading',preferences);apply();fitReadingPane();}
  apply();reduced.addEventListener('change',apply);
  window.addEventListener('storage',e=>{if(e.key==='studio.reading'){preferences=read(e.key,preferences);apply();}});
  function dialog(id,title,body){const el=document.createElement('dialog');el.id=id;el.className='experience-dialog';el.innerHTML=`<div class="dialog-heading"><strong>${title}</strong><button class="icon" data-close-experience aria-label="Close ${title}">✕</button></div>${body}`;document.body.append(el);el.addEventListener('click',e=>{if(e.target.closest('[data-close-experience]'))el.close();});return el;}
  const appearance=dialog('reading-settings','Reading & appearance',`<div class="field"><label for="motion-setting">Motion</label><select id="motion-setting"><option value="off">Off</option><option value="subtle">Subtle</option><option value="full">Full</option></select><p class="hint">System reduced motion always takes priority.</p></div><div class="field"><label for="density-setting">Spacing</label><select id="density-setting"><option value="comfortable">Comfortable</option><option value="dense">Dense</option></select></div><div class="field"><label for="text-scale">Message text size</label><select id="text-scale"><option value="90">90%</option><option value="100">100%</option><option value="110">110%</option><option value="120">120%</option><option value="140">140%</option></select></div><p class="hint">Saved across the Library and ZIP reader. Drag a pane edge, or focus it and use arrow keys, to resize.</p>`);
  const header=document.querySelector(reader?'.reader-header':'.app-header');
  const appearanceButton=document.createElement('button');appearanceButton.className='icon';appearanceButton.textContent='Aa';appearanceButton.setAttribute('aria-label','Reading and appearance');header.append(appearanceButton);
  appearanceButton.onclick=()=>{byId('motion-setting').value=preferences.motion||'subtle';byId('density-setting').value=preferences.density||'comfortable';byId('text-scale').value=String(preferences.scale||100);appearance.showModal();};
  for(const [id,key] of [['motion-setting','motion'],['density-setting','density'],['text-scale','scale']])byId(id).onchange=()=>{preferences[key]=key==='scale'?Number(byId(id).value):byId(id).value;savePreferences();};
  const pane=document.querySelector(reader?'.calendar-pane':'.channel-pane');
  if(pane){
    const collapse=document.createElement('button');collapse.className='subtle pane-toggle';collapse.textContent=reader?'Calendar':'Channels';collapse.setAttribute('aria-label',reader?'Show or hide calendar':'Show or hide channel pane');header.append(collapse);
    const collapsedKey=reader?'calendarCollapsed':'sidebarCollapsed';collapse.setAttribute('aria-expanded',String(!preferences[collapsedKey]));
    collapse.onclick=()=>{preferences[collapsedKey]=!preferences[collapsedKey];savePreferences();collapse.setAttribute('aria-expanded',String(!preferences[collapsedKey]));};
    const resize=document.createElement('div');resize.className='pane-resizer';resize.tabIndex=0;resize.setAttribute('role','separator');resize.setAttribute('aria-orientation','vertical');resize.setAttribute('aria-label',reader?'Resize calendar':'Resize channel pane');resize.setAttribute('aria-valuemin',reader?'220':'190');resize.setAttribute('aria-valuemax',reader?'440':'400');pane.append(resize);
    const keyName=reader?'calendar':'sidebar',min=reader?220:190,max=reader?440:400;let start=null;
    const set=value=>{preferences[keyName]=Math.min(max,Math.max(min,value));resize.setAttribute('aria-valuenow',String(Math.round(preferences[keyName])));apply();};
    resize.addEventListener('pointerdown',e=>{if(e.button!==0)return;start={x:e.clientX,width:pane.getBoundingClientRect().width};resize.setPointerCapture(e.pointerId);e.preventDefault();});
    resize.addEventListener('pointermove',e=>{if(start)set(start.width+e.clientX-start.x);});
    resize.addEventListener('pointerup',()=>{if(start){start=null;savePreferences();}});resize.addEventListener('pointercancel',()=>{start=null;});
    resize.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();set((Number(preferences[keyName])||300)+(e.key==='ArrowRight'?10:-10));savePreferences();}});
  }
  const searchInput=byId(reader?'reader-search':'library-search');
  const names=reader?['search','author','attachment','type','start','end','phrase']:['search','server','channel','person','attachment','type','start','end','phrase'];
  const prefix=reader?'reader-':'library-';
  if(!reader){const filters=byId('page-library').querySelector('.library-filters'),drawer=document.createElement('details');drawer.className='library-filter-drawer';drawer.innerHTML='<summary>Filters · server, channel, person, files & dates</summary>';filters.before(drawer);drawer.append(filters);
    const advanced=byId('advanced'),body=advanced.querySelector('.advanced-body'),advancedDialog=dialog('advanced-export-dialog','Export details','');
    advancedDialog.setAttribute('aria-label','Export details');
    const tabs=document.createElement('div');tabs.className='export-settings-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Export settings sections');
    const groups=[['capture','Capture','Choose what appears in your exported files.'],['files','Files','Package your saved conversations and locally cached assets.'],['pacing','Pacing','Control the spacing between message requests.']];
    const panels=groups.map(([key,title,description])=>{const panel=document.createElement('section');panel.id='export-section-'+key;panel.className='export-settings-section';panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','export-tab-'+key);panel.innerHTML=`<h2>${title}</h2><p class="hint">${description}</p>`;const button=document.createElement('button');button.id='export-tab-'+key;button.type='button';button.textContent=title;button.setAttribute('role','tab');button.setAttribute('aria-controls',panel.id);tabs.append(button);return panel;});
    const setTab=index=>{panels.forEach((panel,i)=>{panel.hidden=i!==index;const button=tabs.children[i];button.setAttribute('aria-selected',String(i===index));button.tabIndex=i===index?0:-1;});body.scrollTop=0;};
    [...tabs.children].forEach((button,index)=>{button.onclick=()=>setTab(index);button.onkeydown=e=>{let next;if(e.key==='ArrowRight')next=(index+1)%groups.length;else if(e.key==='ArrowLeft')next=(index+groups.length-1)%groups.length;else if(e.key==='Home')next=0;else if(e.key==='End')next=groups.length-1;if(next!==undefined){e.preventDefault();setTab(next);tabs.children[next].focus();}};});
    const move=(id,panel)=>{const input=byId(id),node=input.closest('.field')||input.closest('label');if(input.type==='checkbox'){const copy=document.createElement('span');copy.className='setting-copy';for(const child of [...node.childNodes])if(child!==input)copy.append(child);node.classList.add('export-option');node.replaceChildren(copy,input);}panel.append(node);};
    for(const id of ['include-reactions','include-edits','role-colors','exclude-bots'])move(id,panels[0]);
    const dates=document.createElement('div');dates.className='export-fields';panels[0].append(dates);for(const id of ['date-start','date-end'])move(id,dates);move('people-filter',panels[0]);
    for(const id of ['recheck-edits','full-rescan'])move(id,panels[0]);
    panels[0].insertAdjacentHTML('beforeend','<p class="export-settings-note">Filters apply to exported files. Your saved library keeps captured messages. Regular scans continue after the latest saved message; full-history rescans require an explicit export.</p>');
    for(const id of ['include-attachments','download-media','include-avatars'])move(id,panels[1]);
    const splitting=document.createElement('div');splitting.className='export-fields';panels[1].append(splitting);for(const id of ['split-count','split-mb'])move(id,splitting);move('max-media',panels[1]);
    panels[1].insertAdjacentHTML('beforeend','<p class="export-settings-note">Attachments are downloaded only when you select them in Library. Text comes first; videos over 10 MB are skipped.</p>');
    for(const id of ['page-delay','timing-variation'])move(id,panels[2]);
    panels[2].insertAdjacentHTML('beforeend','<p class="export-settings-note">Choose batch size and batch rest in the export workspace. These options apply to new tasks; edit waiting tasks from Queue.</p>');
    body.replaceChildren(...panels);advancedDialog.append(tabs,body);advancedDialog.insertAdjacentHTML('beforeend','<div class="export-settings-footer"><span>Changes are saved automatically</span><button data-close-experience class="primary">Done</button></div>');setTab(0);
    advanced.open=false;advanced.querySelector('summary span').textContent='Open settings';advanced.querySelector('summary').addEventListener('click',e=>{e.preventDefault();advancedDialog.showModal();});
    const historyTools=document.createElement('div');historyTools.className='history-tools';historyTools.innerHTML='<input id="history-search" type="search" aria-label="Search saved conversations" placeholder="Search a conversation or server…"><select id="history-server" aria-label="Conversation group"><option value="">All conversations</option></select><span id="history-filter-count" class="muted" role="status"></span>';byId('history-saved').before(historyTools);
    for(const id of ['history-search','history-server'])byId(id).addEventListener('input',()=>{historySignature='';renderSavedHistory();});
    byId('history-list').previousElementSibling.textContent='Export activity';
  }
  function query(){return Object.fromEntries(names.map(name=>[name,name==='phrase'?byId(prefix+name).checked:byId(prefix+name).value]));}
  function scope(){return reader?'reader:'+key:'library';}
  function searches(){return read('studio.saved-searches',[]);}
  function bookmarks(){return read('studio.bookmarks',[]);}
  function runQuery(value){
    if(!reader)showPage('library');
    for(const name of names){const el=byId(prefix+name);if(name==='phrase')el.checked=!!value[name];else el.value=value[name]||'';if(name==='server'&&!reader)updateLibraryChannels();}
    if(reader){loading=false;loadMessages('replace');}else{offset=0;searchLibrary();}
    refreshTools();
  }
  const toolRow=document.createElement('div');toolRow.className='reading-tools';toolRow.innerHTML='<button id="command-open" class="subtle">⌕ Quick search <kbd>Ctrl K</kbd></button><select id="saved-search-select" aria-label="Saved searches"><option value="">Saved searches…</option></select><button id="save-reading-search" class="subtle">Save search</button><button id="remove-reading-search" class="subtle" disabled>Remove</button><button id="open-bookmarks" class="subtle">★ Bookmarks</button>';
  document.querySelector(reader?'.reader-tools':'.library-tools').after(toolRow);
  if(!reader){const utilities=dialog('library-utilities','Downloads & saved assets',''),panels=[...byId('page-library').querySelectorAll(':scope > details.panel')];for(const panel of panels)utilities.append(panel);const button=document.createElement('button');button.className='subtle';button.textContent='Downloads & assets';button.onclick=()=>utilities.showModal();toolRow.append(button);}
  const chips=document.createElement('div');chips.className='filter-chips';toolRow.after(chips);
  if(!reader){const libraryTools=byId('page-library').querySelector('.library-tools');libraryTools.append(toolRow,chips);}
  const saveSearch=dialog('save-search-dialog','Save search','<form id="save-search-form"><div class="field"><label for="saved-search-name">Search name</label><input id="saved-search-name" maxlength="80" required placeholder="Give this search a name"></div><button class="primary" type="submit">Save locally</button></form>');
  byId('save-reading-search').onclick=()=>{byId('saved-search-name').value='';saveSearch.showModal();};
  byId('save-search-form').onsubmit=e=>{e.preventDefault();const name=byId('saved-search-name').value.trim();if(!name){byId('saved-search-name').setCustomValidity('Enter a search name.');byId('saved-search-name').reportValidity();return;}const rows=searches().filter(s=>!(s.scope===scope()&&s.name===name));rows.unshift({id:crypto.randomUUID(),scope:scope(),name,query:query()});put('studio.saved-searches',rows.slice(0,50));saveSearch.close();refreshTools();};
  byId('saved-search-name').oninput=()=>byId('saved-search-name').setCustomValidity('');
  byId('saved-search-select').onchange=()=>{const saved=searches().find(s=>s.id===byId('saved-search-select').value);if(saved)runQuery(saved.query);byId('remove-reading-search').disabled=!saved;};
  byId('remove-reading-search').onclick=()=>{put('studio.saved-searches',searches().filter(s=>s.id!==byId('saved-search-select').value));refreshTools();};
  function refreshTools(){
    const select=byId('saved-search-select'),chosen=select.value;
    select.innerHTML='<option value="">Saved searches…</option>'+searches().filter(s=>s.scope===scope()).map(s=>`<option value="${html(s.id)}">${html(s.name)}</option>`).join('');select.value=chosen;byId('remove-reading-search').disabled=!select.value;
    const values=query(),filterLabel=n=>n==='phrase'?'Exact phrase':n==='server'&&!reader?(state?.servers.find(s=>s.id===values[n])?.name||values[n]):n==='channel'&&!reader?(state?.channels.find(c=>c.id===values[n])?.name||values[n]):values[n];
    chips.innerHTML=names.filter(n=>values[n]).map(n=>`<button data-clear-filter="${n}" class="filter-chip" aria-label="Remove ${html(n)} filter: ${html(filterLabel(n))}">${n==='channel'?'# ':['server','phrase'].includes(n)?'':html(n)+': '}${html(filterLabel(n))} <span aria-hidden="true">×</span></button>`).join('');
    decorate();fitReadingPane();
  }
  function fitReadingPane(){if(reader){requestAnimationFrame(()=>document.documentElement.style.setProperty('--reader-height',Math.max(220,innerHeight-byId('reader-timeline').getBoundingClientRect().top-60)+'px'));return;}if(currentPage!=='library')return;requestAnimationFrame(()=>{const box=byId('library-results'),tray=byId('queue-tray').getBoundingClientRect(),bottom=Math.min(innerHeight,tray.top>0?tray.top:innerHeight);document.documentElement.style.setProperty('--library-height',Math.max(180,bottom-box.getBoundingClientRect().top-64)+'px');});}
  window.addEventListener('resize',fitReadingPane);document.querySelector(reader?'.reader-filters':'.library-filter-drawer').addEventListener('toggle',fitReadingPane);
  chips.onclick=e=>{const b=e.target.closest('[data-clear-filter]');if(!b)return;const q=query();q[b.dataset.clearFilter]=b.dataset.clearFilter==='phrase'?false:'';runQuery(q);};
  for(const name of names)byId(prefix+name).addEventListener('input',refreshTools);
  byId(reader?'reader-clear-filters':'clear-library').addEventListener('click',()=>queueMicrotask(refreshTools));
  const bookmarkDialog=dialog('bookmarks-dialog','Bookmarks','<div id="bookmark-list" class="drawer-list"></div>');
  function showBookmarks(){byId('bookmark-list').innerHTML=bookmarks().map(b=>`<div class="bookmark-row"><a href="${html(b.url)}" ${reader?'':'target="_blank" rel="noopener"'}><strong>${html(b.author)}</strong><small>${html(b.content)} · ${html(b.timestamp)}</small></a><button data-remove-bookmark="${html(b.key)}" aria-label="Remove bookmark">×</button></div>`).join('')||'<p class="hint">Bookmark a message to return to its saved conversation.</p>';bookmarkDialog.showModal();}
  byId('open-bookmarks').onclick=showBookmarks;
  byId('bookmark-list').onclick=e=>{const b=e.target.closest('[data-remove-bookmark]');if(b){put('studio.bookmarks',bookmarks().filter(x=>x.key!==b.dataset.removeBookmark));bookmarkDialog.close();showBookmarks();decorate();}};
  const authorDialog=dialog('author-dialog','Captured person','<div id="author-details" class="drawer-list"></div>');let authorRequest=0;
  async function showAuthor(uid){
    const token=++authorRequest;byId('author-details').textContent='Reading captured identity…';authorDialog.showModal();
    try{const response=await fetch('/api/author?'+new URLSearchParams({id:uid,...(reader?{archive:key}:{})})),value=await response.json();if(!response.ok)throw Error(value.error);if(token!==authorRequest)return;
      byId('author-details').innerHTML=`<h2>${html(value.name)}</h2><p><code>${html(value.id)}</code> · ${Number(value.messages).toLocaleString()} saved messages</p><p class="hint">${html(value.source)}. Names below were captured from saved messages; different IDs are linked only explicitly.</p><h3>Captured names</h3><ul>${value.names.map(n=>`<li>${html(n)}</li>`).join('')}</ul>${value.linked_ids.length?`<p>Explicit links: ${value.linked_ids.map(html).join(', ')}</p>`:''}<button id="search-captured-person">Search saved messages by this ID</button>`;
      byId('search-captured-person').onclick=()=>{authorDialog.close();const value=query();value[reader?'author':'person']=uid;runQuery(value);};
    }catch(e){if(token===authorRequest)byId('author-details').textContent=e.message;}
  }
  function rowMessage(row){return reader?messages.find(m=>String(m.id)===row.dataset.id):messageMap.get(row.dataset.messageId);}
  function bookmarkKey(m){return (reader?(overview?.archive.source==='library'?channel:key):m.channel_id)+':'+m.id;}
  async function messageURL(m){
    let archive=reader?key:'';if(!reader){const server=state.channels.find(c=>c.id===m.channel_id)?.server_id||m.server_id;if(!server)throw Error('This message is missing its saved server mapping.');archive=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode('library:'+server)))].map(x=>x.toString(16).padStart(2,'0')).join('');}
    return '/reader.html?'+new URLSearchParams({archive,channel:m.channel_id||channel,message:m.id,surrounding:'1'});
  }
  function highlight(container,terms){
    container.querySelectorAll('mark.search-match').forEach(mark=>mark.replaceWith(document.createTextNode(mark.textContent)));container.normalize();
    if(!terms.length)return;const walker=document.createTreeWalker(container,NodeFilter.SHOW_TEXT),nodes=[];let node;
    while(node=walker.nextNode())if(!node.parentElement.closest('code,pre,button,.custom-emoji,script,style'))nodes.push(node);
    for(const node of nodes){const text=node.data,lower=text.toLocaleLowerCase(),ranges=[];for(const term of terms){let from=0,pos;while((pos=lower.indexOf(term,from))!==-1){ranges.push([pos,pos+term.length]);from=pos+term.length;if(ranges.length>=100)break;}}
      ranges.sort((a,b)=>a[0]-b[0]);if(!ranges.length)continue;const fragment=document.createDocumentFragment();let end=0;for(const [a,b] of ranges){if(a<end)continue;fragment.append(document.createTextNode(text.slice(end,a)));const mark=document.createElement('mark');mark.className='search-match';mark.textContent=text.slice(a,b);fragment.append(mark);end=b;}fragment.append(document.createTextNode(text.slice(end)));node.replaceWith(fragment);}
  }
  let decorationQueued=false;
  const observer=new MutationObserver(records=>{if(!decorationQueued&&records.some(record=>reader||record.target.closest?.('#library-results,#mini-preview,.message'))){decorationQueued=true;queueMicrotask(()=>{decorationQueued=false;decorate();});}});
  const root=reader?byId('reader-timeline'):byId('main-reading-root')||document.querySelector('.workspace');
  function decorate(){
    observer.disconnect();const input=searchInput.value.trim().slice(0,500);const terms=(query().phrase?[input]:[...input.matchAll(/"([^"]+)"|(\S+)/g)].map(m=>m[1]||m[2])).filter(Boolean).slice(0,30).map(s=>s.toLocaleLowerCase());
    const saved=new Set(bookmarks().map(b=>b.key));
    for(const row of root.querySelectorAll(reader?'.reader-message[data-id]':'.message[data-message-id]')){
      const m=rowMessage(row);if(!m)continue;const author=row.querySelector('.message-author');if(author){author.tabIndex=0;author.setAttribute('role','button');author.dataset.capturedAuthor=String(m.author?.id||'');author.title='Captured names and identity';}
      let actions=row.querySelector('.reading-actions');if(!actions){actions=row.querySelector('.message-actions')||document.createElement('div');actions.classList.add('reading-actions');actions.insertAdjacentHTML('beforeend','<button data-bookmark-message aria-label="Bookmark message">☆</button><a data-message-context>Surrounding conversation ↗</a>');if(!actions.isConnected)row.querySelector('.message-body').append(actions);}
      const mark=actions.querySelector('[data-bookmark-message]'),identity=bookmarkKey(m);mark.textContent=saved.has(identity)?'★':'☆';mark.setAttribute('aria-pressed',String(saved.has(identity)));mark.title=saved.has(identity)?'Remove bookmark':'Bookmark message';
      const link=actions.querySelector('[data-message-context]');link.href='#';link.dataset.contextId=m.id;link.setAttribute('role','button');
      const content=row.querySelector('.message-content');if(content&&content.dataset.highlight!==input+'|'+query().phrase){highlight(content,terms);content.dataset.highlight=input+'|'+query().phrase;}
    }
    observer.observe(root,{childList:true,subtree:true});
  }
  document.addEventListener('click',async e=>{
    const author=e.target.closest('[data-captured-author]');if(author?.dataset.capturedAuthor){showAuthor(author.dataset.capturedAuthor);return;}
    const b=e.target.closest('[data-bookmark-message],[data-message-context]');if(!b)return;e.preventDefault();const row=b.closest('.message,.reader-message'),m=rowMessage(row);if(!m)return;
    try{if(b.hasAttribute('data-message-context')){const url=await messageURL(m);if(reader){for(const n of names){if(n==='phrase')byId(prefix+n).checked=false;else byId(prefix+n).value='';}loading=false;await loadMessages('replace',{message:m.id,surrounding:'1'});refreshTools();}else window.open(url,'_blank','noopener');return;}
      const identity=bookmarkKey(m),rows=bookmarks(),existing=rows.some(x=>x.key===identity);
      put('studio.bookmarks',existing?rows.filter(x=>x.key!==identity):[{key:identity,url:await messageURL(m),author:m.author?.global_name||m.author?.username||m.author?.name||'Unknown',content:String(m.content||'').slice(0,160),timestamp:m.timestamp},...rows].slice(0,300));decorate();
    }catch(error){reader?status(error.message,true):toast(error.message,true);}
  });
  document.addEventListener('keydown',e=>{if(e.target.dataset.capturedAuthor&&['Enter',' '].includes(e.key)){e.preventDefault();showAuthor(e.target.dataset.capturedAuthor);}});
  const command=dialog('command-dialog','Quick search','<input id="command-query" type="search" aria-label="Quick search" placeholder="Search saved text, navigate, or find a bookmark…"><div id="command-results" class="command-results"></div><p class="hint">Enter searches saved messages. Esc closes. Tab moves through commands.</p>');
  function commandResults(){const q=byId('command-query').value.trim(),options=[{name:'Search saved messages'+(q?' for “'+q+'”':''),run:()=>{if(!reader)showPage('library');searchInput.value=q;reader?(loading=false,loadMessages('replace')):(offset=0,searchLibrary());refreshTools();}}];
    if(!reader)for(const page of ['export','queue','library','archives','people','history','schedules','settings'])if(!q||page.includes(q.toLowerCase()))options.push({name:'Open '+(page==='archives'?'ZIP reader':page),run:()=>showPage(page)});
    for(const saved of searches().filter(s=>s.scope===scope()&&(!q||s.name.toLowerCase().includes(q.toLowerCase()))).slice(0,10))options.push({name:'Saved search: '+saved.name,run:()=>runQuery(saved.query)});
    for(const saved of bookmarks().filter(b=>q&&(b.author+' '+b.content).toLowerCase().includes(q.toLowerCase())).slice(0,10))options.push({name:'Bookmark: '+saved.author+' · '+saved.content.slice(0,70),run:()=>reader?location.assign(saved.url):window.open(saved.url,'_blank','noopener')});
    options.push({name:'Open bookmarks',run:showBookmarks},{name:'Reading & appearance',run:()=>appearanceButton.click()});
    byId('command-results').replaceChildren(...options.map(option=>{const b=document.createElement('button');b.textContent=option.name;b.onclick=()=>{command.close();option.run();};return b;}));
  }
  function openCommand(){byId('command-query').value='';commandResults();command.showModal();byId('command-query').focus();}
  byId('command-open').onclick=openCommand;byId('command-query').oninput=commandResults;
  const quickButton=document.createElement('button');quickButton.className='icon';quickButton.textContent='⌕';quickButton.setAttribute('aria-label','Quick search and navigation');quickButton.title='Quick search · Ctrl+K';quickButton.onclick=openCommand;header.append(quickButton);
  byId('command-query').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();byId('command-results').firstElementChild?.click();}else if(e.key==='ArrowDown'){e.preventDefault();byId('command-results').firstElementChild?.focus();}};
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();if(!command.open)openCommand();}});
  document.addEventListener('studio-page',()=>{refreshTools();if(document.documentElement.dataset.motion==='full')document.querySelector('.page.active')?.animate([{opacity:.4,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],{duration:180,easing:'ease-out'});});
  const ghostObserver=new MutationObserver(()=>document.querySelectorAll('.queue-ghost').forEach(el=>{el.inert=true;}));ghostObserver.observe(document.body,{childList:true});
  if(reader){const originalRender=render;render=function(){originalRender();refreshTools();};}else{const originalRender=renderResults;renderResults=function(){originalRender();refreshTools();};}
  if(reader){let positionTimer;timeline.addEventListener('scroll',()=>{clearTimeout(positionTimer);positionTimer=setTimeout(()=>{if(loading)return;const bounds=timeline.getBoundingClientRect(),row=[...timeline.querySelectorAll('[data-id]')].find(el=>el.getBoundingClientRect().bottom>bounds.top+8);if(!row)return;const prefs=read('studio.reader:'+key,{});prefs.position={channel,message:row.dataset.id,offset:row.getBoundingClientRect().top-bounds.top};put('studio.reader:'+key,prefs);},160);},{passive:true});}
  else{let positionTimer;byId('library-results').addEventListener('scroll',()=>{clearTimeout(positionTimer);positionTimer=setTimeout(()=>{if(libraryBusy||libraryTab!=='messages')return;const bounds=libraryContainer.getBoundingClientRect(),row=[...libraryContainer.querySelectorAll('[data-message-id]')].find(el=>el.getBoundingClientRect().bottom>bounds.top+8),m=row&&messageMap.get(row.dataset.messageId);if(!m?._cursor)return;put('studio.library-position',{signature:JSON.stringify(libraryQuery()),cursor:m._cursor,message:String(m.id),top:row.getBoundingClientRect().top-bounds.top,index:offset+results.messages.findIndex(x=>String(x.id)===String(m.id))});},160);},{passive:true});}
  refreshTools();return {decorate,preferences,highlight};
})();
