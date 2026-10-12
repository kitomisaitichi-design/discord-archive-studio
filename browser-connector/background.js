'use strict';
const apiPattern=/^https:\/\/(?:ptb\.|canary\.)?discord\.com\/api\/v\d+\//;
let lastDigest='',busy=false,lastAttempt='',lastAttemptTime=0;
async function forward(token, force=false){
  if(busy)return;
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(token))),n=>n.toString(16).padStart(2,'0')).join('');
  const settings=await chrome.storage.local.get(['key','port']);
  if(!settings.key){await chrome.storage.local.set({status:'Pair once with the local app.'});return;}
  if(digest===lastDigest&&!force)return;
  if(digest===lastAttempt&&Date.now()-lastAttemptTime<30000&&!force)return;
  lastAttempt=digest;lastAttemptTime=Date.now();
  busy=true;
  try{
    const healthResponse=await fetch(`http://127.0.0.1:${settings.port||8765}/api/health`);
    const health=await healthResponse.json();
    if(!healthResponse.ok||health.app!=='Discord Archive Studio')throw new Error('Set the connector port to the address shown in Archive Studio Settings.');
    const response=await fetch(`http://127.0.0.1:${settings.port||8765}/api/bridge/connect`,{method:'POST',headers:{'Content-Type':'application/json','X-Bridge-Key':settings.key},body:JSON.stringify({token,extension_id:chrome.runtime.id})});
    const value=await response.json();
    if(!response.ok)throw new Error(value.error||'Connection rejected.');
    lastDigest=digest;await chrome.storage.local.set({status:`Connected as ${value.account.name}.`});
    await chrome.action.setBadgeText({text:'✓'});await chrome.action.setBadgeBackgroundColor({color:'#6653de'});
  }catch(error){await chrome.storage.local.set({status:error.message==='Failed to fetch'?'Open the archive app, then reload Discord.':error.message});await chrome.action.setBadgeText({text:'!'});}
  finally{busy=false;}
}
chrome.webRequest.onBeforeSendHeaders.addListener(details=>{
  if(!apiPattern.test(details.url)||!/^https:\/\/(?:ptb\.|canary\.)?discord\.com(?:\/|$)/.test(details.initiator||''))return;
  const header=details.requestHeaders?.find(h=>h.name.toLowerCase()==='authorization');
  if(header?.value&&!header.value.startsWith('Bot ')){
    // Session storage disappears when the browser closes; credentials are never written to local/sync storage.
    chrome.storage.session.set({sessionToken:header.value});forward(header.value);
  }
},{urls:['https://discord.com/api/*','https://ptb.discord.com/api/*','https://canary.discord.com/api/*']},['requestHeaders','extraHeaders']);
chrome.webRequest.onBeforeRequest.addListener(()=>{lastDigest='';lastAttempt='';},{urls:['https://discord.com/*','https://ptb.discord.com/*','https://canary.discord.com/*'],types:['main_frame']});
chrome.storage.onChanged.addListener((changes,area)=>{if(area==='local'&&changes.key){lastDigest='';lastAttempt='';chrome.storage.session.get('sessionToken').then(value=>{if(value.sessionToken)forward(value.sessionToken,true);});}});
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(sender.id!==chrome.runtime.id)return;
  if(message.action==='reconnect')chrome.storage.session.get('sessionToken').then(async value=>{if(value.sessionToken){await forward(value.sessionToken,true);reply({ok:true});}else reply({error:'Open or reload logged-in Discord first.'});});
  return true;
});
