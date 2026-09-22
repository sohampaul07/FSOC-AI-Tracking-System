/* TRACKAI v7 Safety Siren
   Cross-route audible + visual warning system.
   - Browser-safe Web Audio API; no external audio file required.
   - Explicit user enable/test action satisfies browser audio policies.
   - Preference persists across Dashboard/Alerts/Live Tracking/etc.
   - WARNING/CRITICAL/ERROR events trigger the siren when enabled.
   - Success/INFO events never trigger the siren.
*/
(function () {
  'use strict';

  const STORAGE_KEY = 'fsoc_siren_enabled';
  const COOLDOWN_MS = 1200;
  let ctx = null;
  let enabled = localStorage.getItem(STORAGE_KEY) === '1';
  let lastSoundAt = 0;
  const seenIds = new Set();
  let seeded = false;

  function getAudioContext() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!ctx) ctx = new AC();
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    return ctx;
  }

  function tone(freqStart, freqEnd, duration, startTime, peak) {
    const c = ctx;
    if (!c) return;
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(freqStart, startTime);
    osc.frequency.linearRampToValueAtTime(freqEnd, startTime + duration);
    gain.gain.setValueAtTime(0.0001, startTime);
    gain.gain.linearRampToValueAtTime(peak, startTime + 0.04);
    gain.gain.linearRampToValueAtTime(0.0001, startTime + duration);
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start(startTime);
    osc.stop(startTime + duration + 0.02);
  }

  function flashBanner(severity, message) {
    document.querySelectorAll('[data-siren-banner]').forEach((el) => {
      const critical = severity === 'CRITICAL' || severity === 'ERROR';
      el.textContent = (critical ? '🚨 CRITICAL SAFETY ALERT — ' : '⚠ WARNING — ')
        + (message || severity);
      el.classList.add('siren-flash-active');
      clearTimeout(el._sirenTimer);
      el._sirenTimer = setTimeout(() => el.classList.remove('siren-flash-active'), 4200);
    });
    document.body.classList.add('siren-page-flash');
    clearTimeout(document.body._sirenPageTimer);
    document.body._sirenPageTimer = setTimeout(
      () => document.body.classList.remove('siren-page-flash'), 4200
    );
  }

  function play(severity, message) {
    if (!enabled) {
      flashBanner(severity, message);
      return;
    }
    const nowMs = Date.now();
    if (nowMs - lastSoundAt < COOLDOWN_MS) {
      flashBanner(severity, message);
      return;
    }
    const c = getAudioContext();
    if (!c) {
      flashBanner(severity, message);
      return;
    }

    lastSoundAt = nowMs;
    const critical = severity === 'CRITICAL' || severity === 'ERROR';
    const pulses = critical ? 4 : 2;
    const duration = critical ? 0.42 : 0.52;
    const gap = critical ? 0.10 : 0.16;
    const peak = critical ? 0.20 : 0.15;
    const base = c.currentTime + 0.02;

    for (let i = 0; i < pulses; i++) {
      const t = base + i * (duration + gap);
      tone(critical ? 720 : 560, critical ? 1040 : 880, duration, t, peak);
    }
    flashBanner(severity, message);
  }

  function updateUI() {
    document.querySelectorAll('[data-siren-toggle]').forEach((btn) => {
      btn.textContent = enabled ? '🔊 Siren: ON' : '🔇 Siren: OFF';
      btn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
      btn.classList.toggle('siren-on', enabled);
    });
    document.querySelectorAll('[data-siren-status]').forEach((el) => {
      el.textContent = enabled ? 'ARMED' : 'STANDBY';
      el.classList.toggle('siren-on', enabled);
    });
  }

  function qualifying(sev) {
    sev = String(sev || '').toUpperCase();
    return sev === 'WARNING' || sev === 'CRITICAL' || sev === 'ERROR';
  }

  window.Siren = {
    isEnabled: () => enabled,

    enable() {
      enabled = true;
      localStorage.setItem(STORAGE_KEY, '1');
      const c = getAudioContext();
      if (c) tone(680, 680, 0.14, c.currentTime + 0.02, 0.10);
      updateUI();
    },

    disable() {
      enabled = false;
      localStorage.setItem(STORAGE_KEY, '0');
      updateUI();
    },

    toggle() {
      enabled ? this.disable() : this.enable();
    },

    test(severity) {
      const wasEnabled = enabled;
      if (!wasEnabled) {
        // Test is intentionally allowed without arming the system permanently.
        const c = getAudioContext();
        if (c) {
          tone(560, 880, 0.52, c.currentTime + 0.02, 0.15);
          tone(560, 880, 0.52, c.currentTime + 0.78, 0.15);
        }
        flashBanner('WARNING', 'Siren test — safety audio verified');
        return;
      }
      play(String(severity || 'WARNING').toUpperCase(), 'Siren test — safety audio verified');
    },

    notify(severity, message, id) {
      const sev = String(severity || '').toUpperCase();
      if (!qualifying(sev)) return;
      if (id !== undefined && id !== null) {
        const key = String(id);
        if (seenIds.has(key)) return;
        seenIds.add(key);
      }
      play(sev, message);
    },

    seedFromList(rows, idKey, sevKey) {
      (rows || []).forEach((row) => {
        const id = row && row[idKey];
        if (id !== undefined && id !== null) seenIds.add(String(id));
      });
      seeded = true;
    },

    notifyFromList(rows, idKey, sevKey, messageKey) {
      (rows || []).forEach((row) => {
        const id = row && row[idKey];
        const sev = row && row[sevKey];
        const msg = messageKey ? row && row[messageKey] : row && row.message;
        if (!qualifying(sev)) return;
        if (id === undefined || id === null) return;
        const key = String(id);
        if (seenIds.has(key)) return;
        seenIds.add(key);
        play(String(sev).toUpperCase(), msg);
      });
      seeded = true;
    }
  };

  document.addEventListener('DOMContentLoaded', updateUI);
  window.addEventListener('storage', (e) => {
    if (e.key === STORAGE_KEY) {
      enabled = e.newValue === '1';
      updateUI();
    }
  });
})();
