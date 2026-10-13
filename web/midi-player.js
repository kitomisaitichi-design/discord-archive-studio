'use strict';
window.MidiPlayer=(()=>{
  function parse(buffer){
    const bytes=new Uint8Array(buffer),view=new DataView(buffer);let p=0;
    const read=(n)=>{if(p+n>bytes.length)throw Error('Truncated MIDI file.');const at=p;p+=n;return at;};
    const word=()=>view.getUint16(read(2)),long=()=>view.getUint32(read(4)),tag=()=>String.fromCharCode(...bytes.slice(read(4),p));
    if(bytes.length>10000000||tag()!=='MThd')throw Error('Unsupported MIDI file.');
    const header=long(),headerEnd=p+header,format=word(),tracks=word(),division=word();
    if(header<6||format>1||tracks>256||!division||(division&0x8000))throw Error('Use standard MIDI format 0 or 1 with a musical timebase.');
    p=headerEnd;const events=[];let count=0;
    for(let track=0;track<tracks;track++){
      if(tag()!=='MTrk')throw Error('Invalid MIDI track.');const length=long(),end=p+length;if(end>bytes.length)throw Error('Truncated MIDI track.');
      let tick=0,running=0;
      const variable=()=>{let value=0;for(let i=0;i<4;i++){const b=bytes[read(1)];value=value*128+(b&127);if(!(b&128))return value;}throw Error('Invalid MIDI delta.');};
      while(p<end){
        tick+=variable();let status=bytes[p];if(status&128){p++;if(status<240)running=status;}else{if(!running)throw Error('Missing MIDI status.');status=running;}
        if(++count>200000)throw Error('MIDI event limit exceeded.');
        if(status===255){const kind=bytes[read(1)],size=variable(),at=read(size);if(kind===81&&size===3)events.push({tick,tempo:(bytes[at]<<16)|(bytes[at+1]<<8)|bytes[at+2]});if(kind===47)break;}
        else if(status===240||status===247){read(variable());running=0;}
        else if(status<240){const kind=status>>4,channel=status&15,a=bytes[read(1)],b=(kind===12||kind===13)?0:bytes[read(1)];if([8,9,11].includes(kind))events.push({tick,kind,channel,a,b});}
        else throw Error('Unsupported MIDI event.');
        if(p>end)throw Error('MIDI event crosses its track.');
      }p=end;
    }
    events.sort((a,b)=>a.tick-b.tick);let tick=0,time=0,tempo=500000;const notes=[],held=new Map(),pedal=new Set(),released=new Set();
    const finish=(key,at)=>{const note=held.get(key);if(note){note.end=Math.max(note.start+.025,at);notes.push(note);held.delete(key);}released.delete(key);};
    for(const event of events){time+=(event.tick-tick)*tempo/division/1000000;tick=event.tick;if(event.tempo){if(event.tempo>0)tempo=event.tempo;continue;}
      const key=event.channel+':'+event.a;
      if(event.kind===9&&event.b){finish(key,time);held.set(key,{start:time,end:time+.1,note:event.a,velocity:event.b/127,channel:event.channel});}
      else if(event.kind===8||event.kind===9){if(pedal.has(event.channel))released.add(key);else finish(key,time);}
      else if(event.kind===11&&event.a===64){if(event.b>=64)pedal.add(event.channel);else{pedal.delete(event.channel);for(const k of [...released])if(k.startsWith(event.channel+':'))finish(k,time);}}
    }
    for(const key of [...held.keys()])finish(key,time+.15);
    notes.sort((a,b)=>a.start-b.start);const duration=notes.reduce((n,note)=>Math.max(n,note.end),Math.max(.1,time));
    if(duration>86400)throw Error('MIDI duration exceeds the playback limit.');return {notes,duration};
  }
  let context,current=null;
  class Player{
    constructor(element,data){this.element=element;this.data=data;this.position=0;this.voices=new Set();this.running=false;this.button=element.querySelector('[data-midi-play]');this.seek=element.querySelector('[data-midi-seek]');this.status=element.querySelector('[data-midi-status]');this.seek.max=data.duration;this.seek.oninput=()=>{const playing=this.running;this.pause();this.position=Number(this.seek.value);if(playing)this.play();else this.paint();};}
    voice(note,at){if(this.voices.size>=32)return;const oscillator=context.createOscillator(),gain=context.createGain(),duration=Math.max(.025,note.end-Math.max(note.start,at));oscillator.type=note.channel===9?'triangle':'sine';oscillator.frequency.value=440*2**((note.note-69)/12);const when=context.currentTime+Math.max(0,note.start-at);gain.gain.setValueAtTime(0,when);gain.gain.linearRampToValueAtTime(note.velocity*.09,when+.01);gain.gain.setValueAtTime(note.velocity*.075,when+duration*.7);gain.gain.linearRampToValueAtTime(0,when+duration+.04);oscillator.connect(gain);gain.connect(context.destination);oscillator.start(when);oscillator.stop(when+duration+.05);this.voices.add(oscillator);oscillator.onended=()=>{this.voices.delete(oscillator);oscillator.disconnect();gain.disconnect();};}
    async play(){if(current&&current!==this)current.pause();current=this;context||=new AudioContext();await context.resume();if(this.position>=this.data.duration)this.position=0;this.start=context.currentTime-this.position;this.index=this.data.notes.findIndex(n=>n.end>this.position);if(this.index<0)this.index=this.data.notes.length;this.running=true;this.element.dataset.midiPlaying='true';this.button.textContent='Ⅱ Pause MIDI';this.step();}
    step(){if(!this.running)return;this.position=context.currentTime-this.start;while(this.index<this.data.notes.length&&this.data.notes[this.index].start<this.position+.25){const note=this.data.notes[this.index++];if(note.end>this.position)this.voice(note,this.position);}this.paint();if(this.position>=this.data.duration){this.pause();this.position=this.data.duration;this.paint();return;}if(!this.element.isConnected){this.pause();return;}this.frame=requestAnimationFrame(()=>this.step());}
    pause(){if(this.running)this.position=Math.min(this.data.duration,context.currentTime-this.start);this.running=false;this.element.dataset.midiPlaying='false';cancelAnimationFrame(this.frame);for(const voice of this.voices){try{voice.stop();}catch{}}this.voices.clear();this.button.textContent='▶ Play MIDI';this.paint();}
    paint(){this.seek.value=this.position;const format=v=>Math.floor(v/60)+':'+String(Math.floor(v%60)).padStart(2,'0');this.status.textContent=format(this.position)+' / '+format(this.data.duration)+' · local synth';}
  }
  const players=new WeakMap();
  document.addEventListener('click',async event=>{const button=event.target.closest('[data-midi-play]');if(!button)return;const element=button.closest('[data-midi-src]');if(button.disabled)return;let player=players.get(element);try{if(!player){button.disabled=true;button.textContent='Loading saved MIDI…';const response=await fetch(element.dataset.midiSrc);if(!response.ok)throw Error('Saved MIDI is unavailable.');if(Number(response.headers.get('Content-Length'))>10000000)throw Error('MIDI exceeds the 10 MB playback cap.');player=new Player(element,parse(await response.arrayBuffer()));players.set(element,player);if(!element.isConnected)return;}if(player.running)player.pause();else await player.play();}catch(error){element.querySelector('[data-midi-status]').textContent=error.message;button.textContent='Retry MIDI';}finally{button.disabled=false;}});
  return {parse,stop(root){for(const el of root.querySelectorAll('[data-midi-src]'))players.get(el)?.pause();}};
})();
