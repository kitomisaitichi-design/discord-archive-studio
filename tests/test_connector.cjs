const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');const {webcrypto}=require('node:crypto');
const local={key:'test-pair-key',port:8765},session={},hooks={},requests=[];let healthApp='Discord Archive Studio';
function storage(values){return {get:async keys=>Object.fromEntries((Array.isArray(keys)?keys:[keys]).map(k=>[k,values[k]])),set:async value=>Object.assign(values,value)};}
const context=vm.createContext({console,crypto:webcrypto,TextEncoder,Date,setTimeout,
  fetch:async(url,opts)=>{requests.push({url,...opts});return {ok:true,json:async()=>url.endsWith('/api/health')?{app:healthApp}:{account:{name:'Test account'}}};},
  chrome:{storage:{local:storage(local),session:storage(session),onChanged:{addListener:fn=>hooks.changed=fn}},
    action:{setBadgeText:async()=>{},setBadgeBackgroundColor:async()=>{}},
    webRequest:{onBeforeSendHeaders:{addListener:(fn,filter,flags)=>{hooks.headers=fn;hooks.flags=flags;hooks.filter=filter;}},onBeforeRequest:{addListener:fn=>hooks.navigation=fn}},
    runtime:{id:'test-extension',onMessage:{addListener:fn=>hooks.message=fn}}}});
vm.runInContext(fs.readFileSync('browser-connector/background.js','utf8'),context);
const token='simulated-session-credential-never-a-real-token';
const details={url:'https://discord.com/api/v10/users/@me',initiator:'https://discord.com',requestHeaders:[{name:'Authorization',value:token}]};
const settle=()=>new Promise(r=>setTimeout(r,30));
(async()=>{
  hooks.headers(details);await settle();
  assert.equal(requests.length,2);assert.equal(requests[0].url.endsWith('/api/health'),true);assert.equal(session.sessionToken,token);
  assert.ok(!JSON.stringify(local).includes(token));assert.ok(hooks.flags.includes('extraHeaders'));
  hooks.headers(details);await settle();assert.equal(requests.length,2,'same document should not keep validating');
  hooks.navigation({});hooks.headers(details);await settle();assert.equal(requests.length,4,'Discord reload should reconnect');
  hooks.headers({...details,initiator:'https://unrelated.example'});await settle();assert.equal(requests.length,4);
  healthApp='Unrelated localhost service';hooks.navigation({});hooks.headers(details);await settle();
  assert.equal(requests.length,5,'wrong local service gets only a health check');assert.equal(requests.filter(r=>r.method==='POST').length,2,'credential must not be forwarded to the wrong service');
  assert.ok(requests.every(r=>r.url.startsWith('http://127.0.0.1:8765/')));
  console.log('Browser connector: service identity gate, local-only forwarding, session-only credential storage, reload reconnection, and duplicate-event suppression passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
