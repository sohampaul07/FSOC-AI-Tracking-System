"""Robust arbitrary moving-object tracker for the Live AI Camera.

The tracker deliberately does NOT let generic YOLO detections hijack the target.
It first acquires a moving object with background subtraction, then keeps the
same target with an OpenCV CSRT/KCF tracker. If the target is lost it searches
again. This works for arbitrary objects such as a pendulum, bottle cap, etc.
"""
import math
import time
import cv2
import numpy as np


class YoloObjectTracker:
    def __init__(self, weights_path=None, conf=0.25, iou=0.45,
                 min_area=120, max_area_ratio=0.25):
        self.weights_path = weights_path
        self.conf = conf
        self.iou = iou
        self.min_area = min_area
        self.max_area_ratio = max_area_ratio

        self.track_id = 1
        self.tracker = None
        self.tracker_kind = "none"
        self.tracking = False
        self.previous_center = None
        self.previous_box = None
        self.last_seen = 0.0
        self.missed = 0
        self.frames_since_acquire = 0

        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=180,
            varThreshold=28,
            detectShadows=False
        )

        self.kernel = np.ones((5, 5), np.uint8)

    @property
    def available(self):
        return False

    @property
    def yolo_available(self):
        return False

    @property
    def active_weights(self):
        return None

    @property
    def mode(self):
        return "OpenCV Motion + CSRT"

    def reset(self):
        self.tracker = None
        self.tracker_kind = "none"
        self.tracking = False
        self.previous_center = None
        self.previous_box = None
        self.last_seen = 0.0
        self.missed = 0
        self.frames_since_acquire = 0
        self.track_id = 1
        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=180,
            varThreshold=28,
            detectShadows=False
        )

    def _make_tracker(self):
        makers = []
        if hasattr(cv2, "TrackerCSRT_create"):
            makers.append(("CSRT", cv2.TrackerCSRT_create))
        if hasattr(cv2, "legacy"):
            if hasattr(cv2.legacy, "TrackerCSRT_create"):
                makers.append(("CSRT", cv2.legacy.TrackerCSRT_create))
            if hasattr(cv2.legacy, "TrackerKCF_create"):
                makers.append(("KCF", cv2.legacy.TrackerKCF_create))
        if hasattr(cv2, "TrackerKCF_create"):
            makers.append(("KCF", cv2.TrackerKCF_create))
        for name, maker in makers:
            try:
                return maker(), name
            except Exception:
                pass
        return None, "none"

    def _valid_box(self, box, fw, fh):
        x, y, w, h = [float(v) for v in box]
        x = max(0.0, min(x, fw - 2.0))
        y = max(0.0, min(y, fh - 2.0))
        w = min(w, fw - x)
        h = min(h, fh - y)
        area = w * h
        if w < 8 or h < 8:
            return None
        if area < self.min_area or area > fw * fh * self.max_area_ratio:
            return None
        return x, y, w, h

    def _motion_candidates(self, frame):
        mask = self.bg.apply(frame, learningRate=0.008)
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=2)
        mask = cv2.dilate(mask, self.kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        fh, fw = mask.shape
        candidates = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < self.min_area or area > fw * fh * self.max_area_ratio:
                continue
            x, y, w, h = cv2.boundingRect(c)
            box = self._valid_box((x, y, w, h), fw, fh)
            if box is None:
                continue
            x, y, w, h = box
            cx, cy = x + w / 2.0, y + h / 2.0

            # Prefer the object near the previous target when reacquiring.
            score = area
            if self.previous_center is not None:
                dist = math.hypot(cx - self.previous_center[0], cy - self.previous_center[1])
                score *= 1.0 + max(0.0, 1.0 - dist / max(fw, fh)) * 5.0

            # Prefer compact objects over a huge moving background region.
            compactness = min(1.0, area / max(1.0, w * h))
            score *= 0.8 + 0.4 * compactness
            candidates.append((score, area, x, y, w, h, cx, cy))

        return candidates

    def _acquire(self, frame):
        fh, fw = frame.shape[:2]
        candidates = self._motion_candidates(frame)
        if not candidates:
            return None

        _, area, x, y, w, h, cx, cy = max(candidates, key=lambda v: v[0])

        # Expand the acquisition box slightly so CSRT has texture around the target.
        pad = max(4, int(min(w, h) * 0.18))
        x = max(0, x - pad)
        y = max(0, y - pad)
        w = min(fw - x, w + 2 * pad)
        h = min(fh - y, h + 2 * pad)

        tracker, kind = self._make_tracker()
        if tracker is not None:
            try:
                tracker.init(frame, (float(x), float(y), float(w), float(h)))
                self.tracker = tracker
                self.tracker_kind = kind
                self.tracking = True
            except Exception:
                self.tracker = None
                self.tracker_kind = "none"
                self.tracking = False

        self.previous_center = (x + w / 2.0, y + h / 2.0)
        self.previous_box = (x, y, w, h)
        self.last_seen = time.perf_counter()
        self.missed = 0
        self.frames_since_acquire = 0

        return self._result(x, y, w, h, 78.0, "moving-object")

    def _result(self, x, y, w, h, confidence, label):
        cx = x + w / 2.0
        cy = y + h / 2.0
        return {
            "track_id": self.track_id,
            "class_id": -1,
            "label": label,
            "confidence": float(max(1.0, min(99.0, confidence))),
            "x": float(x),
            "y": float(y),
            "w": float(w),
            "h": float(h),
            "cx": float(cx),
            "cy": float(cy),
            "method": "opencv-csrt" if self.tracking else "opencv-motion",
        }

    def _track_existing(self, frame):
        if not self.tracking or self.tracker is None:
            return None
        try:
            ok, box = self.tracker.update(frame)
        except Exception:
            ok = False
            box = None
        if not ok or box is None:
            return None

        fh, fw = frame.shape[:2]
        valid = self._valid_box(box, fw, fh)
        if valid is None:
            return None

        x, y, w, h = valid
        cx, cy = x + w / 2.0, y + h / 2.0
        jump = 0.0
        if self.previous_center is not None:
            jump = math.hypot(cx - self.previous_center[0], cy - self.previous_center[1])
            max_jump = max(120.0, max(fw, fh) * 0.30)
            if jump > max_jump:
                return None

        self.previous_center = (cx, cy)
        self.previous_box = (x, y, w, h)
        self.last_seen = time.perf_counter()
        self.missed = 0
        self.frames_since_acquire += 1

        # Confidence gently decays when tracker runs without a correction.
        conf = max(55.0, 94.0 - min(30.0, self.frames_since_acquire * 0.35))
        return self._result(x, y, w, h, conf, "moving-object")

    def track(self, frame):
        if self.tracking:
            result = self._track_existing(frame)
            if result is not None:
                return [result]

            self.missed += 1
            if self.missed <= 5:
                return []

            self.tracker = None
            self.tracker_kind = "none"
            self.tracking = False
            self.missed = 0

        result = self._acquire(frame)
        if result is not None:
            return [result]

        return []
