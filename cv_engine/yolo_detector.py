"""
Optional deep-learning detector for the FSOC terminal/beacon, built on
Ultralytics YOLO (which itself runs on PyTorch).

Honesty note: a stock pretrained YOLO checkpoint (COCO classes) has no
"FSOC terminal" class, so out of the box it will not meaningfully
out-detect the classical OpenCV bright-spot detector. This module is
built so you can drop in your own weights once you have one:

    1. Label a small dataset of your beacon/terminal (Roboflow or
       LabelImg both export YOLO-format labels quickly).
    2. Train:  yolo detect train data=your_data.yaml model=yolov8n.pt epochs=50
    3. Copy the resulting best.pt into fsoc_v7/models/best.pt
    4. Restart the app — this module auto-loads it if present.

If ultralytics/torch are not installed, or no camera-plausible model is
available, `available` is False and live_engine.py transparently falls
back to the OpenCV detector — the live pipeline still runs end-to-end.
"""
import os

try:
    from ultralytics import YOLO
    _ULTRALYTICS_OK = True
except Exception:
    _ULTRALYTICS_OK = False


class YoloBeaconDetector:
    def __init__(self, weights_path=None, conf=0.25):
        self.available = False
        self.model = None
        self.conf = conf
        self.weights_path = weights_path

        if not _ULTRALYTICS_OK:
            return

        try:
            path = weights_path if weights_path and os.path.exists(weights_path) else 'yolov8n.pt'
            self.model = YOLO(path)
            self.available = True
            self.using_custom_weights = bool(weights_path and os.path.exists(weights_path))
        except Exception:
            self.available = False
            self.model = None

    def detect(self, frame_bgr):
        """Returns a dict with cx, cy, x, y, w, h, confidence, method — or None if unavailable/no detection."""
        if not self.available or self.model is None:
            return None
        try:
            results = self.model.predict(frame_bgr, conf=self.conf, verbose=False)
        except Exception:
            return None
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return None

        boxes = results[0].boxes
        best_idx = int(boxes.conf.argmax())
        x1, y1, x2, y2 = [float(v) for v in boxes.xyxy[best_idx]]
        confidence = float(boxes.conf[best_idx]) * 100.0
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0

        return {
            'cx': cx, 'cy': cy, 'x': x1, 'y': y1, 'w': x2 - x1, 'h': y2 - y1,
            'confidence': confidence, 'method': 'yolo',
        }
