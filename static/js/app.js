const $=id=>document.getElementById(id); let poll=null; let errSeries=[]; let commandSeries=[];

async function logEvent(category,message,severity='INFO',sessionId=null){
    try{
        await api('/api/events/log',{
            method:'POST',
            body:JSON.stringify({
                category:category,
                message:message,
                severity:severity,
                session_id:sessionId
            })
        });
    }catch(error){
        console.error('Event logging failed:',error);
    }
}
async function api(url,opt={}){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...opt}); if(!r.ok)throw new Error(await r.text()); return r.json()}

function setText(id,v){if($(id))$(id).textContent=v}
async function startTracking(mode='auto-align'){
    try{
        const scenario=window.currentScenario||'Nominal Orbital';

        const result=await api('/api/session/start',{
            method:'POST',
            body:JSON.stringify({
                mode:mode,
                scenario:scenario
            })
        });

        await logEvent(
            'SYSTEM',
            `Tracking session started · ${mode.toUpperCase()} · ${scenario}`,
            'SUCCESS',
            result.session_id
        );

        beginPoll();
    }catch(error){
        console.error(error);
    }
}
function startAuto(){startTracking('auto-align')}
async function stopTracking(){
    try{
        const result=await api('/api/session/stop',{
            method:'POST'
        });

        if(poll){
            clearInterval(poll);
            poll=null;
        }

        setText('trackingPill','STOPPED');

        await logEvent(
            'SYSTEM',
            'Tracking session stopped by operator',
            'INFO',
            result.session_id
        );
    }catch(error){
        console.error(error);
    }
}
async function centerTarget(){
    try{
        const result=await api('/api/session/center',{
            method:'POST'
        });

        await logEvent(
            'ALIGNMENT',
            'Operator commanded Center Target · alignment correction initiated',
            'INFO',
            result.session_id
        );

        beginPoll();
    }catch(error){
        console.error(error);
    }
}
async function reacquire(){
    try{
        const result=await api('/api/session/reacquire',{
            method:'POST'
        });

        await logEvent(
            'TRACKING',
            'Target reacquisition sequence started by operator',
            'WARNING',
            result.session_id
        );

        beginPoll();
    }catch(error){
        console.error(error);
    }
}
async function manualCommand(c){
    try{
        const result=await api('/api/session/manual-command',{
            method:'POST',
            body:JSON.stringify({
                command:c,
                step:0.5
            })
        });

        await logEvent(
            'TRACKING',
            `Manual gimbal command executed · ${c}`,
            'INFO',
            result.session_id
        );

        beginPoll();
    }catch(error){
        console.error(error);
    }
}
function beginPoll(){if(poll)clearInterval(poll); fetchState(); poll=setInterval(fetchState,900)}
async function fetchState(){try{const d=await api('/api/state'); if(d.error)return; renderState(d)}catch(e){console.error(e)}}
function renderState(d){
 setText('tx',d.target.x+' px');setText('ty',d.target.y+' px');setText('hErr',fmt(d.h_error));setText('vErr',fmt(d.v_error));setText('totalErr',d.total_error.toFixed(2)+'°');setText('az',fmt(d.azimuth));setText('el',fmt(d.elevation));setText('conf',d.confidence+'%');setText('signal',d.signal_dbm+' dBm');setText('score',d.alignment_score+'%');setText('phasePill',d.phase);setText('commandPill',d.command);setText('guidanceText',d.command==='HOLD'?'AI HOLD · Target centered':'AI COMMAND · '+d.command);
 setText('trackingPill','TRACKING');setText('stDetection','LOCKED');setText('stAcq',d.phase==='SEARCHING'?'SEARCHING':'COMPLETE');setText('stCoarse',d.total_error<=2?'PASSED':'ACTIVE');setText('stFine',d.total_error<=.5?'LOCKED':d.total_error<=2?'ACTIVE':'STANDBY');setText('stLock',d.fine_locked?'YES':'NO');setText('stMode',d.mode.toUpperCase());setText('targetPill',d.fine_locked?'FINE LOCK':'DETECTED');setText('alignPhase',d.phase);setText('alignTotal',d.total_error.toFixed(2)+'°');setText('alignScore',d.alignment_score+'%');setText('alignBar',d.alignment_score+'%'); if($('alignBar'))$('alignBar').style.width=d.alignment_score+'%';
 setText('acqScore',d.confidence+'%');setText('coarseScore',d.total_error<=2?'PASSED':'ACTIVE');setText('fineScore',d.total_error<=.5?'LOCKED':d.total_error<=2?'ACTIVE':'WAITING');setText('lockScore',d.fine_locked?'100%':'—');
 setText('sideTarget',d.fine_locked?'FINE LOCK':d.locked?'LOCKED':'TRACKING');setText('sideTracking',d.mode.toUpperCase());setText('topConfidence',d.confidence+'%');setText('topScore',d.alignment_score+'%');setText('topSignal',d.signal_dbm+' dBm');setText('dashAI',d.confidence+'%');setText('dashTarget',d.fine_locked?'FINE LOCK':d.locked?'LOCKED':'TRACKING');setText('dashScore',d.alignment_score+'%');setText('dashController',d.mode==='auto-align'?'AUTO CLOSED-LOOP':'MANUAL');setText('dashCoarse',d.total_error<=2?'PASSED':'ACTIVE');setText('dashFine',d.total_error<=.5?'LOCKED':d.total_error<=2?'ACTIVE':'STANDBY');
 const sat=$('satellite'), box=$('bbox'), cam=$('camera'); if(sat&&cam){const cw=cam.clientWidth,ch=cam.clientHeight;const px=(d.target.x/1280)*cw,py=(d.target.y/720)*ch;sat.style.left=(px-85)+'px';sat.style.top=(py-60)+'px';box.style.left=(px-105)+'px';box.style.top=(py-80)+'px'}
 errSeries.push(d.total_error); if(errSeries.length>90)errSeries.shift(); drawLine('errorChart',errSeries); commandSeries.unshift({c:d.command,t:new Date().toLocaleTimeString()}); if(commandSeries.length>8)commandSeries.pop(); renderCommands(); phaseActive(d.phase);
}
function fmt(v){return (v>=0?'+':'')+v.toFixed(2)+'°'}
function phaseActive(p){['phaseSearch','phaseAcquire','phaseCoarse','phaseFine','phaseLock'].forEach(id=>$(id)?.classList.remove('active','locked'));let ids=p==='SEARCHING'?['phaseSearch']:p==='ACQUISITION'?['phaseSearch','phaseAcquire']:p==='COARSE ALIGNMENT'?['phaseSearch','phaseAcquire','phaseCoarse']:p==='FINE ALIGNMENT'?['phaseSearch','phaseAcquire','phaseCoarse','phaseFine']:['phaseSearch','phaseAcquire','phaseCoarse','phaseFine','phaseLock'];ids.forEach(id=>$(id)?.classList.add(p==='FINE LOCK'?'locked':'active'))}
function renderCommands(){const el=$('commandHistory');if(!el)return;el.innerHTML=commandSeries.map(x=>`<div class="event-row"><span>${x.t}</span><b>AI CONTROLLER</b><span>${x.c}</span><span class="green-text">EXECUTED</span></div>`).join('')}
function drawLine(id,data){const c=$(id);if(!c)return;const ctx=c.getContext('2d'),w=c.clientWidth*devicePixelRatio,h=c.height*devicePixelRatio;c.width=w;c.height=h;ctx.clearRect(0,0,w,h);ctx.strokeStyle='#dbe3ee';ctx.lineWidth=1;for(let i=1;i<5;i++){let y=h*i/5;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}if(data.length<2)return;const max=Math.max(2,...data),min=0;ctx.strokeStyle='#1769e0';ctx.lineWidth=2;ctx.beginPath();data.forEach((v,i)=>{const x=i/(data.length-1)*w,y=h-(v-min)/(max-min)*h*.82-h*.05;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke()}
async function initDashboard(){const d=await api('/api/dashboard');setText('dashSessions',d.sessions);setText('dashAI',Number(d.ai_confidence).toFixed(1)+'%');setText('dashScore',Number(d.alignment_score).toFixed(1)+'%');renderRecent(d.recent_events);const a=await api('/api/analytics');drawLine('dashChart',a.recent_error.map(x=>x.v))}
function renderRecent(rows){const e=$('recentEvents');if(e)e.innerHTML=rows.map(x=>`<div class="event-row"><span>${x.time}</span><b>${x.category}</b><span>${x.message}</span><span>${x.severity}</span></div>`).join('')}
function initLiveTracking(){beginPoll()}

async function initAnalytics(){const d=await api('/api/analytics');setText('aSessions',d.kpi.sessions);setText('aSamples',d.kpi.samples);setText('aError',d.kpi.avg_error+'°');setText('aLock',d.kpi.fine_lock_rate+'%');drawLine('analyticsChart',d.recent_error.map(x=>x.v));bars('phaseBars',d.phase_counts);bars('commandBars',d.commands);const st=$('scenarioTable');st.innerHTML=Object.entries(d.scenarios).map(([k,v])=>`<div class="bar-row"><span>${k}</span><div class="bar"><i style="width:${Math.min(100,v.avg_error*10)}%"></i></div><b>${v.avg_error}°</b></div>`).join('')}
function bars(id,obj){const el=$(id);if(!el)return;const max=Math.max(1,...Object.values(obj));el.innerHTML=Object.entries(obj).map(([k,v])=>`<div class="bar-row"><span>${k}</span><div class="bar"><i style="width:${v/max*100}%"></i></div><b>${v}</b></div>`).join('')}
async function initReports(){
  await Promise.all([loadSimulatedReports(),loadLiveReports(),loadScenarioReports()]);
}
function switchReportTab(tab){
  document.querySelectorAll('.report-tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  ['simulated','live','scenarios'].forEach(t=>{
    const p=$('reportPanel'+t.charAt(0).toUpperCase()+t.slice(1));
    if(p)p.classList.toggle('active',t===tab);
  });
}
function reportEsc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function reportDate(v){return v?new Date(v).toLocaleString():'—'}
async function loadSimulatedReports(){
  const a=await api('/api/reports/simulated');
  const list=$('simReportList'), k=$('simReportKpis');
  const samples=a.reduce((n,x)=>n+(x.samples||0),0);
  const avg=a.length?a.reduce((n,x)=>n+(x.avg_error||0),0)/a.length:0;
    k.innerHTML=`<div class="report-kpi"><small>Stored Sessions</small><b>${a.length}</b></div><div class="report-kpi"><small>Total Samples</small><b>${samples}</b></div><div class="report-kpi"><small>Avg Session Error</small><b>${avg.toFixed(2)}°</b></div><div class="report-kpi"><small>Peak Confidence</small><b>${a.length?Math.max(...a.map(x=>x.peak_confidence||0)).toFixed(1):'0.0'}%</b></div>`;
  if(!a.length){list.innerHTML='<div class="report-empty">No simulated tracking session has been stored yet. Start the Simulated Scenario Camera from Live Tracking.</div>';return}
  list.innerHTML=a.map(x=>`<div class="report-row">
    <div class="report-main"><b>Simulated Camera Run #${x.id} · ${reportEsc(x.target_id)}</b><small>${reportDate(x.started)}${x.ended?' → '+reportDate(x.ended):' · ACTIVE'} · ${reportEsc(x.status)}</small></div>
    <div class="report-stat"><small>Samples</small><b>${x.samples}</b></div>
    <div class="report-stat"><small>Avg Error</small><b>${Number(x.avg_error||0).toFixed(2)}°</b></div>
    <div class="report-stat"><small>Max Error</small><b>${Number(x.max_error||0).toFixed(2)}°</b></div>
    <div class="report-stat"><small>Confidence</small><b>${Number(x.peak_confidence||0).toFixed(1)}%</b></div>
    <div class="report-actions"><button class="btn btn-sm btn-outline-primary" onclick="downloadReport('${x.download_url}')">⇩ PDF</button></div>
  </div>`).join('');
}
async function loadLiveReports(){
  const a=await api('/api/reports/live');
  const list=$('liveReportList'), k=$('liveReportKpis');
  const detections=a.reduce((n,x)=>n+(x.detection_count||0),0);
  const completed=a.filter(x=>x.status==='COMPLETED').length;
  k.innerHTML=`<div class="report-kpi"><small>Stored Camera Runs</small><b>${a.length}</b></div><div class="report-kpi"><small>Detections Stored</small><b>${detections}</b></div><div class="report-kpi"><small>Completed Runs</small><b>${completed}</b></div><div class="report-kpi"><small>Pipeline</small><b>${a.length?'CONNECTED':'READY'}</b></div>`;
  if(!a.length){list.innerHTML='<div class="report-empty">No Live AI Camera run has been stored yet. Start Live AI Camera from Live Tracking.</div>';return}
  list.innerHTML=a.map(x=>`<div class="report-row">
    <div class="report-main"><b>Live Camera Run #${x.id}</b><small>${reportDate(x.started)}${x.ended?' → '+reportDate(x.ended):' · ACTIVE'}</small></div>
    <div class="report-stat"><small>Detector</small><b>${reportEsc(x.detector)}</b></div>
    <div class="report-stat"><small>Camera</small><b>${reportEsc(x.camera_mode)}</b></div>
    <div class="report-stat"><small>Detections</small><b>${x.detection_count||0}</b></div>
    <div class="report-stat"><small>Status</small><b>${reportEsc(x.status)}</b></div>
    <div class="report-actions"><button class="btn btn-sm btn-outline-primary" onclick="downloadReport('${x.download_url}')">⇩ PDF</button></div>
  </div>`).join('');
}
async function loadScenarioReports(){
  const a=await api('/api/reports/scenarios');
  const el=$('scenarioReportList');
  if(!a.length){el.innerHTML='<div class="report-empty">No scenario reports available.</div>';return}
  el.innerHTML=a.map(x=>`<div class="scenario-report-group">
    <div class="scenario-report-group-head">
      <div><b>${reportEsc(x.scenario)}</b><span>${reportEsc(x.description)}</span></div>
      <div class="scenario-group-meta">${x.sessions} SESSION${x.sessions===1?'':'S'} · ${x.samples} SAMPLES</div>
    </div>
    <div class="scenario-session-list">
      ${x.session_reports.length ? x.session_reports.map(r=>`<div class="scenario-session-row">
        <div class="report-main"><b>Session #${r.session_id}</b><small>${reportDate(r.started)}${r.ended?' → '+reportDate(r.ended):' · ACTIVE'} · ${reportEsc(r.status)}</small></div>
        <div class="report-stat"><small>Samples</small><b>${r.samples}</b></div>
        <div class="report-stat"><small>Avg Error</small><b>${Number(r.avg_error||0).toFixed(2)}°</b></div>
        <div class="report-stat"><small>Max Error</small><b>${Number(r.max_error||0).toFixed(2)}°</b></div>
        <div class="report-stat"><small>Confidence</small><b>${Number(r.peak_confidence||0).toFixed(1)}%</b></div>
        <div class="report-actions"><button class="btn btn-sm btn-outline-primary" onclick="downloadReport('${r.download_url}')">⇩ PDF</button></div>
      </div>`).join('') : '<div class="report-empty">No session recorded for this scenario yet.</div>'}
    </div>
  </div>`).join('');
}
function downloadReport(url){window.location.href=url}
function previewReport(url,title){
  $('reportPdfTitle').textContent=title||'REPORT PREVIEW';
  $('reportPdfFrame').src=url+'?preview='+Date.now();
  $('reportPdfModal').style.display='flex';
}
function closeReportPdf(){if($('reportPdfModal'))$('reportPdfModal').style.display='none';if($('reportPdfFrame'))$('reportPdfFrame').src=''}

let eventLogTimer=null;

function initEvents(){
    loadEvents();

    if(eventLogTimer){
        clearInterval(eventLogTimer);
    }

    eventLogTimer=setInterval(()=>{
        loadEvents();
    },2000);
}

async function loadEvents(){
    try{
        const q=encodeURIComponent(
            $('eventSearch')?.value||''
        );

        const c=encodeURIComponent(
            $('eventCategory')?.value||'ALL'
        );

        const events=await api(
            '/api/events?q='+q+'&category='+c+'&limit=500'
        );

        const list=$('eventList');

        if(!list) return;

        if(!events.length){
            list.innerHTML=
                '<div class="muted">No events recorded.</div>';
            return;
        }

        list.innerHTML=events.map(x=>`
            <div class="event-row">
                <span>${x.time}</span>
                <b>${x.category}</b>
                <span>${x.message}</span>
                <span>${x.severity}</span>
            </div>
        `).join('');

    }catch(error){
        console.error('Event Log loading failed:',error);
    }
}

async function setScenario(s){
    try{
        window.currentScenario=s;

        const result=await api('/api/scenario',{
            method:'POST',
            body:JSON.stringify({
                scenario:s
            })
        });

        setText('scenarioLive',s);

        await logEvent(
            'SYSTEM',
            `Scenario changed to ${s}`,
            'INFO',
            result.session_id
        );

        startAuto();
    }catch(error){
        console.error(error);
    }
}
