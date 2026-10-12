'use strict';
const $=id=>document.getElementById(id);
async function state(){const s=await chrome.storage.local.get(['status','port']);$('status').textContent=s.status||'Pair once, then reload logged-in Discord.';$('port').value=s.port||8765;}
$('pair').onclick=async()=>{
  $('pair').disabled=true;
  try{const port=Number($('port').value);if(!Number.isInteger(port)||port<1024||port>65535)throw new Error('Choose a valid local app port.');const response=await fetch(`http://127.0.0.1:${port}/api/bridge/pair`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('code').value.trim(),extension_id:chrome.runtime.id})});const result=await response.json();if(!response.ok)throw new Error(result.error);await chrome.storage.local.set({key:result.key,port,status:'Paired. Open or reload Discord to connect.'});$('code').value='';await state();}catch(e){$('status').textContent=e.message;}finally{$('pair').disabled=false;}
};
$('reconnect').onclick=async()=>{const r=await chrome.runtime.sendMessage({action:'reconnect'});if(r.error)$('status').textContent=r.error;else await state();};state();
