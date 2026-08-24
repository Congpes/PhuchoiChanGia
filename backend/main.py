import cv2
import mediapipe as mp
import math
import os
import time
import threading
import json
import uuid
from collections import deque
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import custom sub-modules
from database import get_db_connection, init_db
from camera_fusion import (
    DualCameraSynchronizer,
    apply_stereo_flexion,
    fuse_synchronized_sample,
    sagittal_fallback_sample,
)
from pose_identity_lock import PoseIdentityLock
from pose_quality import assess_pose_sample
from stereo_calibration import StereoCalibrationError, StereoCalibrationManager

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

# Camera roles are intentionally selected in the setup screen before Scan.
# Environment variables can still preconfigure a deployed appliance if needed.
_env_frontal_index = os.getenv("CAMERA_FRONTAL_INDEX")
_env_sagittal_index = os.getenv("CAMERA_SAGITTAL_INDEX")
SINGLE_CAMERA_MODE = os.getenv("SINGLE_CAMERA_MODE", "false").lower() in ("1", "true", "yes")
CAMERA_FRONTAL_INDEX = int(_env_frontal_index) if _env_frontal_index is not None else None
CAMERA_SAGITTAL_INDEX = int(_env_sagittal_index) if _env_sagittal_index is not None else None
camera_configured = CAMERA_FRONTAL_INDEX is not None and (
    SINGLE_CAMERA_MODE or CAMERA_SAGITTAL_INDEX is not None
)
CAMERA_BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY

CAMERA_RETRY_SECONDS = float(os.getenv('CAMERA_RETRY_SECONDS', '2.0'))
CAMERA_READ_FAILURE_LIMIT = int(os.getenv('CAMERA_READ_FAILURE_LIMIT', '30'))
CAMERA_SYNC_TOLERANCE_MS = float(os.getenv('CAMERA_SYNC_TOLERANCE_MS', '40.0'))
CAMERA_FRAME_DELAY_SECONDS = float(os.getenv('CAMERA_FRAME_DELAY_SECONDS', '0.005'))
CAMERA_MAX_REPROJECTION_ERROR_PX = float(os.getenv('CAMERA_MAX_REPROJECTION_ERROR_PX', '8.0'))

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
latest_raw_frame_0 = None
latest_raw_frame_1 = None
latest_frame_0_at = 0.0
latest_frame_1_at = 0.0
latest_frame_0_ns = 0
latest_frame_1_ns = 0
latest_pose_0_at = 0.0
latest_pose_1_at = 0.0
latest_sagittal_pose_at = 0.0
frame_lock_0 = threading.Lock()
frame_lock_1 = threading.Lock()
camera_roles_lock = threading.Lock()
camera_roles_swapped = False

# A rolling sagittal-pose buffer supports realtime gait charts even when a
# recording has not been started. Timestamps are Unix seconds so they share the
# same clock as live FSR packets.
live_gait_samples = deque(maxlen=3600)
live_gait_lock = threading.Lock()
gait_store_lock = threading.Lock()
camera_synchronizer = DualCameraSynchronizer(CAMERA_SYNC_TOLERANCE_MS)
stereo_calibration = StereoCalibrationManager(
    os.getenv(
        "CAMERA_STEREO_CALIBRATION_PATH",
        os.path.join(os.path.dirname(__file__), "camera_stereo_calibration.json"),
    )
)

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
recorded_trunk_tilt = []
recorded_left_hip = []
recorded_right_hip = []
recorded_pose_quality = []
session_markers = []

# MediaPipe Pose Setup. Each capture thread creates its own Pose instance because
# a single MediaPipe graph must not be processed concurrently by two threads.
mp_pose = mp.solutions.pose

# Skeleton for gait analysis: intentionally excludes face, elbows, wrists and hands.
GAIT_LANDMARKS = (
    mp_pose.PoseLandmark.LEFT_SHOULDER,
    mp_pose.PoseLandmark.RIGHT_SHOULDER,
    mp_pose.PoseLandmark.LEFT_HIP,
    mp_pose.PoseLandmark.RIGHT_HIP,
    mp_pose.PoseLandmark.LEFT_KNEE,
    mp_pose.PoseLandmark.RIGHT_KNEE,
    mp_pose.PoseLandmark.LEFT_ANKLE,
    mp_pose.PoseLandmark.RIGHT_ANKLE,
    mp_pose.PoseLandmark.LEFT_HEEL,
    mp_pose.PoseLandmark.RIGHT_HEEL,
    mp_pose.PoseLandmark.LEFT_FOOT_INDEX,
    mp_pose.PoseLandmark.RIGHT_FOOT_INDEX,
)
GAIT_CONNECTIONS = frozenset({
    (mp_pose.PoseLandmark.LEFT_SHOULDER.value, mp_pose.PoseLandmark.RIGHT_SHOULDER.value),
    (mp_pose.PoseLandmark.LEFT_SHOULDER.value, mp_pose.PoseLandmark.LEFT_HIP.value),
    (mp_pose.PoseLandmark.RIGHT_SHOULDER.value, mp_pose.PoseLandmark.RIGHT_HIP.value),
    (mp_pose.PoseLandmark.LEFT_HIP.value, mp_pose.PoseLandmark.RIGHT_HIP.value),
    (mp_pose.PoseLandmark.LEFT_HIP.value, mp_pose.PoseLandmark.LEFT_KNEE.value),
    (mp_pose.PoseLandmark.LEFT_KNEE.value, mp_pose.PoseLandmark.LEFT_ANKLE.value),
    (mp_pose.PoseLandmark.LEFT_ANKLE.value, mp_pose.PoseLandmark.LEFT_HEEL.value),
    (mp_pose.PoseLandmark.LEFT_HEEL.value, mp_pose.PoseLandmark.LEFT_FOOT_INDEX.value),
    (mp_pose.PoseLandmark.RIGHT_HIP.value, mp_pose.PoseLandmark.RIGHT_KNEE.value),
    (mp_pose.PoseLandmark.RIGHT_KNEE.value, mp_pose.PoseLandmark.RIGHT_ANKLE.value),
    (mp_pose.PoseLandmark.RIGHT_ANKLE.value, mp_pose.PoseLandmark.RIGHT_HEEL.value),
    (mp_pose.PoseLandmark.RIGHT_HEEL.value, mp_pose.PoseLandmark.RIGHT_FOOT_INDEX.value),
})
GAIT_COLOR = (0, 220, 0)
GAIT_MIN_VISIBILITY_TO_DRAW = 0.15


def draw_gait_skeleton(frame, landmarks):
    """Draw only gait landmarks with OpenCV, avoiding MediaPipe's all-index mapping."""
    height, width = frame.shape[:2]
    points = {}
    for landmark in GAIT_LANDMARKS:
        item = landmarks.landmark[landmark.value]
        if float(getattr(item, "visibility", 1.0)) < GAIT_MIN_VISIBILITY_TO_DRAW:
            continue
        points[landmark.value] = (int(item.x * width), int(item.y * height))

    for start_index, end_index in GAIT_CONNECTIONS:
        if start_index in points and end_index in points:
            cv2.line(frame, points[start_index], points[end_index], GAIT_COLOR, 2, cv2.LINE_AA)
    for point in points.values():
        cv2.circle(frame, point, 3, GAIT_COLOR, -1, cv2.LINE_AA)

QUALITY_LANDMARKS = {
    "left_shoulder": mp_pose.PoseLandmark.LEFT_SHOULDER,
    "right_shoulder": mp_pose.PoseLandmark.RIGHT_SHOULDER,
    "left_hip": mp_pose.PoseLandmark.LEFT_HIP,
    "right_hip": mp_pose.PoseLandmark.RIGHT_HIP,
    "left_knee": mp_pose.PoseLandmark.LEFT_KNEE,
    "right_knee": mp_pose.PoseLandmark.RIGHT_KNEE,
    "left_ankle": mp_pose.PoseLandmark.LEFT_ANKLE,
    "right_ankle": mp_pose.PoseLandmark.RIGHT_ANKLE,
}
FUSION_LANDMARKS = {
    **QUALITY_LANDMARKS,
    "left_heel": mp_pose.PoseLandmark.LEFT_HEEL,
    "right_heel": mp_pose.PoseLandmark.RIGHT_HEEL,
}


def landmark_visibility(landmarks):
    return {
        name: float(getattr(landmarks.landmark[item.value], "visibility", 0.0))
        for name, item in QUALITY_LANDMARKS.items()
    }


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

def normalize_axial_angle(angle):
    """Wrap an unoriented body-axis angle to the clinically useful ±90°."""
    angle = float(angle)
    if angle > 90.0:
        angle -= 180.0
    elif angle < -90.0:
        angle += 180.0
    return angle

def calculate_flexion_angle(a, b, c):
    """Return unsigned 2D flexion: 0° at full extension, increasing with flexion."""
    return max(0.0, 180.0 - float(calculate_angle(a, b, c)))


def pose_sample_from_landmarks(landmarks, width, height):

    """Calculate the gait metrics needed by the logical sagittal camera."""
    lm = landmarks.landmark
    def point(name):
        item = lm[name.value]
        return [item.x * width, item.y * height]

    r_shoulder = point(mp_pose.PoseLandmark.RIGHT_SHOULDER)
    r_hip = point(mp_pose.PoseLandmark.RIGHT_HIP)
    r_knee = point(mp_pose.PoseLandmark.RIGHT_KNEE)
    r_ankle = point(mp_pose.PoseLandmark.RIGHT_ANKLE)
    r_heel = point(mp_pose.PoseLandmark.RIGHT_HEEL)
    l_shoulder = point(mp_pose.PoseLandmark.LEFT_SHOULDER)
    l_hip = point(mp_pose.PoseLandmark.LEFT_HIP)
    l_knee = point(mp_pose.PoseLandmark.LEFT_KNEE)
    l_ankle = point(mp_pose.PoseLandmark.LEFT_ANKLE)
    l_heel = point(mp_pose.PoseLandmark.LEFT_HEEL)

    # Use the shoulder midpoint as a shared trunk reference for both hips.
    # The lower-limb identity lock may swap leg landmarks during occlusion;
    # tying a corrected hip to one raw shoulder can otherwise create a
    # diagonal, non-anatomical hip angle.
    mid_shoulder = [(l_shoulder[0] + r_shoulder[0]) / 2,
                    (l_shoulder[1] + r_shoulder[1]) / 2]
    sample = {
        "right_hip": calculate_flexion_angle(mid_shoulder, r_hip, r_knee),
        "right_knee": calculate_flexion_angle(r_hip, r_knee, r_ankle),
        "right_ankle": calculate_angle(r_knee, r_ankle, r_heel),
        "left_hip": calculate_flexion_angle(mid_shoulder, l_hip, l_knee),
        "left_knee": calculate_flexion_angle(l_hip, l_knee, l_ankle),
        "left_ankle": calculate_angle(l_knee, l_ankle, l_heel),
    }
    sample["pelvic_tilt"] = math.degrees(math.atan2(
        l_hip[1] - r_hip[1], l_hip[0] - r_hip[0]
    ))
    mid_hip = [(l_hip[0] + r_hip[0]) / 2,
               (l_hip[1] + r_hip[1]) / 2]
    sample["trunk_tilt"] = normalize_axial_angle(math.degrees(math.atan2(
        mid_shoulder[0] - mid_hip[0], mid_hip[1] - mid_shoulder[1]
    )))
    values = tuple(sample.values())
    if not (
        all(0.0 <= value <= 180.0 for value in values[:6])
        and all(math.isfinite(float(value)) for value in values)
    ):
        return None
    sample["poseQuality"] = assess_pose_sample(
        sample,
        landmark_visibility(landmarks),
        target_side=prosthetic_leg,
    )
    return sample


def draw_sagittal_metrics(frame, landmarks, sample, width, height):
    lm = landmarks.landmark
    right_hip = lm[mp_pose.PoseLandmark.RIGHT_HIP.value]
    right_knee = lm[mp_pose.PoseLandmark.RIGHT_KNEE.value]
    left_hip = lm[mp_pose.PoseLandmark.LEFT_HIP.value]
    left_knee = lm[mp_pose.PoseLandmark.LEFT_KNEE.value]
    draw_overlay_text(frame, f"Hong P: {sample['right_hip']:.1f}*", (int(right_hip.x * width) + 10, int(right_hip.y * height)), color=(0, 255, 255))
    draw_overlay_text(frame, f"Hong T: {sample['left_hip']:.1f}*", (int(left_hip.x * width) + 10, int(left_hip.y * height)), color=(255, 150, 0))
    draw_overlay_text(frame, f"Goi P: {sample['right_knee']:.1f}*", (int(right_knee.x * width) + 10, int(right_knee.y * height)), color=(0, 255, 255))
    draw_overlay_text(frame, f"Goi T: {sample['left_knee']:.1f}*", (int(left_knee.x * width) + 10, int(left_knee.y * height)), color=(255, 150, 0))
    draw_overlay_text(frame, f"Than: {sample['trunk_tilt']:.1f}*", (20, 80), color=(100, 255, 100))


def pose_landmark_mapping(landmarks):
    """Copy the normalized gait landmarks so camera threads never share protobufs."""
    return {
        name: {
            "x": float(landmarks.landmark[item.value].x),
            "y": float(landmarks.landmark[item.value].y),
            "z": float(getattr(landmarks.landmark[item.value], "z", 0.0)),
            "visibility": float(getattr(landmarks.landmark[item.value], "visibility", 0.0)),
        }
        for name, item in FUSION_LANDMARKS.items()
    }


def submit_camera_pose(
    physical_slot, landmarks, sagittal_sample, frame_at, captured_ns, width, height
):
    """Synchronize logical views and store exactly one sample per sagittal frame."""
    if SINGLE_CAMERA_MODE:
        if sagittal_sample is not None:
            store_sagittal_sample(
                sagittal_fallback_sample(sagittal_sample, single_camera=True),
                frame_at,
            )
        return

    with camera_roles_lock:
        swapped = camera_roles_swapped
    logical_view = (
        "sagittal" if (physical_slot == 0) == swapped else "frontal"
    )
    observation = {
        "captured_ns": captured_ns,
        "captured_at": frame_at,
        "landmarks": pose_landmark_mapping(landmarks),
        "sample": sagittal_sample if logical_view == "sagittal" else None,
        "physicalSlot": int(physical_slot),
        "imageSize": [int(width), int(height)],
    }
    for output in camera_synchronizer.submit(logical_view, observation):
        sagittal = output["sagittal"]
        sample = sagittal.get("sample")
        if sample is None:
            continue
        if output["kind"] == "paired":
            fused = fuse_synchronized_sample(
                sample,
                sagittal["landmarks"],
                output["frontal"]["landmarks"],
                output["syncErrorMs"],
                CAMERA_SYNC_TOLERANCE_MS,
            )
            frontal = output["frontal"]
            by_slot = {
                int(sagittal["physicalSlot"]): sagittal,
                int(frontal["physicalSlot"]): frontal,
            }
            camera_indices = (CAMERA_FRONTAL_INDEX, CAMERA_SAGITTAL_INDEX)
            calibration_compatible = stereo_calibration.compatible(camera_indices)
            fused.setdefault("cameraFusion", {})["stereoCalibrated"] = calibration_compatible
            if calibration_compatible and 0 in by_slot and 1 in by_slot:
                try:
                    triangulation = stereo_calibration.triangulate(
                        by_slot[0]["landmarks"],
                        by_slot[1]["landmarks"],
                        camera_indices=camera_indices,
                        image_size_0=tuple(by_slot[0]["imageSize"]),
                        image_size_1=tuple(by_slot[1]["imageSize"]),
                    )
                    fused = apply_stereo_flexion(
                        fused,
                        triangulation,
                        max_reprojection_error_px=CAMERA_MAX_REPROJECTION_ERROR_PX,
                    )
                except (StereoCalibrationError, ValueError, TypeError) as exc:
                    fused["cameraFusion"].update({
                        "stereoUsed": False,
                        "stereoError": str(exc),
                    })
                    quality = fused.setdefault("poseQuality", {})
                    quality["stereoReprojectionReliable"] = False
                    quality["frameReliable"] = False
        else:
            fused = sagittal_fallback_sample(sample, single_camera=False)
        store_sagittal_sample(fused, float(sagittal["captured_at"]))


def store_sagittal_sample(sample, frame_at):
    """Store live and optional recording data from the active sagittal source."""
    global is_recording, latest_sagittal_pose_at
    with gait_store_lock:
        with live_gait_lock:
            live_gait_samples.append({"time": frame_at, **sample})
        latest_sagittal_pose_at = frame_at
        if not is_recording:
            return
        elapsed = frame_at - record_start_time
        if elapsed > record_duration:
            is_recording = False
            save_recorded_data_to_db()
            return
        recorded_timestamps.append(elapsed)
        recorded_left_knee.append(sample["left_knee"])
        recorded_right_knee.append(sample["right_knee"])
        recorded_left_ankle.append(sample["left_ankle"])
        recorded_right_ankle.append(sample["right_ankle"])
        recorded_pelvic_tilt.append(sample["pelvic_tilt"])
        recorded_trunk_tilt.append(sample["trunk_tilt"])
        recorded_left_hip.append(sample["left_hip"])
        recorded_right_hip.append(sample["right_hip"])
        recorded_pose_quality.append(sample.get("poseQuality", {}))

def open_camera(camera_index, label, *, allow_fallback=True):
    """Open a camera, optionally avoiding slow Windows fallback during discovery."""
    backends = [CAMERA_BACKEND]
    if allow_fallback and CAMERA_BACKEND != cv2.CAP_ANY:
        backends.append(cv2.CAP_ANY)
    for backend in backends:
        capture = cv2.VideoCapture(camera_index, backend)
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            capture.set(cv2.CAP_PROP_FPS, 30)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            backend_name = 'default' if backend == cv2.CAP_ANY else 'DirectShow'
            print(f'[{label}] Opened device index {camera_index} with {backend_name} backend.')
            return capture
        capture.release()
    return None

def wait_for_camera(camera_index, label):
    next_log_at = 0.0
    while running and not camera_stop_event.is_set():
        capture = open_camera(camera_index, label)
        if capture is not None:
            return capture
        now = time.time()
        if now >= next_log_at:
            print(f'[{label}] Cannot open device index {camera_index}; retrying.')
            next_log_at = now + 10.0
        if camera_stop_event.wait(CAMERA_RETRY_SECONDS):
            break
    return None

def camera_loop_0():
    """Camera index 0: Frontal view"""
    global latest_frame_0, latest_raw_frame_0, latest_frame_0_at, latest_frame_0_ns, latest_pose_0_at, running
    pose = create_pose_detector()
    identity_lock = PoseIdentityLock()
    cap = wait_for_camera(CAMERA_FRONTAL_INDEX, 'Camera 0 / frontal')
    if cap is None:
        print(f'[Camera 0] Cannot open device index {CAMERA_FRONTAL_INDEX}.')
        pose.close()
        return
    read_failures = 0
    
    print("[Camera 0] Frontal thread started.")
    
    while running and not camera_stop_event.is_set():
        success, frame = cap.read()
        if not success:
            read_failures += 1
            if read_failures == 1:
                print(f'[Camera 0] Device index {CAMERA_FRONTAL_INDEX} stopped returning frames.')
            if read_failures >= CAMERA_READ_FAILURE_LIMIT:
                cap.release()
                cap = wait_for_camera(CAMERA_FRONTAL_INDEX, 'Camera 0 / frontal')
                read_failures = 0
                if cap is None:
                    break
            time.sleep(0.03)
            continue
        read_failures = 0
        captured_ns = time.perf_counter_ns()
        frame_at = time.time()
        raw_frame = frame.copy()
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)
        
        locked_landmarks = None
        pose_sample = None
        if results.pose_landmarks:
            locked_landmarks = identity_lock.update(results.pose_landmarks, frame_at)
            draw_gait_skeleton(frame, locked_landmarks)
            with camera_roles_lock:
                use_for_gait = camera_roles_swapped
            if use_for_gait:
                try:
                    pose_sample = pose_sample_from_landmarks(locked_landmarks, w, h)
                    if pose_sample is not None:
                        draw_sagittal_metrics(frame, locked_landmarks, pose_sample, w, h)
                except Exception:
                    pose_sample = None
            try:
                submit_camera_pose(
                    0, locked_landmarks, pose_sample, frame_at, captured_ns, w, h
                )
            except Exception:
                pass
            
        with frame_lock_0:
            latest_frame_0 = frame.copy()
            latest_raw_frame_0 = raw_frame
            latest_frame_0_at = frame_at
            latest_frame_0_ns = captured_ns
            if locked_landmarks is not None:
                latest_pose_0_at = frame_at
            
        if camera_stop_event.wait(CAMERA_FRAME_DELAY_SECONDS):
            break
        
    if cap is not None:
        cap.release()
    pose.close()
    print("[Camera 0] thread stopped.")

def camera_loop_1():
    """Camera index 1: Sagittal view (does joints calculations & recording buffers)"""
    global latest_frame_1, latest_raw_frame_1, latest_frame_1_at, latest_frame_1_ns, latest_pose_1_at, running, is_recording, record_start_time
    global recorded_timestamps, recorded_left_knee, recorded_right_knee, recorded_left_ankle, recorded_right_ankle
    global recorded_left_hip, recorded_right_hip, recorded_pelvic_tilt, recorded_trunk_tilt
    
    pose = create_pose_detector()
    identity_lock = PoseIdentityLock()
    camera_index = CAMERA_FRONTAL_INDEX if SINGLE_CAMERA_MODE else CAMERA_SAGITTAL_INDEX
    cap = wait_for_camera(camera_index, 'Camera 1 / sagittal')
    if cap is None:
        print(f'[Camera 1] Cannot open device index {camera_index}.')
        pose.close()
        return
    read_failures = 0
    
    print("[Camera 1] Sagittal thread started.")
    
    while running and not camera_stop_event.is_set():
        success, frame = cap.read()
        if not success:
            read_failures += 1
            if read_failures == 1:
                print(f'[Camera 1] Device index {camera_index} stopped returning frames.')
            if read_failures >= CAMERA_READ_FAILURE_LIMIT:
                cap.release()
                cap = wait_for_camera(camera_index, 'Camera 1 / sagittal')
                read_failures = 0
                if cap is None:
                    break
            time.sleep(0.05)
            continue
        read_failures = 0
        captured_ns = time.perf_counter_ns()
        frame_at = time.time()
        raw_frame = frame.copy()
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)
        
        pose_sample = None
        locked_landmarks = None

        if results.pose_landmarks:
            locked_landmarks = identity_lock.update(results.pose_landmarks, frame_at)
            draw_gait_skeleton(frame, locked_landmarks)
            with camera_roles_lock:
                use_for_gait = not camera_roles_swapped
            if use_for_gait:
                try:
                    pose_sample = pose_sample_from_landmarks(locked_landmarks, w, h)
                    if pose_sample is not None:
                        draw_sagittal_metrics(frame, locked_landmarks, pose_sample, w, h)
                except Exception:
                    pose_sample = None
            try:
                submit_camera_pose(
                    1,
                    locked_landmarks,
                    pose_sample if use_for_gait else None,
                    frame_at,
                    captured_ns,
                    w,
                    h,
                )
            except Exception:
                pass
            latest_pose_1_at = frame_at
                
        if is_recording:
            elapsed = time.time() - record_start_time
            draw_overlay_text(frame, f"REC: {elapsed:.1f}s", (20, 40), scale=0.8, color=(0, 0, 255))
            cv2.circle(frame, (w - 30, 30), 10, (0, 0, 255), -1)
            
        with frame_lock_1:
            latest_frame_1 = frame.copy()
            latest_raw_frame_1 = raw_frame
            latest_frame_1_at = frame_at
            latest_frame_1_ns = captured_ns
            
        if camera_stop_event.wait(CAMERA_FRAME_DELAY_SECONDS):
            break
        
    if cap is not None:
        cap.release()
    pose.close()
    print("[Camera 1] thread stopped.")

# Camera workers start only after the setup screen commits a device selection.
thread_0 = None
thread_1 = None
camera_workers_started = False
camera_worker_lock = threading.Lock()
camera_stop_event = threading.Event()


def start_camera_workers():
    """Start capture threads once after camera roles have been configured."""
    global thread_0, thread_1, camera_workers_started
    with camera_worker_lock:
        if camera_workers_started:
            return False
        if not camera_configured or CAMERA_FRONTAL_INDEX is None:
            raise RuntimeError("Camera roles have not been configured.")
        if not SINGLE_CAMERA_MODE and CAMERA_SAGITTAL_INDEX is None:
            raise RuntimeError("A sagittal camera must be selected in two-camera mode.")
        camera_stop_event.clear()
        if not SINGLE_CAMERA_MODE:
            thread_0 = threading.Thread(
                target=camera_loop_0,
                name="camera-frontal",
                daemon=True,
            )
            thread_0.start()
        else:
            thread_0 = None
        thread_1 = threading.Thread(
            target=camera_loop_1,
            name="camera-sagittal",
            daemon=True,
        )
        thread_1.start()
        camera_workers_started = True
        return True


def stop_camera_workers(timeout=6.0):
    """Stop only camera capture workers and release devices for reconfiguration."""
    global thread_0, thread_1, camera_workers_started
    global latest_frame_0, latest_frame_1, latest_raw_frame_0, latest_raw_frame_1
    global latest_frame_0_at, latest_frame_1_at, latest_frame_0_ns, latest_frame_1_ns
    global latest_pose_0_at, latest_pose_1_at, latest_sagittal_pose_at

    with camera_worker_lock:
        if not camera_workers_started:
            return False
        camera_stop_event.set()
        workers = [worker for worker in (thread_0, thread_1) if worker is not None]
        deadline = time.monotonic() + max(0.5, float(timeout))
        for worker in workers:
            remaining = max(0.0, deadline - time.monotonic())
            worker.join(remaining)
        alive = [worker.name for worker in workers if worker.is_alive()]
        if alive:
            raise RuntimeError(
                "Camera worker did not stop in time: " + ", ".join(alive)
            )

        thread_0 = None
        thread_1 = None
        camera_workers_started = False
        with frame_lock_0:
            latest_frame_0 = None
            latest_raw_frame_0 = None
            latest_frame_0_at = 0.0
            latest_frame_0_ns = 0
            latest_pose_0_at = 0.0
        with frame_lock_1:
            latest_frame_1 = None
            latest_raw_frame_1 = None
            latest_frame_1_at = 0.0
            latest_frame_1_ns = 0
            latest_pose_1_at = 0.0
        latest_sagittal_pose_at = 0.0
        return True


if camera_configured:
    start_camera_workers()
# Optional hardware/media services are installed after camera state exists.

import sys
from realtime_services import install_realtime_services
install_realtime_services(app, sys.modules[__name__])

def gen_frames(camera_index):
    while True:
        frame_to_send = None
        with camera_roles_lock:
            swapped = camera_roles_swapped
        physical_index = camera_index
        if not SINGLE_CAMERA_MODE and swapped:
            physical_index = 1 - camera_index
        if physical_index == 0 and not SINGLE_CAMERA_MODE:
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
        healthy_leg, active_session_id,
        recorded_pose_quality,
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
    global recorded_left_hip, recorded_right_hip, recorded_pelvic_tilt, recorded_trunk_tilt
    global recorded_pose_quality, active_session_id, active_scan_type, session_markers
    
    recorded_timestamps = []
    recorded_left_knee = []
    recorded_right_knee = []
    recorded_left_ankle = []
    recorded_right_ankle = []
    recorded_pelvic_tilt = []
    recorded_trunk_tilt = []
    recorded_left_hip = []
    recorded_right_hip = []
    recorded_pose_quality = []
    session_markers = []
    camera_synchronizer.reset()
    
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
            healthy_leg, session_id,
            recorded_pose_quality,
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
    global recorded_left_hip, recorded_right_hip, recorded_trunk_tilt
    return {
        "left_knee": resample(recorded_left_knee),
        "right_knee": resample(recorded_right_knee),
        "left_ankle": resample(recorded_left_ankle),
        "right_ankle": resample(recorded_right_ankle),
        "pelvic_tilt": resample(recorded_pelvic_tilt),
        "trunk_tilt": resample(recorded_trunk_tilt),
        "left_hip": resample(recorded_left_hip),
        "right_hip": resample(recorded_right_hip),
        "total_frames_collected": len(recorded_left_knee)
    }

def shutdown_event():
    global running
    running = False
    camera_stop_event.set()

app.router.add_event_handler("shutdown", shutdown_event)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
