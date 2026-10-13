const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{},document:{addEventListener(){}},AbortController,requestAnimationFrame(){},cancelAnimationFrame(){},console};vm.createContext(context);
vm.runInContext(fs.readFileSync('web/midi-player.js','utf8'),context);
function midi(track,division=480){const body=Buffer.from(track),header=Buffer.from('4d546864000000060000000101e04d54726b','hex');header.writeUInt16BE(division,12);const size=Buffer.alloc(4);size.writeUInt32BE(body.length);const raw=Buffer.concat([header,size,body]);return raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.length);}
const song=context.window.MidiPlayer.parse(midi([0,0xff,0x51,3,7,0xa1,0x20,0,0x90,60,100,0x83,0x60,0x80,60,0,0,0xff,0x2f,0]));
assert.equal(song.notes.length,1);assert.equal(song.notes[0].note,60);assert.equal(song.notes[0].end,.5);
const sustained=context.window.MidiPlayer.parse(midi([0,0xb0,64,127,0,0x90,60,80,0x83,0x60,0x80,60,0,0x83,0x60,0xb0,64,0,0,0xff,0x2f,0]));assert.equal(sustained.notes[0].end,1);
assert.throws(()=>context.window.MidiPlayer.parse(midi([0,0x90,60])),/Truncated/);assert.throws(()=>context.window.MidiPlayer.parse(midi([0,0xff,0x2f,0],0x8000)),/timebase/);
vm.runInContext(fs.readFileSync('web/chat-buffer.js','utf8'),context);
(async()=>{let calls=0,resolve;const Pages=context.window.ChatBuffer.Pages,pages=new Pages((params,signal)=>{calls++;return new Promise((done,reject)=>{resolve=done;signal.addEventListener('abort',()=>reject(Object.assign(Error('Cancelled'),{name:'AbortError'})));});});
const a=pages.get('a',{cursor:'one'}),b=pages.get('a',{cursor:'one'});assert.equal(calls,1);resolve({messages:['one']});assert.equal((await a).messages[0],'one');await b;
const stale=pages.get('a',{cursor:'two'});pages.reset();const fresh=pages.get('a',{cursor:'two'});const freshResolve=resolve;assert.equal(await stale,null);freshResolve({messages:['fresh']});assert.equal((await fresh).messages[0],'fresh');await pages.get('a',{cursor:'two'});assert.equal(calls,3);
for(let i=0;i<10;i++){const pending=pages.get('page',{i});resolve({messages:[]});await pending;}assert.ok(pages.entries.size<=3);console.log('Reader frontend: MIDI timing, sustain, malformed input, shared page cache, cancellation and bounded cache passed.');})().catch(error=>{console.error(error);process.exitCode=1;});
