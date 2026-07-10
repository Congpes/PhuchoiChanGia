import cv2
import mp_image as mp_img
import mediapipe as mp
import math
import time
import threading
import json
import os
import uuid
import sqlite3
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistent SQLite Database Setup
DB_FILE = os.path.join(os.path.dirname(__file__), "gait_analysis.db")

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # Create Patients Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        age INTEGER,
        height_cm REAL,
        weight_kg REAL,
        healthy_leg TEXT CHECK(healthy_leg IN ('LEFT', 'RIGHT')),
        prosthetic_leg TEXT CHECK(prosthetic_leg IN ('LEFT', 'RIGHT'))
    );
    """)
    
    # Create Sessions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        patient_id TEXT,
        created_at TEXT,
        FOREIGN KEY(patient_id) REFERENCES patients(id) ON DELETE CASCADE
    );
    """)
    
    # Create Scans Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scans (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        scan_type TEXT,
        label TEXT,
        left_knee TEXT,
        right_knee TEXT,
        left_ankle TEXT,
        right_ankle TEXT,
        pelvic_tilt TEXT,
        cadence REAL,
        stride_length REAL,
        actual_adjustment_degrees REAL DEFAULT 0.0,
        actual_adjustment_notes TEXT DEFAULT '',
        recorded_at TEXT,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );
    """)
    
    conn.commit()
    conn.close()

def populate_mock_data():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patients")
    count = cursor.fetchone()[0]
    if count == 0:
        # Nguyễn Văn An (45 tuổi, cụt chân phải)
        cursor.execute("INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?, ?)",
                       ("p-01", "Nguyễn Văn An", 45, 172.0, 68.0, "LEFT", "RIGHT"))
        
        # Session 1
        cursor.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                       ("s-01", "p-01", "2026-07-08T09:30:00Z"))
        
        # Curves
        left_knee_base = [62 - math.sin(i / 10) * 12 for i in range(101)]
        right_knee_base = [50 - math.sin(i / 10) * 10 for i in range(101)]
        left_ankle_base = [10 + math.cos(i / 15) * 5 for i in range(101)]
        right_ankle_base = [8 + math.cos(i / 15) * 4 for i in range(101)]
        pelvic_base = [math.sin(i / 8) * 2.5 for i in range(101)]
        
        cursor.execute("INSERT INTO scans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("baseline", "s-01", "baseline", "Baseline chân lành",
                        json.dumps(left_knee_base), json.dumps(right_knee_base),
                        json.dumps(left_ankle_base), json.dumps(right_ankle_base),
                        json.dumps(pelvic_base), 112.0, 0.82, 0.0, "", "2026-07-08T09:32:00Z"))
        
        # Scan 1: Đánh giá chân giả (Deficit)
        left_knee_s1 = [62 - math.sin(i / 10) * 12 for i in range(101)]
        right_knee_s1 = [42 - math.sin(i / 10) * 8 for i in range(101)]
        left_ankle_s1 = [10 + math.cos(i / 15) * 5 for i in range(101)]
        right_ankle_s1 = [4 + math.cos(i / 15) * 2 for i in range(101)]
        pelvic_s1 = [math.sin(i / 8) * 8.2 for i in range(101)]
        
        cursor.execute("INSERT INTO scans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("scan_1", "s-01", "scan_1", "Đánh giá chân giả - Scan #1",
                        json.dumps(left_knee_s1), json.dumps(right_knee_s1),
                        json.dumps(left_ankle_s1), json.dumps(right_ankle_s1),
                        json.dumps(pelvic_s1), 90.0, 0.62, 10.0, "Nới lỏng phuộc gối phải 10 độ", "2026-07-08T09:35:00Z"))
        
        # Scan 2: Đánh giá sau căn chỉnh (Improved)
        left_knee_s2 = [62 - math.sin(i / 10) * 12 for i in range(101)]
        right_knee_s2 = [52 - math.sin(i / 10) * 11 for i in range(101)]
        left_ankle_s2 = [10 + math.cos(i / 15) * 5 for i in range(101)]
        right_ankle_s2 = [8 + math.cos(i / 15) * 4 for i in range(101)]
        pelvic_s2 = [math.sin(i / 8) * 4.1 for i in range(101)]
        
        cursor.execute("INSERT INTO scans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("scan_2", "s-01", "scan_2", "Đánh giá chân giả - Scan #2",
                        json.dumps(left_knee_s2), json.dumps(right_knee_s2),
                        json.dumps(left_ankle_s2), json.dumps(right_ankle_s2),
                        json.dumps(pelvic_s2), 108.0, 0.78, 0.0, "Dáng đi cải thiện rõ rệt, kết thúc phiên tinh chỉnh.", "2026-07-08T09:42:00Z"))
        
        # Patient 2: Lê Hoàng Nam (32 tuổi, cụt chân trái)
        cursor.execute("INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?, ?)",
                       ("p-02", "Lê Hoàng Nam", 32, 168.0, 58.0, "RIGHT", "LEFT"))
        
        conn.commit()
    conn.close()

# Start up initialization
init_db()
populate_mock_data()

# Global variables for recording state
is_recording = False
record_start_time = 0.0
record_duration = 10.0
healthy_leg = 'LEFT'
prosthetic_leg = 'RIGHT'
recorded_left_knee = []
recorded_right_knee = []
recorded_left_ankle = []
recorded_right_ankle = []
recorded_pelvic_tilt = []

# Recording target identifiers
active_session_id = ""
active_scan_type = "baseline"

# Thread sharing variables
latest_frame = None
frame_lock = threading.Lock()
running = True

# MediaPipe Pose initialization
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=1,
    smooth_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

def calculate_angle(a, b, c):
    """Tính góc giữa 3 điểm: Hông (a), Đầu gối (b - đỉnh góc), Mắt cá (c)"""
    try:
        radians = math.atan2(c[1] - b[1], c[0] - b[0]) - math.atan2(a[1] - b[1], a[0] - b[0])
        angle = abs(radians * 180.0 / math.pi)
        if angle > 180.0:
            angle = 360.0 - angle
        return int(angle)
    except Exception:
        return 0

def draw_overlay_text(frame, text, pos, color=(255, 255, 255), scale=0.7, thickness=2):
    """Hàm vẽ chữ có viền đen để dễ đọc trên mọi nền sáng/tối"""
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)

def resample(data, target_len=101):
    if not data:
        return [0.0 for _ in range(target_len)]
    if len(data) == target_len:
        return data
    resampled = []
    for i in range(target_len):
        idx = i * (len(data) - 1) / (target_len - 1)
        low = int(math.floor(idx))
        high = int(math.ceil(idx))
        weight = idx - low
        val = data[low] * (1 - weight) + data[high] * weight
        resampled.append(round(val, 2))
    return resampled

def count_peaks(angles, threshold=45):
    """Đếm số chu kỳ dao động khớp để tính nhịp Cadence"""
    peaks = 0
    state = "low"
    for a in angles:
        if state == "low" and a > threshold:
            peaks += 1
            state = "high"
        elif state == "high" and a < (threshold - 10):
            state = "low"
    return max(1, peaks)

def save_recorded_data_to_db():
    global recorded_left_knee, recorded_right_knee, recorded_left_ankle, recorded_right_ankle, recorded_pelvic_tilt
    global active_session_id, active_scan_type, healthy_leg
    
    left_knee = resample(recorded_left_knee)
    right_knee = resample(recorded_right_knee)
    left_ankle = resample(recorded_left_ankle)
    right_ankle = resample(recorded_right_ankle)
    pelvic_tilt = resample(recorded_pelvic_tilt)
    
    # Calculate Cadence based on healthy knee sway peaks
    knee_angles = left_knee if healthy_leg == 'LEFT' else right_knee
    peaks = count_peaks(knee_angles)
    cadence_val = float(peaks * 2 * 6)
    
    # Calculate height from db to estimate stride length
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT height_cm FROM patients WHERE id = (SELECT patient_id FROM sessions WHERE id = ?)", (active_session_id,))
    res = cursor.fetchone()
    height_cm = res[0] if res else 170.0
    
    # Realistic stride length estimation (meters)
    stride_len_val = round(0.52 * (height_cm / 170.0) + (peaks / 6) * 0.15, 2)
    
    # Insert or update SQLite Database scan
    if active_scan_type == "baseline":
        cursor.execute("DELETE FROM scans WHERE session_id = ? AND scan_type = 'baseline'", (active_session_id,))
        cursor.execute("INSERT INTO scans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("baseline", active_session_id, "baseline", "Baseline chân lành",
                        json.dumps(left_knee), json.dumps(right_knee),
                        json.dumps(left_ankle), json.dumps(right_ankle),
                        json.dumps(pelvic_tilt), cadence_val, stride_len_val,
                        0.0, "", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    else:
        cursor.execute("SELECT id, actual_adjustment_degrees, actual_adjustment_notes FROM scans WHERE session_id = ? AND scan_type = ?", 
                       (active_session_id, active_scan_type))
        existing = cursor.fetchone()
        
        deg = 0.0
        notes = ""
        if existing:
            deg = existing[1]
            notes = existing[2]
            cursor.execute("DELETE FROM scans WHERE id = ?", (existing[0],))
            
        cursor.execute("INSERT INTO scans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (active_scan_type, active_session_id, active_scan_type,
                        f"Đánh giá chân giả - {active_scan_type.replace('scan_', 'Scan #')}",
                        json.dumps(left_knee), json.dumps(right_knee),
                        json.dumps(left_ankle), json.dumps(right_ankle),
                        json.dumps(pelvic_tilt), cadence_val, stride_len_val,
                        deg, notes, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
                        
    conn.commit()
    conn.close()
    print(f"💾 SQLite: Saved {active_scan_type} database entry.")

def webcam_capture_loop():
    global latest_frame, running, is_recording, record_start_time, record_duration
    global recorded_left_knee, recorded_right_knee, recorded_left_ankle, recorded_right_ankle, recorded_pelvic_tilt
    global healthy_leg, prosthetic_leg
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        cap = cv2.VideoCapture(1)
        if not cap.isOpened():
            print("❌ Error: Cannot open webcam index 0 or 1")
            return
            
    print("🎥 Webcam capture thread started successfully.")
    
    while running:
        success, frame = cap.read()
        if not success:
            time.sleep(0.01)
            continue
            
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb_frame)
        
        right_knee_angle = 0
        left_knee_angle = 0
        right_ankle_angle = 0
        left_ankle_angle = 0
        pelvic_tilt_deg = 0.0
        
        if results.pose_landmarks:
            mp_drawing.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
            lm = results.pose_landmarks.landmark
            
            try:
                # Right leg
                r_hip = [lm[mp_pose.PoseLandmark.RIGHT_HIP.value].x * w, lm[mp_pose.PoseLandmark.RIGHT_HIP.value].y * h]
                r_knee = [lm[mp_pose.PoseLandmark.RIGHT_KNEE.value].x * w, lm[mp_pose.PoseLandmark.RIGHT_KNEE.value].y * h]
                r_ankle = [lm[mp_pose.PoseLandmark.RIGHT_ANKLE.value].x * w, lm[mp_pose.PoseLandmark.RIGHT_ANKLE.value].y * h]
                r_heel = [lm[mp_pose.PoseLandmark.RIGHT_HEEL.value].x * w, lm[mp_pose.PoseLandmark.RIGHT_HEEL.value].y * h]
                
                right_knee_angle = calculate_angle(r_hip, r_knee, r_ankle)
                right_ankle_angle = calculate_angle(r_knee, r_ankle, r_heel)
                
                # Left leg
                l_hip = [lm[mp_pose.PoseLandmark.LEFT_HIP.value].x * w, lm[mp_pose.PoseLandmark.LEFT_HIP.value].y * h]
                l_knee = [lm[mp_pose.PoseLandmark.LEFT_KNEE.value].x * w, lm[mp_pose.PoseLandmark.LEFT_KNEE.value].y * h]
                l_ankle = [lm[mp_pose.PoseLandmark.LEFT_ANKLE.value].x * w, lm[mp_pose.PoseLandmark.LEFT_ANKLE.value].y * h]
                l_heel = [lm[mp_pose.PoseLandmark.LEFT_HEEL.value].x * w, lm[mp_pose.PoseLandmark.LEFT_HEEL.value].y * h]
                
                left_knee_angle = calculate_angle(l_hip, l_knee, l_ankle)
                left_ankle_angle = calculate_angle(l_knee, l_ankle, l_heel)
                
                # Pelvic tilt (Hip tilt angle) relative to horizontal line
                dy = l_hip[1] - r_hip[1]
                dx = l_hip[0] - r_hip[0]
                pelvic_tilt_deg = math.atan2(dy, dx) * 180.0 / math.pi
                
                # Draw angles and tilt overlay
                draw_overlay_text(frame, f"Goi P: {right_knee_angle}*", (int(r_knee[0]) + 10, int(r_knee[1])), color=(0, 255, 255))
                draw_overlay_text(frame, f"Goi T: {left_knee_angle}*", (int(l_knee[0]) + 10, int(l_knee[1])), color=(255, 150, 0))
                draw_overlay_text(frame, f"Tilt: {pelvic_tilt_deg:.1f}*", (20, 80), color=(100, 255, 100))
            except Exception:
                pass
                
            # Recording logic
            if is_recording:
                elapsed = time.time() - record_start_time
                if elapsed <= record_duration:
                    recorded_left_knee.append(left_knee_angle)
                    recorded_right_knee.append(right_knee_angle)
                    recorded_left_ankle.append(left_ankle_angle)
                    recorded_right_ankle.append(right_ankle_angle)
                    recorded_pelvic_tilt.append(pelvic_tilt_deg)
                else:
                    is_recording = False
                    save_recorded_data_to_db()
                    
        # Add visual indicator if recording
        if is_recording:
            elapsed = time.time() - record_start_time
            draw_overlay_text(frame, f"REC: {max(0.0, record_duration - elapsed):.1f}s", (20, 40), scale=0.8, color=(0, 0, 255))
            cv2.circle(frame, (w - 30, 30), 10, (0, 0, 255), -1)
            
        with frame_lock:
            latest_frame = frame.copy()
            
        time.sleep(0.03)
        
    cap.release()
    print("🎥 Webcam capture thread stopped.")

# Start capture thread
capture_thread = threading.Thread(target=webcam_capture_loop, daemon=True)
capture_thread.start()

def gen_frames():
    global latest_frame
    while True:
        frame_to_send = None
        with frame_lock:
            if latest_frame is not None:
                frame_to_send = latest_frame.copy()
                
        if frame_to_send is None:
            time.sleep(0.03)
            continue
            
        ret, jpeg = cv2.imencode('.jpg', frame_to_send)
        if not ret:
            time.sleep(0.03)
            continue
            
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(0.03)

@app.get("/video_feed")
def video_feed():
    return StreamingResponse(gen_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

# REST API Endpoints
@app.get("/patients")
def get_patients():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients")
    patient_rows = cursor.fetchall()
    
    patients_list = []
    for p in patient_rows:
        p_id = p["id"]
        cursor.execute("SELECT * FROM sessions WHERE patient_id = ?", (p_id,))
        session_rows = cursor.fetchall()
        
        sessions_list = []
        for s in session_rows:
            s_id = s["id"]
            
            # Fetch baseline scan
            cursor.execute("SELECT * FROM scans WHERE session_id = ? AND scan_type = 'baseline'", (s_id,))
            baseline_row = cursor.fetchone()
            baseline_data = None
            if baseline_row:
                baseline_data = {
                    "scanId": baseline_row["id"],
                    "label": baseline_row["label"],
                    "leftKnee": json.loads(baseline_row["left_knee"]),
                    "rightKnee": json.loads(baseline_row["right_knee"]),
                    "leftAnkle": json.loads(baseline_row["left_ankle"]),
                    "rightAnkle": json.loads(baseline_row["right_ankle"]),
                    "pelvicTilt": json.loads(baseline_row["pelvic_tilt"]) if baseline_row["pelvic_tilt"] else [],
                    "cadence": baseline_row["cadence"],
                    "strideLength": baseline_row["stride_length"],
                    "actualAdjustmentDegrees": baseline_row["actual_adjustment_degrees"],
                    "actualAdjustmentNotes": baseline_row["actual_adjustment_notes"],
                    "recordedAt": baseline_row["recorded_at"]
                }
                
            # Fetch other scans
            cursor.execute("SELECT * FROM scans WHERE session_id = ? AND scan_type != 'baseline' ORDER BY recorded_at ASC", (s_id,))
            scan_rows = cursor.fetchall()
            scans_list = []
            for sc in scan_rows:
                scans_list.append({
                    "scanId": sc["id"],
                    "label": sc["label"],
                    "leftKnee": json.loads(sc["left_knee"]),
                    "rightKnee": json.loads(sc["right_knee"]),
                    "leftAnkle": json.loads(sc["left_ankle"]),
                    "rightAnkle": json.loads(sc["right_ankle"]),
                    "pelvicTilt": json.loads(sc["pelvic_tilt"]) if sc["pelvic_tilt"] else [],
                    "cadence": sc["cadence"],
                    "strideLength": sc["stride_length"],
                    "actualAdjustmentDegrees": sc["actual_adjustment_degrees"],
                    "actualAdjustmentNotes": sc["actual_adjustment_notes"],
                    "recordedAt": sc["recorded_at"]
                })
                
            sessions_list.append({
                "id": s_id,
                "createdAt": s["created_at"],
                "baseline": baseline_data,
                "scans": scans_list
            })
            
        patients_list.append({
            "id": p_id,
            "name": p["name"],
            "age": p["age"],
            "heightCm": p["height_cm"],
            "weightKg": p["weight_kg"],
            "healthyLeg": p["healthy_leg"],
            "prostheticLeg": p["prosthetic_leg"],
            "sessions": sorted(sessions_list, key=lambda x: x["createdAt"])
        })
        
    conn.close()
    return patients_list

@app.post("/patients")
def create_patient(data: dict):
    new_id = "p-" + str(uuid.uuid4())[:6]
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (new_id, data.get("name", "Bệnh nhân mới"), int(data.get("age", 30)),
                    float(data.get("heightCm", 170.0)), float(data.get("weightKg", 60.0)),
                    data.get("healthyLeg", "LEFT"), data.get("prostheticLeg", "RIGHT")))
    conn.commit()
    conn.close()
    
    return {
        "id": new_id,
        "name": data.get("name", "Bệnh nhân mới"),
        "age": int(data.get("age", 30)),
        "heightCm": float(data.get("heightCm", 170.0)),
        "weightKg": float(data.get("weightKg", 60.0)),
        "healthyLeg": data.get("healthyLeg", "LEFT"),
        "prostheticLeg": data.get("prostheticLeg", "RIGHT"),
        "sessions": []
    }

@app.post("/patients/{patient_id}/sessions")
def create_session(patient_id: str):
    new_sess_id = "s-" + str(uuid.uuid4())[:6]
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions VALUES (?, ?, ?)", (new_sess_id, patient_id, created_at))
    conn.commit()
    conn.close()
    
    return {
        "id": new_sess_id,
        "createdAt": created_at,
        "baseline": None,
        "scans": []
    }

@app.post("/scans/{session_id}/{scan_id}/adjustment")
def save_adjustment(session_id: str, scan_id: str, data: dict):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE scans SET actual_adjustment_degrees = ?, actual_adjustment_notes = ? WHERE session_id = ? AND id = ?",
                   (float(data.get("degrees", 0.0)), data.get("notes", ""), session_id, scan_id))
    conn.commit()
    conn.close()
    return {"status": "saved"}

@app.post("/start_recording")
def start_recording(
    session_id: str,
    scan_type: str,
    duration: float = 10.0,
    healthy: str = Query("LEFT", pattern="^(LEFT|RIGHT)$"),
    prosthetic: str = Query("RIGHT", pattern="^(LEFT|RIGHT)$")
):
    global is_recording, record_start_time, record_duration, healthy_leg, prosthetic_leg
    global recorded_left_knee, recorded_right_knee, recorded_left_ankle, recorded_right_ankle, recorded_pelvic_tilt
    global active_session_id, active_scan_type
    
    recorded_left_knee = []
    recorded_right_knee = []
    recorded_left_ankle = []
    recorded_right_ankle = []
    recorded_pelvic_tilt = []
    
    active_session_id = session_id
    active_scan_type = scan_type
    healthy_leg = healthy
    prosthetic_leg = prosthetic
    record_duration = duration
    record_start_time = time.time()
    is_recording = True
    
    return {"status": "started", "session_id": session_id, "scan_type": scan_type}

@app.get("/status")
def get_status():
    global is_recording, record_start_time, record_duration
    elapsed = time.time() - record_start_time if is_recording else 0.0
    return {
        "is_recording": is_recording,
        "elapsed": min(elapsed, record_duration),
        "finished": not is_recording and elapsed >= record_duration
    }

@app.get("/get_angles")
def get_angles():
    global recorded_left_knee, recorded_right_knee, recorded_left_ankle, recorded_right_ankle, recorded_pelvic_tilt
    return {
        "left_knee": resample(recorded_left_knee),
        "right_knee": resample(recorded_right_knee),
        "left_ankle": resample(recorded_left_ankle),
        "right_ankle": resample(recorded_right_ankle),
        "pelvic_tilt": resample(recorded_pelvic_tilt),
        "total_frames_collected": len(recorded_left_knee)
    }

@app.on_event("shutdown")
def shutdown_event():
    global running
    running = False

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)