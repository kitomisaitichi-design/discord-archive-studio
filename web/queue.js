'use strict';
let draggedJob=null,queuePointer=null,queueMovePending=false;
const queueSpaceObserver=new ResizeObserver(()=>document.documentElement.style.setProperty('--queue-space',Math.ceil($('queue-tray').getBoundingClientRect().height+24)+'px'));
queueSpaceObserver.observe($('queue-tray'));
function clearQueueGesture(){
  document.querySelectorAll('.dragging,.drop-before,.drop-after').forEach(e=>e.classList.remove('dragging','drop-before','drop-after'));
  draggedJob=null;queuePointer=null;document.body.classList.remove('queue-dragging');queueSignature='';if(state)renderQueue();
}
async function moveQueueTask(id,before){
  queueMovePending=true;
  try{await api('reorder',{id,before});applyState(await api('state'));toast('Queue order saved.');}
  catch(error){toast(error.message,true);}
  finally{queueMovePending=false;queueSignature='';if(state)renderQueue();}
}
for(const container of [$('queue-detail'),$('tray-jobs')]){
  container.addEventListener('pointerdown',event=>{
    const handle=event.target.closest('.drag-handle'),row=event.target.closest('[data-queue-job]');
    if(!row||row.dataset.movable!=='true'||queueMovePending||event.button!==0)return;
    if(!handle&&event.target.closest('button,input,select,textarea,a,label,[contenteditable]'))return;
    if(handle)event.preventDefault();row.setPointerCapture(event.pointerId);
    draggedJob=row.dataset.queueJob;queuePointer={id:draggedJob,x:event.clientX,y:event.clientY,moved:false,allowed:false,before:null,pointer:event.pointerId};
  });
}
document.addEventListener('pointermove',event=>{
  const gesture=queuePointer;if(!gesture||event.pointerId!==gesture.pointer)return;
  if(!gesture.moved&&Math.hypot(event.clientX-gesture.x,event.clientY-gesture.y)<5)return;
  event.preventDefault();
  gesture.moved=true;document.body.classList.add('queue-dragging');
  document.querySelectorAll('[data-queue-job]').forEach(row=>row.classList.toggle('dragging',row.dataset.queueJob===draggedJob));
  document.querySelectorAll('.drop-before,.drop-after').forEach(e=>e.classList.remove('drop-before','drop-after'));
  const hit=document.elementFromPoint(event.clientX,event.clientY),container=hit?.closest('#queue-detail,#tray-jobs'),row=hit?.closest('[data-queue-job]');
  gesture.allowed=!!container&&row?.dataset.movable!=='false';gesture.before=null;
  if(!gesture.allowed)return;
  if(container){const rect=container.getBoundingClientRect();if(event.clientY<rect.top+30)container.scrollTop-=12;else if(event.clientY>rect.bottom-30)container.scrollTop+=12;}
  if(row){
    gesture.before=row.dataset.queueJob;
    const after=event.clientY>=row.getBoundingClientRect().top+row.getBoundingClientRect().height/2;
    if(after){let next=row.nextElementSibling;while(next&&(next.dataset.movable!=='true'||next.dataset.queueJob===draggedJob))next=next.nextElementSibling;gesture.before=next?.dataset.queueJob||null;}
    if(row.dataset.queueJob!==draggedJob)row.classList.add(after?'drop-after':'drop-before');
  }
});
document.addEventListener('pointerup',event=>{
  const gesture=queuePointer;if(!gesture||gesture.pointer!==event.pointerId)return;
  clearQueueGesture();if(gesture.moved&&gesture.allowed&&gesture.before!==gesture.id)moveQueueTask(gesture.id,gesture.before);
});
document.addEventListener('pointercancel',()=>{if(queuePointer)clearQueueGesture();});
