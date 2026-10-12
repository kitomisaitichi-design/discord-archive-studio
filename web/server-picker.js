'use strict';
const serverPickers=[];
const foldName=value=>String(value||'').normalize('NFKD').replace(/\p{M}/gu,'').toLocaleLowerCase();
function renderServerPickers(){
  for(const picker of serverPickers){
    if(!picker.open)picker.input.value=state?.servers.find(s=>s.id===selectedServer)?.name||'';
    else picker.draw();
  }
}
for(const [selectId,inputId,label] of [['server-select','server-search','Server'],['compact-server','compact-server-search','Compact server']]){
  const native=$(selectId),wrap=document.createElement('div');wrap.className='server-picker';
  native.before(wrap);native.hidden=true;
  wrap.innerHTML=`<input id="${inputId}" role="combobox" aria-label="${label}" aria-autocomplete="list" aria-expanded="false" aria-controls="${inputId}-options" autocomplete="off" placeholder="Find a server…"><div id="${inputId}-options" class="server-options" role="listbox" aria-label="${label} names" hidden></div>`;
  const input=$(inputId),list=$(inputId+'-options');
  const picker={input,open:false,index:0,choices:[],draw(){
    const q=foldName(input.value);this.choices=(state?.servers||[]).filter(s=>foldName(s.name+' '+s.id).includes(q));
    this.index=Math.max(0,Math.min(this.index,this.choices.length-1));
    list.innerHTML=this.choices.map((s,i)=>`<button type="button" id="${inputId}-option-${i}" role="option" aria-selected="${s.id===selectedServer}" data-picker-id="${esc(s.id)}" class="${i===this.index?'picked':''}">${esc(s.name)}</button>`).join('')||'<div class="picker-empty" role="status">No matching servers.</div>';
    input.setAttribute('aria-activedescendant',this.choices.length?`${inputId}-option-${this.index}`:'');
  },show(){this.open=true;input.setAttribute('aria-expanded','true');list.hidden=false;this.draw();},close(){this.open=false;list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');input.value=state?.servers.find(s=>s.id===selectedServer)?.name||'';},choose(id){
    this.close();if(id===selectedServer)return;
    $('server-select').value=id;$('server-select').dispatchEvent(new Event('change'));
  }};
  serverPickers.push(picker);
  input.addEventListener('focus',()=>{input.value='';picker.index=0;picker.show();});
  input.addEventListener('input',()=>{picker.index=0;picker.show();});
  input.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();picker.close();return;}
    if(['ArrowDown','ArrowUp','Enter'].includes(event.key)){
      event.preventDefault();if(!picker.open){input.value='';picker.show();return;}
      if(event.key==='Enter'){if(picker.choices[picker.index])picker.choose(picker.choices[picker.index].id);return;}
      picker.index=Math.max(0,Math.min(picker.choices.length-1,picker.index+(event.key==='ArrowDown'?1:-1)));picker.draw();list.querySelector('.picked')?.scrollIntoView({block:'nearest'});
    }
  });
  list.addEventListener('pointerdown',event=>event.preventDefault());
  list.addEventListener('click',event=>{const option=event.target.closest('[data-picker-id]');if(option)picker.choose(option.dataset.pickerId);});
  input.addEventListener('blur',event=>{if(!wrap.contains(event.relatedTarget))picker.close();});
  document.addEventListener('pointerdown',event=>{if(!wrap.contains(event.target))picker.close();});
}
renderServerPickers();
