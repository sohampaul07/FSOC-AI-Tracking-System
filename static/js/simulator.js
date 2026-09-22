(() => {
  const canvas = document.getElementById('cameraCanvas');
  const stage = document.getElementById('camera');
  const ctx = canvas?.getContext('2d');
  const startBtn = document.getElementById('startBtn');
  const autoBtn = document.getElementById('autoBtn');
  const centerBtn = document.getElementById('centerBtn');
  const resetBtn = document.getElementById('resetBtn');
  if (!canvas || !ctx || !startBtn || !autoBtn || !centerBtn || !resetBtn) return;

  const W = canvas.width, H = canvas.height;
  let sessionId = null, tracking = false, autoMode = false, timer = null, busy = false;
  let target = {x:810, y:170}, lastDetection = null, samples = 0;
  const $ = id => document.getElementById(id);
  const txt = (id,v) => { const e=$(id); if(e) e.textContent=v; };

  function drawScene(){
    ctx.clearRect(0,0,W,H);
    const bg=ctx.createLinearGradient(0,0,0,H); bg.addColorStop(0,'#06111f'); bg.addColorStop(1,'#0b1c2d'); ctx.fillStyle=bg; ctx.fillRect(0,0,W,H);
    ctx.strokeStyle='rgba(90,160,200,.12)'; ctx.lineWidth=1;
    for(let x=0;x<=W;x+=50){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke()}
    for(let y=0;y<=H;y+=50){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke()}
    ctx.strokeStyle='rgba(95,224,255,.55)'; ctx.setLineDash([8,8]);
    ctx.beginPath();ctx.moveTo(W/2,0);ctx.lineTo(W/2,H);ctx.stroke();
    ctx.beginPath();ctx.moveTo(0,H/2);ctx.lineTo(W,H/2);ctx.stroke();ctx.setLineDash([]);
    ctx.strokeStyle='rgba(255,255,255,.6)'; ctx.beginPath();ctx.arc(W/2,H/2,38,0,Math.PI*2);ctx.stroke();
    ctx.fillStyle='rgba(255,255,255,.55)';ctx.font='600 10px Arial';ctx.fillText('OPTICAL AXIS',W/2+44,H/2-8);ctx.fillText('CENTER / BORESIGHT',W/2+44,H/2+8);
    const glow=ctx.createRadialGradient(target.x,target.y,2,target.x,target.y,75);glow.addColorStop(0,'rgba(102,229,255,.8)');glow.addColorStop(1,'rgba(102,229,255,0)');ctx.fillStyle=glow;ctx.beginPath();ctx.arc(target.x,target.y,75,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#8de8ff';ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(target.x,target.y,27,0,Math.PI*2);ctx.fill();ctx.stroke();
    ctx.fillStyle='#0a2130';ctx.fillRect(target.x-12,target.y-9,24,18);ctx.fillStyle='#bff7ff';ctx.fillRect(target.x-8,target.y-6,16,12);
    ctx.font='600 14px Arial';ctx.fillStyle='#d9f4ff';ctx.fillText('FSOC TERMINAL',target.x-60,target.y+53);
    if(lastDetection?.found){const b=lastDetection.box;ctx.strokeStyle='#55f2a7';ctx.lineWidth=3;ctx.strokeRect(b.x,b.y,b.w,b.h);ctx.fillStyle='#55f2a7';ctx.fillRect(b.x,b.y-24,130,22);ctx.fillStyle='#052319';ctx.font='700 12px Arial';ctx.fillText(`AI TARGET ${lastDetection.confidence.toFixed(0)}%`,b.x+7,b.y-9)}
  }

  function placeBox(d){
    const b=$('detectionBox'); if(!b||!stage)return;
    const r=stage.getBoundingClientRect();
    b.style.left=`${d.box.x/W*r.width}px`; b.style.top=`${d.box.y/H*r.width*(H/W)}px`;
    b.style.width=`${d.box.w/W*r.width}px`; b.style.height=`${d.box.h/H*r.width*(H/W)}px`;
    b.style.display=d.found?'block':'none';
  }
  function direction(g){
    ['leftDir','rightDir','upDir','downDir'].forEach(i=>$(i)?.classList.remove('on'));
    if(g.includes('LEFT'))$('leftDir')?.classList.add('on'); if(g.includes('RIGHT'))$('rightDir')?.classList.add('on');
    if(g.includes('UP'))$('upDir')?.classList.add('on'); if(g.includes('DOWN'))$('downDir')?.classList.add('on');
  }
  function stageRender(status){
    ['coarseStage','fineStage','lockStage'].forEach(id=>$(id)?.classList.remove('active','current'));
    if(status==='SEARCHING') $('coarseStage')?.classList.add('current');
    if(status==='COARSE ALIGNMENT') $('coarseStage')?.classList.add('current');
    if(status==='FINE ALIGNMENT') { $('coarseStage')?.classList.add('active'); $('fineStage')?.classList.add('current'); }
    if(status==='FINE ALIGNED') { $('coarseStage')?.classList.add('active'); $('fineStage')?.classList.add('active'); $('lockStage')?.classList.add('current'); }
  }
  function render(d,det){
    txt('xValue',d.x.toFixed(1)); txt('yValue',d.y.toFixed(1));
    txt('hValue',`${d.h_error>=0?'+':'−'}${Math.abs(d.h_error).toFixed(2)}°`);
    txt('vValue',`${d.v_error>=0?'+':'−'}${Math.abs(d.v_error).toFixed(2)}°`);
    txt('totalValue',`${d.total_error.toFixed(2)}°`); txt('confidenceValue',`${d.confidence.toFixed(1)}%`); txt('confidenceBarText',`${d.confidence.toFixed(1)}%`); $('confidenceBar').style.width=`${d.confidence}%`;
    txt('alignmentStatus',d.status); txt('detectorState',`AI DETECTOR: LOCK ${d.confidence.toFixed(0)}%`); txt('trackingState','TRACK: ACTIVE'); txt('cameraMode',autoMode?'AUTO AI TRACKING':'AI TRACKING'); txt('detectBadge','TARGET LOCKED'); $('detectBadge').className='status-pill success';
    const achieved=d.status==='FINE ALIGNED';
    txt('guideBanner',achieved?'✓ FINE ALIGNMENT LOCKED':`AI POINTING: ${d.guidance}`);
    txt('guidanceText',achieved?'FINE ALIGNMENT LOCKED':d.guidance); txt('guidanceArrow',d.arrow);
    txt('guidanceSub',achieved?'Target is centered inside the ±0.5° fine-lock gate.':d.status==='FINE ALIGNMENT'?'Coarse gate passed. Use the smaller movement indicated by the AI for fine alignment.':'Move the optical axis in the highlighted direction(s).');
    direction(d.guidance); stageRender(d.status);
    txt('statusDescription',achieved?'Fine alignment complete. Optical axis is effectively centered.':d.status==='FINE ALIGNMENT'?'Coarse alignment achieved. Continue small corrections until ≤ 0.5°.':d.status==='COARSE ALIGNMENT'?'Target is detected. Reduce the large H/V error until the ≤ 2° coarse gate is crossed.':'AI target lock is active; H/V angular errors drive the movement instruction.');
    $('sessionDot').className='dot live'; txt('sessionLabel',`#${sessionId} · ${autoMode?'AUTO':'MANUAL'} · RUNNING`); txt('sampleCount',`${samples} sample${samples===1?'':'s'}`);
    $('thresholdMarker').style.left=`${Math.min(95,Math.max(5,d.total_error/10*100))}%`;
    lastDetection=det; placeBox(det); drawScene();
  }
  function log(d){
    const body=$('liveRows'); if(samples===1)body.innerHTML='';
    const tr=document.createElement('tr'); const c=d.status==='FINE ALIGNED'?'success':d.status==='FINE ALIGNMENT'?'success':'warn';
    tr.innerHTML=`<td>${new Date().toLocaleTimeString()}</td><td>${d.h_error>=0?'+':''}${d.h_error.toFixed(2)}°</td><td>${d.v_error>=0?'+':''}${d.v_error.toFixed(2)}°</td><td><strong>${d.total_error.toFixed(2)}°</strong></td><td>${d.guidance}</td><td><span class="status-pill ${c}">${d.status}</span></td>`;
    body.prepend(tr); while(body.children.length>8)body.lastChild.remove();
  }
  async function json(url,opt={}){const r=await fetch(url,opt);let d;try{d=await r.json()}catch{throw new Error(`Server returned ${r.status}`)}if(!r.ok||d.success===false)throw new Error(d.error||`Request failed (${r.status})`);return d;}
  async function start(mode){const d=await json('/api/session/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});sessionId=d.session.id;target={x:d.session.target_x??810,y:d.session.target_y??170};samples=0;$('liveRows').innerHTML='<tr><td colspan="6" class="empty">AI detector initializing...</td></tr>';tracking=true;stage.classList.add('interactive');return d;}
  async function autoTick(){if(!tracking||!autoMode||busy)return;busy=true;try{const d=await json(`/api/session/${sessionId}/auto-tick`,{method:'POST'});target=d.target; samples=d.samples; render(d.reading,d.detection); log(d.reading);if(d.complete) await stop();}catch(e){console.error(e);await stop(false)}finally{busy=false}}
  async function manualTick(){if(!tracking||autoMode||busy)return;busy=true;try{const d=await json(`/api/session/${sessionId}/reading`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:target.x,y:target.y})});samples=d.samples;render(d.reading,d.detection);log(d.reading)}catch(e){console.error(e)}finally{busy=false}}
  async function centerStep(){if(!tracking||autoMode||busy)return;busy=true;try{const d=await json(`/api/session/${sessionId}/center-step`,{method:'POST'});target=d.target;samples=d.samples;render(d.reading,d.detection);log(d.reading)}catch(e){alert(e.message)}finally{busy=false}}
  async function stop(close=true){if(timer){clearInterval(timer);timer=null}if(sessionId&&close){try{await json(`/api/session/${sessionId}/stop`,{method:'POST'})}catch(e){console.error(e)}}tracking=false;autoMode=false;stage.classList.remove('interactive');txt('startBtn','▶ Start AI Tracking');txt('autoBtn','✦ Auto Demo');txt('sessionLabel',sessionId?`#${sessionId} · STOPPED`:'READY');$('sessionDot').className='dot neutral';txt('trackingState','TRACK: IDLE');}

  startBtn.addEventListener('click',async()=>{if(tracking){await stop();return}try{autoMode=false;await start('MANUAL');txt('startBtn','■ Stop Tracking');await manualTick();timer=setInterval(manualTick,650)}catch(e){alert(e.message)}});
  autoBtn.addEventListener('click',async()=>{if(autoMode){await stop();return}try{if(tracking)await stop();autoMode=true;await start('AUTO');txt('startBtn','■ Stop Tracking');txt('autoBtn','■ Stop Auto Demo');await autoTick();timer=setInterval(autoTick,650)}catch(e){autoMode=false;tracking=false;alert(e.message)}});
  centerBtn.addEventListener('click',centerStep);
  canvas.addEventListener('click',async(e)=>{
    if(!tracking||autoMode)return;
    const r=canvas.getBoundingClientRect(); target={x:Math.max(0,Math.min(W,(e.clientX-r.left)/r.width*W)),y:Math.max(0,Math.min(H,(e.clientY-r.top)/r.height*H))}; drawScene(); await manualTick();
  });
  resetBtn.addEventListener('click',async()=>{await stop();sessionId=null;samples=0;target={x:810,y:170};lastDetection=null;drawScene();$('detectionBox').style.display='none';txt('sessionLabel','READY');txt('cameraMode','STANDBY');txt('detectorState','AI DETECTOR: STANDBY');txt('trackingState','TRACK: IDLE');txt('detectBadge','STANDBY');$('detectBadge').className='status-pill neutral';txt('alignmentStatus','READY');txt('guideBanner','Start AI Tracking to detect the terminal');txt('guidanceText','CENTER TARGET');txt('guidanceArrow','+');txt('guidanceSub','The AI system will tell the operator how to move the optical axis.');txt('xValue','—');txt('yValue','—');txt('hValue','—');txt('vValue','—');txt('totalValue','—');txt('confidenceValue','—');txt('confidenceBarText','—');$('confidenceBar').style.width='0%';$('liveRows').innerHTML='<tr><td colspan="6" class="empty">No AI measurements yet.</td></tr>';txt('sampleCount','0 samples');stageRender('READY');});
  window.addEventListener('resize',()=>{drawScene();if(lastDetection)placeBox(lastDetection)}); drawScene();
})();
