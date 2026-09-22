"""Background engine for Live Demo Camera generic object tracking."""
import threading
import time
from datetime import datetime, timezone
from math import sqrt

from .geometry import pixel_to_angle, classify_phase


class DemoObjectEngine:
    def __init__(self, app, db, socketio, camera, tracker, detection_model, alert_model,
                 coarse_limit=2.0, fine_limit=0.5, hfov=42.0, vfov=24.0, rate_hz=10):
        self.app = app
        self.db = db
        self.socketio = socketio
        self.camera = camera
        self.tracker = tracker
        self.Detection = detection_model
        self.Alert = alert_model
        self.coarse_limit = coarse_limit
        self.fine_limit = fine_limit
        self.hfov = hfov
        self.vfov = vfov
        self.rate_hz = rate_hz
        self._running = False
        self._thread = None
        self._last_by_track = {}
        self._active_track = None

    @property
    def is_running(self):
        return self._running

    @property
    def active_detector(self):
        if getattr(self.camera, 'mode', '') == 'synthetic':
            return 'synthetic-object-tracker'
        return 'yolo-object-tracker' if self.tracker.available else 'unavailable'

    def start(self):
        if self._running:
            return
        self.camera.start()
        self._running = True
        self._last_by_track = {}
        self._active_track = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        thread = self._thread
        self._thread = None
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        self.camera.stop()
        self._last_by_track = {}
        self._active_track = None

    def _persist(self, d, h, v, total, signal, score, phase, command, speed):
        try:
            row = self.Detection(
                timestamp=datetime.now(timezone.utc), track_id=d['track_id'],
                object_label=d['label'], source=d.get('source', 'yolo'), cx=d['cx'], cy=d['cy'],
                h_error=h, v_error=v, total_error=total, confidence=d['confidence'],
                signal_dbm=signal, alignment_score=score, phase=phase,
                command=command, movement_speed=speed,
            )
            self.db.session.add(row)
            self.db.session.commit()
        except Exception:
            self.db.session.rollback()

    def _alert(self, severity, message):
        try:
            row = self.Alert(timestamp=datetime.now(timezone.utc), severity=severity, message=message)
            self.db.session.add(row)
            self.db.session.commit()
            payload = {'id': row.id, 'severity': severity, 'message': message,
                       'time': row.timestamp.strftime('%H:%M:%S')}
        except Exception:
            self.db.session.rollback()
            payload = {'id': None, 'severity': severity, 'message': message,
                       'time': datetime.now(timezone.utc).strftime('%H:%M:%S')}
        self.socketio.emit('demo_alert', payload)

    @staticmethod
    def _command(h, v, total):
        dead = 0.08 if total < 1 else 0.12
        x = 'RIGHT' if h > dead else 'LEFT' if h < -dead else ''
        y = 'UP' if v > dead else 'DOWN' if v < -dead else ''
        if x and y:
            return f'{x} + {y}'
        return x or y or 'HOLD'

    def _get_objects(self, frame):
        # The synthetic scene has known non-person objects. Use those directly
        # so a no-camera hackathon setup still demonstrates movement + IDs.
        if getattr(self.camera, 'mode', '') == 'synthetic' and hasattr(self.camera, 'get_synthetic_objects'):
            return self.camera.get_synthetic_objects(), 'synthetic'
        return self.tracker.track(frame), 'yolo'

    def _loop(self):
        with self.app.app_context():
            was_locked = False
            last_active = None
            while self._running:
                frame = self.camera.get_frame()
                if frame is None:
                    time.sleep(0.05)
                    continue
                fh, fw = frame.shape[:2]
                objects, source = self._get_objects(frame)

                # Select one target for the detailed telemetry while the overlay
                # still receives every detected/tracked object.
                target = None
                if self._active_track is not None:
                    same = [o for o in objects if o['track_id'] == self._active_track]
                    if same:
                        target = same[0]
                if target is None and objects:
                    target = max(objects, key=lambda o: (o['w'] * o['h'], o['confidence']))
                    self._active_track = target['track_id']

                overlay_objects = [
                    {
                        'track_id': int(o.get('track_id', -1)),
                        'label': o['label'],
                        'confidence': round(float(o['confidence']), 1),
                        'class_id': int(o.get('class_id', -1)),
                        'x': round(float(o['x']), 1), 'y': round(float(o['y']), 1),
                        'w': round(float(o['w']), 1), 'h': round(float(o['h']), 1),
                        'cx': round(float(o['cx']), 1), 'cy': round(float(o['cy']), 1),
                    }
                    for o in objects
                ]

                if target:
                    tid = target['track_id']
                    now_t = time.time()
                    prev = self._last_by_track.get(tid)
                    speed = 0.0
                    if prev:
                        dt = max(0.001, now_t - prev[2])
                        speed = sqrt((target['cx']-prev[0])**2 + (target['cy']-prev[1])**2) / dt
                    self._last_by_track[tid] = (target['cx'], target['cy'], now_t)
                    last_active = now_t

                    h, v, total = pixel_to_angle(target['cx'], target['cy'], fw, fh, self.hfov, self.vfov)
                    phase = classify_phase(total, self.coarse_limit, self.fine_limit)
                    locked = phase in ('FINE ALIGNMENT', 'FINE LOCK')
                    command = self._command(h, v, total)
                    score = max(0.0, min(100.0, 100.0 - total * 7.0))
                    signal = max(-95.0, min(-35.0, -42.0 - total * 1.8 + (target['confidence']-100.0)*0.08))

                    payload = {
                        'found': True, 'source': source, 'timestamp': datetime.now(timezone.utc).isoformat(),
                        'track_id': tid, 'object_label': target['label'], 'class_id': target.get('class_id', -1),
                        'cx': round(target['cx'],1), 'cy': round(target['cy'],1), 'frame_w': fw, 'frame_h': fh,
                        'box': {'x': target['x'], 'y': target['y'], 'w': target['w'], 'h': target['h']},
                        'objects': overlay_objects,
                        'h_error': round(h,3), 'v_error': round(v,3), 'total_error': round(total,3),
                        'azimuth': round(h,3), 'elevation': round(v,3), 'confidence': round(target['confidence'],1),
                        'signal_dbm': round(signal,1), 'alignment_score': round(score,1), 'phase': phase,
                        'command': command, 'locked': locked, 'fine_locked': phase == 'FINE LOCK',
                        'movement_speed': round(speed,1), 'coarse_limit': self.coarse_limit,
                        'fine_limit': self.fine_limit, 'camera_mode': self.camera.mode,
                        'person_tracking': False,
                    }
                    self._persist(target, h, v, total, signal, score, phase, command, speed)
                    if locked and not was_locked:
                        self._alert('SUCCESS', f'Live Demo: {target["label"]} #{tid} entered alignment gate · error {total:.2f}°')
                    was_locked = locked
                    self.socketio.emit('demo_tracking_update', payload)
                else:
                    self.socketio.emit('demo_tracking_update', {
                        'found': False, 'timestamp': datetime.now(timezone.utc).isoformat(),
                        'objects': overlay_objects, 'camera_mode': self.camera.mode,
                        'person_tracking': False,
                    })
                    if was_locked and (last_active is None or time.time()-last_active > 2.0):
                        self._alert('WARNING', 'Live Demo: tracked object lost · reacquisition required')
                        was_locked = False
                time.sleep(1.0 / self.rate_hz)
