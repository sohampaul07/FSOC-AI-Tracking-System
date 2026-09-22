from flask import Flask, render_template, jsonify, request, Response, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from sqlalchemy import func
from datetime import datetime
from math import sqrt, sin, cos, radians, degrees, atan2
import csv, io, json, os, random, uuid, re
from urllib.parse import quote

from cv_engine.camera_stream import VideoCamera
from cv_engine.opencv_detector import OpenCVBeaconDetector
from cv_engine.yolo_detector import YoloBeaconDetector
from cv_engine.live_engine import LiveEngine
from cv_engine.object_tracker import YoloObjectTracker

BASE = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE, 'instance', 'fsoc_v7.sqlite3')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

COARSE_LIMIT = 2.0
FINE_LIMIT = 0.5

class AlignmentSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_key = db.Column(db.String(40), unique=True, nullable=False)
    mode = db.Column(db.String(30), default='manual')
    scenario = db.Column(db.String(80), default='Nominal Orbital')
    status = db.Column(db.String(30), default='ACTIVE')
    started_at = db.Column(db.DateTime, default=lambda: utcnow_naive())
    ended_at = db.Column(db.DateTime, nullable=True)
    samples = db.Column(db.Integer, default=0)
    lock_count = db.Column(db.Integer, default=0)
    avg_error = db.Column(db.Float, default=0)
    max_error = db.Column(db.Float, default=0)
    peak_confidence = db.Column(db.Float, default=0)
    disturbance_score = db.Column(db.Float, default=0)

class Reading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('alignment_session.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: utcnow_naive())
    target_x = db.Column(db.Float, default=640)
    target_y = db.Column(db.Float, default=360)
    h_error = db.Column(db.Float, default=0)
    v_error = db.Column(db.Float, default=0)
    total_error = db.Column(db.Float, default=0)
    azimuth = db.Column(db.Float, default=0)
    elevation = db.Column(db.Float, default=0)
    confidence = db.Column(db.Float, default=95)
    signal_dbm = db.Column(db.Float, default=-48)
    alignment_score = db.Column(db.Float, default=0)
    phase = db.Column(db.String(30), default='SEARCHING')
    command = db.Column(db.String(20), default='HOLD')
    detected = db.Column(db.Boolean, default=True)
    locked = db.Column(db.Boolean, default=False)
    fine_locked = db.Column(db.Boolean, default=False)

class PhaseTiming(db.Model):
    """Persisted phase intervals for measurable acquisition/alignment/recovery timing."""
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('alignment_session.id'), nullable=False, index=True)
    phase = db.Column(db.String(40), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=lambda: utcnow_naive())
    ended_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Float, default=0)

class EnvironmentalReading(db.Model):
    """Per-sample environmental/link context used by historical Dashboard analytics."""
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('alignment_session.id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=lambda: utcnow_naive(), index=True)
    atmospheric_turbulence = db.Column(db.Float, default=0)
    platform_vibration = db.Column(db.Float, default=0)
    background_noise = db.Column(db.Float, default=0)
    visibility = db.Column(db.Float, default=100)
    scintillation = db.Column(db.Float, default=0)
    link_reliability = db.Column(db.Float, default=100)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: utcnow_naive())
    category = db.Column(db.String(30), default='SYSTEM')
    message = db.Column(db.String(255), nullable=False)
    severity = db.Column(db.String(20), default='INFO')
    session_id = db.Column(db.Integer, nullable=True)

class Alert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: utcnow_naive())
    category = db.Column(db.String(30), default='SYSTEM')
    message = db.Column(db.String(255), nullable=False)
    severity = db.Column(db.String(20), default='INFO')
    acknowledged = db.Column(db.Boolean, default=False)

class AppSetting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(255), nullable=False)

# --- Live AI camera pipeline (OpenCV / YOLO) tables — additive, separate from the simulator's data ---
class LiveDetection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: utcnow_naive())
    source = db.Column(db.String(20), default='opencv')  # 'opencv' or 'yolo'
    cx = db.Column(db.Float, default=0)
    cy = db.Column(db.Float, default=0)
    h_error = db.Column(db.Float, default=0)
    v_error = db.Column(db.Float, default=0)
    total_error = db.Column(db.Float, default=0)
    confidence = db.Column(db.Float, default=0)
    phase = db.Column(db.String(30), default='SEARCHING')

class LiveAlert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: utcnow_naive())
    severity = db.Column(db.String(20), default='INFO')
    message = db.Column(db.String(255), nullable=False)

class LiveReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=lambda: utcnow_naive())
    ended_at = db.Column(db.DateTime, nullable=True)
    detector = db.Column(db.String(40), default='opencv')
    camera_mode = db.Column(db.String(40), default='synthetic')
    first_detection_id = db.Column(db.Integer, nullable=True)
    last_detection_id = db.Column(db.Integer, nullable=True)
    detection_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='ACTIVE')

class SimulatedCameraReport(db.Model):
    __tablename__ = 'simulated_camera_report'
    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=lambda: utcnow_naive())
    ended_at = db.Column(db.DateTime, nullable=True)
    target_id = db.Column(db.String(40), default='—')
    status = db.Column(db.String(20), default='ACTIVE')
    sample_count = db.Column(db.Integer, default=0)
    avg_error = db.Column(db.Float, default=0)
    max_error = db.Column(db.Float, default=0)
    peak_confidence = db.Column(db.Float, default=0)

class SimulatedCameraSample(db.Model):
    __tablename__ = 'simulated_camera_sample'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('simulated_camera_report.id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=lambda: utcnow_naive(), index=True)
    target_id = db.Column(db.String(40), default='—')
    x = db.Column(db.Float, default=0)
    y = db.Column(db.Float, default=0)
    h_error = db.Column(db.Float, default=0)
    v_error = db.Column(db.Float, default=0)
    total_error = db.Column(db.Float, default=0)
    pixel_error = db.Column(db.Float, default=0)
    confidence = db.Column(db.Float, default=0)
    velocity = db.Column(db.Float, default=0)
    angular_rate = db.Column(db.Float, default=0)
    phase = db.Column(db.String(30), default='TRACKING')

with app.app_context():
    os.makedirs(os.path.join(BASE, 'instance'), exist_ok=True)
    db.create_all()
    defaults = {
        'camera_hfov':'42', 'camera_vfov':'24', 'coarse_limit':'2.0', 'fine_limit':'0.5',
        'step_coarse':'1.2', 'step_fine':'0.35', 'auto_align':'true', 'tracking_rate':'10',
        'ai_model':'FSOC-Beacon-Detector v7 (simulation)', 'notifications':'true'
    }
    for k,v in defaults.items():
        if not AppSetting.query.get(k): db.session.add(AppSetting(key=k,value=v))
    db.session.commit()

# --- Live AI camera pipeline wiring (additive; does not touch the simulator above) ---
LIVE_CAMERA = VideoCamera(width=960, height=540, cam_index=0)
LIVE_OPENCV_DETECTOR = OpenCVBeaconDetector()
LIVE_YOLO_DETECTOR = YoloBeaconDetector(weights_path=os.path.join(BASE, 'models', 'best.pt'))
LIVE_ENGINE = LiveEngine(
    app=app, db=db, socketio=socketio, camera=LIVE_CAMERA,
    opencv_detector=LIVE_OPENCV_DETECTOR, yolo_detector=LIVE_YOLO_DETECTOR,
    live_detection_model=LiveDetection, live_alert_model=LiveAlert,
    coarse_limit=COARSE_LIMIT, fine_limit=FINE_LIMIT, hfov=42.0, vfov=24.0, rate_hz=12,
)

# In-memory simulator state is only the control surface; all observations/events are persisted in SQLite.
LIVE_REPORT_ID = None
SIM_CAMERA_REPORT_ID = None

SIM = {
    'running': False, 'session_id': None, 'mode': 'manual', 'scenario': 'Nominal Orbital',
    'target_az': 14.0, 'target_el': -8.0, 'gimbal_az': 0.0, 'gimbal_el': 0.0,
    'last_command': 'HOLD', 'last_phase': 'SEARCHING', 'tick': 0, 'reacquire': False,
    'target_lost': False, 'target_lost_at': None, 'target_lost_telemetry': {}, 'worker_running': False, 'last_reading_id': None
}

SCENARIOS = {
    'Nominal Orbital': {'drift':0.10, 'noise':0.05, 'turbulence':0.03, 'target_motion':0.18, 'signal':-46, 'visibility':96, 'vibration':8, 'background_noise':6, 'scintillation':4},
    'Atmospheric Turbulence': {'drift':0.18, 'noise':0.22, 'turbulence':0.28, 'target_motion':0.25, 'signal':-55, 'visibility':68, 'vibration':16, 'background_noise':18, 'scintillation':28},
    'Platform Vibration': {'drift':0.12, 'noise':0.18, 'turbulence':0.16, 'target_motion':0.22, 'signal':-51, 'visibility':84, 'vibration':58, 'background_noise':12, 'scintillation':16},
    'Low Beacon SNR': {'drift':0.10, 'noise':0.20, 'turbulence':0.10, 'target_motion':0.16, 'signal':-72, 'visibility':78, 'vibration':12, 'background_noise':48, 'scintillation':12},
    'Fast Target Motion': {'drift':0.14, 'noise':0.12, 'turbulence':0.08, 'target_motion':0.55, 'signal':-50, 'visibility':90, 'vibration':14, 'background_noise':10, 'scintillation':8},
    'Target Lost': {'drift':0.10, 'noise':0.35, 'turbulence':0.18, 'target_motion':0.20, 'signal':-95, 'visibility':42, 'vibration':25, 'background_noise':30, 'scintillation':22},
}

def utcnow_naive(): return datetime.utcnow()
def now(): return utcnow_naive()
def setting(k, fallback):
    x = AppSetting.query.get(k)
    return float(x.value) if x and x.value.replace('.','',1).isdigit() else fallback

def event(category, message, severity='INFO', session_id=None):
    db.session.add(Event(category=category, message=message, severity=severity, session_id=session_id))

def alert(category, message, severity='WARNING'):
    # Persist the alert and immediately broadcast it to every open Alerts tab.
    row = Alert(category=category, message=message, severity=severity)
    db.session.add(row)
    db.session.flush()
    socketio.emit('alert_event', {
        'id': row.id,
        'time': row.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        'category': row.category,
        'message': row.message,
        'severity': row.severity,
        'acknowledged': row.acknowledged,
        'source': 'scenario'
    })
    return row

def clamp(x,a,b): return max(a,min(b,x))

def new_session(mode='manual', scenario='Nominal Orbital'):
    key = uuid.uuid4().hex[:16]
    s = AlignmentSession(session_key=key, mode=mode, scenario=scenario)
    db.session.add(s); db.session.flush()
    SIM.update({'running':True,'session_id':s.id,'mode':mode,'scenario':scenario,'target_az':(random.uniform(-7,7) if mode=='demo' else random.uniform(-18,18)),'target_el':(random.uniform(-5,5) if mode=='demo' else random.uniform(-10,10)),
                'gimbal_az':0.0,'gimbal_el':0.0,'last_command':'HOLD','last_phase':'SEARCHING','tick':0,'reacquire':False,
                 'target_lost':False,'target_lost_at':None,'target_lost_telemetry':{},'target_lost_alert_id':None})
    event('SYSTEM', f'{mode.upper()} alignment session started · {scenario}', 'INFO', s.id)
    _phase_now_start(s.id, 'SEARCHING')
    db.session.commit()
    return s

def target_motion(scn):
    p=SCENARIOS.get(scn,SCENARIOS['Nominal Orbital']); t=SIM['tick']
    # target is a distant FSOC optical terminal/satellite, never a ground object
    SIM['target_az'] += sin(t/11.0)*p['target_motion']*0.08 + random.gauss(0,p['noise']*0.08)
    SIM['target_el'] += cos(t/13.0)*p['target_motion']*0.06 + random.gauss(0,p['noise']*0.06)
    SIM['target_az']=clamp(SIM['target_az'],-30,30); SIM['target_el']=clamp(SIM['target_el'],-18,18)

def guidance(h,v,total):
    dead=0.08 if total<1 else 0.12
    horiz = 'RIGHT' if h>dead else 'LEFT' if h<-dead else ''
    vert = 'UP' if v>dead else 'DOWN' if v<-dead else ''
    if not horiz and not vert: return 'HOLD'
    if horiz and vert: return f'{horiz} + {vert}'
    return horiz or vert

def compute_reading(s):
    p=SCENARIOS.get(SIM['scenario'],SCENARIOS['Nominal Orbital'])
    # relative line-of-sight error
    h = SIM['target_az'] - SIM['gimbal_az'] + random.gauss(0,p['noise']*0.05)
    v = SIM['target_el'] - SIM['gimbal_el'] + random.gauss(0,p['noise']*0.04)
    total=sqrt(h*h+v*v)
    if SIM.get('target_lost'):
        phase='TARGET LOST'; command='REACQUIRE'; locked=False; fine=False
    elif SIM['reacquire']:
        phase='REACQUISITION'; command='SEARCH SWEEP'; locked=False; fine=False
    elif total>12:
        phase='SEARCHING'; command=guidance(h,v,total); locked=False; fine=False
    elif total>6:
        phase='ACQUISITION'; command=guidance(h,v,total); locked=False; fine=False
    elif total>setting('coarse_limit',COARSE_LIMIT):
        phase='COARSE ALIGNMENT'; command=guidance(h,v,total); locked=False; fine=False
    elif total>setting('fine_limit',FINE_LIMIT):
        phase='FINE ALIGNMENT'; command=guidance(h,v,total); locked=True; fine=False
    else:
        phase='FINE LOCK'; command='HOLD'; locked=True; fine=True
    if SIM.get('target_lost'):
        conf=0.0
        signal=-95.0
    else:
        conf=clamp(98.5-total*1.25-p['noise']*8+random.gauss(0,0.25),55,99.8)
        signal=p['signal']-p['turbulence']*7-total*0.25+random.gauss(0,0.8)
    score=clamp(100-total*7.0-p['noise']*15,0,100)
    if SIM.get('target_lost') and SIM.get('scenario') == 'Target Lost':
        conf=0.0
        signal=p['signal']
        score=0.0
    # image coordinates from angular error in a 1280x720 virtual camera
    x=640+ (h/setting('camera_hfov',42))*1280
    y=360- (v/setting('camera_vfov',24))*720
    return dict(x=clamp(x,40,1240),y=clamp(y,40,680),h=h,v=v,total=total,phase=phase,command=command,
                confidence=conf,signal=signal,score=score,locked=locked,fine=fine)

def auto_control(r):
    if not SIM['running'] or SIM['mode'] not in ('auto','auto-align','demo'): return
    h,v,t=r['h'],r['v'],r['total']
    if SIM['reacquire']:
        # small deterministic spiral search to reacquire the beacon
        SIM['gimbal_az'] += 0.8*cos(SIM['tick']/4); SIM['gimbal_el'] += 0.6*sin(SIM['tick']/4)
        return
    step = setting('step_fine',0.35) if t<=COARSE_LIMIT else setting('step_coarse',1.2)
    if t>FINE_LIMIT:
        SIM['gimbal_az'] += clamp(h,-step,step)
        SIM['gimbal_el'] += clamp(v,-step,step)
    # Once locked, track a tiny fraction of target motion to keep the lock alive.
    else:
        SIM['gimbal_az'] += clamp(h,-0.12,0.12)
        SIM['gimbal_el'] += clamp(v,-0.10,0.10)

def _phase_now_start(session_id, phase):
    """Get/create the current open phase interval for a session."""
    row = PhaseTiming.query.filter_by(session_id=session_id, phase=phase, ended_at=None).order_by(PhaseTiming.id.desc()).first()
    if row:
        return row
    row = PhaseTiming(session_id=session_id, phase=phase, started_at=now())
    db.session.add(row)
    db.session.flush()
    return row

def _close_open_phase(session_id, phase, ended=None):
    ended = ended or now()
    row = PhaseTiming.query.filter_by(session_id=session_id, phase=phase, ended_at=None).order_by(PhaseTiming.id.desc()).first()
    if not row:
        return None
    row.ended_at = ended
    row.duration_seconds = max(0.0, (ended - row.started_at).total_seconds())
    return row

def _record_phase_transition(session_id, previous_phase, new_phase, transition_time=None):
    """Persist exact phase boundaries. Existing sessions remain readable via derived fallback below."""
    t = transition_time or now()
    if previous_phase and previous_phase != new_phase:
        _close_open_phase(session_id, previous_phase, t)
    _phase_now_start(session_id, new_phase)

def _environment_sample(scenario, reading):
    p = SCENARIOS.get(scenario, SCENARIOS['Nominal Orbital'])
    # Values are deterministic around the scenario baseline with small telemetry variation.
    turb = clamp(p.get('turbulence', 0) * 100 + random.gauss(0, 1.2), 0, 100)
    vibration = clamp(p.get('vibration', 0) + abs(reading.v_error) * 2.0 + random.gauss(0, 1.0), 0, 100)
    bg = clamp(p.get('background_noise', 0) + max(0, 100 - reading.confidence) * 0.25 + random.gauss(0, 1.0), 0, 100)
    visibility = clamp(p.get('visibility', 90) - turb * 0.12 - bg * 0.05 + random.gauss(0, 0.7), 0, 100)
    scint = clamp(p.get('scintillation', 5) + turb * 0.25 + abs(reading.total_error) * 1.5 + random.gauss(0, 0.5), 0, 100)
    link = clamp(100 - turb * 0.22 - vibration * 0.10 - bg * 0.16 - scint * 0.10 + max(0, reading.confidence - 80) * 0.08, 0, 100)
    return turb, vibration, bg, visibility, scint, link

def _derived_phase_intervals(session_id):
    """Fallback timing for legacy sessions recorded before PhaseTiming existed."""
    rows = Reading.query.filter_by(session_id=session_id).order_by(Reading.timestamp.asc(), Reading.id.asc()).all()
    if not rows:
        return []
    out=[]; current=rows[0].phase; start=rows[0].timestamp
    for r in rows[1:]:
        if r.phase != current:
            out.append({'phase':current,'started_at':start,'ended_at':r.timestamp,'duration_seconds':max(0,(r.timestamp-start).total_seconds()),'source':'derived-from-readings'})
            current=r.phase; start=r.timestamp
    last=rows[-1].timestamp
    out.append({'phase':current,'started_at':start,'ended_at':last,'duration_seconds':max(0,(last-start).total_seconds()),'source':'derived-from-readings'})
    return out

def tick(session_id=None, allow_control=True):
    s=db.session.get(AlignmentSession, session_id or SIM['session_id'])
    if not s: raise ValueError('No active session')
    SIM['tick'] += 1; target_motion(SIM['scenario'])
    r=compute_reading(s)
    if allow_control: auto_control(r); r=compute_reading(s)
    reading=Reading(session_id=s.id,target_x=r['x'],target_y=r['y'],h_error=r['h'],v_error=r['v'],total_error=r['total'],
                    azimuth=SIM['gimbal_az'],elevation=SIM['gimbal_el'],confidence=r['confidence'],signal_dbm=r['signal'],
                    alignment_score=r['score'],phase=r['phase'],command=r['command'],detected=not SIM.get('target_lost',False),
                    locked=r['locked'],fine_locked=r['fine'])
    db.session.add(reading); db.session.flush(); s.samples+=1

    # Persist phase timing and environmental context for historical analytics.
    if r['phase'] != SIM['last_phase']:
        _record_phase_transition(s.id, SIM['last_phase'], r['phase'], reading.timestamp)
    else:
        _phase_now_start(s.id, r['phase'])

    turb, vibration, bg, visibility, scint, link = _environment_sample(SIM['scenario'], reading)
    db.session.add(EnvironmentalReading(
        session_id=s.id, timestamp=reading.timestamp,
        atmospheric_turbulence=turb, platform_vibration=vibration,
        background_noise=bg, visibility=visibility, scintillation=scint,
        link_reliability=link
    ))
    vals=[x.total_error for x in Reading.query.filter_by(session_id=s.id).order_by(Reading.id.desc()).limit(100).all()]
    s.avg_error=sum(vals)/len(vals); s.max_error=max(vals) if vals else 0; s.peak_confidence=max(s.peak_confidence,r['confidence'])
    if r['fine']: s.lock_count+=1
    s.disturbance_score=clamp((SCENARIOS[SIM['scenario']]['noise']+SCENARIOS[SIM['scenario']]['turbulence'])*100,0,100)
    if SIM['reacquire'] and SIM['tick'] % 8 == 0:
        SIM['reacquire']=False
        event('TRACKING','Beacon reacquired · returning to closed-loop alignment','SUCCESS',s.id)
    if r['phase'] != SIM['last_phase']:
        event('ALIGNMENT', f"Phase changed: {SIM['last_phase']} → {r['phase']}", 'SUCCESS' if r['fine'] else 'INFO', s.id)
        SIM['last_phase']=r['phase']
    if r['command'] != SIM['last_command']:
        event('AI', f"AI guidance: {r['command']}", 'INFO', s.id)
        SIM['last_command']=r['command']
    if r['fine'] and s.lock_count==1: event('TRACKING','Fine lock acquired · auto-align controller holding target', 'SUCCESS', s.id)
    db.session.commit()
    return s,r,reading


def _reading_payload_from_row(s, reading):
    """Serialize the latest persisted simulator observation without advancing the simulation."""
    return {
        'session_id': s.id,
        'session_key': s.session_key,
        'mode': s.mode,
        'scenario': s.scenario,
        'timestamp': reading.timestamp.isoformat(),
        'running': bool(SIM.get('running') and s.status == 'ACTIVE'),
        'detected': bool(reading.detected),
        'locked': bool(reading.locked),
        'fine_locked': bool(reading.fine_locked),
        'phase': reading.phase,
        'command': reading.command,
        'target': {'x': round(reading.target_x, 1), 'y': round(reading.target_y, 1)},
        'h_error': round(reading.h_error, 3),
        'v_error': round(reading.v_error, 3),
        'total_error': round(reading.total_error, 3),
        'azimuth': round(reading.azimuth, 3),
        'elevation': round(reading.elevation, 3),
        'confidence': round(reading.confidence, 1),
        'signal_dbm': round(reading.signal_dbm, 1),
        'alignment_score': round(reading.alignment_score, 1),
        'coarse_limit': COARSE_LIMIT,
        'fine_limit': FINE_LIMIT,
        'gimbal': {'az': round(reading.azimuth, 3), 'el': round(reading.elevation, 3)},
        'samples': s.samples
    }

def _simulator_worker(expected_session_id):
    """Server-side mission clock. One worker belongs to one session; browser polling never advances time."""
    with app.app_context():
        SIM['worker_running'] = True
        try:
            while SIM.get('running') and SIM.get('session_id') == expected_session_id:
                try:
                    s = db.session.get(AlignmentSession, expected_session_id)
                    if not s or s.status != 'ACTIVE':
                        SIM['running'] = False
                        break
                    allow = SIM.get('mode') in ('auto', 'auto-align', 'demo')
                    s, r, reading = tick(expected_session_id, allow_control=allow)
                    SIM['last_reading_id'] = reading.id
                    payload = reading_json(s, r, reading)
                    socketio.emit('mission_telemetry', payload)
                    socketio.emit('mission_phase', {
                        'session_id': s.id,
                        'phase': reading.phase,
                        'detected': bool(reading.detected),
                        'locked': bool(reading.locked),
                        'fine_locked': bool(reading.fine_locked),
                        'timestamp': reading.timestamp.isoformat()
                    })
                except Exception as exc:
                    app.logger.exception('Simulator worker tick failed: %s', exc)
                    db.session.rollback()
                socketio.sleep(0.45)
        finally:
            if SIM.get('session_id') == expected_session_id:
                SIM['worker_running'] = False
            db.session.remove()

def ensure_simulator_worker(session_id=None):
    sid = session_id or SIM.get('session_id')
    if SIM.get('running') and sid:
        socketio.start_background_task(_simulator_worker, sid)

def reading_json(s,r,reading):
    return {'session_id':s.id,'session_key':s.session_key,'mode':s.mode,'scenario':s.scenario,'timestamp':reading.timestamp.isoformat(),
            'detected':bool(r.get('detected', not SIM.get('target_lost',False))),'locked':r['locked'],'fine_locked':r['fine'],'phase':r['phase'],'command':r['command'],
            'target':{'x':round(r['x'],1),'y':round(r['y'],1)},'h_error':round(r['h'],3),'v_error':round(r['v'],3),'total_error':round(r['total'],3),
            'azimuth':round(SIM['gimbal_az'],3),'elevation':round(SIM['gimbal_el'],3),'confidence':round(r['confidence'],1),
            'signal_dbm':round(r['signal'],1),'alignment_score':round(r['score'],1),'coarse_limit':COARSE_LIMIT,'fine_limit':FINE_LIMIT,
            'gimbal':{'az':round(SIM['gimbal_az'],3),'el':round(SIM['gimbal_el'],3)},'samples':s.samples}

@app.context_processor
def inject(): return {'app_title':'TRACKAI · SIH26169','sim':SIM}

@app.get('/')
def dashboard(): return render_template('dashboard.html', page='dashboard')
@app.get('/live-tracking')
def live_tracking(): return render_template('live_tracking.html', page='live-tracking')
@app.get('/simulator')
def simulator_alias(): return render_template('live_tracking.html', page='live-tracking')

@app.get('/scenarios')
def scenarios(): return render_template('scenarios.html', page='scenarios', scenarios=list(SCENARIOS.keys()))
@app.get('/analytics')
def analytics(): return render_template('analytics.html', page='analytics')
@app.get('/reports')
def reports(): return render_template('reports.html', page='reports')
@app.get('/history')
def history(): return render_template('history_v7.html', page='reports')

@app.get('/event-log')
def event_log(): return render_template('event_log.html', page='event-log')


@app.get('/api/health')
def health(): return jsonify({'status':'online','database':'connected','flask':'connected','simulator':SIM['running']})

@app.get('/api/dashboard')
def api_dashboard():
    active=db.session.get(AlignmentSession,SIM['session_id']) if SIM['session_id'] else None
    recent=Event.query.order_by(Event.id.desc()).limit(7).all()
    latest=Reading.query.filter_by(session_id=SIM['session_id']).order_by(Reading.id.desc()).first() if SIM['session_id'] else None
    total_sessions=AlignmentSession.query.count()
    locks=AlignmentSession.query.with_entities(db.func.sum(AlignmentSession.lock_count)).scalar() or 0
    performance=None
    if active:
        phases=PhaseTiming.query.filter_by(session_id=active.id).all()
        if phases:
            totals={}
            for p in phases: totals[p.phase]=totals.get(p.phase,0)+(p.duration_seconds if p.ended_at else max(0,(now()-p.started_at).total_seconds()))
        else:
            totals={}
            for p in _derived_phase_intervals(active.id): totals[p['phase']]=totals.get(p['phase'],0)+p['duration_seconds']
        env=EnvironmentalReading.query.filter_by(session_id=active.id).order_by(EnvironmentalReading.id.desc()).first()
        performance={'acquisition_seconds':round(totals.get('ACQUISITION',0),3),'coarse_alignment_seconds':round(totals.get('COARSE ALIGNMENT',0),3),
                     'fine_alignment_seconds':round(totals.get('FINE ALIGNMENT',0),3),'reacquisition_seconds':round(totals.get('REACQUISITION',0),3),
                     'target_lost_seconds':round(totals.get('TARGET LOST',0),3),
                     'environment':({'atmospheric_turbulence':round(env.atmospheric_turbulence,1),'platform_vibration':round(env.platform_vibration,1),
                                     'background_noise':round(env.background_noise,1),'visibility':round(env.visibility,1),'scintillation':round(env.scintillation,1),
                                     'link_reliability':round(env.link_reliability,1)} if env else None)}
    return jsonify({'active':bool(active and active.status=='ACTIVE'),'session_id':SIM['session_id'],'target_status':'FINE LOCK' if latest and latest.fine_locked else ('LOCKED' if latest and latest.locked else 'TRACKING'),
                    'camera_status':'ONLINE','ai_confidence':latest.confidence if latest else 97.3,'alignment_score':latest.alignment_score if latest else 0,
                    'signal_dbm':latest.signal_dbm if latest else -48,'sessions':total_sessions,'locks':locks,
                    'performance':performance,
                    'recent_events':[{'time':e.timestamp.strftime('%H:%M:%S'),'category':e.category,'message':e.message,'severity':e.severity} for e in recent]})

@app.get('/api/state')
def api_state():
    # IMPORTANT: this endpoint is read-only. The server worker advances telemetry.
    sid = SIM.get('session_id')
    if not sid:
        return jsonify({'running': False, 'message': 'No active session'})
    try:
        s = db.session.get(AlignmentSession, sid)
        if not s:
            return jsonify({'running': False, 'message': 'No active session'})
        reading = Reading.query.filter_by(session_id=sid).order_by(Reading.id.desc()).first()
        if not reading:
            return jsonify({'running': s.status == 'ACTIVE', 'session_id': s.id,
                            'session_key': s.session_key, 'mode': s.mode,
                            'scenario': s.scenario, 'phase': 'SEARCHING'})
        return jsonify(_reading_payload_from_row(s, reading))
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@app.post('/api/session/start')
def api_start():
    data=request.get_json(silent=True) or {}; mode=data.get('mode','manual'); scenario=data.get('scenario',SIM['scenario'])
    if scenario not in SCENARIOS: return jsonify({'error':'Unknown scenario'}),400
    if SIM['session_id']:
        old=db.session.get(AlignmentSession,SIM['session_id'])
        if old and old.status=='ACTIVE':
            ended=now()
            old.status='STOPPED'
            old.ended_at=ended
            _close_open_phase(old.id, SIM.get('last_phase') or 'SEARCHING', ended)
            event('SYSTEM','Previous mission stopped automatically for new mission','INFO',old.id)
            db.session.commit()
    s=new_session(mode,scenario)
    if mode in ('auto','auto-align','demo'):
        event('AI','Auto-alignment controller enabled · closed-loop mode','SUCCESS',s.id)
    db.session.commit()
    ensure_simulator_worker(s.id)
    return jsonify({'ok':True,'session_id':s.id,'session_key':s.session_key,'mode':mode,'scenario':scenario,
                    'worker':True,'message':'Mission started; server telemetry clock is running.'})

@app.post('/api/session/stop')
def api_stop():
    if not SIM['session_id']: return jsonify({'ok':True})
    s=db.session.get(AlignmentSession,SIM['session_id'])
    if s:
        ended = now(); s.status='STOPPED'; s.ended_at=ended
        _close_open_phase(s.id, SIM.get('last_phase') or 'SEARCHING', ended)
        event('SYSTEM','Session stopped by operator','INFO',s.id); db.session.commit()
    SIM['running']=False
    SIM['target_lost']=False
    SIM['target_lost_at']=None
    SIM['target_lost_telemetry']={}
    SIM['reacquire']=False
    return jsonify({'ok':True,'session_id':SIM['session_id']})

@app.post('/api/session/auto-align')
def api_auto_align():
    if not SIM['session_id'] or not SIM['running']:
        s=new_session('auto-align',SIM['scenario'])
    else:
        s=db.session.get(AlignmentSession,SIM['session_id']); s.mode='auto-align'; SIM['mode']='auto-align'; db.session.commit()
    ensure_simulator_worker(s.id)
    return jsonify({'ok':True,'session_id':s.id,'mode':'auto-align'})

@app.post('/api/session/reacquire')
def api_reacquire():
    SIM['reacquire']=True
    event('TRACKING','Target reacquisition sequence started · orbital search sweep', 'WARNING', SIM['session_id']); db.session.commit()
    return jsonify({'ok':True})

@app.post('/api/session/manual-command')
def api_manual_command():
    data=request.get_json(silent=True) or {}; cmd=data.get('command','HOLD').upper(); step=float(data.get('step',0.5))
    if not SIM['session_id']: new_session('manual',SIM['scenario'])
    mapping={'LEFT':(-step,0),'RIGHT':(step,0),'UP':(0,step),'DOWN':(0,-step)}
    if cmd in mapping:
        da,de=mapping[cmd]; SIM['gimbal_az']+=da; SIM['gimbal_el']+=de
    SIM['mode']='manual'; SIM['last_command']=cmd
    event('TRACKING',f'Manual gimbal command: {cmd}', 'INFO', SIM['session_id']); db.session.commit()
    return jsonify({'ok':True,'command':cmd})

@app.post('/api/session/center')
def api_center():
    if not SIM['session_id']:
        s = new_session('auto-align', SIM['scenario'])
    else:
        s = db.session.get(AlignmentSession, SIM['session_id'])

    SIM['mode'] = 'auto-align'

    ensure_simulator_worker(SIM.get('session_id'))

    # Run several alignment iterations for the Center Target command
    for _ in range(4):
        tick(SIM['session_id'], allow_control=True)

    # Record the operator action in Event Log
    event(
        'ALIGNMENT',
        'Operator commanded Center Target · alignment correction initiated',
        'INFO',
        SIM['session_id']
    )

    db.session.commit()

    return jsonify({
        'ok': True,
        'mode': 'auto-align',
        'session_id': SIM['session_id']
    })

@app.post('/api/scenario')
def api_scenario():
    data=request.get_json(silent=True) or {}; name=data.get('scenario','Nominal Orbital')
    if name not in SCENARIOS: return jsonify({'error':'Unknown scenario'}),400
    # A scenario change is a hard boundary: clear any previous Target Lost state.
    SIM['scenario']=name
    SIM['target_lost']=False
    SIM['target_lost_at']=None
    SIM['reacquire']=False
    SIM['target_lost_alert_id']=None
    if SIM['session_id']:
        s=db.session.get(AlignmentSession,SIM['session_id'])
        s.scenario=name
        event('SYSTEM',f'Scenario changed to {name}','INFO',s.id)
        db.session.commit()
    socketio.emit('target_lost_state', {
        'active': False,
        'scenario': name
    })
    return jsonify({'ok':True,'scenario':name})


@app.post('/api/scenario/target-lost')
def api_target_lost():
    """Synchronize the current Target Lost incident with Flask/SQLite."""
    data = request.get_json(silent=True) or {}
    action = str(data.get('action', 'lost')).lower()

    if action not in ('lost', 'recovered'):
        return jsonify({'error': 'action must be lost or recovered'}), 400

    # A stale browser request must never activate Target Lost after a scenario switch.
    if SIM.get('scenario') != 'Target Lost':
        SIM['target_lost'] = False
        SIM['target_lost_at'] = None
        SIM['target_lost_telemetry'] = {}
        SIM['target_lost_alert_id'] = None
        SIM['reacquire'] = False
        db.session.commit()
        return jsonify({
            'ok': False,
            'state': 'IGNORED',
            'reason': 'Target Lost is not the active scenario'
        }), 409

    session_id = SIM.get('session_id')

    if action == 'lost':
        telemetry = data.get('telemetry') or {}
        if SIM.get('target_lost'):
            return jsonify({
                'ok': True,
                'state': 'TARGET LOST',
                'session_id': session_id,
                'report_url': '/reports/target-lost/pdf/preview',
                'download_url': '/reports/target-lost/pdf',
                'report_ready': os.path.exists(os.path.join(BASE, 'reports', 'Target_Lost_Incident_Report.pdf')),
                'alert_id': SIM.get('target_lost_alert_id')
            })

        lost_time = now()
        SIM['target_lost'] = True
        SIM['target_lost_at'] = lost_time.isoformat()
        SIM['target_lost_telemetry'] = telemetry
        SIM['reacquire'] = True
        previous_phase = SIM.get('last_phase') or 'SEARCHING'
        if session_id:
            _close_open_phase(session_id, previous_phase, lost_time)
            _phase_now_start(session_id, 'TARGET LOST')
        SIM['last_phase'] = 'TARGET LOST'
        SIM['last_command'] = 'REACQUIRE'

        event(
            'ALERT',
            'TARGET LOST · optical beacon disappeared · siren activated',
            'CRITICAL',
            session_id
        )
        incident_alert = alert(
            'TARGET LOST',
            'Optical beacon lost · siren activated · automatic reacquisition started',
            'CRITICAL'
        )
        SIM['target_lost_alert_id'] = incident_alert.id
        db.session.commit()

        # Push the incident immediately to every connected Alerts tab.
        socketio.emit('target_lost_state', {
            'active': True,
            'scenario': 'Target Lost',
            'session_id': session_id,
            'severity': 'CRITICAL',
            'message': 'Optical beacon lost · siren activated · automatic reacquisition started',
            'report_url': '/reports/target-lost/pdf/preview',
            'download_url': '/reports/target-lost/pdf'
        })

        # Generate the report now, but do not force the browser to preview it.
        try:
            report_path = _build_target_lost_report()
        except ImportError:
            report_path = None
        except Exception as exc:
            app.logger.exception('Target Lost PDF generation failed: %s', exc)
            report_path = None

        return jsonify({
            'ok': True,
            'state': 'TARGET LOST',
            'session_id': session_id,
            'report_url': '/reports/target-lost/pdf/preview',
            'download_url': '/reports/target-lost/pdf',
            'report_ready': bool(report_path),
            'alert_id': SIM.get('target_lost_alert_id')
        })

    recovered_time = now()
    SIM['target_lost'] = False
    SIM['target_lost_at'] = None
    SIM['target_lost_telemetry'] = {}
    SIM['target_lost_alert_id'] = None
    SIM['reacquire'] = True
    if session_id:
        _close_open_phase(session_id, 'TARGET LOST', recovered_time)
        _phase_now_start(session_id, 'REACQUISITION')
    SIM['last_phase'] = 'REACQUISITION'
    SIM['last_command'] = 'SEARCH SWEEP'

    event(
        'TRACKING',
        'Target reacquired · Target Lost alarm cleared',
        'SUCCESS',
        session_id
    )
    db.session.commit()

    socketio.emit('target_lost_state', {
        'active': False,
        'scenario': 'Target Lost',
        'session_id': session_id,
        'message': 'Target reacquired · Target Lost alarm cleared'
    })

    return jsonify({
        'ok': True,
        'state': 'REACQUIRED',
        'session_id': session_id
    })


@app.get('/api/alerts/target-lost')
def api_target_lost_alert():
    row = Alert.query.filter_by(category='TARGET LOST').order_by(Alert.id.desc()).first()
    return jsonify({
        'ok': True,
        'active': bool(SIM.get('target_lost')) and SIM.get('scenario') == 'Target Lost',
        'alert': ({
            'id': row.id,
            'time': row.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'category': row.category,
            'message': row.message,
            'severity': row.severity,
            'acknowledged': row.acknowledged
        } if row else None),
        'preview_url': '/reports/target-lost/pdf/preview',
        'download_url': '/reports/target-lost/pdf'
    })


@app.get('/api/scenario/target-lost/status')
def api_target_lost_status():
    return jsonify({
        'ok': True,
        'scenario': SIM.get('scenario'),
        'target_lost': bool(SIM.get('target_lost')) and SIM.get('scenario') == 'Target Lost',
        'target_lost_at': SIM.get('target_lost_at') if SIM.get('scenario') == 'Target Lost' else None,
        'report_ready': os.path.exists(os.path.join(BASE, 'reports', 'Target_Lost_Incident_Report.pdf')),
        'running': bool(SIM.get('running')),
        'session_id': SIM.get('session_id')
    })


@app.get('/api/sessions')
def api_sessions():
    rows=AlignmentSession.query.order_by(AlignmentSession.id.desc()).limit(100).all()
    return jsonify([{'id':s.id,'key':s.session_key,'mode':s.mode,'scenario':s.scenario,'status':s.status,'started':s.started_at.isoformat(),'ended':s.ended_at.isoformat() if s.ended_at else None,
                     'samples':s.samples,'avg_error':round(s.avg_error,3),'max_error':round(s.max_error,3),'lock_count':s.lock_count,'peak_confidence':round(s.peak_confidence,1)} for s in rows])

@app.get('/api/session/<int:sid>')
def api_session(sid):
    s=db.session.get(AlignmentSession,sid)
    if not s:return jsonify({'error':'Not found'}),404
    rs=Reading.query.filter_by(session_id=sid).order_by(Reading.id.desc()).limit(250).all()
    phases=PhaseTiming.query.filter_by(session_id=sid).order_by(PhaseTiming.started_at.asc()).all()
    env=EnvironmentalReading.query.filter_by(session_id=sid).order_by(EnvironmentalReading.timestamp.asc()).limit(250).all()
    return jsonify({'session':{'id':s.id,'key':s.session_key,'mode':s.mode,'scenario':s.scenario,'status':s.status,'samples':s.samples,'avg_error':s.avg_error,'max_error':s.max_error,'lock_count':s.lock_count},
                    'readings':[{'t':r.timestamp.isoformat(),'h':r.h_error,'v':r.v_error,'total':r.total_error,'phase':r.phase,'command':r.command,'confidence':r.confidence,'score':r.alignment_score,'signal':r.signal_dbm} for r in reversed(rs)],
                    'phase_timings':[{'phase':p.phase,'started_at':p.started_at.isoformat(),'ended_at':p.ended_at.isoformat() if p.ended_at else None,'duration_seconds':round(p.duration_seconds if p.ended_at else max(0,(now()-p.started_at).total_seconds()),3)} for p in phases],
                    'environment':[{'t':e.timestamp.isoformat(),'atmospheric_turbulence':e.atmospheric_turbulence,'platform_vibration':e.platform_vibration,'background_noise':e.background_noise,'visibility':e.visibility,'scintillation':e.scintillation,'link_reliability':e.link_reliability} for e in env]})

@app.get('/api/analytics')
def api_analytics():
    sessions=AlignmentSession.query.all(); readings=Reading.query.all()
    total=len(readings); locks=sum(1 for r in readings if r.fine_locked); fine=sum(1 for r in readings if r.phase=='FINE ALIGNMENT')
    avg=sum(r.total_error for r in readings)/total if total else 0
    phase_counts={}
    for r in readings: phase_counts[r.phase]=phase_counts.get(r.phase,0)+1
    commands={}
    for r in readings: commands[r.command]=commands.get(r.command,0)+1
    scenarios={}
    for s in sessions:
        scenarios.setdefault(s.scenario,{'sessions':0,'avg_error':0,'locks':0}); scenarios[s.scenario]['sessions']+=1; scenarios[s.scenario]['avg_error']+=s.avg_error; scenarios[s.scenario]['locks']+=s.lock_count
    for v in scenarios.values(): v['avg_error']=round(v['avg_error']/v['sessions'],3) if v['sessions'] else 0
    return jsonify({'kpi':{'sessions':len(sessions),'samples':total,'avg_error':round(avg,3),'fine_lock_rate':round((locks/total*100) if total else 0,1),'fine_samples':fine},'phase_counts':phase_counts,'commands':commands,'scenarios':scenarios,
                    'recent_error':[{'t':r.timestamp.strftime('%H:%M:%S'),'v':round(r.total_error,3)} for r in readings[-60:]]})

@app.get('/api/dashboard/telemetry')
def api_dashboard_telemetry():
    """Return synchronized historical telemetry for the Dashboard's four technical graphs."""
    sid = request.args.get('session_id', type=int) or SIM.get('session_id')
    limit = min(max(request.args.get('limit', 180, type=int), 20), 1000)
    if not sid:
        return jsonify({'session': None, 'readings': [], 'environment': [], 'phase_timings': [], 'performance': []})
    s = db.session.get(AlignmentSession, sid)
    if not s:
        return jsonify({'error':'Session not found'}), 404
    readings = Reading.query.filter_by(session_id=sid).order_by(Reading.timestamp.desc(), Reading.id.desc()).limit(limit).all()
    readings = list(reversed(readings))
    env = EnvironmentalReading.query.filter_by(session_id=sid).order_by(EnvironmentalReading.timestamp.desc(), EnvironmentalReading.id.desc()).limit(limit).all()
    env = list(reversed(env))
    phases = PhaseTiming.query.filter_by(session_id=sid).order_by(PhaseTiming.started_at.asc(), PhaseTiming.id.asc()).all()
    if not phases:
        phases = []
        for x in _derived_phase_intervals(sid):
            phases.append(x)
        phase_json = phases
    else:
        phase_json = [{'id':p.id,'phase':p.phase,'started_at':p.started_at.isoformat(),'ended_at':p.ended_at.isoformat() if p.ended_at else None,
                       'duration_seconds':round(p.duration_seconds if p.ended_at else max(0,(now()-p.started_at).total_seconds()),3),'source':'persisted'} for p in phases]
    env_by_ts={e.timestamp.isoformat():e for e in env}
    telemetry=[]
    for r in readings:
        e = min(env, key=lambda x: abs((x.timestamp-r.timestamp).total_seconds())) if env else None
        telemetry.append({
            't': r.timestamp.isoformat(), 'time': r.timestamp.strftime('%H:%M:%S'),
            'h_error':round(r.h_error,4), 'v_error':round(r.v_error,4), 'total_error':round(r.total_error,4),
            'azimuth':round(r.azimuth,4), 'elevation':round(r.elevation,4),
            'confidence':round(r.confidence,2), 'signal_dbm':round(r.signal_dbm,2),
            'signal_percent':round(clamp((r.signal_dbm+100)/55*100,0,100),2),
            'alignment_score':round(r.alignment_score,2), 'phase':r.phase,
            'detected':bool(r.detected), 'locked':bool(r.locked), 'fine_locked':bool(r.fine_locked),
            'target_x':round(r.target_x,2), 'target_y':round(r.target_y,2),
            'environment': ({
                'atmospheric_turbulence':round(e.atmospheric_turbulence,2),
                'platform_vibration':round(e.platform_vibration,2),
                'background_noise':round(e.background_noise,2),
                'visibility':round(e.visibility,2), 'scintillation':round(e.scintillation,2),
                'link_reliability':round(e.link_reliability,2)
            } if e else None)
        })
    phase_map={}
    for p in phase_json:
        phase_map[p['phase']]=phase_map.get(p['phase'],0)+p['duration_seconds']
    def phase_time(*names): return round(sum(phase_map.get(n,0) for n in names),3)
    fine_locks=sum(1 for r in readings if r.fine_locked)
    performance={
        'acquisition_seconds':phase_time('ACQUISITION'),
        'coarse_alignment_seconds':phase_time('COARSE ALIGNMENT'),
        'fine_alignment_seconds':phase_time('FINE ALIGNMENT'),
        'reacquisition_seconds':phase_time('REACQUISITION'),
        'target_lost_seconds':phase_time('TARGET LOST'),
        'fine_lock_samples':fine_locks,
        'sample_count':len(readings),
        'average_error':round(sum(r.total_error for r in readings)/len(readings),4) if readings else 0,
        'peak_error':round(max((r.total_error for r in readings),default=0),4),
        'peak_confidence':round(max((r.confidence for r in readings),default=0),2),
        'average_signal_dbm':round(sum(r.signal_dbm for r in readings)/len(readings),2) if readings else 0,
        'average_link_reliability':round(sum((e.link_reliability for e in env))/len(env),2) if env else None
    }
    return jsonify({
        'session':{'id':s.id,'key':s.session_key,'mode':s.mode,'scenario':s.scenario,'status':s.status,
                   'started_at':s.started_at.isoformat(),'ended_at':s.ended_at.isoformat() if s.ended_at else None},
        'thresholds':{'coarse_limit':COARSE_LIMIT,'fine_limit':FINE_LIMIT},
        'readings':telemetry, 'environment':[{
            't':e.timestamp.isoformat(),'time':e.timestamp.strftime('%H:%M:%S'),
            'atmospheric_turbulence':round(e.atmospheric_turbulence,2),
            'platform_vibration':round(e.platform_vibration,2),'background_noise':round(e.background_noise,2),
            'visibility':round(e.visibility,2),'scintillation':round(e.scintillation,2),
            'link_reliability':round(e.link_reliability,2)} for e in env],
        'phase_timings':phase_json, 'phase_totals':{k:round(v,3) for k,v in phase_map.items()},
        'performance':performance
    })

@app.get('/api/analytics/insights')
def api_analytics_insights():
    """Analytics-only read endpoint.
    Reads the existing Live Tracking, Scenario, Live AI Camera and Simulated Camera
    tables. Each data source is isolated so one empty/new table cannot make the whole
    Analytics page return 500 and therefore show zeros.
    """
    scenario_names = list(SCENARIOS.keys())

    def avg(values):
        vals = [float(v) for v in values if v is not None]
        return (sum(vals) / len(vals)) if vals else 0.0

    def pct(a, b):
        return (float(a) / float(b) * 100.0) if b else 0.0

    # ------------------------------------------------------------------
    # 1) LIVE TRACKING / SCENARIO DATA
    # ------------------------------------------------------------------
    try:
        session_count = int(db.session.query(func.count(AlignmentSession.id)).scalar() or 0)
        total_samples = int(db.session.query(func.count(Reading.id)).scalar() or 0)
        avg_error = float(db.session.query(func.avg(Reading.total_error)).scalar() or 0)
        peak_error = float(db.session.query(func.max(Reading.total_error)).scalar() or 0)
        avg_conf = float(db.session.query(func.avg(Reading.confidence)).scalar() or 0)
        avg_signal = float(db.session.query(func.avg(Reading.signal_dbm)).scalar() or 0)
        fine_lock_samples = int(db.session.query(func.count(Reading.id)).filter(Reading.fine_locked.is_(True)).scalar() or 0)

        avg_link = float(db.session.query(func.avg(EnvironmentalReading.link_reliability)).scalar() or 0)

        phase_counts = {}
        for phase, count in db.session.query(Reading.phase, func.count(Reading.id)).group_by(Reading.phase).all():
            phase_counts[phase or 'UNKNOWN'] = int(count)

        command_counts = {}
        for command, count in db.session.query(Reading.command, func.count(Reading.id)).group_by(Reading.command).all():
            command_counts[command or 'HOLD'] = int(count)

        phase_duration = {}
        phase_rows = PhaseTiming.query.order_by(PhaseTiming.id.asc()).all()
        for p in phase_rows:
            d = p.duration_seconds if p.ended_at else max(0, (now() - p.started_at).total_seconds())
            phase_duration[p.phase] = phase_duration.get(p.phase, 0) + float(d or 0)
        if not phase_duration:
            phase_duration = {k: float(v) for k, v in phase_counts.items()}

        # Only the latest points are needed for charts; aggregate KPIs above stay exact.
        recent = Reading.query.order_by(Reading.id.desc()).limit(180).all()
        recent.reverse()
        convergence = [{
            't': r.timestamp.strftime('%H:%M:%S'),
            'h': round(float(r.h_error or 0), 3),
            'v': round(float(r.v_error or 0), 3),
            'total': round(float(r.total_error or 0), 3)
        } for r in recent]

        env_recent = EnvironmentalReading.query.order_by(EnvironmentalReading.id.desc()).limit(180).all()
        env_recent.reverse()
        environment = [{
            't': e.timestamp.strftime('%H:%M:%S'),
            'turbulence': round(float(e.atmospheric_turbulence or 0), 2),
            'vibration': round(float(e.platform_vibration or 0), 2),
            'noise': round(float(e.background_noise or 0), 2),
            'visibility': round(float(e.visibility or 0), 1),
            'scintillation': round(float(e.scintillation or 0), 2),
            'link': round(float(e.link_reliability or 0), 1)
        } for e in env_recent]

        # Scenario statistics are calculated directly from Reading/EnvironmentalReading,
        # so Scenario reports/sessions never get mixed into the Simulated Camera section.
        scenario_data = {}
        for name in scenario_names:
            session_ids = [x[0] for x in db.session.query(AlignmentSession.id)
                           .filter(AlignmentSession.scenario == name).all()]
            if session_ids:
                rrq = Reading.query.filter(Reading.session_id.in_(session_ids))
                eeq = EnvironmentalReading.query.filter(EnvironmentalReading.session_id.in_(session_ids))
                scount = len(session_ids)
                samples = int(rrq.count())
                avge = float(db.session.query(func.avg(Reading.total_error)).filter(Reading.session_id.in_(session_ids)).scalar() or 0)
                peake = float(db.session.query(func.max(Reading.total_error)).filter(Reading.session_id.in_(session_ids)).scalar() or 0)
                conf = float(db.session.query(func.avg(Reading.confidence)).filter(Reading.session_id.in_(session_ids)).scalar() or 0)
                locks = int(db.session.query(func.count(Reading.id)).filter(Reading.session_id.in_(session_ids), Reading.fine_locked.is_(True)).scalar() or 0)
                link = float(db.session.query(func.avg(EnvironmentalReading.link_reliability)).filter(EnvironmentalReading.session_id.in_(session_ids)).scalar() or 0)
                turb = float(db.session.query(func.avg(EnvironmentalReading.atmospheric_turbulence)).filter(EnvironmentalReading.session_id.in_(session_ids)).scalar() or 0)
                vib = float(db.session.query(func.avg(EnvironmentalReading.platform_vibration)).filter(EnvironmentalReading.session_id.in_(session_ids)).scalar() or 0)
                noise = float(db.session.query(func.avg(EnvironmentalReading.background_noise)).filter(EnvironmentalReading.session_id.in_(session_ids)).scalar() or 0)
                vis = float(db.session.query(func.avg(EnvironmentalReading.visibility)).filter(EnvironmentalReading.session_id.in_(session_ids)).scalar() or 0)
                scint = float(db.session.query(func.avg(EnvironmentalReading.scintillation)).filter(EnvironmentalReading.session_id.in_(session_ids)).scalar() or 0)
            else:
                scount = samples = locks = 0
                avge = peake = conf = link = turb = vib = noise = vis = scint = 0.0
            scenario_data[name] = {
                'sessions': scount, 'samples': samples,
                'avg_error': round(avge, 3), 'peak_error': round(peake, 3),
                'confidence': round(conf, 1), 'lock_rate': round(pct(locks, samples), 1),
                'link_reliability': round(link, 1), 'turbulence': round(turb, 2),
                'vibration': round(vib, 2), 'noise': round(noise, 2),
                'visibility': round(vis, 1), 'scintillation': round(scint, 2)
            }

        target_motion = []
        previous = None
        for r in recent:
            if previous is None:
                speed = angular_rate = 0.0
            else:
                dt = max((r.timestamp - previous.timestamp).total_seconds(), 0.001)
                dx = float(r.target_x or 0) - float(previous.target_x or 0)
                dy = float(r.target_y or 0) - float(previous.target_y or 0)
                speed = ((dx * dx + dy * dy) ** 0.5) / dt
                da = ((float(r.azimuth or 0) - float(previous.azimuth or 0)) ** 2 +
                      (float(r.elevation or 0) - float(previous.elevation or 0)) ** 2) ** 0.5
                angular_rate = da / dt
            target_motion.append({
                't': r.timestamp.strftime('%H:%M:%S'), 'x': round(float(r.target_x or 0), 1),
                'y': round(float(r.target_y or 0), 1), 'speed': round(speed, 2),
                'angular_rate': round(angular_rate, 3)
            })
            previous = r

        # Lock/recovery metrics from persisted phase timings and readings.
        lock_durations = [float(p.duration_seconds or 0) for p in phase_rows if p.phase == 'FINE LOCK' and p.ended_at]
        reacq_times = [float(p.duration_seconds or 0) for p in phase_rows if p.phase == 'REACQUISITION' and p.ended_at]
        target_lost_events = sum(1 for p in phase_rows if p.phase == 'TARGET LOST')
        first_lock_seconds = []
        for s in AlignmentSession.query.order_by(AlignmentSession.id.desc()).limit(100).all():
            first_read = Reading.query.filter_by(session_id=s.id).order_by(Reading.id.asc()).first()
            if first_read:
                first = Reading.query.filter(Reading.session_id == s.id, Reading.fine_locked.is_(True)).order_by(Reading.id.asc()).first()
                if first:
                    first_lock_seconds.append(max(0, (first.timestamp - first_read.timestamp).total_seconds()))

        history_rows = AlignmentSession.query.order_by(AlignmentSession.id.desc()).limit(12).all()
        history = []
        for s in history_rows:
            duration = ((s.ended_at - s.started_at).total_seconds() if s.ended_at
                        else max(0, (now() - s.started_at).total_seconds()))
            history.append({
                'session_id': s.id, 'scenario': s.scenario,
                'started': s.started_at.strftime('%Y-%m-%d %H:%M:%S'),
                'duration': round(duration, 1), 'samples': int(s.samples or 0),
                'avg_error': round(float(s.avg_error or 0), 3),
                'peak_error': round(float(s.max_error or 0), 3),
                'lock_count': int(s.lock_count or 0),
                'confidence': round(float(s.peak_confidence or 0), 1),
                'status': s.status
            })
    except Exception as exc:
        # Keep the endpoint alive and return a useful error-free zero block if the
        # user's existing DB is from an older schema. db.create_all() above will
        # create missing additive tables without touching existing data.
        print('Analytics live-tracking aggregation warning:', exc)
        session_count = total_samples = fine_lock_samples = 0
        avg_error = peak_error = avg_conf = avg_signal = avg_link = 0.0
        phase_counts = {}; command_counts = {}; phase_duration = {}
        convergence = []; environment = []; target_motion = []; scenario_data = {}
        lock_durations = reacq_times = first_lock_seconds = []; target_lost_events = 0; history = []

    # ------------------------------------------------------------------
    # 2) LIVE AI CAMERA DATA -- independent of simulator/scenario tables
    # ------------------------------------------------------------------
    try:
        live_count = int(db.session.query(func.count(LiveDetection.id)).scalar() or 0)
        live_conf = float(db.session.query(func.avg(LiveDetection.confidence)).scalar() or 0)
        live_err = float(db.session.query(func.avg(LiveDetection.total_error)).scalar() or 0)
        live_peak = float(db.session.query(func.max(LiveDetection.total_error)).scalar() or 0)
        live_reports_count = int(db.session.query(func.count(LiveReport.id)).scalar() or 0)
        live_completed = int(db.session.query(func.count(LiveReport.id)).filter(LiveReport.status == 'COMPLETED').scalar() or 0)
        duration_rows = LiveReport.query.with_entities(LiveReport.started_at, LiveReport.ended_at).all()
        live_duration = []
        for started_at, ended_at in duration_rows:
            if started_at:
                live_duration.append(max(0, ((ended_at or now()) - started_at).total_seconds()))
        live_sources = {}
        for source, count in db.session.query(LiveDetection.source, func.count(LiveDetection.id)).group_by(LiveDetection.source).all():
            live_sources[source or 'unknown'] = int(count)
        live_recent = LiveDetection.query.order_by(LiveDetection.id.desc()).limit(120).all()
        live_recent.reverse()
        live_series = [{'t': d.timestamp.strftime('%H:%M:%S'), 'error': round(float(d.total_error or 0), 3),
                        'confidence': round(float(d.confidence or 0), 1), 'cx': round(float(d.cx or 0), 1),
                        'cy': round(float(d.cy or 0), 1)} for d in live_recent]
    except Exception as exc:
        print('Analytics live-camera aggregation warning:', exc)
        live_count = live_reports_count = live_completed = 0
        live_conf = live_err = live_peak = 0.0
        live_duration = []; live_sources = {}; live_series = []

    # ------------------------------------------------------------------
    # 3) SIMULATED CAMERA REPORT DATA -- independent from Scenario sessions
    # ------------------------------------------------------------------
    try:
        sim_reports_count = int(db.session.query(func.count(SimulatedCameraReport.id)).scalar() or 0)
        sim_total = int(db.session.query(func.count(SimulatedCameraSample.id)).scalar() or 0)
        sim_conf = float(db.session.query(func.avg(SimulatedCameraSample.confidence)).scalar() or 0)
        sim_err = float(db.session.query(func.avg(SimulatedCameraSample.total_error)).scalar() or 0)
        sim_peak = float(db.session.query(func.max(SimulatedCameraSample.total_error)).scalar() or 0)
        sim_velocity = float(db.session.query(func.avg(SimulatedCameraSample.velocity)).scalar() or 0)
        sim_rate = float(db.session.query(func.avg(SimulatedCameraSample.angular_rate)).scalar() or 0)
        sim_phases = {}
        for phase, count in db.session.query(SimulatedCameraSample.phase, func.count(SimulatedCameraSample.id)).group_by(SimulatedCameraSample.phase).all():
            sim_phases[phase or 'UNKNOWN'] = int(count)
    except Exception as exc:
        print('Analytics simulated-camera aggregation warning:', exc)
        sim_reports_count = sim_total = 0
        sim_conf = sim_err = sim_peak = sim_velocity = sim_rate = 0.0
        sim_phases = {}

    return jsonify({
        'kpi': {
            'sessions': session_count, 'samples': total_samples,
            'avg_error': round(avg_error, 3), 'peak_error': round(peak_error, 3),
            'fine_lock_rate': round(pct(fine_lock_samples, total_samples), 1),
            'ai_confidence': round(avg_conf, 1), 'link_reliability': round(avg_link, 1),
            'signal_dbm': round(avg_signal, 1)
        },
        'phase_counts': phase_counts,
        'phase_duration': {k: round(v, 2) for k, v in phase_duration.items()},
        'commands': command_counts,
        'convergence': convergence, 'environment': environment,
        'target_motion': target_motion, 'scenarios': scenario_data,
        'lock_recovery': {
            'locks': fine_lock_samples,
            'first_lock_seconds': round(avg(first_lock_seconds), 1),
            'avg_lock_duration': round(avg(lock_durations), 1),
            'reacquisition_count': len(reacq_times),
            'avg_reacquisition': round(avg(reacq_times), 1),
            'target_lost_events': target_lost_events
        },
        'live': {
            'runs': live_reports_count, 'detections': live_count,
            'completed_runs': live_completed, 'avg_confidence': round(live_conf, 1),
            'avg_error': round(live_err, 3), 'peak_error': round(live_peak, 3),
            'detection_rate': round(pct(live_count, max(1, live_reports_count)), 1),
            'duration': round(avg(live_duration), 1), 'sources': live_sources,
            'series': live_series
        },
        'simulated': {
            'runs': sim_reports_count, 'samples': sim_total,
            'avg_error': round(sim_err, 3), 'peak_error': round(sim_peak, 3),
            'avg_confidence': round(sim_conf, 1), 'avg_velocity': round(sim_velocity, 2),
            'avg_angular_rate': round(sim_rate, 3), 'phases': sim_phases
        },
        'history': history
    })

@app.get('/api/analytics/historical')
def api_analytics_historical():
    """Historical session performance for the Mission Alignment Performance graph."""
    limit=min(max(request.args.get('limit',10,type=int),1),25)
    sessions=AlignmentSession.query.order_by(AlignmentSession.id.desc()).limit(limit).all()
    rows=[]
    for s in reversed(sessions):
        phases=PhaseTiming.query.filter_by(session_id=s.id).all()
        if phases:
            totals={}
            for p in phases:
                d=p.duration_seconds if p.ended_at else max(0,(now()-p.started_at).total_seconds())
                totals[p.phase]=totals.get(p.phase,0)+d
        else:
            totals={}
            for p in _derived_phase_intervals(s.id): totals[p['phase']]=totals.get(p['phase'],0)+p['duration_seconds']
        total_duration=(s.ended_at-s.started_at).total_seconds() if s.ended_at else max(0,(now()-s.started_at).total_seconds())
        rows.append({'session_id':s.id,'session_key':s.session_key,'scenario':s.scenario,'status':s.status,
                     'total_seconds':round(total_duration,3),'acquisition_seconds':round(totals.get('ACQUISITION',0),3),
                     'coarse_alignment_seconds':round(totals.get('COARSE ALIGNMENT',0),3),
                     'fine_alignment_seconds':round(totals.get('FINE ALIGNMENT',0),3),
                     'reacquisition_seconds':round(totals.get('REACQUISITION',0),3),
                     'target_lost_seconds':round(totals.get('TARGET LOST',0),3),
                     'avg_error':round(s.avg_error,3),'max_error':round(s.max_error,3),
                     'peak_confidence':round(s.peak_confidence,1),'lock_count':s.lock_count,'samples':s.samples})
    return jsonify({'sessions':rows})

@app.get('/api/events')
def api_events():
    cat=request.args.get('category','ALL'); q=request.args.get('q','').lower(); limit=min(int(request.args.get('limit',200)),500)
    query=Event.query.order_by(Event.id.desc())
    if cat!='ALL': query=query.filter_by(category=cat)
    rows=query.limit(limit).all()
    if q: rows=[e for e in rows if q in e.message.lower() or q in e.category.lower()]
    return jsonify([{'id':e.id,'time':e.timestamp.strftime('%Y-%m-%d %H:%M:%S'),'category':e.category,'message':e.message,'severity':e.severity} for e in rows])

@app.post('/api/events/log')
def api_log_event():
    data = request.get_json(silent=True) or {}

    category = str(data.get('category', 'SYSTEM')).strip().upper()
    message = str(data.get('message', '')).strip()
    severity = str(data.get('severity', 'INFO')).strip().upper()
    session_id = data.get('session_id')

    allowed_categories = {
        'DETECTION',
        'TRACKING',
        'ALIGNMENT',
        'SYSTEM',
        'AI'
    }

    allowed_severity = {
        'INFO',
        'SUCCESS',
        'WARNING',
        'ERROR'
    }

    if category not in allowed_categories:
        category = 'SYSTEM'

    if severity not in allowed_severity:
        severity = 'INFO'

    if not message:
        return jsonify({
            'ok': False,
            'error': 'Event message is required'
        }), 400

    if session_id:
        try:
            session_id = int(session_id)
        except (TypeError, ValueError):
            session_id = None

    row = Event(
        category=category,
        message=message,
        severity=severity,
        session_id=session_id
    )

    db.session.add(row)
    db.session.commit()

    return jsonify({
        'ok': True,
        'id': row.id,
        'time': row.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        'category': row.category,
        'message': row.message,
        'severity': row.severity
    })

@app.get('/api/alerts')
def api_alerts():
    return jsonify([{'id':a.id,'time':a.timestamp.strftime('%Y-%m-%d %H:%M:%S'),'category':a.category,'message':a.message,'severity':a.severity,'acknowledged':a.acknowledged} for a in Alert.query.order_by(Alert.id.desc()).limit(200).all()])

@app.post('/api/alerts/<int:aid>/ack')
def ack_alert(aid):
    a = db.session.get(Alert, aid)
    if not a:
        return jsonify({'error':'Not found'}), 404
    a.acknowledged = True
    db.session.commit()
    socketio.emit('alert_acknowledged', {
        'id': a.id,
        'acknowledged': True
    })
    return jsonify({'ok':True, 'id':a.id, 'acknowledged':True})

@app.get('/api/settings')
def api_settings(): return jsonify({x.key:x.value for x in AppSetting.query.all()})
@app.post('/api/settings')
def api_settings_save():
    data=request.get_json(silent=True) or {}
    for k,v in data.items():
        if AppSetting.query.get(k): AppSetting.query.get(k).value=str(v)
    db.session.commit(); event('SYSTEM','Operator settings updated','INFO'); db.session.commit(); return jsonify({'ok':True})

@app.get('/video_feed')
def video_feed():
    def generate():
        while True:
            jpg = LIVE_CAMERA.get_jpeg()
            if jpg is not None:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')
            else:
                # camera thread may not have produced a frame yet
                import time as _t; _t.sleep(0.05)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.post('/api/simulated-camera/start')
def api_simulated_camera_start():
    global SIM_CAMERA_REPORT_ID
    if SIM_CAMERA_REPORT_ID:
        old = db.session.get(SimulatedCameraReport, SIM_CAMERA_REPORT_ID)
        if old and old.status == 'ACTIVE':
            old.status = 'COMPLETED'; old.ended_at = now()
    report = SimulatedCameraReport(target_id=(request.get_json(silent=True) or {}).get('target_id','—'), status='ACTIVE')
    db.session.add(report); db.session.flush(); SIM_CAMERA_REPORT_ID = report.id
    db.session.commit()
    return jsonify({'ok':True,'report_id':report.id})

@app.post('/api/simulated-camera/sample')
def api_simulated_camera_sample():
    report_id = (request.get_json(silent=True) or {}).get('report_id')
    report = db.session.get(SimulatedCameraReport, report_id) if report_id else None
    if not report or report.status != 'ACTIVE': return jsonify({'ok':False,'error':'No active simulated camera report'}), 404
    d=request.get_json(silent=True) or {}
    sample=SimulatedCameraSample(report_id=report.id, target_id=d.get('target_id','—'), x=float(d.get('x',0)), y=float(d.get('y',0)),
        h_error=float(d.get('h_error',0)), v_error=float(d.get('v_error',0)), total_error=float(d.get('total_error',0)),
        pixel_error=float(d.get('pixel_error',0)), confidence=float(d.get('confidence',0)), velocity=float(d.get('velocity',0)),
        angular_rate=float(d.get('angular_rate',0)), phase=d.get('phase','TRACKING'))
    db.session.add(sample); report.sample_count = (report.sample_count or 0)+1
    vals=SimulatedCameraSample.query.filter_by(report_id=report.id).all()
    report.avg_error = sum(x.total_error for x in vals)/len(vals) if vals else 0
    report.max_error = max((x.total_error for x in vals), default=0)
    report.peak_confidence = max((x.confidence for x in vals), default=0)
    report.target_id = sample.target_id
    db.session.commit()
    return jsonify({'ok':True})

@app.post('/api/simulated-camera/stop')
def api_simulated_camera_stop():
    global SIM_CAMERA_REPORT_ID
    report = db.session.get(SimulatedCameraReport, SIM_CAMERA_REPORT_ID) if SIM_CAMERA_REPORT_ID else None
    if report:
        report.status='COMPLETED'; report.ended_at=now(); db.session.commit()
    rid = report.id if report else None
    SIM_CAMERA_REPORT_ID=None
    return jsonify({'ok':True,'report_id':rid})

@app.get('/api/reports/simulated')
def api_reports_simulated():
    rows = SimulatedCameraReport.query.order_by(SimulatedCameraReport.id.desc()).limit(100).all()
    return jsonify([{
        'id': r.id, 'target_id': r.target_id, 'status': r.status,
        'started': r.started_at.isoformat(), 'ended': r.ended_at.isoformat() if r.ended_at else None,
        'samples': r.sample_count, 'avg_error': round(r.avg_error or 0,3), 'max_error': round(r.max_error or 0,3),
        'peak_confidence': round(r.peak_confidence or 0,1), 'download_url': f'/reports/simulated/{r.id}/pdf'
    } for r in rows])

@app.post('/api/live/start')
def api_live_start():
    global LIVE_REPORT_ID
    try:
        LIVE_ENGINE.start()
    except RuntimeError as exc:
        return jsonify({'ok': False, 'running': False, 'error': str(exc), 'camera_mode': LIVE_CAMERA.mode}), 503

    first = LiveDetection.query.order_by(LiveDetection.id.desc()).first()
    report = LiveReport(
        detector=LIVE_ENGINE.active_detector or 'opencv',
        camera_mode=LIVE_CAMERA.mode or 'synthetic',
        first_detection_id=(first.id + 1) if first else 1,
        status='ACTIVE'
    )
    db.session.add(report)
    db.session.flush()
    LIVE_REPORT_ID = report.id

    event('SYSTEM', f'Live physical camera tracking started · detector: {LIVE_ENGINE.active_detector} · camera: {LIVE_CAMERA.mode}', 'SUCCESS')
    db.session.commit()
    return jsonify({'ok': True, 'running': True, 'report_id': report.id,
                    'detector': LIVE_ENGINE.active_detector, 'yolo_available': LIVE_ENGINE.yolo_available,
                    'camera_mode': LIVE_CAMERA.mode})

@app.post('/api/live/stop')
def api_live_stop():
    global LIVE_REPORT_ID
    LIVE_ENGINE.stop()

    report = db.session.get(LiveReport, LIVE_REPORT_ID) if LIVE_REPORT_ID else None
    if report:
        last = LiveDetection.query.order_by(LiveDetection.id.desc()).first()
        report.last_detection_id = last.id if last else report.first_detection_id
        if report.first_detection_id and report.last_detection_id:
            report.detection_count = max(0, report.last_detection_id - report.first_detection_id + 1)
        else:
            report.detection_count = 0
        report.ended_at = now()
        report.status = 'COMPLETED'

    event('SYSTEM', 'Live AI camera pipeline stopped', 'INFO')
    db.session.commit()
    LIVE_REPORT_ID = None
    return jsonify({'ok': True, 'running': False, 'report_id': report.id if report else None})

@app.get('/api/live/status')
def api_live_status():
    return jsonify({
        'running': LIVE_ENGINE.is_running,
        'detector': LIVE_ENGINE.active_detector,
        'yolo_available': LIVE_ENGINE.yolo_available,
        'camera_mode': LIVE_CAMERA.mode,
        'camera_error': LIVE_CAMERA.error,
        'coarse_limit': COARSE_LIMIT, 'fine_limit': FINE_LIMIT,
    })

@app.get('/api/live/history')
def api_live_history():
    limit = min(int(request.args.get('limit', 100)), 500)
    rows = LiveDetection.query.order_by(LiveDetection.id.desc()).limit(limit).all()
    return jsonify([{
        't': r.timestamp.strftime('%H:%M:%S'), 'source': r.source, 'cx': r.cx, 'cy': r.cy,
        'h_error': r.h_error, 'v_error': r.v_error, 'total_error': r.total_error,
        'confidence': r.confidence, 'phase': r.phase,
    } for r in reversed(rows)])

@app.get('/api/live/alerts')
def api_live_alerts():
    limit = min(int(request.args.get('limit', 50)), 200)
    rows = LiveAlert.query.order_by(LiveAlert.id.desc()).limit(limit).all()
    return jsonify([{'id': r.id, 'time': r.timestamp.strftime('%H:%M:%S'), 'severity': r.severity, 'message': r.message} for r in rows])

@app.get('/export-live.csv')
def export_live_csv():
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(['timestamp', 'source', 'cx', 'cy', 'h_error_deg', 'v_error_deg', 'total_error_deg', 'confidence_pct', 'phase'])
    for r in LiveDetection.query.order_by(LiveDetection.id.asc()).all():
        w.writerow([r.timestamp.isoformat(), r.source, round(r.cx, 2), round(r.cy, 2), r.h_error, r.v_error, r.total_error, r.confidence, r.phase])
    return Response(out.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=fsoc_live_ai_detections.csv'})

@app.get('/export.csv')
def export_csv():
    out=io.StringIO(); w=csv.writer(out); w.writerow(['session_id','timestamp','scenario','phase','command','target_x','target_y','horizontal_error_deg','vertical_error_deg','total_error_deg','azimuth_deg','elevation_deg','confidence_pct','signal_dbm','alignment_score_pct','fine_locked','atmospheric_turbulence','platform_vibration','background_noise','visibility','scintillation','link_reliability'])
    for r in Reading.query.join(AlignmentSession,Reading.session_id==AlignmentSession.id).order_by(Reading.id.asc()).all():
        e=EnvironmentalReading.query.filter_by(session_id=r.session_id).order_by(db.func.abs(db.func.julianday(EnvironmentalReading.timestamp)-db.func.julianday(r.timestamp))).first()
        w.writerow([r.session_id,r.timestamp.isoformat(),db.session.get(AlignmentSession,r.session_id).scenario,r.phase,r.command,round(r.target_x,2),round(r.target_y,2),r.h_error,r.v_error,r.total_error,r.azimuth,r.elevation,r.confidence,r.signal_dbm,r.alignment_score,r.fine_locked,
                    e.atmospheric_turbulence if e else '',e.platform_vibration if e else '',e.background_noise if e else '',e.visibility if e else '',e.scintillation if e else '',e.link_reliability if e else ''])
    return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=fsoc_alignment_readings.csv'})

@app.get('/export.json')
def export_json():
    data=[]
    for r in Reading.query.order_by(Reading.id.asc()).all():
        s=db.session.get(AlignmentSession,r.session_id)
        data.append({'session_id':r.session_id,'scenario':s.scenario,'timestamp':r.timestamp.isoformat(),'phase':r.phase,'command':r.command,'h_error':r.h_error,'v_error':r.v_error,'total_error':r.total_error,'confidence':r.confidence,'signal_dbm':r.signal_dbm,'alignment_score':r.alignment_score,'fine_locked':r.fine_locked})
    return Response(json.dumps(data,indent=2),mimetype='application/json',headers={'Content-Disposition':'attachment; filename=fsoc_alignment_data.json'})

def _gather_report_data():
    analytics = api_analytics().get_json()['kpi']
    sim_readings = [{'total_error': r.total_error, 'confidence': r.confidence, 'phase': r.phase}
                     for r in Reading.query.order_by(Reading.id.asc()).all()]
    live_rows = LiveDetection.query.order_by(LiveDetection.id.asc()).all()
    live_detections = [{'total_error': r.total_error, 'confidence': r.confidence, 'phase': r.phase, 'source': r.source}
                        for r in live_rows]
    live_meta = {
        'detector': (live_rows[-1].source if live_rows else LIVE_ENGINE.active_detector),
        'camera_mode': LIVE_CAMERA.mode,
    }
    return analytics, sim_readings, live_detections, live_meta

def _build_report():
    from report_builder import build_report_pdf
    analytics, sim_readings, live_detections, live_meta = _gather_report_data()
    path = os.path.join(BASE, 'reports', 'FSOC_Performance_Report.pdf')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    build_report_pdf(path, analytics, sim_readings, live_detections, live_meta=live_meta,
                      coarse_limit=COARSE_LIMIT, fine_limit=FINE_LIMIT)
    return path

@app.get('/reports/pdf')
def report_pdf():
    try:
        path = _build_report()
    except ImportError:
        return 'Install reportlab with: pip install reportlab', 500
    return send_file(path, as_attachment=True, download_name='FSOC_Performance_Report.pdf')

@app.get('/reports/pdf/preview')
def report_pdf_preview():
    """Same report, served inline (not as a download) so it can be shown in an <iframe> before the user commits to downloading it."""
    try:
        path = _build_report()
    except ImportError:
        return 'Install reportlab with: pip install reportlab', 500
    return send_file(path, mimetype='application/pdf', as_attachment=False, download_name='FSOC_Performance_Report.pdf')

def _build_target_lost_report():
    """Generate a fresh Target Lost incident PDF for the active incident."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    path = os.path.join(BASE, 'reports', 'Target_Lost_Incident_Report.pdf')
    os.makedirs(os.path.dirname(path), exist_ok=True)

    session_id = SIM.get('session_id')
    scenario = SIM.get('scenario', 'Target Lost')
    latest = None
    if session_id:
        latest = Reading.query.filter_by(session_id=session_id).order_by(Reading.id.desc()).first()

    incident_time = SIM.get('target_lost_at') or now().isoformat()

    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    y = h - 25 * mm

    # Use standard Helvetica-safe ASCII text so the PDF works without a font plugin.
    c.setFillColor(colors.HexColor('#8b0000'))
    c.setFont('Helvetica-Bold', 18)
    c.drawString(20 * mm, y, 'TARGET LOST - INCIDENT REPORT')
    y -= 12 * mm

    c.setFillColor(colors.black)
    rows = [
        ('Incident Time', str(incident_time)[:32]),
        ('Scenario', scenario),
        ('Status', 'TARGET LOST'),
        ('Response', 'Siren activated; automatic reacquisition initiated'),
        ('Session ID', str(session_id or 'N/A')),
        ('Detection', 'Optical beacon unavailable'),
        ('Recovery Mode', 'Automatic reacquisition'),
    ]

    for label, value in rows:
        c.setFont('Helvetica-Bold', 10)
        c.drawString(22 * mm, y, label + ':')
        c.setFont('Helvetica', 10)
        c.drawString(62 * mm, y, str(value)[:105])
        y -= 8 * mm

    y -= 4 * mm
    c.setFont('Helvetica-Bold', 12)
    c.drawString(20 * mm, y, 'LATEST TRACKING TELEMETRY')
    y -= 9 * mm

    incident = SIM.get('target_lost_telemetry') or {}
    telemetry = [
        ('Horizontal Error', incident.get('horizontal_error', getattr(latest, 'h_error', None) if latest else None)),
        ('Vertical Error', incident.get('vertical_error', getattr(latest, 'v_error', None) if latest else None)),
        ('Total Error', incident.get('total_error', getattr(latest, 'total_error', None) if latest else None)),
        ('AI Confidence', incident.get('confidence', getattr(latest, 'confidence', None) if latest else None)),
        ('Signal Strength', incident.get('signal_dbm', getattr(latest, 'signal_dbm', None) if latest else None)),
        ('Alignment Score', incident.get('alignment_score', getattr(latest, 'alignment_score', None) if latest else None)),
        ('Phase', 'TARGET LOST'),
    ]

    for label, value in telemetry:
        c.setFont('Helvetica-Bold', 9)
        c.drawString(22 * mm, y, label + ':')
        c.setFont('Helvetica', 9)
        c.drawString(62 * mm, y, '--' if value is None else str(value))
        y -= 6.5 * mm

    y -= 6 * mm
    c.setFillColor(colors.HexColor('#555555'))
    c.setFont('Helvetica', 8)
    c.drawString(20 * mm, y, 'Generated automatically by TRACKAI Target Lost alert system.')
    c.save()
    return path


@app.get('/reports/target-lost/pdf')
def target_lost_report_pdf():
    try:
        path = _build_target_lost_report()
    except ImportError:
        return 'Install reportlab with: pip install reportlab', 500
    except Exception as exc:
        app.logger.exception('Target Lost PDF download failed: %s', exc)
        return jsonify({'error': 'Target Lost PDF generation failed'}), 500
    return send_file(path, as_attachment=True, download_name='Target_Lost_Incident_Report.pdf')


@app.get('/reports/target-lost/pdf/preview')
def target_lost_report_preview():
    try:
        path = _build_target_lost_report()
    except ImportError:
        return 'Install reportlab with: pip install reportlab', 500
    except Exception as exc:
        app.logger.exception('Target Lost PDF preview failed: %s', exc)
        return jsonify({'error': 'Target Lost PDF generation failed'}), 500
    return send_file(path, mimetype='application/pdf', as_attachment=False, download_name='Target_Lost_Incident_Report.pdf')



# ============================================================
# INTERCONNECTED REPORT CENTER
# ============================================================

def _report_pdf(path, title, subtitle, rows, summary=None):
    """Build a compact operational PDF from already-persisted SQLite data."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    margin = 15 * mm
    y = h - 18 * mm

    def header():
        nonlocal y
        c.setFillColor(colors.HexColor('#12233f'))
        c.setFont('Helvetica-Bold', 16)
        c.drawString(margin, y, 'TRACKAI · FSOC REPORT')
        y -= 8 * mm
        c.setFont('Helvetica-Bold', 11)
        c.setFillColor(colors.HexColor('#1769e0'))
        c.drawString(margin, y, title[:90])
        y -= 5 * mm
        c.setFont('Helvetica', 8.5)
        c.setFillColor(colors.HexColor('#53687d'))
        c.drawString(margin, y, subtitle[:120])
        y -= 9 * mm

    def footer():
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.HexColor('#7b8794'))
        c.drawString(margin, 9 * mm, 'Generated from persisted FSOC SQLite telemetry · TRACKAI')
        c.drawRightString(w - margin, 9 * mm, f'Page {c.getPageNumber()}')

    header()

    if summary:
        c.setFillColor(colors.HexColor('#f2f7fb'))
        c.roundRect(margin, y-18*mm, w-2*margin, 17*mm, 3*mm, fill=1, stroke=0)
        sx = margin + 4*mm
        sy = y - 6*mm
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(colors.HexColor('#23384d'))
        for i,(k,v) in enumerate(summary.items()):
            c.drawString(sx, sy, f'{k}: {v}')
            sx += 45*mm
            if sx > w - 55*mm:
                sx = margin + 4*mm
                sy -= 6*mm
        y -= 23*mm

    headers = ['TIME','SOURCE','X / CX','Y / CY','H ERR','V ERR','TOTAL','CONF','PHASE']
    widths = [27, 30, 19, 19, 19, 19, 20, 18, 28]
    x = margin
    def draw_table_header():
        nonlocal y
        c.setFillColor(colors.HexColor('#17304d'))
        c.rect(margin, y-7*mm, w-2*margin, 7*mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont('Helvetica-Bold', 6.5)
        xx=margin
        for hd,wd in zip(headers,widths):
            c.drawString(xx+1.2*mm, y-4.5*mm, hd)
            xx += wd*mm
        y -= 9*mm

    draw_table_header()
    c.setFont('Helvetica', 6.6)
    for row in rows:
        if y < 18*mm:
            footer(); c.showPage(); y = h - 18*mm; header(); draw_table_header(); c.setFont('Helvetica', 6.6)
        vals = [
            row.get('time','-'), row.get('source','-'),
            row.get('x','-'), row.get('y','-'),
            row.get('h','-'), row.get('v','-'),
            row.get('total','-'), row.get('conf','-'), row.get('phase','-')
        ]
        xx=margin
        c.setFillColor(colors.HexColor('#22324a'))
        for val,wd in zip(vals,widths):
            text=str(val)
            c.drawString(xx+1.2*mm, y, text[:22])
            xx += wd*mm
        c.setStrokeColor(colors.HexColor('#e4ebf2'))
        c.line(margin, y-1.5*mm, w-margin, y-1.5*mm)
        y -= 5.5*mm
    footer()
    c.save()
    return path


def _sim_report_payload(session):
    readings = Reading.query.filter_by(session_id=session.id).order_by(Reading.id.asc()).all()
    rows = []
    for r in readings:
        rows.append({
            'time': r.timestamp.strftime('%H:%M:%S'),
            'source': 'SIM',
            'x': f'{r.target_x:.0f}', 'y': f'{r.target_y:.0f}',
            'h': f'{r.h_error:+.2f}°', 'v': f'{r.v_error:+.2f}°',
            'total': f'{r.total_error:.2f}°', 'conf': f'{r.confidence:.1f}%',
            'phase': r.phase
        })
    return readings, rows


@app.get('/api/reports/live')
def api_reports_live():
    rows = LiveReport.query.order_by(LiveReport.id.desc()).limit(100).all()
    result = []
    for r in rows:
        result.append({
            'id': r.id,
            'started': r.started_at.isoformat(),
            'ended': r.ended_at.isoformat() if r.ended_at else None,
            'detector': r.detector, 'camera_mode': r.camera_mode,
            'detection_count': r.detection_count,
            'status': r.status,
            'download_url': f'/reports/live/{r.id}/pdf'
        })
    return jsonify(result)


@app.get('/api/reports/scenarios')
def api_reports_scenarios():
    result = []
    descriptions = {
        'Nominal Orbital':'Stable orbital beacon tracking',
        'Atmospheric Turbulence':'Scintillation + optical turbulence',
        'Platform Vibration':'Gimbal/platform vibration',
        'Low Beacon SNR':'Weak beacon + noisy detection',
        'Fast Target Motion':'High angular-rate target',
        'Target Lost':'Beacon loss + siren + instant report'
    }
    for name in SCENARIOS.keys():
        sessions = AlignmentSession.query.filter_by(scenario=name).order_by(AlignmentSession.id.desc()).all()
        session_reports = []
        for ss in sessions:
            readings = Reading.query.filter_by(session_id=ss.id).order_by(Reading.id.asc()).all()
            session_reports.append({
                'session_id': ss.id,
                'session_key': ss.session_key,
                'status': ss.status,
                'started': ss.started_at.isoformat(),
                'ended': ss.ended_at.isoformat() if ss.ended_at else None,
                'samples': len(readings),
                'avg_error': round(sum(r.total_error for r in readings)/len(readings), 3) if readings else 0,
                'max_error': round(max((r.total_error for r in readings), default=0), 3),
                'peak_confidence': round(max((r.confidence for r in readings), default=0), 1),
                'download_url': f'/reports/scenario/{quote(name, safe="")}/{ss.id}'
            })
        result.append({
            'scenario': name,
            'description': descriptions.get(name, ''),
            'sessions': len(session_reports),
            'samples': sum(x['samples'] for x in session_reports),
            'session_reports': session_reports
        })
    return jsonify(result)


@app.get('/reports/simulated/<int:sid>/pdf')
def report_simulated_pdf(sid):
    r = db.session.get(SimulatedCameraReport, sid)
    if not r: return jsonify({'error':'Report not found'}), 404
    samples = SimulatedCameraSample.query.filter_by(report_id=r.id).order_by(SimulatedCameraSample.id.asc()).all()
    rows=[{'time':x.timestamp.strftime('%H:%M:%S'),'source':x.target_id,'x':f'{x.x:.1f}%','y':f'{x.y:.1f}%',
           'h':f'{x.h_error:+.2f}°','v':f'{x.v_error:+.2f}°','total':f'{x.total_error:.2f}°',
           'conf':f'{x.confidence:.1f}%','phase':x.phase} for x in samples]
    if len(rows)>900: rows=rows[-900:]
    path=os.path.join(BASE,'reports','simulated',f'Simulated_Camera_Report_{sid}.pdf')
    _report_pdf(path,f'Live Tracking · Simulated Scenario Camera Report · Run #{sid}',
                f'{r.target_id} · {r.status}',rows,{'Samples':len(samples),'Avg Error':f'{r.avg_error:.3f}°',
                'Max Error':f'{r.max_error:.3f}°','Peak Confidence':f'{r.peak_confidence:.1f}%'})
    return send_file(path,as_attachment=True,download_name=f'Simulated_Camera_Report_{sid}.pdf')


@app.get('/reports/live/<int:rid>/pdf')
def report_live_pdf(rid):
    r = db.session.get(LiveReport, rid)
    if not r:
        return jsonify({'error':'Live report not found'}), 404
    q = LiveDetection.query
    if r.first_detection_id is not None:
        q = q.filter(LiveDetection.id >= r.first_detection_id)
    if r.last_detection_id is not None:
        q = q.filter(LiveDetection.id <= r.last_detection_id)
    detections = q.order_by(LiveDetection.id.asc()).all()
    rows = [{
        'time': d.timestamp.strftime('%H:%M:%S'),
        'source': d.source.upper(), 'x':f'{d.cx:.0f}', 'y':f'{d.cy:.0f}',
        'h':f'{d.h_error:+.2f}°', 'v':f'{d.v_error:+.2f}°',
        'total':f'{d.total_error:.2f}°', 'conf':f'{d.confidence:.1f}%',
        'phase':d.phase
    } for d in detections]
    avg = sum(d.total_error for d in detections)/len(detections) if detections else 0
    path = os.path.join(BASE, 'reports', 'live', f'Live_AI_Camera_Report_{rid}.pdf')
    _report_pdf(path, f'Live AI Camera Report · Run #{rid}',
                f'{r.detector.upper()} · {r.camera_mode.upper()} · {r.status}',
                rows, {'Detections':len(detections), 'Avg Error':f'{avg:.3f}°',
                       'Started':r.started_at.strftime('%Y-%m-%d %H:%M:%S'),
                       'Ended':r.ended_at.strftime('%Y-%m-%d %H:%M:%S') if r.ended_at else 'ACTIVE'})
    return send_file(path, as_attachment=True, download_name=f'Live_AI_Camera_Report_{rid}.pdf')


@app.get('/reports/scenario/<path:name>/<int:sid>')
def report_scenario_session_pdf(name, sid):
    if name not in SCENARIOS:
        return jsonify({'error':'Unknown scenario'}), 404
    session = db.session.get(AlignmentSession, sid)
    if not session or session.scenario != name:
        return jsonify({'error':'Scenario session not found'}), 404
    readings = Reading.query.filter_by(session_id=session.id).order_by(Reading.id.asc()).all()
    rows = [{
        'time': r.timestamp.strftime('%H:%M:%S'),
        'source': f'S#{r.session_id}', 'x':f'{r.target_x:.0f}', 'y':f'{r.target_y:.0f}',
        'h':f'{r.h_error:+.2f}°', 'v':f'{r.v_error:+.2f}°',
        'total':f'{r.total_error:.2f}°', 'conf':f'{r.confidence:.1f}%',
        'phase':r.phase
    } for r in readings]
    if len(rows) > 900:
        rows = rows[-900:]
    avg = sum(r.total_error for r in readings)/len(readings) if readings else 0
    safe_name = re.sub(r'[^A-Za-z0-9_-]+', '_', name)
    path = os.path.join(BASE, 'reports', 'scenarios', safe_name, f'{safe_name}_Session_{sid}.pdf')
    _report_pdf(path, f'Scenario Report · {name} · Session #{sid}',
                f'{session.status} · {len(readings)} persisted telemetry samples',
                rows, {'Session ID':sid, 'Samples':len(readings),
                       'Average Error':f'{avg:.3f}°',
                       'Maximum Error':f'{max((r.total_error for r in readings), default=0):.3f}°',
                       'Peak Confidence':f'{max((r.confidence for r in readings), default=0):.1f}%'})
    return send_file(path, as_attachment=True,
                     download_name=f'{safe_name}_Session_{sid}_Report.pdf')

if __name__ == "__main__":
    socketio.run(app, host="127.0.0.1", port=5000, debug=True, allow_unsafe_werkzeug=True)
