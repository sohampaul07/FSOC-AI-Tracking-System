"""Live physical-camera tracking engine for the Live Tracking page."""
import math
import threading
import time
from datetime import datetime, timezone

from .geometry import pixel_to_angle, classify_phase
from .object_tracker import YoloObjectTracker


class LiveEngine:
    def __init__(self, app, db, socketio, camera, opencv_detector, yolo_detector,
                 live_detection_model, live_alert_model, coarse_limit=2.0,
                 fine_limit=0.5, hfov=42.0, vfov=24.0, rate_hz=15):
        self.app = app
        self.db = db
        self.socketio = socketio
        self.camera = camera
        self.LiveDetection = live_detection_model
        self.LiveAlert = live_alert_model
        self.coarse_limit = coarse_limit
        self.fine_limit = fine_limit
        self.hfov = hfov
        self.vfov = vfov
        self.rate_hz = rate_hz
        self._running = False
        self._thread = None
        self._tracker = YoloObjectTracker(
            weights_path='yolov8n.pt', conf=0.25, iou=0.45,
            min_area=160, max_area_ratio=0.35
        )
        self._sx = None
        self._sy = None
        self._px = None
        self._py = None
        self._pt = None
        self._last_seen = None
        self._was_locked = False
        self._lost_alert = False

    @property
    def is_running(self):
        return self._running

    @property
    def active_detector(self):
        return self._tracker.mode

    @property
    def yolo_available(self):
        return self._tracker.available

    def start(self):
        if self._running:
            return
        if not self.camera.start():
            raise RuntimeError(self.camera.error or 'Unable to open webcam')
        self._tracker.reset()
        self._sx = self._sy = self._px = self._py = self._pt = None
        self._last_seen = None
        self._was_locked = False
        self._lost_alert = False
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.5)
        self.camera.stop()
        self._tracker.reset()

    def _persist(self, source, cx, cy, he, ve, te, conf, phase):
        try:
            self.db.session.add(self.LiveDetection(
                timestamp=datetime.now(timezone.utc), source=source,
                cx=cx, cy=cy, h_error=he, v_error=ve,
                total_error=te, confidence=conf, phase=phase
            ))
            self.db.session.commit()
        except Exception:
            self.db.session.rollback()

    def _alert(self, severity, message):
        try:
            row = self.LiveAlert(
                timestamp=datetime.now(timezone.utc),
                severity=severity, message=message
            )
            self.db.session.add(row)
            self.db.session.commit()
            self.socketio.emit('live_alert', {
                'id': row.id, 'severity': severity,
                'message': message,
                'time': row.timestamp.strftime('%H:%M:%S')
            })
        except Exception:
            self.db.session.rollback()

    def _loop(self):
        with self.app.app_context():
            last_frame = time.perf_counter()
            fps = 0.0
            frames = 0
            fps_t = time.perf_counter()

            while self._running:
                started = time.perf_counter()
                frame = self.camera.get_frame()
                if frame is None:
                    time.sleep(0.03)
                    continue

                fh, fw = frame.shape[:2]
                dets = self._tracker.track(frame)
                frames += 1
                if time.perf_counter() - fps_t >= 1.0:
                    fps = frames / (time.perf_counter() - fps_t)
                    frames = 0
                    fps_t = time.perf_counter()

                if dets:
                    d = dets[0]
                    now = time.perf_counter()
                    self._last_seen = now
                    alpha = 0.40
                    self._sx = d['cx'] if self._sx is None else self._sx + alpha*(d['cx']-self._sx)
                    self._sy = d['cy'] if self._sy is None else self._sy + alpha*(d['cy']-self._sy)

                    if self._pt is None:
                        vx = vy = speed = 0.0
                    else:
                        dt = max(now - self._pt, 0.001)
                        vx = (self._sx - self._px) / dt
                        vy = (self._sy - self._py) / dt
                        speed = math.hypot(vx, vy)
                    self._px, self._py, self._pt = self._sx, self._sy, now

                    he, ve, te = pixel_to_angle(
                        self._sx, self._sy, fw, fh, self.hfov, self.vfov
                    )
                    phase = classify_phase(te, self.coarse_limit, self.fine_limit)
                    locked = phase == 'FINE LOCK'
                    px_deg_h = fw / self.hfov
                    px_deg_v = fh / self.vfov
                    av_h = vx / px_deg_h
                    av_v = -vy / px_deg_v
                    av = math.hypot(av_h, av_v)

                    payload = {
                        'found': True, 'source': d.get('method', 'opencv-motion'),
                        'label': d.get('label', 'moving-object'),
                        'track_id': d.get('track_id', 1),
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'cx': round(self._sx, 1), 'cy': round(self._sy, 1),
                        'frame_w': fw, 'frame_h': fh,
                        'box': {'x': d['x'], 'y': d['y'], 'w': d['w'], 'h': d['h']},
                        'h_error': round(he, 3), 'v_error': round(ve, 3),
                        'total_error': round(te, 3), 'phase': phase,
                        'confidence': round(d['confidence'], 1), 'locked': locked,
                        'coarse_limit': self.coarse_limit, 'fine_limit': self.fine_limit,
                        'camera_mode': self.camera.mode,
                        'velocity_px_s': round(speed, 1),
                        'velocity_x_px_s': round(vx, 1), 'velocity_y_px_s': round(vy, 1),
                        'angular_velocity_deg_s': round(av, 3),
                        'angular_velocity_h_deg_s': round(av_h, 3),
                        'angular_velocity_v_deg_s': round(av_v, 3),
                        'offset_px': round(math.hypot(self._sx-fw/2, self._sy-fh/2), 1),
                        'fps': round(fps, 1),
                    }

                    self._persist(payload['source'], self._sx, self._sy, he, ve, te, d['confidence'], phase)
                    if locked and not self._was_locked:
                        self._alert('SUCCESS', f'Live target lock acquired · error {te:.2f}°')
                    self._was_locked = locked
                    self._lost_alert = False
                    self.socketio.emit('tracking_update', payload)
                else:
                    self.socketio.emit('tracking_update', {
                        'found': False,
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'camera_mode': self.camera.mode,
                        'source': self.active_detector,
                        'fps': round(fps, 1)
                    })
                    if self._last_seen and time.perf_counter()-self._last_seen > 1.0 and not self._lost_alert:
                        self._alert('WARNING', 'Live target lost · reacquisition in progress')
                        self._was_locked = False
                        self._lost_alert = True

                delay = (1.0/self.rate_hz) - (time.perf_counter()-started)
                if delay > 0:
                    time.sleep(delay)
