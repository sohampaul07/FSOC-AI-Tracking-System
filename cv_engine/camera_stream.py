"""Real webcam capture for the Live AI Camera."""
import threading
import time
import cv2


class VideoCamera:
    def __init__(self, width=960, height=540, cam_index=0):
        self.width = width
        self.height = height
        self.cam_index = cam_index
        self.mode = 'offline'
        self.error = None
        self.cap = None
        self._lock = threading.Lock()
        self._frame = None
        self._running = False
        self._thread = None

    def _open(self):
        candidates = [
            lambda: cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW),
            lambda: cv2.VideoCapture(self.cam_index),
        ]
        for make_cap in candidates:
            try:
                cap = make_cap()
                if cap is not None and cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        self.cap = cap
                        self.mode = 'camera'
                        self.error = None
                        with self._lock:
                            self._frame = frame
                        return True
                if cap is not None:
                    cap.release()
            except Exception as exc:
                self.error = str(exc)
        self.mode = 'offline'
        if not self.error:
            self.error = 'Webcam could not be opened. Check camera permission or another app using the camera.'
        return False

    def start(self):
        if self._running:
            return True
        if not self._open():
            return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.mode = 'offline'

    def _loop(self):
        while self._running:
            ok, frame = self.cap.read() if self.cap is not None else (False, None)
            if ok and frame is not None:
                frame = cv2.resize(frame, (self.width, self.height))
                with self._lock:
                    self._frame = frame
            else:
                time.sleep(0.05)

    def get_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def get_jpeg(self):
        frame = self.get_frame()
        if frame is None:
            return None
        ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        return buf.tobytes() if ok else None
