"""Camera frame source for the Live AI Camera.

Supports two modes:

1. Local/server webcam:
   Uses OpenCV VideoCapture(0).
   Useful when running the Flask app directly on a machine
   that has a webcam.

2. Browser webcam:
   The browser opens the user's webcam with getUserMedia().
   Browser frames are POSTed to Flask and stored here.
   This is the mode used on Render.
"""

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

    # =========================================================
    # LOCAL / SERVER WEBCAM
    # =========================================================

    def _open(self):
        candidates = [
            lambda: cv2.VideoCapture(
                self.cam_index,
                cv2.CAP_DSHOW
            ),
            lambda: cv2.VideoCapture(
                self.cam_index
            ),
        ]

        for make_cap in candidates:
            try:
                cap = make_cap()

                if cap is not None and cap.isOpened():

                    cap.set(
                        cv2.CAP_PROP_FRAME_WIDTH,
                        self.width
                    )

                    cap.set(
                        cv2.CAP_PROP_FRAME_HEIGHT,
                        self.height
                    )

                    ok, frame = cap.read()

                    if ok and frame is not None:

                        frame = cv2.resize(
                            frame,
                            (self.width, self.height)
                        )

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
            self.error = (
                'Webcam could not be opened. '
                'Check camera permission or another app '
                'using the camera.'
            )

        return False

    def start(self):
        """Start a real OpenCV/server webcam.

        Kept for local development.
        Render should use start_browser().
        """

        if self._running:
            return True

        if not self._open():
            return False

        self._running = True

        self._thread = threading.Thread(
            target=self._loop,
            daemon=True
        )

        self._thread.start()

        return True

    # =========================================================
    # BROWSER WEBCAM
    # =========================================================

    def start_browser(self):
        """Start browser-fed camera mode.

        The actual webcam is opened by JavaScript in the user's
        browser. Frames are then POSTed to /api/live/frame.
        """

        # Stop any previous camera source.
        self.stop()

        self.cap = None
        self.error = None
        self.mode = 'browser'

        # LiveEngine will use get_frame() while this is True.
        self._running = True

        with self._lock:
            self._frame = None

        return True

    def submit_frame(self, frame):
        """Accept one frame received from the browser."""

        if frame is None:
            return False

        try:
            frame = cv2.resize(
                frame,
                (self.width, self.height)
            )
        except Exception as exc:
            self.error = str(exc)
            return False

        with self._lock:
            self._frame = frame

        self.error = None

        return True

    # =========================================================
    # STOP
    # =========================================================

    def stop(self):
        self._running = False

        if self._thread is not None:
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass

        self._thread = None

        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass

            self.cap = None

        with self._lock:
            self._frame = None

        self.mode = 'offline'

    # =========================================================
    # LOCAL CAMERA LOOP
    # =========================================================

    def _loop(self):
        while self._running:

            ok, frame = (
                self.cap.read()
                if self.cap is not None
                else (False, None)
            )

            if ok and frame is not None:

                frame = cv2.resize(
                    frame,
                    (self.width, self.height)
                )

                with self._lock:
                    self._frame = frame

            else:
                time.sleep(0.05)

    # =========================================================
    # FRAME ACCESS
    # =========================================================

    def get_frame(self):
        with self._lock:

            if self._frame is None:
                return None

            return self._frame.copy()

    def get_jpeg(self):
        frame = self.get_frame()

        if frame is None:
            return None

        ok, buf = cv2.imencode(
            '.jpg',
            frame,
            [
                int(
                    cv2.IMWRITE_JPEG_QUALITY
                ),
                82
            ]
        )

        return buf.tobytes() if ok else None
