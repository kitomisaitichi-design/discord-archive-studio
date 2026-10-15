'use strict';
(()=>{
  const panel=document.createElement('section');panel.className='panel application-update-panel';
  panel.innerHTML='<div class="panel-title">Application updates <span id="application-version" class="muted"></span></div><p class="hint">Quiet updates from this app’s GitHub releases. Captures finish before an update is installed.</p><label class="switch-row update-toggle"><span>Automatically update the app</span><input id="application-update-enabled" type="checkbox" checked></label><div class="update-frequency"><label for="application-update-minutes">Check every</label><select id="application-update-minutes"><option value="60">Hour</option><option value="360">6 hours</option><option value="720">12 hours</option><option value="1440" selected>Day</option><option value="4320">3 days</option><option value="10080">Week</option></select><button id="application-update-check" type="button">Check now</button></div><p id="application-update-status" class="hint" role="status">Checking saved update settings…</p><small id="application-update-time" class="muted"></small>';
  const settings=document.querySelector('#page-settings');if(settings)settings.prepend(panel);
  const imageControl=document.createElement('label');imageControl.className='inline-check direct-image-control';imageControl.innerHTML='<input type="checkbox" id="direct-images-enabled">Show images from direct JPG, PNG & GIF links';
  const appearance=document.querySelector('#reading-settings');appearance?.append(imageControl);const imageToggle=imageControl.querySelector('input');imageToggle.checked=MediaView.directEnabled;imageToggle.onchange=()=>MediaView.setDirect(imageToggle.checked);
  window.addEventListener('storage',event=>{if(event.key==='studio.direct-images')imageToggle.checked=event.newValue!=='off';});
  if(!settings)return;
  const by=id=>document.getElementById(id);let pending=false,timer,desired=null;
  async function request(path,data){const response=await fetch('/api/updates'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json','X-Studio-Action':'local'}:{},body:data?JSON.stringify(data):undefined});const value=await response.json();if(!response.ok)throw Error(value.error||'Update request failed.');return value;}
  function render(value){
    by('application-version').textContent='v'+value.current;by('application-update-enabled').checked=value.enabled;
    const frequency=by('application-update-minutes');if(![...frequency.options].some(o=>Number(o.value)===value.minutes))frequency.add(new Option(value.minutes+' minutes',value.minutes));frequency.value=String(value.minutes);
    const messages={checking:'Checking the latest stable release…',downloading:'Downloading and verifying an update quietly…',ready:'Update ready. Waiting for the current capture to finish.',installing:'Updating at a saved checkpoint. This page will reconnect.',current:'You’re up to date.',available:'A newer release is available.',error:value.error||'Update check could not finish.'};
    by('application-update-status').textContent=(value.enabled?'':'Automatic updates are off. ')+(messages[value.status]||(value.enabled?'Automatic updates are on.':''));
    if(!value.portable)by('application-update-status').textContent+=' Automatic installation is available in portable copies.';
    by('application-update-time').textContent=(value.last_check?'Last checked '+new Date(value.last_check*1000).toLocaleString()+'. ':'')+(value.enabled&&value.next_check?'Next check '+new Date(value.next_check*1000).toLocaleString()+'.':'');
    by('application-update-check').disabled=!!value.busy||value.status==='installing';
  }
  async function refresh(){if(pending)return;try{render(await request(''));}catch(error){by('application-update-status').textContent=error.message;}}
  async function save(){desired={enabled:by('application-update-enabled').checked,minutes:Number(by('application-update-minutes').value)};if(pending)return;pending=true;try{while(desired){const value=desired;desired=null;const result=await request('/settings',value);if(!desired)render(result);}}catch(error){by('application-update-status').textContent=error.message;}finally{pending=false;}}
  by('application-update-enabled').onchange=save;by('application-update-minutes').onchange=save;by('application-update-check').onclick=async()=>{try{render(await request('/check',{}));}catch(error){by('application-update-status').textContent=error.message;}};
  document.addEventListener('studio-page',event=>{clearInterval(timer);if(event.detail==='settings'){refresh();timer=setInterval(refresh,5000);}});
  document.addEventListener('visibilitychange',()=>{clearInterval(timer);if(!document.hidden&&document.querySelector('#page-settings.active')){refresh();timer=setInterval(refresh,5000);}});
  let versionOnLoad,restarting=false;async function reconnect(){if(document.hidden)return;try{const response=await fetch('/api/health'),health=await response.json();if(versionOnLoad&&versionOnLoad!==health.version){if(!document.activeElement?.matches('input,textarea,[contenteditable=true]'))location.reload();return;}versionOnLoad=health.version;}catch{}}
  const apply=applyState;applyState=function(value){apply(value);const update=value.application_update;if(update){if(!versionOnLoad)versionOnLoad=update.current;if(document.querySelector('#page-settings.active')&&!pending)render(update);if(update.status==='installing')restarting=true;if(update.current!==versionOnLoad)reconnect();}};
  reconnect();window.addEventListener('online',reconnect);setInterval(()=>{if(restarting)reconnect();},3000);
  if(typeof currentPage!=='undefined'&&currentPage==='settings'){refresh();timer=setInterval(refresh,5000);}
})();
