'use strict';
window.StudioSounds=(()=>{
  let muted=localStorage.getItem('studio.sound.muted')==='true',context,lastProgress=0,lastCue=0;
  const notes={queue:[[660,0,.07],[880,.08,.09]],start:[[440,0,.08],[660,.09,.12]],done:[[660,0,.09],[880,.11,.09],[1100,.22,.18]],progress:[[780,0,.055]],drag:[[330,0,.045]],drop:[[550,0,.06]],menu:[[520,0,.035]],error:[[260,0,.1],[220,.12,.13]]};
  const button=document.createElement('button');button.id='sound-toggle';button.className='sound-toggle';button.type='button';document.querySelector('.app-header,.reader-header')?.append(button);
  function paint(){button.textContent=muted?'🔇':'🔊';button.title=muted?'Unmute interface sounds':'Mute interface sounds';button.setAttribute('aria-label',button.title);button.setAttribute('aria-pressed',String(muted));}
  function unlock(){if(muted)return;try{context||=new AudioContext();if(context.state==='suspended')context.resume().catch(()=>{});}catch{button.title='Sounds are unavailable in this browser';}}
  function play(kind){if(muted||!context||context.state!=='running')return;const now=performance.now();if(now-lastCue<80)return;lastCue=now;
    for(const [frequency,delay,duration] of notes[kind]||notes.menu){const oscillator=context.createOscillator(),gain=context.createGain(),at=context.currentTime+delay;oscillator.type='sine';oscillator.frequency.value=frequency;gain.gain.setValueAtTime(0,at);gain.gain.linearRampToValueAtTime(.025,at+.006);gain.gain.exponentialRampToValueAtTime(.0001,at+duration);oscillator.connect(gain);gain.connect(context.destination);oscillator.start(at);oscillator.stop(at+duration+.015);oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};}}
  button.onclick=()=>{muted=!muted;localStorage.setItem('studio.sound.muted',String(muted));paint();if(!muted){unlock();play('menu');}};paint();
  document.addEventListener('pointerdown',unlock,{passive:true});document.addEventListener('keydown',unlock,{passive:true});
  document.addEventListener('click',event=>{if(event.target.closest('[data-page],[data-library-tab],[data-mode],[data-day],[data-hour]'))play('menu');});
  window.addEventListener('storage',event=>{if(event.key==='studio.sound.muted'){muted=event.newValue==='true';paint();}});
  function update(value,previous){if(!previous)return;const old=new Map([...previous.queue,...previous.history].map(job=>[job.id,job]));let cue=null;
    for(const job of [...value.queue,...value.history]){const before=old.get(job.id);if(!before){if(['queued','waiting'].includes(job.status))cue||='queue';continue;}if(job.status!==before.status){if(job.status==='completed')cue='done';else if(job.status==='failed')cue||='error';else if(job.status==='running')cue||='start';}else if(job.progress>before.progress&&performance.now()-lastProgress>30000){lastProgress=performance.now();cue||='progress';}}
    if(cue)play(cue);
  }
  return {play,update};
})();
