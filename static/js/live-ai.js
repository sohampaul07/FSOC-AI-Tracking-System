/* =========================================================
   PHYSICAL WEBCAM LIVE AI CAMERA
   YOLO + ByteTrack with OpenCV motion fallback

   Tracking Error vs Time graph
   ========================================================= */

(function(){

  const $ = id => document.getElementById(id);

  let socket = null;
  let initialized = false;
  let running = false;

  const MAX = 60;

  const errors = [];
  const labels = [];


  /* =========================================================
     TRACKING MODE SWITCH
     ========================================================= */

  window.showTrackingMode = function(mode){

    const sim = $('simPanel');
    const live = $('liveAiPanel');
    const tabSim = $('tabSim');
    const tabLive = $('tabLive');

    if(!sim || !live){
      return;
    }


    if(mode === 'live'){

      sim.style.display = 'none';

      live.style.display = 'block';


      if(tabSim){
        tabSim.classList.remove('active');
      }

      if(tabLive){
        tabLive.classList.add('active');
      }


      initLiveAI();


      setTimeout(function(){

        updateChartTitle();
        drawChart();
        resizeLiveOverlay();

      },80);


    }else{

      sim.style.display = 'block';

      live.style.display = 'none';


      if(tabLive){
        tabLive.classList.remove('active');
      }

      if(tabSim){
        tabSim.classList.add('active');
      }

    }

  };


  /* =========================================================
     COMPATIBILITY INITIALIZER
     ========================================================= */

  window.initLiveTracking = function(){

    const sim = $('simPanel');
    const live = $('liveAiPanel');
    const tabSim = $('tabSim');
    const tabLive = $('tabLive');


    if(sim){
      sim.style.display = 'block';
    }

    if(live){
      live.style.display = 'none';
    }

    if(tabSim){
      tabSim.classList.add('active');
    }

    if(tabLive){
      tabLive.classList.remove('active');
    }


    initLiveAI();

  };


  /* =========================================================
     SMALL DOM HELPERS
     ========================================================= */

  function text(id,v){

    const e = $(id);

    if(e){
      e.textContent = v;
    }

  }


  function badge(id,v){

    text(id,v);

  }


  /* =========================================================
     INITIALIZE LIVE AI
     ========================================================= */

  function initLiveAI(){

    updateChartTitle();


    if(initialized){

      loadStatus();

      return;

    }


    initialized = true;


    if(typeof io === 'undefined'){

      text(
        'liveEmptyMsg',
        'Socket.IO client failed to load. Check internet connection or the Socket.IO script.'
      );

      return;

    }


    socket = io();


    /* Tracking telemetry */
    socket.on(
      'tracking_update',
      update
    );


    /* Live safety alerts */
    socket.on(
      'live_alert',
      a => renderAlert(a,false)
    );


    /* Load current camera status */
    loadStatus();


    /* Load historical tracking error data */
    fetch(
      '/api/live/history?limit=' + MAX
    )

    .then(r => r.json())

    .then(rows => {

      rows.forEach(r => {

        push(
          r.t,
          r.total_error
        );

      });


      drawChart();

    })

    .catch(() => {});


    /* Load previous alerts */
    fetch(
      '/api/live/alerts?limit=20'
    )

    .then(r => r.json())

    .then(rows => {

      rows
        .reverse()
        .forEach(
          a => renderAlert(a,true)
        );

    })

    .catch(() => {});


    setTimeout(
      resizeLiveOverlay,
      100
    );

  }


  /* =========================================================
     CAMERA STATUS
     ========================================================= */

  function loadStatus(){

    fetch('/api/live/status')

      .then(r => r.json())

      .then(s => {

        badge(
          'liveCameraModeBadge',
          'CAMERA: ' +
          String(
            s.camera_mode || 'OFFLINE'
          ).toUpperCase()
        );


        badge(
          'liveDetectorBadge',
          'DETECTOR: ' +
          String(
            s.detector || '—'
          ).toUpperCase()
        );


        badge(
          'liveRunBadge',
          s.running
            ? 'RUNNING'
            : 'STOPPED'
        );


        if(
          s.camera_error &&
          !s.running
        ){

          text(
            'liveEmptyMsg',
            'Camera ready check: ' +
            s.camera_error
          );

        }


        running = !!s.running;


        if(running){

          const empty = $('liveEmptyMsg');

          if(empty){
            empty.style.display = 'none';
          }

        }

      })

      .catch(() => {});

  }


  /* =========================================================
     START LIVE AI
     ========================================================= */

  window.startLiveAI = function(){

    fetch(
      '/api/live/start',
      {
        method:'POST'
      }
    )

    .then(async r => {

      const s = await r.json();


      if(
        !r.ok ||
        !s.ok
      ){

        throw new Error(
          s.error ||
          'Unable to open the webcam'
        );

      }


      running = true;


      const img =
        $('liveFeedImg');


      if(img){

        img.src =
          '/video_feed?t=' +
          Date.now();


        img.onload = function(){

          resizeLiveOverlay();

          drawChart();

        };

      }


      const empty =
        $('liveEmptyMsg');


      if(empty){

        empty.style.display =
          'none';

      }


      badge(
        'liveRunBadge',
        'RUNNING'
      );


      const assistantStatus =
        $('assistantStatus');


      if(assistantStatus){

        assistantStatus.textContent =
          'WAITING';

        assistantStatus.style.color =
          '#1769e0';

      }


      badge(
        'liveDetectorBadge',
        'DETECTOR: ' +
        String(
          s.detector || '—'
        ).toUpperCase()
      );


      badge(
        'liveCameraModeBadge',
        'CAMERA: ' +
        String(
          s.camera_mode || '—'
        ).toUpperCase()
      );


      updateAssistant({
        found:false
      });


      updateChartTitle();

      drawChart();

    })


    .catch(e => {

      running = false;


      const empty =
        $('liveEmptyMsg');


      if(empty){

        empty.style.display =
          'flex';

        empty.textContent =
          'WEBCAM ERROR: ' +
          e.message +
          ' | Close Camera/Teams/Zoom and allow Windows camera access.';

      }


      badge(
        'liveRunBadge',
        'CAMERA ERROR'
      );


      updateAssistant({
        found:false
      });

    });

  };


  /* =========================================================
     STOP LIVE AI
     ========================================================= */

  window.stopLiveAI = function(){

    fetch(
      '/api/live/stop',
      {
        method:'POST'
      }
    )

    .finally(() => {

      running = false;


      const img =
        $('liveFeedImg');


      if(img){

        img.removeAttribute(
          'src'
        );

      }


      const empty =
        $('liveEmptyMsg');


      if(empty){

        empty.style.display =
          'flex';

        empty.textContent =
          'Click "Start Live AI Tracking" to open the physical webcam.';

      }


      badge(
        'liveRunBadge',
        'STOPPED'
      );


      clearOverlay();


      updateAssistant({
        found:false
      });


      drawChart();

    });

  };


  /* =========================================================
     TRACKING UPDATE
     ========================================================= */

  function update(d){

    if(!running){
      return;
    }


    updateAssistant(d);


    if(!d.found){

      badge(
        'livePhasePill',
        'SEARCHING'
      );


      clearOverlay();


      return;

    }


    badge(
      'livePhasePill',
      d.phase
    );


    const phasePill =
      $('livePhasePill');


    if(phasePill){

      phasePill.className =
        'pill ' +
        (
          d.phase === 'FINE LOCK'
            ? 'green'
            : d.phase &&
              d.phase.includes('ALIGNMENT')
              ? 'blue'
              : 'amber'
        );

    }


    text(
      'liveHErr',
      signed(d.h_error) + '°'
    );


    text(
      'liveVErr',
      signed(d.v_error) + '°'
    );


    text(
      'liveTotalErr',
      Number(
        d.total_error
      ).toFixed(2) + '°'
    );


    text(
      'liveConf',
      Number(
        d.confidence
      ).toFixed(1) + '%'
    );


    text(
      'liveTargetLabel',
      d.label ||
      'moving-object'
    );


    text(
      'liveTrackId',
      '#' +
      (
        d.track_id ??
        1
      )
    );


    text(
      'liveXY',
      Math.round(d.cx) +
      ' / ' +
      Math.round(d.cy) +
      ' px'
    );


    text(
      'liveOffset',
      Number(
        d.offset_px || 0
      ).toFixed(1) +
      ' px'
    );


    text(
      'liveVelocity',
      Number(
        d.velocity_px_s || 0
      ).toFixed(1) +
      ' px/s'
    );


    text(
      'liveAngularRate',
      Number(
        d.angular_velocity_deg_s || 0
      ).toFixed(3) +
      ' °/s'
    );


    text(
      'liveFPS',
      Number(
        d.fps || 0
      ).toFixed(1)
    );


    text(
      'liveSource',
      String(
        d.source || '—'
      ).toUpperCase()
    );


    drawOverlay(d);


    /* =====================================================
       TRACKING ERROR HISTORY

       total_error = distance from target to boresight
       in angular degrees.

       As AI locks onto target:
       total_error → 0°
       ===================================================== */

    push(
      new Date().toLocaleTimeString(),
      d.total_error
    );


    highlight(
      d.phase
    );

  }


  /* =========================================================
     SIGNED NUMBER
     ========================================================= */

  function signed(v){

    return (
      v >= 0
        ? '+'
        : ''
    ) +
    Number(v).toFixed(2);

  }


  /* =========================================================
     PHASE HIGHLIGHT
     ========================================================= */

  function highlight(phase){

    const legend =
      $('phaseLegend');


    if(!legend){
      return;
    }


    legend
      .querySelectorAll('.phase-chip')
      .forEach(c => {

        c.classList.toggle(
          'active',
          c.dataset.phase === phase
        );

      });

  }


  /* =========================================================
     RESIZE LIVE CAMERA OVERLAY
     ========================================================= */

  function resizeLiveOverlay(){

    const img =
      $('liveFeedImg');

    const canvas =
      $('liveOverlay');


    if(
      !img ||
      !canvas ||
      !img.clientWidth ||
      !img.clientHeight
    ){

      return;

    }


    const dpr =
      window.devicePixelRatio ||
      1;


    const w =
      img.clientWidth;


    const h =
      img.clientHeight;


    canvas.width =
      w * dpr;


    canvas.height =
      h * dpr;


    canvas.style.width =
      w + 'px';


    canvas.style.height =
      h + 'px';


    const ctx =
      canvas.getContext('2d');


    if(ctx){

      ctx.setTransform(
        dpr,
        0,
        0,
        dpr,
        0,
        0
      );

    }

  }


  /* =========================================================
     LIVE CAMERA OVERLAY
     ========================================================= */

  function drawOverlay(d){

    const img =
      $('liveFeedImg');


    const canvas =
      $('liveOverlay');


    if(
      !img ||
      !canvas ||
      !img.clientWidth ||
      !img.clientHeight
    ){

      return;

    }


    const dpr =
      window.devicePixelRatio ||
      1;


    const w =
      img.clientWidth;


    const h =
      img.clientHeight;


    canvas.width =
      w * dpr;


    canvas.height =
      h * dpr;


    canvas.style.width =
      w + 'px';


    canvas.style.height =
      h + 'px';


    const x =
      canvas.getContext('2d');


    if(!x){
      return;
    }


    x.setTransform(
      dpr,
      0,
      0,
      dpr,
      0,
      0
    );


    x.clearRect(
      0,
      0,
      w,
      h
    );


    if(
      !d ||
      !d.frame_w ||
      !d.frame_h ||
      !d.box
    ){

      return;

    }


    const sx =
      w / d.frame_w;


    const sy =
      h / d.frame_h;


    const cx =
      d.cx * sx;


    const cy =
      d.cy * sy;


    const b =
      d.box;


    const bx =
      b.x * sx;


    const by =
      b.y * sy;


    const bw =
      b.w * sx;


    const bh =
      b.h * sy;


    const cx0 =
      w / 2;


    const cy0 =
      h / 2;


    const ppd =
      w / 42;


    /* Coarse gate */

    circle(
      x,
      cx0,
      cy0,
      d.coarse_limit * ppd,
      'rgba(255,190,90,.55)'
    );


    /* Fine gate */

    circle(
      x,
      cx0,
      cy0,
      d.fine_limit * ppd,
      'rgba(120,230,180,.75)'
    );


    /* Boresight crosshair */

    x.strokeStyle =
      'rgba(220,240,255,.9)';

    x.lineWidth = 1.5;

    x.beginPath();

    x.moveTo(
      cx0 - 12,
      cy0
    );

    x.lineTo(
      cx0 + 12,
      cy0
    );

    x.moveTo(
      cx0,
      cy0 - 12
    );

    x.lineTo(
      cx0,
      cy0 + 12
    );

    x.stroke();


    /* Target → boresight line */

    x.strokeStyle =
      'rgba(230,240,250,.6)';

    x.setLineDash([
      5,
      4
    ]);

    x.beginPath();

    x.moveTo(
      cx,
      cy
    );

    x.lineTo(
      cx0,
      cy0
    );

    x.stroke();

    x.setLineDash([]);


    /* Bounding box */

    x.strokeStyle =
      d.phase === 'FINE LOCK'
        ? '#5af096'
        : d.phase &&
          d.phase.includes('ALIGNMENT')
          ? '#78b4ff'
          : '#ffbe5a';


    x.lineWidth = 2;


    x.strokeRect(
      bx,
      by,
      bw,
      bh
    );


    /* Target centre */

    x.fillStyle =
      '#fff';


    x.beginPath();

    x.arc(
      cx,
      cy,
      4,
      0,
      Math.PI * 2
    );

    x.fill();


    /* Target label */

    x.font =
      '700 11px Arial';


    x.fillText(
      '#' +
      (d.track_id ?? 1) +
      ' ' +
      (d.label || 'moving-object'),

      bx,

      Math.max(
        14,
        by - 7
      )
    );


    /* Angular tracking error */

    x.fillStyle =
      '#d9f4ff';


    x.fillText(
      Number(
        d.total_error
      ).toFixed(2) + '°',

      ((cx + cx0) / 2) + 7,

      ((cy + cy0) / 2) - 7
    );


    /* Motion vector */

    if(
      Math.abs(
        d.velocity_x_px_s || 0
      ) > 3 ||

      Math.abs(
        d.velocity_y_px_s || 0
      ) > 3
    ){

      x.strokeStyle =
        '#ffdb72';


      x.beginPath();


      x.moveTo(
        cx,
        cy
      );


      x.lineTo(
        cx +
        (d.velocity_x_px_s || 0) *
        .08,

        cy +
        (d.velocity_y_px_s || 0) *
        .08
      );


      x.stroke();

    }

  }


  /* =========================================================
     DRAW CIRCLE
     ========================================================= */

  function circle(
    c,
    x,
    y,
    r,
    color
  ){

    if(r < 2){
      return;
    }


    c.save();


    c.strokeStyle =
      color;


    c.lineWidth = 1;


    c.setLineDash([
      5,
      4
    ]);


    c.beginPath();


    c.arc(
      x,
      y,
      r,
      0,
      Math.PI * 2
    );


    c.stroke();


    c.restore();

  }


  /* =========================================================
     CLEAR OVERLAY
     ========================================================= */

  function clearOverlay(){

    const c =
      $('liveOverlay');


    if(!c){
      return;
    }


    const ctx =
      c.getContext('2d');


    if(ctx){

      ctx.clearRect(
        0,
        0,
        c.width,
        c.height
      );

    }

  }


  /* =========================================================
     ERROR HISTORY
     ========================================================= */

  function push(
    label,
    v
  ){

    labels.push(label);

    errors.push(
      Math.max(
        0,
        Number(v) || 0
      )
    );


    if(
      errors.length > MAX
    ){

      errors.shift();
      labels.shift();

    }


    drawChart();

  }


  /* =========================================================
     UPDATE GRAPH TITLE / DESCRIPTION
     ========================================================= */

  function updateChartTitle(){

    const chart =
      $('liveErrorChart');


    if(!chart){
      return;
    }


    const panel =
      chart.closest('.panel');


    if(!panel){
      return;
    }


    const heading =
      panel.querySelector('.panel-head h2');


    if(heading){

      heading.textContent =
        'Tracking Error vs Time';

    }


    /* Update existing legend */

    const legend =
      panel.querySelector('.chart-legend');


    if(legend){

      legend.innerHTML =

        '<span>' +
        '<i style="background:#1769e0"></i>' +
        'Tracking Error' +
        '</span>' +

        '<span>' +
        '<i style="background:#e08a1e"></i>' +
        'Coarse Gate · 2.0°' +
        '</span>' +

        '<span>' +
        '<i style="background:#1e9e5e"></i>' +
        'Fine Gate · 0.5°' +
        '</span>';

    }

  }


  /* =========================================================
     TRACKING ERROR VS TIME CHART
     ========================================================= */

  function drawChart(){

    const c =
      $('liveErrorChart');


    if(!c){
      return;
    }


    updateChartTitle();


    const dpr =
      window.devicePixelRatio ||
      1;


    const w =
      c.clientWidth ||
      300;


    const h =
      c.clientHeight ||
      170;


    c.width =
      w * dpr;


    c.height =
      h * dpr;


    const x =
      c.getContext('2d');


    if(!x){
      return;
    }


    x.setTransform(
      dpr,
      0,
      0,
      dpr,
      0,
      0
    );


    x.clearRect(
      0,
      0,
      w,
      h
    );


    const L = 46;
    const R = 12;
    const T = 12;
    const B = 30;


    const pw =
      w - L - R;


    const ph =
      h - T - B;


    if(
      pw < 10 ||
      ph < 10
    ){

      return;

    }


    /* =====================================================
       Y AXIS SCALE

       Keep enough headroom for live tracking error.
       The graph always includes 0°.
       ===================================================== */

    const maxData =
      errors.length
        ? Math.max(...errors)
        : 0;


    const max =
      Math.max(
        2.5,
        maxData * 1.15,
        2
      );


    /* =====================================================
       BACKGROUND
       ===================================================== */

    x.fillStyle =
      '#ffffff';


    x.fillRect(
      0,
      0,
      w,
      h
    );


    /* =====================================================
       HORIZONTAL GRID + Y AXIS LABELS
       ===================================================== */

    for(
      let i = 0;
      i <= 4;
      i++
    ){

      const value =
        max -
        (
          max * i / 4
        );


      const y =
        T +
        (
          ph * i / 4
        );


      /* Grid */

      x.strokeStyle =
        '#eef2f7';


      x.lineWidth = 1;


      x.setLineDash([]);


      x.beginPath();

      x.moveTo(
        L,
        y
      );

      x.lineTo(
        L + pw,
        y
      );

      x.stroke();


      /* Y label */

      x.fillStyle =
        '#718096';


      x.font =
        '9px Arial';


      x.textAlign =
        'right';


      x.textBaseline =
        'middle';


      x.fillText(
        value.toFixed(1) + '°',
        L - 7,
        y
      );

    }


    /* =====================================================
       ZERO ERROR LINE

       This is the ideal state:
       target exactly at camera boresight.
       ===================================================== */

    const zeroY =
      T + ph;


    x.strokeStyle =
      '#b8c5d3';


    x.lineWidth = 1;


    x.setLineDash([
      3,
      3
    ]);


    x.beginPath();

    x.moveTo(
      L,
      zeroY
    );

    x.lineTo(
      L + pw,
      zeroY
    );

    x.stroke();

    x.setLineDash([]);


    /* =====================================================
       THRESHOLD LINES
       ===================================================== */

    const thresholdLines = [
      {
        value:2,
        color:'#e08a1e',
        label:'2°'
      },
      {
        value:.5,
        color:'#1e9e5e',
        label:'0.5°'
      }
    ];


    thresholdLines.forEach(
      item => {

        if(item.value > max){
          return;
        }


        const y =
          T +
          ph -
          ph *
          (
            item.value /
            max
          );


        x.strokeStyle =
          item.color;


        x.lineWidth = 1;


        x.setLineDash([
          5,
          4
        ]);


        x.beginPath();

        x.moveTo(
          L,
          y
        );

        x.lineTo(
          L + pw,
          y
        );

        x.stroke();

        x.setLineDash([]);


        x.fillStyle =
          item.color;


        x.font =
          '700 8px Arial';


        x.textAlign =
          'left';


        x.textBaseline =
          'bottom';


        x.fillText(
          item.label,
          L + 4,
          y - 3
        );

      }
    );


    /* =====================================================
       GRAPH MAPPING
       ===================================================== */

    const yy =
      v => {

        const safe =
          Math.max(
            0,
            Math.min(
              Number(v) || 0,
              max
            )
          );


        return (
          T +
          ph -
          ph *
          (
            safe /
            max
          )
        );

      };


    const xx =
      i => {

        if(errors.length <= 1){
          return L;
        }


        return (
          L +
          pw *
          i /
          (
            errors.length - 1
          )
        );

      };


    /* =====================================================
       X AXIS
       ===================================================== */

    x.strokeStyle =
      '#cbd5e1';


    x.lineWidth = 1;


    x.setLineDash([]);


    x.beginPath();

    x.moveTo(
      L,
      T
    );

    x.lineTo(
      L,
      T + ph
    );

    x.lineTo(
      L + pw,
      T + ph
    );

    x.stroke();


    /* =====================================================
       X AXIS TIME LABELS
       ===================================================== */

    if(labels.length){

      const positions = [];


      if(labels.length === 1){

        positions.push(0);

      }else{

        positions.push(0);

        if(labels.length > 2){
          positions.push(
            Math.floor(
              (
                labels.length - 1
              ) / 2
            )
          );
        }

        positions.push(
          labels.length - 1
        );

      }


      const uniquePositions =
        [...new Set(positions)];


      uniquePositions.forEach(
        i => {

          const xpos =
            xx(i);


          x.fillStyle =
            '#718096';


          x.font =
            '8px Arial';


          x.textAlign =
            i === 0
              ? 'left'
              : i === labels.length - 1
                ? 'right'
                : 'center';


          x.textBaseline =
            'top';


          x.fillText(
            labels[i] || '',
            xpos,
            T + ph + 7
          );

        }
      );

    }


    /* =====================================================
       TRACKING ERROR LINE
       ===================================================== */

    if(errors.length > 0){

      /* Soft area under the curve */

      if(errors.length > 1){

        x.beginPath();

        x.moveTo(
          xx(0),
          yy(errors[0])
        );


        for(
          let i = 1;
          i < errors.length;
          i++
        ){

          x.lineTo(
            xx(i),
            yy(errors[i])
          );

        }


        x.lineTo(
          xx(errors.length - 1),
          T + ph
        );


        x.lineTo(
          xx(0),
          T + ph
        );


        x.closePath();


        x.fillStyle =
          'rgba(23,105,224,.07)';


        x.fill();

      }


      /* Main line */

      x.strokeStyle =
        '#1769e0';


      x.lineWidth = 2.5;


      x.lineJoin =
        'round';


      x.lineCap =
        'round';


      x.beginPath();


      errors.forEach(
        (v,i) => {

          if(i === 0){

            x.moveTo(
              xx(i),
              yy(v)
            );

          }else{

            x.lineTo(
              xx(i),
              yy(v)
            );

          }

        }
      );


      x.stroke();


      /* Latest data point */

      const last =
        errors.length - 1;


      const lastX =
        xx(last);


      const lastY =
        yy(
          errors[last]
        );


      x.fillStyle =
        '#ffffff';


      x.beginPath();

      x.arc(
        lastX,
        lastY,
        4,
        0,
        Math.PI * 2
      );

      x.fill();


      x.strokeStyle =
        '#1769e0';


      x.lineWidth = 2;


      x.beginPath();

      x.arc(
        lastX,
        lastY,
        4,
        0,
        Math.PI * 2
      );

      x.stroke();


      /* Latest value */

      x.fillStyle =
        '#1769e0';


      x.font =
        '700 9px Arial';


      x.textAlign =
        'right';


      x.textBaseline =
        'bottom';


      x.fillText(
        Number(
          errors[last]
        ).toFixed(2) + '°',
        lastX - 6,
        lastY - 7
      );

    }


    /* =====================================================
       AXIS TITLES
       ===================================================== */

    /* X-axis title */

    x.fillStyle =
      '#52657a';


    x.font =
      '700 9px Arial';


    x.textAlign =
      'center';


    x.textBaseline =
      'bottom';


    x.fillText(
      'Time',
      L + pw / 2,
      h - 3
    );


    /* Y-axis title */

    x.save();


    x.translate(
      10,
      T + ph / 2
    );


    x.rotate(
      -Math.PI / 2
    );


    x.fillStyle =
      '#52657a';


    x.font =
      '700 9px Arial';


    x.textAlign =
      'center';


    x.textBaseline =
      'middle';


    x.fillText(
      'Tracking Error (°)',
      0,
      0
    );


    x.restore();

  }


  /* =========================================================
     AI ASSISTANT CENTER / RECHECK
     ========================================================= */

  window.assistantCenterGuide =
    function(){

      const r =
        $('assistantRecommendation');


      if(r){

        r.textContent =
          'Rechecking target alignment from the latest live telemetry…';

      }


      const st =
        $('assistantStatus');


      if(st){

        st.textContent =
          'RECHECKING';

        st.style.color =
          '#1769e0';

      }


      setTimeout(
        () => {

          const state =
            $('assistantState');


          if(
            state &&
            state.textContent !==
            'STANDBY'
          ){

            const reason =
              $('assistantReason');


            if(reason){

              reason.textContent =
                'Latest tracking data has been refreshed. Follow the current directional guidance shown above.';

            }

          }

        },
        350
      );

    };


  /* =========================================================
     AI ASSISTANT UPDATE
     ========================================================= */

  function updateAssistant(d){

    const status =
      $('assistantStatus');


    const rec =
      $('assistantRecommendation');


    const reason =
      $('assistantReason');


    const fill =
      $('assistantFill');


    const align =
      $('assistantAlignment');


    const state =
      $('assistantState');


    const target =
      $('assistantTarget');


    const err =
      $('assistantError');


    const motion =
      $('assistantMotion');


    const foot =
      $('assistantFoot');


    if(
      !status ||
      !rec
    ){

      return;

    }


    /* -----------------------------------------
       No target found
       ----------------------------------------- */

    if(
      !d ||
      !d.found
    ){

      status.textContent =
        'SEARCHING';


      status.style.color =
        '#ad6d00';


      rec.textContent =
        'Searching for a moving target…';


      reason.textContent =
        'No stable target is available right now. Keep the object visible and moving; automatic reacquisition will continue.';


      if(align){
        align.textContent =
          '0%';
      }


      if(fill){
        fill.style.width =
          '0%';
      }


      if(state){
        state.textContent =
          'SEARCHING';
      }


      if(target){
        target.textContent =
          '—';
      }


      if(err){
        err.textContent =
          '—';
      }


      if(motion){
        motion.textContent =
          '—';
      }


      if(foot){

        foot.textContent =
          'AI guidance is based only on live camera telemetry; no static target values are used.';

      }


      return;

    }


    /* -----------------------------------------
       Current telemetry
       ----------------------------------------- */

    const te =
      Math.abs(
        Number(
          d.total_error
        ) || 0
      );


    const he =
      Number(
        d.h_error
      ) || 0;


    const ve =
      Number(
        d.v_error
      ) || 0;


    const speed =
      Number(
        d.velocity_px_s
      ) || 0;


    /* -----------------------------------------
       Alignment percentage
       ----------------------------------------- */

    let alignment =
      Math.max(
        0,
        Math.min(
          100,
          100 -
          (
            te /
            Math.max(
              Number(
                d.coarse_limit
              ) || 2,
              .1
            )
          ) *
          100
        )
      );


    if(
      te <=
      Number(
        d.fine_limit ||
        .5
      )
    ){

      alignment =
        Math.max(
          alignment,
          95
        );

    }


    const phase =
      String(
        d.phase ||
        'TRACKING'
      );


    /* -----------------------------------------
       Status
       ----------------------------------------- */

    status.textContent =
      phase === 'FINE LOCK'
        ? 'LOCKED'
        : 'ACTIVE';


    status.style.color =
      phase === 'FINE LOCK'
        ? '#15936d'
        : '#1769e0';


    /* -----------------------------------------
       Alignment
       ----------------------------------------- */

    if(align){

      align.textContent =
        alignment.toFixed(0) +
        '%';

    }


    if(fill){

      fill.style.width =
        alignment.toFixed(0) +
        '%';

    }


    /* -----------------------------------------
       Assistant facts
       ----------------------------------------- */

    if(state){

      state.textContent =
        phase;

    }


    if(target){

      target.textContent =
        (
          d.label ||
          'moving-object'
        ) +
        ' #' +
        (
          d.track_id ??
          1
        );

    }


    if(err){

      err.textContent =
        te.toFixed(2) +
        '°';

    }


    if(motion){

      motion.textContent =
        speed.toFixed(1) +
        ' px/s';

    }


    /* -----------------------------------------
       Recommendation
       ----------------------------------------- */

    if(
      phase === 'FINE LOCK'
    ){

      rec.textContent =
        'Hold position — target is finely locked';


      reason.textContent =
        'The target is inside the fine alignment gate. Avoid unnecessary movement and continue monitoring angular error.';

    }

    else{

      const parts = [];


      const hThresh =
        0.08;


      const vThresh =
        0.08;


      if(
        Math.abs(he) >=
        hThresh
      ){

        parts.push(
          (
            he > 0
              ? 'RIGHT'
              : 'LEFT'
          ) +
          ' by ' +
          Math.abs(he).toFixed(2) +
          '°'
        );

      }


      if(
        Math.abs(ve) >=
        vThresh
      ){

        parts.push(
          (
            ve > 0
              ? 'UP'
              : 'DOWN'
          ) +
          ' by ' +
          Math.abs(ve).toFixed(2) +
          '°'
        );

      }


      rec.textContent =
        parts.length
          ? 'Move ' +
            parts.join(' and ')
          : 'Hold position — tracking is centered';


      reason.textContent =
        parts.length

          ? 'Recommendation is derived from the target-to-boresight angular error. ' +

            (
              speed > 80
                ? 'Target motion is high, so use small corrective steps and recheck lock.'
                : 'Recheck the target after the correction and allow the tracker to settle.'
            )

          : 'Target is close to boresight. Small corrections are unnecessary at the current error level.';

    }


    /* -----------------------------------------
       Assistant footer
       ----------------------------------------- */

    if(foot){

      foot.textContent =
        'Live inputs: ' +
        phase +
        ' · confidence ' +
        Number(
          d.confidence || 0
        ).toFixed(1) +
        '% · angular rate ' +
        Number(
          d.angular_velocity_deg_s || 0
        ).toFixed(3) +
        ' °/s · FPS ' +
        Number(
          d.fps || 0
        ).toFixed(1);

    }

  }


  /* =========================================================
     LIVE ALERTS
     ========================================================= */

  function renderAlert(
    a,
    append
  ){

    const list =
      $('liveAlertsList');


    if(!list){
      return;
    }


    const muted =
      list.querySelector(
        '.muted'
      );


    if(muted){

      list.innerHTML =
        '';

    }


    const row =
      document.createElement(
        'div'
      );


    row.className =
      'live-alert-row';


    const time =
      a &&
      a.time
        ? a.time
        : '—';


    const severity =
      a &&
      a.severity
        ? a.severity
        : 'INFO';


    const message =
      a &&
      a.message
        ? a.message
        : 'Live tracking alert';


    row.innerHTML =
      '<span>' +
      time +
      '</span>' +

      '<span class="sev-' +
      severity +
      '">' +
      severity +
      '</span>' +

      '<span>' +
      message +
      '</span>';


    if(append){

      list.appendChild(
        row
      );

    }else{

      list.prepend(
        row
      );

    }

  }


  /* =========================================================
     WINDOW RESIZE
     ========================================================= */

  window.addEventListener(
    'resize',
    function(){

      resizeLiveOverlay();

      drawChart();

    }
  );


  /* =========================================================
     CAMERA IMAGE RESIZE
     ========================================================= */

  const observeCamera =
    function(){

      const img =
        $('liveFeedImg');


      if(
        !img ||
        typeof ResizeObserver ===
        'undefined'
      ){

        return;

      }


      const observer =
        new ResizeObserver(
          function(){

            resizeLiveOverlay();

          }
        );


      observer.observe(img);

    };


  setTimeout(
    observeCamera,
    100
  );


})();