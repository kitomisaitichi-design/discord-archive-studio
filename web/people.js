'use strict';
let peopleData={contacts:[]},peopleSelected=new Set(),peopleLoading=false,peopleLimit=200,peopleOwner;
$('people-scope').value=localStorage.getItem('studio.people.scope')==='friends'?'friends':'all';
$('people-groups').checked=localStorage.getItem('studio.people.groups')==='true';
$('people-adaptive').checked=localStorage.getItem('studio.people.adaptive')!=='false';
function savePeopleSelection(){if(peopleData.owner)localStorage.setItem('studio.people.selected:'+peopleData.owner,JSON.stringify([...peopleSelected]));}
function peopleChats(person){return [...person.channel_ids,...($('people-groups').checked?person.group_ids:[])];}
function eligiblePeople(){return (peopleData.contacts||[]).filter(p=>($('people-scope').value!=='friends'||p.friend)&&peopleChats(p).length);}
function filteredPeople(){
  const q=foldName($('people-search').value),friends=$('people-scope').value==='friends';
  return (peopleData.contacts||[]).filter(p=>(friends?p.friend:p.channel_ids.length||p.group_ids.length)&&foldName(p.name+' '+p.username+' '+p.id).includes(q));
}
function renderPeople(){
  const filtered=filteredPeople(),eligible=eligiblePeople(),selectedPeople=eligible.filter(p=>peopleSelected.has(p.id));
  const chats=new Set(selectedPeople.flatMap(peopleChats));
  const friends=$('people-scope').value==='friends',unavailable=friends&&!peopleData.friends_available;
  $('people-count').textContent=`${number(filtered.length)} people · ${number(selectedPeople.length)} selected · ${number(chats.size)} DM chats`;
  $('people-note').textContent=unavailable?(peopleData.friends_note||'Choose Refresh to load your current friends list.'):(peopleData.updated?'Contact metadata cached · refreshed '+new Date(peopleData.updated*1000).toLocaleString()+'. Search stays local.':'Refresh to load your available DM contacts.');
  const container=$('people-list'),scroll=container.scrollTop;
  container.innerHTML=filtered.slice(0,peopleLimit).map(p=>{const count=peopleChats(p).length;return `<label class="person-row"><input type="checkbox" data-person="${esc(p.id)}" ${peopleSelected.has(p.id)&&count?'checked':''} ${count?'':'disabled'}><span class="person-name"><strong>${esc(p.name)}</strong><small>${esc(p.username)} · ${esc(p.id)}${p.friend?' · friend':''}</small></span><span class="person-chats">${count?number(count)+' chat'+(count===1?'':'s'):'No available DM'}<small>${number(p.saved)} saved</small></span></label>`;}).join('')||'<div class="empty">No matching people.</div>';
  container.scrollTop=scroll;$('people-more').hidden=filtered.length<=peopleLimit;
  $('people-queue-selected').textContent=`Queue selected (${chats.size})`;
  $('people-queue-filtered').textContent=`Queue filtered (${new Set(filtered.filter(p=>peopleChats(p).length).flatMap(peopleChats)).size})`;
  $('people-queue-selected').disabled=!state?.connection.connected||!chats.size||unavailable;
  $('people-queue-filtered').disabled=!state?.connection.connected||!filtered.some(p=>peopleChats(p).length)||unavailable;
  $('people-refresh').disabled=!state?.connection.connected||peopleLoading;
}
async function loadPeople(force=false){
  if(!state||peopleLoading)return;peopleLoading=true;renderPeople();
  try{
    const previousOwner=peopleData.owner;peopleData=await api('people');
    if(previousOwner!==peopleData.owner)peopleSelected=new Set(JSON.parse(localStorage.getItem('studio.people.selected:'+peopleData.owner)||'[]'));
    const friends=$('people-scope').value==='friends',now=Date.now()/1000;
    if(state.connection.connected&&(force||now-(peopleData.updated||0)>600||(friends&&now-(peopleData.friends_updated||0)>600)))peopleData=await api('people/refresh',{friends,force});
    const valid=new Set(peopleData.contacts.map(p=>p.id));peopleSelected=new Set([...peopleSelected].filter(id=>valid.has(id)));savePeopleSelection();
  }catch(error){toast(error.message,true);}
  finally{peopleLoading=false;renderPeople();}
}
function updatePeopleAccount(){
  const owner=state?.connection.account?.id||null;
  if(owner!==peopleOwner){peopleOwner=owner;peopleData={contacts:[]};peopleSelected.clear();if(currentPage==='people')loadPeople();}
  if(currentPage==='people')renderPeople();
}
async function queuePeople(button,filtered){
  const users=(filtered?filteredPeople():eligiblePeople().filter(p=>peopleSelected.has(p.id))).filter(p=>peopleChats(p).length).map(p=>p.id);
  try{await busy(button,async()=>{const result=await api('people/enqueue',{users,groups:$('people-groups').checked,friends:$('people-scope').value==='friends',adaptive:$('people-adaptive').checked,options:readOptions()});toast(`${result.chats} DM chats added or already queued${result.skipped?' · '+result.skipped+' unavailable contacts skipped':''}.`);});}
  finally{renderPeople();}
}
$('people-refresh').onclick=()=>loadPeople(true);
$('people-search').oninput=()=>{peopleLimit=200;renderPeople();};
$('people-scope').onchange=()=>{localStorage.setItem('studio.people.scope',$('people-scope').value);peopleSelected.clear();savePeopleSelection();peopleLimit=200;loadPeople();};
$('people-groups').onchange=()=>{localStorage.setItem('studio.people.groups',String($('people-groups').checked));renderPeople();};
$('people-adaptive').onchange=()=>localStorage.setItem('studio.people.adaptive',String($('people-adaptive').checked));
$('people-list').onchange=event=>{const id=event.target.dataset.person;if(id){event.target.checked?peopleSelected.add(id):peopleSelected.delete(id);savePeopleSelection();renderPeople();}};
$('people-select-all').onclick=()=>{filteredPeople().filter(p=>peopleChats(p).length).forEach(p=>peopleSelected.add(p.id));savePeopleSelection();renderPeople();};
$('people-clear').onclick=()=>{peopleSelected.clear();savePeopleSelection();renderPeople();};
$('people-more').onclick=()=>{peopleLimit+=200;renderPeople();};
$('people-settings').onclick=()=>showPage('export');
$('people-queue-selected').onclick=()=>queuePeople($('people-queue-selected'),false);
$('people-queue-filtered').onclick=()=>queuePeople($('people-queue-filtered'),true);
if(state)updatePeopleAccount();if(currentPage==='people')loadPeople();
