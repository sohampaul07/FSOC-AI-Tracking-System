"""
Geometry helpers shared by the live AI camera pipeline.

Converts a detected pixel centroid into horizontal/vertical angular error
(degrees) relative to the frame's optical center (boresight), using the
camera's field of view — the same convention already used by the
simulator in app.py, so both subsystems agree on what "2deg coarse gate"
and "0.5deg fine gate" mean.
"""
from math import sqrt


def pixel_to_angle(cx, cy, frame_w, frame_h, hfov_deg=42.0, vfov_deg=24.0):
    """cx, cy: pixel coords (origin top-left). Returns (h_err_deg, v_err_deg, total_err_deg)."""
    if frame_w <= 0 or frame_h <= 0:
        return 0.0, 0.0, 0.0
    h_err = ((cx - frame_w / 2.0) / (frame_w / 2.0)) * (hfov_deg / 2.0)
    # image y grows downward, so invert to get a conventional "up is positive" vertical error
    v_err = -((cy - frame_h / 2.0) / (frame_h / 2.0)) * (vfov_deg / 2.0)
    total_err = sqrt(h_err * h_err + v_err * v_err)
    return h_err, v_err, total_err


def classify_phase(total_err_deg, coarse_limit=2.0, fine_limit=0.5):
    """Mirrors the phase ladder used by the simulator (app.py: compute_reading)."""
    if total_err_deg > 12:
        return 'SEARCHING'
    if total_err_deg > 6:
        return 'ACQUISITION'
    if total_err_deg > coarse_limit:
        return 'COARSE ALIGNMENT'
    if total_err_deg > fine_limit:
        return 'FINE ALIGNMENT'
    return 'FINE LOCK'
