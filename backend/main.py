import cv2
import mediapipe as mp
import math
import os
import time
import threading
import json
import uuid
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import custom sub-modules
from database import get_db_connection, init_db
from algorithms import (
    calculate_angle,
    resample,
    filter_signal,
    estimate_socket_moment,
    homography_project,
    compute_dtw_distance,
    analyze_cropped_segment
)

app = FastAPI()

# The deployed setup uses the laptop camera and one USB camera simultaneously.
# Environment variables still allow falling back to one camera or swapping indexes.
SINGLE_CAMERA_MODE = os.getenv("SINGLE_CAMERA_MODE", "false").lower() in ("1", "true", "yes")
CAMERA_FRONTAL_INDEX = int(os.getenv("CAMERA_FRONTAL_INDEX", "0"))
CAMERA_SAGITTAL_INDEX = int(os.getenv("CAMERA_SAGITTAL_INDEX", "1"))
CAMERA_BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup Database Init
init_db()

# Global frames and locks for 2 camera streams
latest_frame_0 = None
latest_frame_1 = None
frame_lock_0 = threading.Lock()
frame_lock_1 = threading.Lock()

running = True
is_recording = False
record_start_time = 0.0
record_duration = 300.0

active_session_id = ""
active_scan_type = ""
healthy_leg = "LEFT"
prosthetic_leg = "RIGHT"

# Buffers for recording
recorded_timestamps = []
recorded_left_knee = []
recorded_right_knee = []
recorded_left_ankle = []
recorded_right_ankle = []
recorded_pelvic_tilt = []
recorded_left_hip = []
recorded_right_hip = []
session_markers = []

# MediaPipe Pose Setup. Each capture thread creates its own Pose instance because
# a single MediaPipe graph must not be processed concurrently by two threads.
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

def create_pose_detector():
    return mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        smooth_landmarks=True,
        enable_segmentation=False,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

def draw_overlay_text(frame, text, pos, color=(255, 255, 255), scale=0.7, thickness=2):
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)

def camera_loop_0():
    """Camera index 0: Frontal view"""
    global latest_frame_0, running
    pose = create_pose_detector()
    cap = cv2.VideoCapture(CAMERA_FRONTAL_INDEX, CAMERA_BACKEND)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    print("[Camera 0] Frontal thread started.")
    
    while running:
        success, frame = cap.read()
        if not success:
            time.sleep(0.03)
            continue
            
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)
        
        if results.pose_landmarks:
            mp_drawing.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
            
        draw_overlay_text(frame, "CAM 1: MAT TRUOC (FRONTAL)", (20, 40), color=(0, 255, 255))
        
        with frame_lock_0:
            latest_frame_0 = frame.copy()
            
        time.sleep(0.03)
        
    cap.release()
    pose.close()
    print("[Camera 0] thread stopped.")

def camera_loop_1():
    """Camera index 1: Sagittal view (does joints calculations & recording buffers)"""
    global latest_frame_1, latest_frame_0, running, is_recording, record_start_time
    global recorded_timestamps, recorded_left_knee, recorded_right_knee, recorded_left_ankle, recorded_right_ankle
    global recorded_left_hip, recorded_right_hip, recorded_pelvic_tilt
    
    pose = create_pose_detector()
    camera_index = CAMERA_FRONTAL_INDEX if SINGLE_CAMERA_MODE else CAMERA_SAGITTAL_INDEX
    cap = cv2.VideoCapture(camera_index, CAMERA_BACKEND)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    print("[Camera 1] Sagittal thread started.")
    
    while running:
        success, frame = cap.read()
        if not success:
            time.sleep(0.05)
            continue
            
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)
        
        right_knee_angle = 0
        left_knee_angle = 0
        right_ankle_angle = 0
        left_ankle_angle = 0
        right_hip_angle = 0
        left_hip_angle = 0
        pelvic_tilt_deg = 0.0
        
        if results.pose_landmarks:
            mp_drawing.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
            lm = results.pose_landmarks.landmark
            try:
                # Right leg
                r_shoulder = [lm[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].x * w, lm[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].y * h]
                r_hip = [lm[mp_pose.PoseLandmark.RIGHT_HIP.value].x * w, lm[mp_pose.PoseLandmark.RIGHT_HIP.value].y * h]
                r_knee = [lm[mp_pose.PoseLandmark.RIGHT_KNEE.value].x * w, lm[mp_pose.PoseLandmark.RIGHT_KNEE.value].y * h]
                r_ankle = [lm[mp_pose.PoseLandmark.RIGHT_ANKLE.value].x * w, lm[mp_pose.PoseLandmark.RIGHT_ANKLE.value].y * h]
                r_heel = [lm[mp_pose.PoseLandmark.RIGHT_HEEL.value].x * w, lm[mp_pose.PoseLandmark.RIGHT_HEEL.value].y * h]
                
                right_hip_angle = calculate_angle(r_shoulder, r_hip, r_knee)
                right_knee_angle = calculate_angle(r_hip, r_knee, r_ankle)
                right_ankle_angle = calculate_angle(r_knee, r_ankle, r_heel)
                
                # Left leg
                l_shoulder = [lm[mp_pose.PoseLandmark.LEFT_SHOULDER.value].x * w, lm[mp_pose.PoseLandmark.LEFT_SHOULDER.value].y * h]
                l_hip = [lm[mp_pose.PoseLandmark.LEFT_HIP.value].x * w, lm[mp_pose.PoseLandmark.LEFT_HIP.value].y * h]
                l_knee = [lm[mp_pose.PoseLandmark.LEFT_KNEE.value].x * w, lm[mp_pose.PoseLandmark.LEFT_KNEE.value].y * h]
                l_ankle = [lm[mp_pose.PoseLandmark.LEFT_ANKLE.value].x * w, lm[mp_pose.PoseLandmark.LEFT_ANKLE.value].y * h]
                l_heel = [lm[mp_pose.PoseLandmark.LEFT_HEEL.value].x * w, lm[mp_pose.PoseLandmark.LEFT_HEEL.value].y * h]
                
                left_hip_angle = calculate_angle(l_shoulder, l_hip, l_knee)
                left_knee_angle = calculate_angle(l_hip, l_knee, l_ankle)
                left_ankle_angle = calculate_angle(l_knee, l_ankle, l_heel)
                
                # Pelvic tilt
                dy = l_hip[1] - r_hip[1]
                dx = l_hip[0] - r_hip[0]
                pelvic_tilt_deg = math.atan2(dy, dx) * 180.0 / math.pi
                
                draw_overlay_text(frame, f"Hong P: {right_hip_angle}*", (int(r_hip[0]) + 10, int(r_hip[1])), color=(0, 255, 255))
                draw_overlay_text(frame, f"Hong T: {left_hip_angle}*", (int(l_hip[0]) + 10, int(l_hip[1])), color=(255, 150, 0))
                draw_overlay_text(frame, f"Goi P: {right_knee_angle}*", (int(r_knee[0]) + 10, int(r_knee[1])), color=(0, 255, 255))
                draw_overlay_text(frame, f"Goi T: {left_knee_angle}*", (int(l_knee[0]) + 10, int(l_knee[1])), color=(255, 150, 0))
                draw_overlay_text(frame, f"Tilt: {pelvic_tilt_deg:.1f}*", (20, 80), color=(100, 255, 100))
            except Exception:
                pass
                
        # Continuous recording logic
        if is_recording:
            elapsed = time.time() - record_start_time
            if elapsed <= record_duration:
                recorded_timestamps.append(elapsed)
                recorded_left_knee.append(left_knee_angle)
                recorded_right_knee.append(right_knee_angle)
                recorded_left_ankle.append(left_ankle_angle)
                recorded_right_ankle.append(right_ankle_angle)
                recorded_pelvic_tilt.append(pelvic_tilt_deg)
                recorded_left_hip.append(left_hip_angle)
                recorded_right_hip.append(right_hip_angle)
            else:
                is_recording = False
                save_recorded_data_to_db()
                
        if is_recording:
            elapsed = time.time() - record_start_time
            draw_overlay_text(frame, f"REC: {elapsed:.1f}s", (20, 40), scale=0.8, color=(0, 0, 255))
            cv2.circle(frame, (w - 30, 30), 10, (0, 0, 255), -1)
            
        with frame_lock_1:
            latest_frame_1 = frame.copy()
            
        time.sleep(0.03)
        
    cap.release()
    pose.close()
    print("[Camera 1] thread stopped.")

# Do not open the same Windows camera from two threads in single-camera mode.
thread_0 = None
if not SINGLE_CAMERA_MODE:
    thread_0 = threading.Thread(target=camera_loop_0, daemon=True)
    thread_0.start()
thread_1 = threading.Thread(target=camera_loop_1, daemon=True)
thread_1.start()
# Optional hardware/media services are installed after camera state exists.
import sys
from realtime_services import install_realtime_services
install_realtime_services(app, sys.modules[__name__])

def gen_frames(camera_index):
    while True:
        frame_to_send = None
        if camera_index == 0 and not SINGLE_CAMERA_MODE:
            with frame_lock_0:
                if latest_frame_0 is not None:
                    frame_to_send = latest_frame_0.copy()
        else:
            with frame_lock_1:
                if latest_frame_1 is not None:
                    frame_to_send = latest_frame_1.copy()
                    
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

@app.get("/video_feed_0")
def video_feed_0():
    return StreamingResponse(gen_frames(0), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/video_feed_1")
def video_feed_1():
    return StreamingResponse(gen_frames(1), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/video_feed")
def video_feed():
    # Backward compatibility: point to camera index 1 (sagittal view)
    return StreamingResponse(gen_frames(1), media_type="multipart/x-mixed-replace; boundary=frame")

def save_recorded_data_to_db():
    global recorded_timestamps, active_session_id, active_scan_type
    if not recorded_timestamps:
        return
        
    start_t = 0.0
    end_t = recorded_timestamps[-1]
    
    l_knee, r_knee, l_ankle, r_ankle, l_hip, r_hip, pelvic_t, load_sym, cop_traj, cad, stride, fat_flag, fat_slope = analyze_cropped_segment(
        start_t, end_t,
        recorded_timestamps,
        recorded_left_knee, recorded_right_knee,
        recorded_left_ankle, recorded_right_ankle,
        recorded_left_hip, recorded_right_hip,
        recorded_pelvic_tilt,
        healthy_leg, active_session_id
    )
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    segment_id = "seg-default-" + str(uuid.uuid4())[:6]
    cursor.execute("INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (segment_id, active_session_id, start_t, end_t, 'manual', 'Ghi hình ban đầu', 'video_feed.mp4', time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    
    if active_scan_type == "baseline":
        cursor.execute("DELETE FROM scans WHERE session_id = ? AND scan_type = 'baseline'", (active_session_id,))
        cursor.execute("INSERT INTO scans (id, session_id, segment_id, scan_type, label, left_knee, right_knee, left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt, plantar_load_symmetry, cop_trajectory, cadence, stride_length, fatigue_flag, fatigue_slope, actual_adjustment_degrees, actual_adjustment_notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("baseline", active_session_id, segment_id, "baseline", "Baseline chân lành",
                        json.dumps(l_knee), json.dumps(r_knee), json.dumps(l_ankle), json.dumps(r_ankle),
                        json.dumps(l_hip), json.dumps(r_hip), json.dumps(pelvic_t), load_sym, cop_traj,
                        cad, stride, fat_flag, fat_slope, 0.0, "", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
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
            
        cursor.execute("INSERT INTO scans (id, session_id, segment_id, scan_type, label, left_knee, right_knee, left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt, plantar_load_symmetry, cop_trajectory, cadence, stride_length, fatigue_flag, fatigue_slope, actual_adjustment_degrees, actual_adjustment_notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (active_scan_type, active_session_id, segment_id, active_scan_type,
                        f"Đánh giá chân giả - {active_scan_type.replace('scan_', 'Scan #')}",
                        json.dumps(l_knee), json.dumps(r_knee), json.dumps(l_ankle), json.dumps(r_ankle),
                        json.dumps(l_hip), json.dumps(r_hip), json.dumps(pelvic_t), load_sym, cop_traj,
                        cad, stride, fat_flag, fat_slope, deg, notes, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
                        
    conn.commit()
    conn.close()

@app.get("/patients")
def get_patients():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients")
    patient_rows = cursor.fetchall()
    
    patients_list = []
    for p in patient_rows:
        p_id = p["id"]
        
        cursor.execute("SELECT * FROM clinical_notes WHERE patient_id = ?", (p_id,))
        note_rows = cursor.fetchall()
        notes_list = []
        for n in note_rows:
            notes_list.append({
                "id": n["id"],
                "patientId": n["patient_id"],
                "sessionId": n["session_id"],
                "pinnedScanId": n["pinned_scan_id"],
                "noteType": n["note_type"],
                "content": n["content"],
                "createdAt": n["created_at"]
            })
            
        cursor.execute("SELECT * FROM sessions WHERE patient_id = ?", (p_id,))
        session_rows = cursor.fetchall()
        
        sessions_list = []
        for s in session_rows:
            s_id = s["id"]
            
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
                    "leftHip": json.loads(baseline_row["left_hip"]) if baseline_row["left_hip"] else [],
                    "rightHip": json.loads(baseline_row["right_hip"]) if baseline_row["right_hip"] else [],
                    "pelvicTilt": json.loads(baseline_row["pelvic_tilt"]) if baseline_row["pelvic_tilt"] else [],
                    "plantarLoadSymmetry": baseline_row["plantar_load_symmetry"],
                    "copTrajectory": json.loads(baseline_row["cop_trajectory"]) if baseline_row["cop_trajectory"] else [],
                    "cadence": baseline_row["cadence"],
                    "strideLength": baseline_row["stride_length"],
                    "fatigueFlag": baseline_row["fatigue_flag"],
                    "fatigueSlope": baseline_row["fatigue_slope"],
                    "actualAdjustmentDegrees": baseline_row["actual_adjustment_degrees"],
                    "actualAdjustmentNotes": baseline_row["actual_adjustment_notes"],
                    "recordedAt": baseline_row["recorded_at"],
                    "segmentId": baseline_row["segment_id"]
                }
                
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
                    "leftHip": json.loads(sc["left_hip"]) if sc["left_hip"] else [],
                    "rightHip": json.loads(sc["right_hip"]) if sc["right_hip"] else [],
                    "pelvicTilt": json.loads(sc["pelvic_tilt"]) if sc["pelvic_tilt"] else [],
                    "plantarLoadSymmetry": sc["plantar_load_symmetry"],
                    "copTrajectory": json.loads(sc["cop_trajectory"]) if sc["cop_trajectory"] else [],
                    "cadence": sc["cadence"],
                    "strideLength": sc["stride_length"],
                    "fatigueFlag": sc["fatigue_flag"],
                    "fatigueSlope": sc["fatigue_slope"],
                    "actualAdjustmentDegrees": sc["actual_adjustment_degrees"],
                    "actualAdjustmentNotes": sc["actual_adjustment_notes"],
                    "recordedAt": sc["recorded_at"],
                    "segmentId": sc["segment_id"]
                })
                
            sessions_list.append({
                "id": s_id,
                "createdAt": s["created_at"],
                "isPracticeMode": s["is_practice_mode"],
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
            "injuryHistory": p["injury_history"],
            "treatmentGoals": p["treatment_goals"],
            "clinicalNotes": notes_list,
            "sessions": sorted(sessions_list, key=lambda x: x["createdAt"])
        })
        
    conn.close()
    return patients_list

@app.post("/patients")
def create_patient(data: dict):
    new_id = "p-" + str(uuid.uuid4())[:6]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (new_id, data.get("name", "Bệnh nhân mới"), int(data.get("age", 30)),
                    float(data.get("heightCm", 170.0)), float(data.get("weightKg", 60.0)),
                    data.get("healthyLeg", "LEFT"), data.get("prostheticLeg", "RIGHT"),
                    data.get("injuryHistory", ""), data.get("treatmentGoals", "")))
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
        "injuryHistory": data.get("injuryHistory", ""),
        "treatmentGoals": data.get("treatmentGoals", ""),
        "clinicalNotes": [],
        "sessions": []
    }

@app.put("/patients/{patient_id}")
def update_patient(patient_id: str, data: dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE patients SET name=?, age=?, height_cm=?, weight_kg=?, healthy_leg=?, prosthetic_leg=?, injury_history=?, treatment_goals=? WHERE id=?",
                   (data.get("name"), int(data.get("age", 30)), float(data.get("heightCm", 170.0)), float(data.get("weightKg", 60.0)),
                    data.get("healthyLeg", "LEFT"), data.get("prostheticLeg", "RIGHT"),
                    data.get("injuryHistory", ""), data.get("treatmentGoals", ""), patient_id))
    conn.commit()
    conn.close()
    return {"status": "updated"}

@app.post("/patients/{patient_id}/sessions")
def create_session(patient_id: str, data: dict = None):
    is_practice_mode = 0
    if data and "isPracticeMode" in data:
        is_practice_mode = 1 if data["isPracticeMode"] else 0
        
    new_sess_id = "s-" + str(uuid.uuid4())[:6]
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (new_sess_id, patient_id, created_at, is_practice_mode))
    conn.commit()
    conn.close()
    
    return {
        "id": new_sess_id,
        "createdAt": created_at,
        "isPracticeMode": is_practice_mode,
        "baseline": None,
        "scans": []
    }

@app.post("/scans/{session_id}/{scan_id}/adjustment")
def save_adjustment(session_id: str, scan_id: str, data: dict):
    conn = get_db_connection()
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
    duration: float = 300.0,
    healthy: str = Query("LEFT", pattern="^(LEFT|RIGHT)$"),
    prosthetic: str = Query("RIGHT", pattern="^(LEFT|RIGHT)$")
):
    global is_recording, record_start_time, record_duration, healthy_leg, prosthetic_leg
    global recorded_timestamps, recorded_left_knee, recorded_right_knee, recorded_left_ankle, recorded_right_ankle
    global recorded_left_hip, recorded_right_hip, recorded_pelvic_tilt
    global active_session_id, active_scan_type, session_markers
    
    recorded_timestamps = []
    recorded_left_knee = []
    recorded_right_knee = []
    recorded_left_ankle = []
    recorded_right_ankle = []
    recorded_pelvic_tilt = []
    recorded_left_hip = []
    recorded_right_hip = []
    session_markers = []
    
    active_session_id = session_id
    active_scan_type = scan_type
    healthy_leg = healthy
    prosthetic_leg = prosthetic
    record_duration = duration
    record_start_time = time.time()
    is_recording = True
    
    return {"status": "started", "session_id": session_id, "scan_type": scan_type}

@app.post("/stop_recording")
def stop_recording_endpoint():
    global is_recording
    if is_recording:
        is_recording = False
        save_recorded_data_to_db()
        return {"status": "stopped"}
    return {"status": "not_recording"}

@app.get("/status")
def get_status():
    global is_recording, record_start_time, record_duration
    elapsed = time.time() - record_start_time if is_recording else 0.0
    return {
        "is_recording": is_recording,
        "elapsed": min(elapsed, record_duration),
        "finished": not is_recording and elapsed >= record_duration
    }

@app.post("/sessions/{session_id}/markers")
def create_marker(session_id: str, data: dict):
    global session_markers, recorded_timestamps
    offset = data.get("offset")
    if offset is None:
        offset = recorded_timestamps[-1] if recorded_timestamps else 0.0
    note = data.get("note", "Đánh dấu của Bác sĩ")
    marker = {"offset": offset, "note": note}
    session_markers.append(marker)
    return marker

@app.post("/sessions/{session_id}/segments")
def create_segment(session_id: str, data: dict):
    global active_session_id, active_scan_type
    active_session_id = session_id
    start_t = float(data.get("startOffsetSec", 0.0))
    end_t = float(data.get("endOffsetSec", 10.0))
    scan_type = data.get("scanType", "scan_1")
    active_scan_type = scan_type
    note = data.get("note", "Đoạn đã cắt")
    
    try:
        l_knee, r_knee, l_ankle, r_ankle, l_hip, r_hip, pelvic_t, load_sym, cop_traj, cad, stride, fat_flag, fat_slope = analyze_cropped_segment(
            start_t, end_t,
            recorded_timestamps,
            recorded_left_knee, recorded_right_knee,
            recorded_left_ankle, recorded_right_ankle,
            recorded_left_hip, recorded_right_hip,
            recorded_pelvic_tilt,
            healthy_leg, session_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    segment_id = "seg-" + str(uuid.uuid4())[:6]
    cursor.execute("INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (segment_id, session_id, start_t, end_t, 'manual', note, 'video_feed.mp4', time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    
    cursor.execute("DELETE FROM scans WHERE session_id = ? AND scan_type = ?", (session_id, scan_type))
    cursor.execute("INSERT INTO scans (id, session_id, segment_id, scan_type, label, left_knee, right_knee, left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt, plantar_load_symmetry, cop_trajectory, cadence, stride_length, fatigue_flag, fatigue_slope, actual_adjustment_degrees, actual_adjustment_notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (scan_type, session_id, segment_id, scan_type,
                    f"Đánh giá chân giả - {scan_type.replace('scan_', 'Scan #')}" if scan_type != 'baseline' else 'Baseline chân lành',
                    json.dumps(l_knee), json.dumps(r_knee), json.dumps(l_ankle), json.dumps(r_ankle),
                    json.dumps(l_hip), json.dumps(r_hip), json.dumps(pelvic_t), load_sym, cop_traj,
                    cad, stride, fat_flag, fat_slope, 0.0, "", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    conn.commit()
    conn.close()
    
    return {
        "scanId": scan_type,
        "segmentId": segment_id,
        "scanType": scan_type,
        "leftKnee": l_knee,
        "rightKnee": r_knee,
        "leftAnkle": l_ankle,
        "rightAnkle": r_ankle,
        "leftHip": l_hip,
        "rightHip": r_hip,
        "pelvicTilt": pelvic_t,
        "plantarLoadSymmetry": load_sym,
        "copTrajectory": json.loads(cop_traj),
        "cadence": cad,
        "strideLength": stride
    }

@app.post("/patients/{patient_id}/notes")
def create_note(patient_id: str, data: dict):
    new_id = "n-" + str(uuid.uuid4())[:6]
    session_id = data.get("sessionId", "")
    pinned_scan_id = data.get("pinnedScanId")
    note_type = data.get("noteType", "history")
    content = data.get("content", "")
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO clinical_notes VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (new_id, patient_id, session_id, pinned_scan_id, note_type, content, created_at))
    conn.commit()
    conn.close()
    
    return {
        "id": new_id,
        "patientId": patient_id,
        "sessionId": session_id,
        "pinnedScanId": pinned_scan_id,
        "noteType": note_type,
        "content": content,
        "createdAt": created_at
    }

@app.get("/exercises")
def get_exercises():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM exercises WHERE is_active = 1")
    rows = cursor.fetchall()
    ex_list = []
    for r in rows:
        ex_list.append({
            "id": r["id"],
            "name": r["name"],
            "evaluationMethod": r["evaluation_method"],
            "primaryCamera": r["primary_camera"],
            "trackedJoints": json.loads(r["tracked_joints"]) if r["tracked_joints"] else [],
            "referenceVideoPath": r["reference_video_path"],
            "targetSymmetryRatio": r["target_symmetry_ratio"],
            "symmetryTolerance": r["symmetry_tolerance"]
        })
    conn.close()
    return ex_list

@app.get("/practice_attempts")
def get_practice_attempts(patient_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM practice_attempts WHERE patient_id = ?", (patient_id,))
    rows = cursor.fetchall()
    attempts = []
    for r in rows:
        attempts.append({
            "id": r["id"],
            "patientId": r["patient_id"],
            "exerciseId": r["exercise_id"],
            "linkedSessionId": r["linked_session_id"],
            "similarityScoreAvg": r["similarity_score_avg"],
            "dtwDistance": r["dtw_distance"],
            "loadSymmetryActual": r["load_symmetry_actual"],
            "startedAt": r["started_at"],
            "endedAt": r["ended_at"]
        })
    conn.close()
    return attempts

@app.get("/get_angles")
def get_angles():
    global recorded_left_knee, recorded_right_knee, recorded_left_ankle, recorded_right_ankle, recorded_pelvic_tilt
    global recorded_left_hip, recorded_right_hip
    return {
        "left_knee": resample(recorded_left_knee),
        "right_knee": resample(recorded_right_knee),
        "left_ankle": resample(recorded_left_ankle),
        "right_ankle": resample(recorded_right_ankle),
        "pelvic_tilt": resample(recorded_pelvic_tilt),
        "left_hip": resample(recorded_left_hip),
        "right_hip": resample(recorded_right_hip),
        "total_frames_collected": len(recorded_left_knee)
    }

@app.on_event("shutdown")
def shutdown_event():
    global running
    running = False

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
