"""Separate camera source for the Live Demo Camera."""
import math
import threading
import time

import cv2
import numpy as np


class DemoCamera:
    """
    Independent from VideoCamera.

    When a webcam exists, the demo uses the real webcam and the YOLO tracker.
    When no webcam exists, it switches to a distinct moving-object scene and
    exposes deterministic synthetic object boxes to DemoObjectEngine. This
    makes the hackathon demo usable even on a PC with no camera attached.
    """
    def __init__(self, width=960, height=540, cam_index=0):
        self.width = width
        self.height = height
        self.cam_index = cam_index
        self.mode = 'stopped'
        self.cap = None
        self._t = 0
        self._running = False
        self._thread = None
        self._frame = None
        self._lock = threading.Lock()
        self._synthetic_objects = []

    def _open_real_camera(self):
        try:
            cap = cv2.VideoCapture(self.cam_index)
            if cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None:
                    self.cap = cap
                    self.mode = 'camera'
                    return True
                cap.release()
            elif cap is not None:
                cap.release()
        except Exception:
            pass
        self.cap = None
        self.mode = 'synthetic'
        return False

    def start(self):
        if self._running:
            return
        self._open_real_camera()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        thread = self._thread
        self._thread = None
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None
        self.mode = 'stopped'
        with self._lock:
            self._frame = None
            self._synthetic_objects = []

    def _synthetic_frame(self):
        self._t += 1
        t = self._t
        w, h = self.width, self.height
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = (30, 30, 30)
        cv2.rectangle(img, (0, 0), (w, int(h * 0.58)), (48, 48, 48), -1)
        cv2.rectangle(img, (0, int(h * 0.58)), (w, h), (24, 24, 24), -1)

        for y in range(int(h * 0.62), h, 44):
            cv2.line(img, (0, y), (w, y), (58, 58, 58), 1)
        for x in range(-w, 2 * w, 120):
            cv2.line(img, (w // 2, int(h * 0.56)), (x, h), (50, 50, 50), 1)
        for x in (110, 310, 650, 850):
            cv2.rectangle(img, (x, 55), (x + 80, 180), (58, 58, 58), 2)

        car_x = int(120 + (t * 3.2) % 760)
        car_y = int(360 + 18 * math.sin(t / 16.0))
        ball_x = int(180 + (t * 4.6) % 620)
        ball_y = int(255 + 58 * math.sin(t / 12.0))
        bottle_x = int(690 + 65 * math.sin(t / 20.0))
        bottle_y = int(225 + 30 * math.cos(t / 17.0))

        objects = []

        # Track 1: car
        x1, y1, x2, y2 = car_x, car_y, car_x + 120, car_y + 62
        cv2.rectangle(img, (x1, y1), (x2, y2), (70, 155, 220), -1)
        cv2.rectangle(img, (x1 + 22, y1 - 25), (x1 + 78, y1 + 4), (100, 185, 235), -1)
        cv2.circle(img, (x1 + 25, y2), 14, (12, 12, 12), -1)
        cv2.circle(img, (x2 - 25, y2), 14, (12, 12, 12), -1)
        objects.append({'track_id': 1, 'class_id': 2, 'label': 'car', 'confidence': 96.0,
                        'x': float(x1), 'y': float(y1 - 25), 'w': 120.0, 'h': 87.0,
                        'cx': float(x1 + 60), 'cy': float(y1 + 31)})

        # Track 2: sports ball
        bx, by = ball_x, ball_y
        cv2.circle(img, (bx, by), 30, (70, 205, 110), -1)
        cv2.circle(img, (bx - 9, by - 9), 8, (170, 240, 180), -1)
        objects.append({'track_id': 2, 'class_id': 32, 'label': 'sports ball', 'confidence': 94.0,
                        'x': float(bx - 30), 'y': float(by - 30), 'w': 60.0, 'h': 60.0,
                        'cx': float(bx), 'cy': float(by)})

        # Track 3: bottle
        vx, vy = bottle_x, bottle_y
        cv2.rectangle(img, (vx - 15, vy - 40), (vx + 15, vy + 42), (190, 120, 65), -1)
        cv2.rectangle(img, (vx - 9, vy - 55), (vx + 9, vy - 39), (215, 160, 90), -1)
        objects.append({'track_id': 3, 'class_id': 39, 'label': 'bottle', 'confidence': 91.0,
                        'x': float(vx - 18), 'y': float(vy - 55), 'w': 36.0, 'h': 97.0,
                        'cx': float(vx), 'cy': float(vy - 6)})

        cv2.putText(img, 'LIVE DEMO · GENERIC OBJECT TRACKING', (18, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (235, 235, 235), 2, cv2.LINE_AA)
        cv2.putText(img, 'SYNTHETIC OBJECT SCENE · PERSON CLASS DISABLED', (18, h - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 205, 230), 1, cv2.LINE_AA)

        with self._lock:
            self._synthetic_objects = objects
        return img

    def _loop(self):
        while self._running:
            frame = None
            if self.cap is not None:
                try:
                    ok, frame = self.cap.read()
                    if not ok:
                        frame = None
                except Exception:
                    frame = None
            if frame is None:
                if self.mode == 'camera':
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None
                    self.mode = 'synthetic'
                frame = self._synthetic_frame()
            else:
                with self._lock:
                    self._synthetic_objects = []
                frame = cv2.resize(frame, (self.width, self.height))

            with self._lock:
                self._frame = frame.copy()
            time.sleep(1.0 / 30.0)

    def get_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def get_jpeg(self):
        frame = self.get_frame()
        if frame is None:
            return None
        ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        return buf.tobytes() if ok else None

    def get_synthetic_objects(self):
        with self._lock:
            return [dict(o) for o in self._synthetic_objects]
