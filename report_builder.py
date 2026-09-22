"""
Builds the FSOC performance PDF report.

Deliberately DB-agnostic: takes plain dicts/lists so it can be unit
tested without a database, and so app.py stays a thin wrapper that just
queries the DB and calls build_report_pdf().
"""
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


def _header(c, title, subtitle):
    y = PAGE_H - 20 * mm
    c.setFont('Helvetica-Bold', 17)
    c.setFillColor(colors.HexColor('#12233f'))
    c.drawString(MARGIN, y, title)
    y -= 7 * mm
    c.setFont('Helvetica', 9.5)
    c.setFillColor(colors.HexColor('#4a5d75'))
    c.drawString(MARGIN, y, subtitle)
    y -= 4 * mm
    c.setStrokeColor(colors.HexColor('#dde6f0'))
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    return y - 9 * mm


def _footer(c, page_label):
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.HexColor('#93a3b8'))
    c.drawString(MARGIN, 12 * mm, 'TRACKAI · SIH 26169 · FSOC Terminal Tracking System')
    c.drawRightString(PAGE_W - MARGIN, 12 * mm, page_label)


def _draw_line_chart(c, x, y, w, h, values, y_max, line_color, label, unit_note, threshold_lines=None):
    c.setStrokeColor(colors.HexColor('#c7d2df'))
    c.setLineWidth(0.6)
    c.rect(x, y, w, h, stroke=1, fill=0)
    for i in range(1, 4):
        gy = y + h * i / 4
        c.setStrokeColor(colors.HexColor('#eef2f7'))
        c.line(x, gy, x + w, gy)

    if threshold_lines:
        for tv, tcolor, tlabel in threshold_lines:
            if tv > y_max:
                continue
            ty = y + h * min(tv / y_max, 1.0)
            c.setStrokeColor(colors.HexColor(tcolor))
            c.setDash(3, 2)
            c.setLineWidth(0.7)
            c.line(x, ty, x + w, ty)
            c.setDash()
            c.setFont('Helvetica', 6)
            c.setFillColor(colors.HexColor(tcolor))
            c.drawString(x + w + 2, ty - 2, tlabel)

    if values:
        c.setStrokeColor(colors.HexColor(line_color))
        c.setLineWidth(1.3)
        n = len(values)
        pts = []
        for i, v in enumerate(values):
            px = x + (w * i / max(n - 1, 1))
            py = y + h * min(max(v, 0) / y_max, 1.0)
            pts.append((px, py))
        p = c.beginPath()
        p.moveTo(*pts[0])
        for pt in pts[1:]:
            p.lineTo(*pt)
        c.drawPath(p, stroke=1, fill=0)
    else:
        c.setFont('Helvetica-Oblique', 8)
        c.setFillColor(colors.HexColor('#93a3b8'))
        c.drawCentredString(x + w / 2, y + h / 2, 'No data logged yet for this session')

    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor('#33465e'))
    c.drawString(x, y + h + 3, label)
    c.setFont('Helvetica', 6)
    c.setFillColor(colors.HexColor('#7c8ba1'))
    c.drawString(x, y - 8, unit_note)


def _before_after_table(c, x, y, w, before, after, rows):
    """rows: list of (label, before_key, after_key, fmt, better) where better is 'lower' or 'higher'."""
    col1 = x
    col2 = x + w * 0.42
    col3 = x + w * 0.68
    col4 = x + w * 0.86

    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor('#33465e'))
    c.drawString(col1, y, 'METRIC')
    c.drawString(col2, y, 'BEFORE (ACQUISITION)')
    c.drawString(col3, y, 'AFTER (LOCKED)')
    c.drawString(col4, y, 'CHANGE')
    y -= 4 * mm
    c.setStrokeColor(colors.HexColor('#dde6f0'))
    c.line(x, y, x + w, y)
    y -= 5 * mm

    for label, key, fmt, better in rows:
        bv = before.get(key)
        av = after.get(key)
        c.setFont('Helvetica', 9)
        c.setFillColor(colors.HexColor('#22324a'))
        c.drawString(col1, y, label)
        c.drawString(col2, y, fmt(bv) if bv is not None else '—')
        c.drawString(col3, y, fmt(av) if av is not None else '—')
        if bv is not None and av is not None:
            delta = av - bv
            improved = (delta < 0) if better == 'lower' else (delta > 0)
            arrow = ('↓' if delta < 0 else '↑') if delta != 0 else '→'
            c.setFillColor(colors.HexColor('#168548') if improved else colors.HexColor('#ad3d3d'))
            c.setFont('Helvetica-Bold', 9)
            c.drawString(col4, y, f'{arrow} {fmt(abs(delta))}')
        else:
            c.setFillColor(colors.HexColor('#93a3b8'))
            c.drawString(col4, y, '—')
        y -= 6.5 * mm
    return y


def _avg(vals, key):
    xs = [v[key] for v in vals if v.get(key) is not None]
    return sum(xs) / len(xs) if xs else None


def _summarize_edges(rows, n=5):
    """Returns (before, after) dicts averaging the first/last n rows of a chronological reading list."""
    if not rows:
        return {}, {}
    before_rows = rows[:n]
    after_rows = rows[-n:]
    before = {'total_error': _avg(before_rows, 'total_error'), 'confidence': _avg(before_rows, 'confidence')}
    after = {'total_error': _avg(after_rows, 'total_error'), 'confidence': _avg(after_rows, 'confidence')}
    return before, after


LASER_LINK_CHALLENGES = [
    ("Pointing / tracking error", "Beam divergence over long ranges means even sub-mrad mispointing misses the receiver aperture entirely.",
     "Closed-loop coarse->fine gated tracking (this system's core function): coarse acquisition ≤2° then fine lock ≤0.5°, continuously re-corrected."),
    ("Platform vibration & micro-jitter", "Satellite bus vibration, reaction wheels and thermal snap induce continuous angular jitter on the optical bench.",
     "Fast inner control loop (fine-steering mirror / gimbal) with bandwidth well above the disturbance spectrum; vibration isolation mounts."),
    ("Atmospheric turbulence & scintillation", "For ground-to-space or air-to-ground links, turbulence causes beam wander, scintillation fading and angle-of-arrival noise.",
     "Adaptive optics, spatial diversity (multiple receive apertures), and larger link margin budgeted for fade statistics."),
    ("Acquisition time / re-acquisition after occlusion", "Long search times after signal loss (occlusion, maneuver, fade) reduce effective link availability.",
     "Wide-FOV coarse search pattern with fast beacon detection (this system's SEARCHING→ACQUISITION phase), predictive pointing from orbit ephemeris."),
    ("Beam divergence vs. link budget trade-off", "Narrower beams need less power but demand tighter pointing; wider beams relax pointing but lose power density.",
     "System-level trade study balancing pointing accuracy achievable against required divergence and transmit power."),
    ("Relative velocity / Doppler & lead-ahead angle", "Fast relative motion between satellites requires transmitting slightly ahead of the receiver's true position.",
     "Orbit-propagator-driven lead-angle compensation feeding the pointing controller in addition to the vision-based correction."),
    ("Thermal-optical drift", "Thermal cycling in orbit shifts optical alignment (boresight drift) between the tracking sensor and the transmit laser.",
     "Periodic boresight calibration cycles and temperature-compensated optical mounts."),
    ("Background / solar interference", "Sunlit backgrounds or stray light can saturate the tracking sensor or mimic a bright beacon.",
     "Narrowband spectral filtering matched to the beacon wavelength, plus the brightness/circularity confidence heuristic used by this system's detector."),
    ("Clock synchronization & timing jitter", "Coarse pointing windows and beacon scheduling need tight time sync between terminals.",
     "GNSS-disciplined or inter-satellite time-transfer synchronization with margin built into the acquisition window."),
]


def build_report_pdf(path, kpi, sim_readings, live_detections, live_meta=None,
                      coarse_limit=2.0, fine_limit=0.5):
    """
    kpi: {'sessions':int,'samples':int,'avg_error':float,'fine_lock_rate':float}
    sim_readings: chronological list of dicts with total_error, confidence, phase (simulator Reading rows)
    live_detections: chronological list of dicts with total_error, confidence, phase, source (LiveDetection rows)
    live_meta: optional {'detector':str,'camera_mode':str}
    """
    live_meta = live_meta or {}
    c = canvas.Canvas(path, pagesize=A4)

    # ---------------- Page 1: Overview ----------------
    y = _header(c, 'TRACKAI · SIH 26169 — FSOC Performance Report',
                'AI-based virtual camera tracking and coarse/fine optical alignment — summary for review')

    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(colors.HexColor('#12233f'))
    c.drawString(MARGIN, y, 'Key Performance Indicators — Simulated Scenario Mode')
    y -= 7 * mm
    c.setFont('Helvetica', 9.5)
    c.setFillColor(colors.HexColor('#22324a'))
    for label, val in [('Sessions run', kpi.get('sessions', 0)), ('Samples logged', kpi.get('samples', 0)),
                        ('Average total error', f"{kpi.get('avg_error', 0)}°"),
                        ('Fine-lock sample rate', f"{kpi.get('fine_lock_rate', 0)}%")]:
        c.drawString(MARGIN + 2 * mm, y, f'{label}:')
        c.setFont('Helvetica-Bold', 9.5)
        c.drawString(MARGIN + 55 * mm, y, str(val))
        c.setFont('Helvetica', 9.5)
        y -= 6 * mm

    y -= 4 * mm
    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(colors.HexColor('#12233f'))
    c.drawString(MARGIN, y, 'Alignment Workflow')
    y -= 7 * mm
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.HexColor('#22324a'))
    for line in ['AI detection -> target lock -> H/V error estimation -> LEFT/RIGHT/UP/DOWN guidance',
                 f'Coarse alignment gate <= {coarse_limit}\u00b0 -> fine alignment -> automatic fine lock <= {fine_limit}\u00b0',
                 'All tracking readings, commands, alerts and events are persisted in SQLite.',
                 'A second, independent pipeline (below) runs real OpenCV/YOLO computer-vision detection on a live camera feed.']:
        c.drawString(MARGIN + 2 * mm, y, '\u2022 ' + line)
        y -= 5.5 * mm

    y -= 6 * mm
    before, after = _summarize_edges(sim_readings, n=5)
    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(colors.HexColor('#12233f'))
    c.drawString(MARGIN, y, 'Before vs. After Alignment — Simulated Scenario')
    y -= 8 * mm
    y = _before_after_table(c, MARGIN, y, PAGE_W - 2 * MARGIN, before, after, rows=[
        ('Total angular error (°)', 'total_error', lambda v: f'{v:.2f}\u00b0', 'lower'),
        ('AI confidence (%)', 'confidence', lambda v: f'{v:.1f}%', 'higher'),
    ])
    y -= 6 * mm
    chart_h = 42 * mm
    _draw_line_chart(c, MARGIN, y - chart_h, PAGE_W - 2 * MARGIN - 15 * mm, chart_h,
                      [r['total_error'] for r in sim_readings][-120:], max(coarse_limit * 3, 4),
                      '#1769e0', 'Total Angular Error Over Session (simulated)', 'Most recent readings, left -> right',
                      threshold_lines=[(coarse_limit, '#e08a1e', f'Coarse {coarse_limit}\u00b0'),
                                        (fine_limit, '#1e9e5e', f'Fine {fine_limit}\u00b0')])
    _footer(c, 'Page 1 / 3')
    c.showPage()

    # ---------------- Page 2: Live AI Camera pipeline ----------------
    y = _header(c, 'Live AI Camera Pipeline', 'Real OpenCV / YOLO computer-vision detection results — not simulated')
    lbefore, lafter = _summarize_edges(live_detections, n=10)

    c.setFont('Helvetica', 9.5)
    c.setFillColor(colors.HexColor('#22324a'))
    detector = live_meta.get('detector', 'opencv').upper()
    camera_mode = live_meta.get('camera_mode', 'synthetic').upper()
    c.drawString(MARGIN, y, f'Active detector: {detector}    ·    Camera source: {camera_mode}    ·    Logged detections: {len(live_detections)}')
    y -= 9 * mm

    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(colors.HexColor('#12233f'))
    c.drawString(MARGIN, y, 'Before vs. After Alignment — Live Camera')
    y -= 8 * mm
    y = _before_after_table(c, MARGIN, y, PAGE_W - 2 * MARGIN, lbefore, lafter, rows=[
        ('Total angular error (°)', 'total_error', lambda v: f'{v:.2f}\u00b0', 'lower'),
        ('AI confidence (%)', 'confidence', lambda v: f'{v:.1f}%', 'higher'),
    ])
    y -= 6 * mm
    chart_h = 42 * mm
    _draw_line_chart(c, MARGIN, y - chart_h, PAGE_W - 2 * MARGIN - 15 * mm, chart_h,
                      [r['total_error'] for r in live_detections][-120:], max(coarse_limit * 3, 4),
                      '#8a3ffc', 'Total Angular Error Over Time (live camera)', 'Most recent detections, left -> right',
                      threshold_lines=[(coarse_limit, '#e08a1e', f'Coarse {coarse_limit}\u00b0'),
                                        (fine_limit, '#1e9e5e', f'Fine {fine_limit}\u00b0')])
    y -= chart_h + 18 * mm

    if not live_detections:
        c.setFont('Helvetica-Oblique', 8.5)
        c.setFillColor(colors.HexColor('#93a3b8'))
        c.drawString(MARGIN, y, 'No live detections logged yet — start "Live AI Tracking" on the Live Tracking page before generating this report to include real results.')

    _footer(c, 'Page 2 / 3')
    c.showPage()

    # ---------------- Page 3: Laser link challenges (ISRO-relevant reference) ----------------
    y = _header(c, 'Free-Space Optical / Inter-Satellite Laser Link', 'Key technical challenges and this system\u2019s mitigation approach')
    for name, problem, mitigation in LASER_LINK_CHALLENGES:
        if y < 30 * mm:
            _footer(c, 'Page 3 / 3 (cont.)')
            c.showPage()
            y = _header(c, 'Free-Space Optical / Inter-Satellite Laser Link (continued)', '')
        c.setFont('Helvetica-Bold', 9.5)
        c.setFillColor(colors.HexColor('#12233f'))
        c.drawString(MARGIN, y, name)
        y -= 5 * mm
        c.setFont('Helvetica', 8.3)
        c.setFillColor(colors.HexColor('#4a5d75'))
        y = _wrap_text(c, problem, MARGIN + 2 * mm, y, PAGE_W - 2 * MARGIN - 4 * mm)
        c.setFont('Helvetica-Oblique', 8.3)
        c.setFillColor(colors.HexColor('#168548'))
        y = _wrap_text(c, 'Mitigation: ' + mitigation, MARGIN + 2 * mm, y, PAGE_W - 2 * MARGIN - 4 * mm)
        y -= 4 * mm

    _footer(c, 'Page 3 / 3')
    c.save()
    return path


def _wrap_text(c, text, x, y, max_w, line_h=4.6 * mm, font='Helvetica', size=8.3):
    words = text.split(' ')
    line = ''
    for w in words:
        trial = (line + ' ' + w).strip()
        if c.stringWidth(trial, font, size) > max_w and line:
            c.drawString(x, y, line)
            y -= line_h
            line = w
        else:
            line = trial
    if line:
        c.drawString(x, y, line)
        y -= line_h
    return y
