/* ================================================================
   Live Demo Camera — separate generic object tracking UI
   ================================================================ */

(function () {

  const $ = (id) =>
    document.getElementById(id);

  let demoInitialized = false;
  let demoRunning = false;
  let demoSocket = null;

  let demoErrSeries = [];

  const MAX = 60;

  /*
   * ================================================================
   * SHARED THREE-MODE SWITCHER
   *
   * sim  = Simulator
   * live = Live AI Camera
   * demo = Live Demo Camera
   * ================================================================
   */

  window.showTrackingMode = function (mode) {

    const sim =
      $('simPanel');

    const live =
      $('liveAiPanel');

    const demo =
      $('liveDemoPanel');

    const tabSim =
      $('tabSim');

    const tabLive =
      $('tabLive');

    const tabDemo =
      $('tabDemo');

    /*
     * Hide every panel first.
     */
    if (sim) {
      sim.style.display =
        'none';
    }

    if (live) {
      live.style.display =
        'none';
    }

    if (demo) {
      demo.style.display =
        'none';
    }

    /*
     * Remove active state
     * from all three tabs.
     */
    [
      tabSim,
      tabLive,
      tabDemo
    ].forEach(tab => {

      if (tab) {
        tab.classList.remove(
          'active'
        );
      }

    });

    /*
     * SIMULATOR
     */
    if (mode === 'sim') {

      if (sim) {
        sim.style.display =
          'block';
      }

      if (tabSim) {
        tabSim.classList.add(
          'active'
        );
      }

      /*
       * If a camera was previously running,
       * stop it when returning to simulator.
       */
      if (
        demoRunning &&
        typeof window.stopDemoCamera === 'function'
      ) {
        window.stopDemoCamera();
      }

      return;
    }

    /*
     * LIVE AI
     */
    if (mode === 'live') {

      if (live) {
        live.style.display =
          'block';
      }

      if (tabLive) {
        tabLive.classList.add(
          'active'
        );
      }

      /*
       * Make sure Demo Camera is stopped.
       */
      if (
        demoRunning &&
        typeof window.stopDemoCamera === 'function'
      ) {
        window.stopDemoCamera();
      }

      /*
       * Initialize the original Live AI.
       */
      if (
        typeof window.initLiveAI ===
        'function'
      ) {
        window.initLiveAI();
      }

      return;
    }

    /*
     * LIVE DEMO CAMERA
     */
    if (mode === 'demo') {

      if (demo) {
        demo.style.display =
          'block';
      }

      if (tabDemo) {
        tabDemo.classList.add(
          'active'
        );
      }

      /*
       * Initialize Demo Camera.
       */
      window.initDemoCamera();

      return;
    }

  };

  /*
   * ================================================================
   * PAGE INITIALIZATION
   * ================================================================
   */

  window.initLiveTracking = function () {

    /*
     * Start on simulator.
     * Do not automatically start either camera.
     */
    window.showTrackingMode(
      'sim'
    );

  };

  /*
   * ================================================================
   * HELPERS
   * ================================================================
   */

  function setText(
    id,
    value
  ) {

    const el = $(id);

    if (el) {
      el.textContent =
        value;
    }

  }

  function badge(
    id,
    value
  ) {

    setText(
      id,
      value
    );

  }

  function phaseClass(
    phase
  ) {

    if (
      phase ===
      'FINE LOCK'
    ) {
      return 'green';
    }

    if (
      phase ===
        'FINE ALIGNMENT' ||
      phase ===
        'COARSE ALIGNMENT'
    ) {
      return 'blue';
    }

    return 'amber';
  }

  /*
   * ================================================================
   * DEMO CAMERA INITIALIZATION
   * ================================================================
   */

  window.initDemoCamera =
    function () {

      if (demoInitialized) {
        return;
      }

      demoInitialized = true;

      /*
       * Socket.IO connection.
       */
      demoSocket = io();

      demoSocket.on(
        'demo_tracking_update',
        onDemoUpdate
      );

      demoSocket.on(
        'demo_alert',
        onDemoAlert
      );

      /*
       * Get camera/tracker status.
       */
      fetch(
        '/api/demo-camera/status'
      )
        .then(r => r.json())
        .then(s => {

          badge(
            'demoCameraModeBadge',
            'CAMERA: ' +
              String(
                s.camera_mode || '—'
              ).toUpperCase()
          );

          badge(
            'demoDetectorBadge',
            'TRACKER: ' +
              String(
                s.detector || '—'
              ).toUpperCase()
          );

          badge(
            'demoRunBadge',
            s.running
              ? 'RUNNING'
              : 'STOPPED'
          );

          demoRunning =
            !!s.running;

        })
        .catch(() => {});

      /*
       * Load previous alerts.
       */
      fetch(
        '/api/demo-camera/alerts?limit=20'
      )
        .then(r => r.json())
        .then(rows => {

          rows
            .reverse()
            .forEach(
              a => renderDemoAlert(a)
            );

        })
        .catch(() => {});

    };

  /*
   * ================================================================
   * START DEMO CAMERA
   * ================================================================
   */

  window.startDemoCamera =
    function () {

      /*
       * Make sure Socket.IO is initialized.
       */
      window.initDemoCamera();

      fetch(
        '/api/demo-camera/start',
        {
          method: 'POST'
        }
      )
        .then(r => r.json())
        .then(s => {

          if (!s.ok) {
            throw new Error(
              s.error ||
              'Unable to start demo camera'
            );
          }

          demoRunning =
            true;

          const img =
            $('demoFeedImg');

          if (img) {

            /*
             * Cache-busting timestamp.
             */
            img.src =
              '/demo_video_feed?t=' +
              Date.now();

          }

          const empty =
            $('demoEmptyMsg');

          if (empty) {
            empty.style.display =
              'none';
          }

          badge(
            'demoRunBadge',
            'RUNNING'
          );

          badge(
            'demoCameraModeBadge',
            'CAMERA: ' +
              String(
                s.camera_mode || '—'
              ).toUpperCase()
          );

          badge(
            'demoDetectorBadge',
            'TRACKER: ' +
              String(
                s.detector || '—'
              ).toUpperCase()
          );

        })
        .catch(err => {

          console.error(
            'Demo Camera start error:',
            err
          );

        });

    };

  /*
   * ================================================================
   * STOP DEMO CAMERA
   * ================================================================
   */

  window.stopDemoCamera =
    function () {

      fetch(
        '/api/demo-camera/stop',
        {
          method: 'POST'
        }
      )
        .finally(() => {

          demoRunning =
            false;

          const img =
            $('demoFeedImg');

          if (img) {
            img.removeAttribute(
              'src'
            );
          }

          const empty =
            $('demoEmptyMsg');

          if (empty) {
            empty.style.display =
              'flex';
          }

          badge(
            'demoRunBadge',
            'STOPPED'
          );

          clearDemoOverlay();

        });

    };

  /*
   * ================================================================
   * CLEAR DEMO OVERLAY
   * ================================================================
   */

  function clearDemoOverlay() {

    const canvas =
      $('demoOverlay');

    if (!canvas) {
      return;
    }

    const ctx =
      canvas.getContext('2d');

    ctx.clearRect(
      0,
      0,
      canvas.width,
      canvas.height
    );

  }

  /*
   * ================================================================
   * DEMO SOCKET UPDATE
   * ================================================================
   */

  function onDemoUpdate(d) {

    if (!demoRunning) {
      return;
    }

    /*
     * No target.
     */
    if (!d.found) {

      setText(
        'demoPhasePill',
        'SEARCHING'
      );

      setText(
        'demoObject',
        '—'
      );

      setText(
        'demoTrackId',
        '—'
      );

      setText(
        'demoSpeed',
        '0 px/s'
      );

      drawDemoOverlay(d);

      return;
    }

    /*
     * Phase.
     */
    const pill =
      $('demoPhasePill');

    if (pill) {

      pill.textContent =
        d.phase;

      pill.className =
        'pill ' +
        phaseClass(
          d.phase
        );

    }

    /*
     * Selected object.
     */
    setText(
      'demoObject',
      d.object_label ||
        'object'
    );

    setText(
      'demoTrackId',
      '#' +
        d.track_id
    );

    /*
     * Pixel position.
     */
    setText(
      'demoX',
      Math.round(
        d.cx
      ) +
        ' px'
    );

    setText(
      'demoY',
      Math.round(
        d.cy
      ) +
        ' px'
    );

    /*
     * Angular error.
     */
    setText(
      'demoHErr',
      (
        d.h_error >= 0
          ? '+'
          : ''
      ) +
        Number(
          d.h_error || 0
        ).toFixed(2) +
        '°'
    );

    setText(
      'demoVErr',
      (
        d.v_error >= 0
          ? '+'
          : ''
      ) +
        Number(
          d.v_error || 0
        ).toFixed(2) +
        '°'
    );

    setText(
      'demoTotalErr',
      Number(
        d.total_error || 0
      ).toFixed(2) +
        '°'
    );

    /*
     * Azimuth / elevation.
     */
    setText(
      'demoAz',
      (
        d.azimuth >= 0
          ? '+'
          : ''
      ) +
        Number(
          d.azimuth || 0
        ).toFixed(2) +
        '°'
    );

    setText(
      'demoEl',
      (
        d.elevation >= 0
          ? '+'
          : ''
      ) +
        Number(
          d.elevation || 0
        ).toFixed(2) +
        '°'
    );

    /*
     * Confidence.
     */
    setText(
      'demoConf',
      Number(
        d.confidence || 0
      ).toFixed(1) +
        '%'
    );

    /*
     * Signal.
     */
    setText(
      'demoSignal',
      Number(
        d.signal_dbm || 0
      ).toFixed(1) +
        ' dBm'
    );

    /*
     * Alignment score.
     */
    setText(
      'demoScore',
      Number(
        d.alignment_score || 0
      ).toFixed(1) +
        '%'
    );

    /*
     * Movement speed.
     */
    setText(
      'demoSpeed',
      Number(
        d.movement_speed || 0
      ).toFixed(1) +
        ' px/s'
    );

    /*
     * Guidance command.
     */
    setText(
      'demoCommand',
      d.command ||
        'HOLD'
    );

    /*
     * Draw all tracked objects.
     */
    drawDemoOverlay(d);

    /*
     * Error chart.
     */
    demoErrSeries.push(
      Number(
        d.total_error || 0
      )
    );

    if (
      demoErrSeries.length >
      MAX
    ) {
      demoErrSeries.shift();
    }

    drawDemoChart();

    highlightDemoPhase(
      d.phase
    );

  }

  /*
   * ================================================================
   * DRAW DEMO OBJECT OVERLAY
   * ================================================================
   */

  function drawDemoOverlay(d) {

    const img =
      $('demoFeedImg');

    const canvas =
      $('demoOverlay');

    if (
      !img ||
      !canvas ||
      !img.clientWidth ||
      !d.frame_w
    ) {
      return;
    }

    const dpr =
      window.devicePixelRatio || 1;

    const cw =
      img.clientWidth;

    const ch =
      img.clientHeight;

    if (
      canvas.width !==
        cw * dpr ||
      canvas.height !==
        ch * dpr
    ) {

      canvas.width =
        cw * dpr;

      canvas.height =
        ch * dpr;

    }

    const ctx =
      canvas.getContext('2d');

    ctx.setTransform(
      dpr,
      0,
      0,
      dpr,
      0,
      0
    );

    ctx.clearRect(
      0,
      0,
      cw,
      ch
    );

    const sx =
      cw / d.frame_w;

    const sy =
      ch / d.frame_h;

    /*
     * Backend should provide every tracked object.
     *
     * Fallback to the selected target if objects[]
     * isn't available.
     */
    const objects =
      d.objects ||
      (
        d.box
          ? [{
              track_id:
                d.track_id,

              label:
                d.object_label,

              confidence:
                d.confidence,

              x:
                d.box.x,

              y:
                d.box.y,

              w:
                d.box.w,

              h:
                d.box.h,

              cx:
                d.cx,

              cy:
                d.cy
            }]
          : []
      );

    /*
     * Draw every tracked object.
     */
    objects.forEach(
      o => {

        const x =
          o.x * sx;

        const y =
          o.y * sy;

        const w =
          o.w * sx;

        const h =
          o.h * sy;

        const selected =
          Number(
            o.track_id
          ) ===
          Number(
            d.track_id
          );

        /*
         * Selected object = thicker green box.
         * Other objects = blue box.
         */
        ctx.lineWidth =
          selected
            ? 3
            : 1.5;

        ctx.strokeStyle =
          selected
            ? '#5af096'
            : '#66c7ff';

        ctx.strokeRect(
          x,
          y,
          w,
          h
        );

        /*
         * Object label.
         */
        ctx.font =
          '700 11px Inter,Arial,sans-serif';

        ctx.fillStyle =
          selected
            ? '#5af096'
            : '#e8f7ff';

        const label =
          (
            o.label ||
            'object'
          ) +
          '  #' +
          (
            o.track_id ??
            '—'
          ) +
          '  ' +
          Number(
            o.confidence || 0
          ).toFixed(0) +
          '%';

        const labelY =
          Math.max(
            14,
            y - 5
          );

        ctx.fillText(
          label,
          x,
          labelY
        );

        /*
         * Centroid.
         */
        ctx.fillStyle =
          '#ffffff';

        ctx.beginPath();

        ctx.arc(
          o.cx * sx,
          o.cy * sy,
          selected ? 4 : 3,
          0,
          Math.PI * 2
        );

        ctx.fill();

      }
    );

    /*
     * ============================================================
     * BORESIGHT + ANGULAR GATES
     *
     * Same FSOC telemetry geometry:
     * HFOV = 42 degrees
     * Coarse = 2 degrees
     * Fine = 0.5 degrees
     * ============================================================
     */

    const bx =
      cw / 2;

    const by =
      ch / 2;

    const pxPerDeg =
      cw / 42.0;

    drawCircle(
      ctx,
      bx,
      by,
      (
        d.coarse_limit ||
        2
      ) * pxPerDeg,
      'rgba(255,190,90,.55)'
    );

    drawCircle(
      ctx,
      bx,
      by,
      (
        d.fine_limit ||
        0.5
      ) * pxPerDeg,
      'rgba(120,230,180,.75)'
    );

    /*
     * Boresight crosshair.
     */
    ctx.strokeStyle =
      'rgba(235,245,255,.9)';

    ctx.lineWidth = 1.5;

    ctx.beginPath();

    ctx.moveTo(
      bx - 10,
      by
    );

    ctx.lineTo(
      bx + 10,
      by
    );

    ctx.moveTo(
      bx,
      by - 10
    );

    ctx.lineTo(
      bx,
      by + 10
    );

    ctx.stroke();

  }

  /*
   * ================================================================
   * ANGULAR CIRCLE
   * ================================================================
   */

  function drawCircle(
    ctx,
    x,
    y,
    r,
    color
  ) {

    if (r < 2) {
      return;
    }

    ctx.save();

    ctx.strokeStyle =
      color;

    ctx.lineWidth = 1;

    ctx.setLineDash([
      5,
      4
    ]);

    ctx.beginPath();

    ctx.arc(
      x,
      y,
      r,
      0,
      Math.PI * 2
    );

    ctx.stroke();

    ctx.restore();

  }

  /*
   * ================================================================
   * DEMO ERROR CHART
   * ================================================================
   */

  function drawDemoChart() {

    const canvas =
      $('demoErrorChart');

    if (!canvas) {
      return;
    }

    const dpr =
      window.devicePixelRatio || 1;

    const w =
      canvas.clientWidth ||
      300;

    const h =
      canvas.clientHeight ||
      170;

    if (
      canvas.width !==
        w * dpr ||
      canvas.height !==
        h * dpr
    ) {

      canvas.width =
        w * dpr;

      canvas.height =
        h * dpr;

    }

    const ctx =
      canvas.getContext('2d');

    ctx.setTransform(
      dpr,
      0,
      0,
      dpr,
      0,
      0
    );

    ctx.clearRect(
      0,
      0,
      w,
      h
    );

    const padL = 32;
    const padR = 8;
    const padT = 10;
    const padB = 25;

    const pw =
      w -
      padL -
      padR;

    const ph =
      h -
      padT -
      padB;

    const max =
      Math.max(
        2.5,
        ...(
          demoErrSeries.length
            ? demoErrSeries
            : [0]
        )
      ) * 1.15;

    /*
     * Grid.
     */
    ctx.strokeStyle =
      '#eef2f7';

    ctx.lineWidth = 1;

    for (
      let i = 0;
      i <= 4;
      i++
    ) {

      const y =
        padT +
        ph -
        (
          ph *
          i /
          4
        );

      ctx.beginPath();

      ctx.moveTo(
        padL,
        y
      );

      ctx.lineTo(
        padL + pw,
        y
      );

      ctx.stroke();

    }

    const yAt =
      v =>
        padT +
        ph -
        (
          ph *
          Math.min(
            v / max,
            1
          )
        );

    const xAt =
      i =>
        padL +
        pw *
        i /
        Math.max(
          demoErrSeries.length - 1,
          1
        );

    /*
     * Coarse and fine thresholds.
     */
    const thresholds = [
      {
        value: 2.0,
        label: '2.0°',
        color: '#e08a1e'
      },
      {
        value: 0.5,
        label: '0.5°',
        color: '#1e9e5e'
      }
    ];

    thresholds.forEach(
      t => {

        const y =
          yAt(
            t.value
          );

        ctx.strokeStyle =
          t.color;

        ctx.setLineDash([
          5,
          4
        ]);

        ctx.beginPath();

        ctx.moveTo(
          padL,
          y
        );

        ctx.lineTo(
          padL + pw,
          y
        );

        ctx.stroke();

        ctx.setLineDash([]);

        ctx.fillStyle =
          t.color;

        ctx.font =
          '700 8px Arial';

        ctx.fillText(
          t.label,
          padL + 4,
          y - 2
        );

      }
    );

    /*
     * Error line.
     */
    if (
      demoErrSeries.length > 1
    ) {

      ctx.strokeStyle =
        '#1769e0';

      ctx.lineWidth = 2;

      ctx.beginPath();

      demoErrSeries.forEach(
        (v, i) => {

          if (i) {

            ctx.lineTo(
              xAt(i),
              yAt(v)
            );

          } else {

            ctx.moveTo(
              xAt(i),
              yAt(v)
            );

          }

        }
      );

      ctx.stroke();

    }

    /*
     * Border.
     */
    ctx.strokeStyle =
      '#c7d2df';

    ctx.strokeRect(
      padL,
      padT,
      pw,
      ph
    );

    /*
     * Axis title.
     */
    ctx.fillStyle =
      '#4a5d75';

    ctx.font =
      '700 8px Arial';

    ctx.textAlign =
      'center';

    ctx.fillText(
      'Angular pointing error (°)',
      padL + pw / 2,
      h - 5
    );

  }

  /*
   * ================================================================
   * PHASE LEGEND
   * ================================================================
   */

  function highlightDemoPhase(
    phase
  ) {

    const legend =
      $('demoPhaseLegend');

    if (!legend) {
      return;
    }

    legend
      .querySelectorAll(
        '.phase-chip'
      )
      .forEach(
        chip => {

          chip.classList.toggle(
            'active',
            chip.dataset.demoPhase ===
              phase
          );

        }
      );

  }

  /*
   * ================================================================
   * DEMO ALERTS
   * ================================================================
   */

  function onDemoAlert(a) {

    renderDemoAlert(a);

  }

  function renderDemoAlert(a) {

    const list =
      $('demoAlertsList');

    if (!list) {
      return;
    }

    const muted =
      list.querySelector(
        '.muted'
      );

    if (muted) {
      list.innerHTML = '';
    }

    const row =
      document.createElement(
        'div'
      );

    row.className =
      'live-alert-row';

    row.innerHTML =
      `<span>${a.time || ''}</span>` +
      `<span class="sev-${a.severity || 'INFO'}">${a.severity || 'INFO'}</span>` +
      `<span>${a.message || ''}</span>`;

    list.prepend(
      row
    );

  }

  /*
   * ================================================================
   * RESIZE
   * ================================================================
   */

  window.addEventListener(
    'resize',
    drawDemoChart
  );

})();