'use strict';
let queueSelection=new Set(),queueEditorIds=[],queuePrefsOwner=null,queuePrefsTimer=null,queueDefaultSignature='',queuePrefsTime=0;
const queueFields=[
 ['batch_messages','Messages per batch','number',100,100000],['cooldown_minutes','Rest between batches (minutes)','number',1,1440],
 ['page_delay','Seconds between requests','number',1,60],['timing_variation','Extra timing variation (%)','number',0,100],
 ['formats','Export formats','formats'],['include_attachments','Include attachment metadata','checkbox'],['download_media','Include manually saved files in ZIP','checkbox'],
 ['reactions','Include reactions','checkbox'],['edits','Include edit timestamps','checkbox'],['role_colors','Preserve available role colors','checkbox'],
 ['exclude_bots','Exclude bot messages','checkbox'],['split_count','Split at this message count','number',1,100000],['split_mb','Split at estimated JSON size (MB, 0 = off)','number',0,1000],
 ['max_media_mb','ZIP attachment cap (MB; videos still capped at 10)','number',1,100],['start','From date','date'],['end','Through date','date'],
 ['people','Only these user IDs (comma separated)','text'],['archived_threads','Discover archived threads','checkbox'],
 ['recheck_edits','Recheck recent edits (up to 500 messages)','checkbox'],['edit_lookback_days','Recent edit window (days)','number',1,365]
];
function editableQueueJobs(){return [...state.queue,...state.history.filter(j=>j.status==='failed')].filter(j=>j.id!==state.processing_job&&j.owner_id===state.settings_owner&&['queued','waiting','paused','blocked','failed'].includes(j.status));}
function updateQueueSettingsState(){
 if(!state)return;
 if(queuePrefsOwner!==state.settings_owner){
  queuePrefsOwner=state.settings_owner;queueSelection.clear();clearTimeout(queuePrefsTimer);queueDefaultSignature='';
  let cached={};try{cached=JSON.parse(localStorage.getItem('studio.form:'+queuePrefsOwner)||'{}');}catch{}
  const remote=state.queue_preferences||{},prefs=(cached.updated||0)>(remote.updated||0)?cached:remote;
  loadOptions({...state.defaults,...prefs.options,full_rescan:false});$('include-archived').checked=!!prefs.options?.archived_threads;
  $('schedule-scope').value=prefs.scope||'server';document.querySelector(`input[name="schedule-mode"][value="${prefs.mode||'fixed'}"]`).checked=true;
  setIntervalMinutes(prefs.minutes||1440);$('use-future-defaults').checked=prefs.use_defaults!==false;$('advanced').open=!!prefs.advanced;
  queuePrefsTime=prefs.updated||0;$('export-settings-status').textContent=prefs.options?'Settings restored':'Settings save automatically';
  if(prefs===cached&&cached.options)saveExportPreferences();
 }
 const signature=JSON.stringify(state.queue_defaults||{});
 if(signature!==queueDefaultSignature){queueDefaultSignature=signature;if($('use-future-defaults').checked&&Object.keys(state.queue_defaults||{}).length){loadOptions({...readOptions(),...state.queue_defaults});saveExportPreferences();}}
 const editable=editableQueueJobs();queueSelection=new Set([...queueSelection].filter(id=>editable.some(j=>j.id===id)));
 $('queue-settings-count').textContent=`${queueSelection.size} selected · ${editable.length} editable`;
 $('edit-selected-queue').disabled=!queueSelection.size;$('edit-all-queue').disabled=!editable.length;
}
function saveExportPreferences(){
 if(!queuePrefsOwner||!state)return;
 const owner=queuePrefsOwner;queuePrefsTime=Math.max(Date.now(),queuePrefsTime+1);
 const value={owner,options:{...readOptions(),full_rescan:false},scope:$('schedule-scope').value,mode:document.querySelector('input[name="schedule-mode"]:checked').value,minutes:interval(),use_defaults:$('use-future-defaults').checked,advanced:$('advanced').open,updated:queuePrefsTime};
 const invalid=queueFields.find(([key,label,type,min,max])=>type==='number'&&value.options[key]!==undefined&&(!Number.isFinite(value.options[key])||value.options[key]<min||value.options[key]>max));
 if(invalid||!value.options.formats.length||(value.options.start&&value.options.end&&value.options.start>value.options.end)){clearTimeout(queuePrefsTimer);$('export-settings-status').textContent='Not saved: '+(invalid?'check '+invalid[1].toLowerCase():!value.options.formats.length?'select an export format':'end date must follow start date');return;}
 localStorage.setItem('studio.form:'+owner,JSON.stringify(value));$('export-settings-status').textContent='Saving settings…';clearTimeout(queuePrefsTimer);
 queuePrefsTimer=setTimeout(async()=>{if(queuePrefsOwner!==owner)return;try{await api('queue/preferences',value);if(queuePrefsOwner===owner)$('export-settings-status').textContent='Settings saved';}catch(e){if(queuePrefsOwner===owner)$('export-settings-status').textContent='Not saved: '+e.message;}},350);
}
function queueFieldControl(field,value){
 const [key,label,type,min,max]=field,id='qe-value-'+key;
 if(type==='formats')return `<div class="queue-format-options">${['json','html','md','txt'].map(fmt=>`<label class="inline-check"><input type="checkbox" data-qe-format="${fmt}" ${(value||[]).includes(fmt)?'checked':''}>${fmt.toUpperCase()}</label>`).join('')}</div>`;
 return `<input id="${id}" aria-label="${esc(label)}" type="${type}" ${type==='checkbox'?(value?'checked':''):`value="${esc(type==='text'&&Array.isArray(value)?value.join(', '):value)}"`} ${type==='number'?`min="${min}" max="${max}" step="${key==='page_delay'?'0.5':'1'}"`:''}>`;
}
function renderQueueEditor(){
 const target=$('queue-settings-target').value,jobs=target==='all'?editableQueueJobs():editableQueueJobs().filter(j=>queueEditorIds.includes(j.id));
 const seed=target==='future'?{...state.defaults,...state.queue_preferences?.options,...state.queue_defaults}:jobs[0]?.options||state.defaults;
 $('queue-settings-context').textContent=target==='future'?'Saved defaults apply only to future additions. Existing tasks keep their settings.':`${jobs.length} editable task${jobs.length===1?'':'s'}. Check only the fields you want to change.`;
 $('queue-also-future-label').hidden=target==='future';$('queue-also-future').checked=false;
 $('queue-settings-fields').innerHTML=queueFields.map(field=>{const [key,label]=field,mixed=target!=='future'&&jobs.some(j=>JSON.stringify(j.options[key])!==JSON.stringify(seed[key]));return `<div class="queue-setting-field" data-qe-field="${key}"><label class="queue-apply"><input id="qe-apply-${key}" type="checkbox" aria-label="Apply ${esc(label)}"><span>${esc(label)}</span>${mixed?'<small>Mixed · unchanged unless checked</small>':''}</label>${queueFieldControl(field,seed[key])}</div>`;}).join('');
}
function openQueueEditor(target,ids=[]){
 queueEditorIds=[...ids];$('queue-settings-target').value=target;$('queue-settings-title').textContent=target==='items'&&ids.length===1?'Edit task settings':'Queue settings';renderQueueEditor();
 if(!$('queue-settings-dialog').open)$('queue-settings-dialog').showModal();
}
const prefsControl=document.createElement('div');prefsControl.className='saved-preferences';prefsControl.innerHTML='<label class="inline-check"><input id="use-future-defaults" type="checkbox" checked>Use saved future defaults for new tasks</label><span id="export-settings-status" class="hint" role="status">Settings save automatically</span>';
$('page-export').querySelector('.page-heading').after(prefsControl);
document.addEventListener('click',e=>{const b=e.target.closest('button');if(b?.dataset.queueSettings)openQueueEditor('items',[b.dataset.queueSettings]);});
document.addEventListener('change',e=>{if(e.target.dataset.selectQueue){e.target.checked?queueSelection.add(e.target.dataset.selectQueue):queueSelection.delete(e.target.dataset.selectQueue);queueSignature='';renderQueue();updateQueueSettingsState();}});
$('select-editable-queue').onclick=()=>{queueSelection=new Set(editableQueueJobs().filter(j=>state.queue.some(q=>q.id===j.id)).map(j=>j.id));queueSignature='';renderQueue();updateQueueSettingsState();};
$('clear-queue-selection').onclick=()=>{queueSelection.clear();queueSignature='';renderQueue();updateQueueSettingsState();};
$('edit-selected-queue').onclick=()=>openQueueEditor('items',[...queueSelection]);$('edit-all-queue').onclick=()=>openQueueEditor('all');$('edit-future-queue').onclick=()=>openQueueEditor('future');
$('close-queue-settings').onclick=()=>$('queue-settings-dialog').close();$('queue-settings-target').onchange=renderQueueEditor;
$('queue-settings-fields').addEventListener('input',e=>{const field=e.target.closest('[data-qe-field]');if(field&&!e.target.id.startsWith('qe-apply-'))$('qe-apply-'+field.dataset.qeField).checked=true;});
$('queue-settings-form').onsubmit=e=>{e.preventDefault();busy($('save-queue-settings'),async()=>{const changes={};for(const [key,label,type] of queueFields){if(!$('qe-apply-'+key).checked)continue;const input=$('qe-value-'+key);changes[key]=type==='formats'?Array.from(document.querySelectorAll('[data-qe-format]:checked'),x=>x.dataset.qeFormat):type==='checkbox'?input.checked:type==='number'?Number(input.value):key==='people'?input.value.split(',').map(x=>x.trim()).filter(Boolean):input.value;}if(!Object.keys(changes).length)throw new Error('Check at least one setting to apply.');const result=await api('queue/configure',{owner:state.settings_owner,target:$('queue-settings-target').value,ids:queueEditorIds,changes,future:$('queue-also-future').checked});applyState(await api('state'));$('queue-settings-dialog').close();toast(`${result.changed} tasks updated${result.future?' · future defaults saved':''}. Checkpoints and current rest preserved.`);});};
document.querySelectorAll('#page-export input,#page-export select,#include-archived').forEach(el=>{el.addEventListener('input',saveExportPreferences);el.addEventListener('change',saveExportPreferences);});
$('advanced').addEventListener('toggle',saveExportPreferences);$('seven-day').addEventListener('click',saveExportPreferences);
$('use-future-defaults').addEventListener('change',()=>{if($('use-future-defaults').checked&&state){loadOptions({...readOptions(),...state.queue_defaults});saveExportPreferences();}});
if(state)updateQueueSettingsState();
