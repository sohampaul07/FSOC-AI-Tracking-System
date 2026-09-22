"""Computer-vision adapters for the FSOC tracking prototype.

The default implementation is deterministic and dependency-light so the demo runs
without a camera or model weights. When enabled, OpenCV can preprocess camera
frames and Ultralytics YOLO can provide real detections from a custom model.
"""
from dataclasses import dataclass
from typing import Any, Optional
import os
import numpy as np

try:
    import cv2
except ImportError:  # optional at import time
    cv2 = None

try:
    from ultralytics import YOLO
except ImportError:  # optional because model packages are large
    YOLO = None


@dataclass
class Detection:
    detected: bool
    label: str = "FSOC_TERMINAL"
    confidence: float = 0.0
    x: float = 640.0
    y: float = 360.0
    width: float = 74.0
    height: float = 74.0
    source: str = "simulation"


class FSOCVision:
    """Camera/YOLO adapter with a safe simulation fallback."""

    def __init__(self, model_path: Optional[str] = None, target_label: str = "FSOC_TERMINAL"):
        self.target_label = target_label
        self.model_path = model_path or os.getenv("FSOC_YOLO_MODEL", "")
        self.model = None
        self.mode = "simulation"
        if self.model_path and YOLO is not None and os.path.exists(self.model_path):
            self.model = YOLO(self.model_path)
            self.mode = "yolo"

    @staticmethod
    def preprocess(frame: Any) -> Any:
        """Apply a modest OpenCV enhancement pipeline when a frame is available."""
        if frame is None or cv2 is None:
            return frame
        image = np.asarray(frame)
        if image.ndim != 3:
            return image
        denoised = cv2.GaussianBlur(image, (3, 3), 0)
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return cv2.cvtColor(cv2.merge((clahe.apply(l), a, b)), cv2.COLOR_LAB2BGR)

    def detect(self, frame: Any = None) -> Detection:
        if self.model is None or frame is None:
            return Detection(detected=True, confidence=0.97, source=self.mode)
        results = self.model.predict(source=self.preprocess(frame), verbose=False, conf=0.25)
        best = None
        for result in results:
            names = result.names
            for box in result.boxes:
                cls_id = int(box.cls[0])
                label = str(names.get(cls_id, cls_id))
                confidence = float(box.conf[0])
                if best is None or confidence > best[0]:
                    coords = box.xyxy[0].tolist()
                    best = (confidence, label, coords)
        if best is None:
            return Detection(False, label=self.target_label, source="yolo")
        confidence, label, (x1, y1, x2, y2) = best
        return Detection(True, label, confidence, (x1+x2)/2, (y1+y2)/2, x2-x1, y2-y1, "yolo")

    @staticmethod
    def angular_error(target_x: float, target_y: float, width: int = 1280, height: int = 720,
                      hfov: float = 42.0, vfov: float = 24.0) -> dict:
        """Convert a target centroid from image coordinates into angular error."""
        h = (float(target_x) - width / 2) / width * hfov
        v = (height / 2 - float(target_y)) / height * vfov
        return {"horizontal": h, "vertical": v, "total": float(np.hypot(h, v))}


vision = FSOCVision()
