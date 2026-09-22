"""
Classical computer-vision detector for an FSOC optical beacon.

Approach: the beacon/LED on an FSOC terminal is, by design, the brightest
and most saturated point source in the frame — the same "bright-spot
centroid" principle used in real optical beacon trackers, star trackers,
and laser-designator seekers. This makes it a legitimate and fast
(CPU-only, no GPU needed) primary detector, independent of whether a
deep-learning model is installed.

Pipeline: grayscale -> Gaussian blur -> brightness threshold -> contour
extraction -> pick the largest/brightest contour -> centroid via image
moments -> confidence heuristic from blob size + circularity.
"""
import cv2
import numpy as np


class OpenCVBeaconDetector:
    def __init__(self, brightness_thresh=200, min_area=8):
        self.brightness_thresh = brightness_thresh
        self.min_area = min_area

    def detect(self, frame_bgr):
        """Returns a dict with cx, cy, x, y, w, h, area, confidence, method — or None if no beacon found."""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (9, 9), 0)
        _, mask = cv2.threshold(blur, self.brightness_thresh, 255, cv2.THRESH_BINARY)
        mask = cv2.dilate(mask, None, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        c = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(c)
        if area < self.min_area:
            return None

        m = cv2.moments(c)
        if m['m00'] == 0:
            return None
        cx = m['m10'] / m['m00']
        cy = m['m01'] / m['m00']
        x, y, w, h = cv2.boundingRect(c)

        (_, _), radius = cv2.minEnclosingCircle(c)
        circularity = float(area / (np.pi * (radius ** 2) + 1e-6))
        confidence = float(np.clip(55 + circularity * 35 + min(area, 400) / 400 * 10, 0, 99.5))

        return {
            'cx': cx, 'cy': cy, 'x': x, 'y': y, 'w': w, 'h': h,
            'area': area, 'confidence': confidence, 'method': 'opencv',
        }
