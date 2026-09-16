import cv2
import mediapipe as mp
import numpy as np
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
    hip_flexion_from_body_axis,
    normalize_sagittal_trunk_lean,
    sagittal_trunk_frame_angle,
    sagittal_fallback_sample,
)
from pose_identity_lock import PoseIdentityLock
from pose_angle_overlay import draw_joint_angle_labels
from pose_quality import assess_pose_sample, assess_temporal_consistency
from stereo_calibration import StereoCalibrationError, StereoCalibrationManager

from algorithms import (
    calculate_angle,
    resample,
    estimate_socket_moment,
    homography_project,
    compute_dtw_distance,
    analyze_cropped_segment
)

app = FastAPI()

# Camera roles are intentionally selected in the setup screen before Scan.
# Environment variables can still preconfigure a deployed appliance if needed.
_env_frontal_index = (os.getenv("CAMERA_FRONTAL_INDEX") or "").strip()
_env_sagittal_index = (os.getenv("CAMERA_SAGITTAL_INDEX") or "").strip()
SINGLE_CAMERA_MODE = os.getenv("SINGLE_CAMERA_MODE", "false").lower() in ("1", "true", "yes")
CAMERA_FRONTAL_INDEX = int(_env_frontal_index) if _env_frontal_index else None
CAMERA_SAGITTAL_INDEX = int(_env_sagittal_index) if _env_sagittal_index else None
camera_configured = CAMERA_FRONTAL_INDEX is not None and (
    SINGLE_CAMERA_MODE or CAMERA_SAGITTAL_INDEX is not None
)
CAMERA_BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY

CAMERA_RETRY_SECONDS = float(os.getenv('CAMERA_RETRY_SECONDS', '2.0'))
CAMERA_READ_FAILURE_LIMIT = int(os.getenv('CAMERA_READ_FAILURE_LIMIT', '30'))
CAMERA_SYNC_TOLERANCE_MS = float(os.getenv('CAMERA_SYNC_TOLERANCE_MS', '40.0'))
CAMERA_FRAME_DELAY_SECONDS = float(os.getenv('CAMERA_FRAME_DELAY_SECONDS', '0.005'))
CAMERA_MAX_REPROJECTION_ERROR_PX = float(os.getenv('CAMERA_MAX_REPROJECTION_ERROR_PX', '8.0'))
POSE_INPUT_WIDTH = min(1280, max(256, int(os.getenv('CAMERA_POSE_INPUT_WIDTH', '640'))))
POSE_REACQUIRE_INPUT_WIDTH = min(
    1280,
    max(POSE_INPUT_WIDTH, int(os.getenv('CAMERA_POSE_REACQUIRE_WIDTH', '854'))),
)
POSE_REACQUIRE_INTERVAL = min(
    30,
    max(2, int(os.getenv('CAMERA_POSE_REACQUIRE_INTERVAL', '8'))),
)
POSE_TARGET_FPS = min(30.0, max(8.0, float(os.getenv('CAMERA_POSE_FPS', '12'))))
POSE_MODEL_COMPLEXITY = min(2, max(0, int(os.getenv('CAMERA_POSE_MODEL_COMPLEXITY', '1'))))
POSE_DETECTION_CONFIDENCE = min(0.95, max(0.3, float(os.getenv('CAMERA_POSE_DETECTION_CONFIDENCE', '0.50'))))
POSE_TRACKING_CONFIDENCE = min(0.95, max(0.3, float(os.getenv('CAMERA_POSE_TRACKING_CONFIDENCE', '0.45'))))
STREAM_TARGET_FPS = min(30.0, max(8.0, float(os.getenv('CAMERA_STREAM_FPS', '20'))))
STREAM_JPEG_QUALITY = min(92, max(65, int(os.getenv('CAMERA_STREAM_JPEG_QUALITY', '84'))))
STREAM_MAX_WIDTH = min(1920, max(640, int(os.getenv('CAMERA_STREAM_WIDTH', '1280'))))
CAMERA_REQUEST_WIDTH = min(1920, max(320, int(os.getenv('CAMERA_WIDTH', '1280'))))
CAMERA_REQUEST_HEIGHT = min(1080, max(240, int(os.getenv('CAMERA_HEIGHT', '720'))))
# Two simultaneous 720p Brio streams are intentionally requested at 20 FPS:
# enough temporal detail for walking, while leaving CPU for both pose models
# and JPEG preview. The profile negotiator can still fall back to native 30/15.
CAMERA_REQUEST_FPS = min(60.0, max(10.0, float(os.getenv('CAMERA_REQUEST_FPS', '20'))))

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
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
latest_processed_frame_0_ns = 0
latest_processed_frame_1_ns = 0
latest_capture_sequence_0 = 0
latest_capture_sequence_1 = 0
capture_times_0 = deque(maxlen=120)
capture_times_1 = deque(maxlen=120)
pose_times_0 = deque(maxlen=90)
pose_times_1 = deque(maxlen=90)
pose_inference_times_0 = deque(maxlen=120)
pose_inference_times_1 = deque(maxlen=120)
pose_reliable_times_0 = deque(maxlen=120)
pose_reliable_times_1 = deque(maxlen=120)
camera_health_0 = {}
camera_health_1 = {}
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
recorded_frontal_trunk_lean = []
recorded_left_hip = []
recorded_right_hip = []
recorded_pose_quality = []
recorded_foot_tracking = []
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
GAIT_LEFT_COLOR = (255, 170, 30)
GAIT_RIGHT_COLOR = (20, 220, 255)
GAIT_TRUNK_COLOR = (80, 230, 100)
# These thresholds are display-only. Clinical measurements keep their stricter
# gates in pose_quality.py; lowering this value merely prevents the overlay from
# blinking when the far leg is briefly occluded in the sagittal view.
GAIT_MIN_VISIBILITY_TO_DRAW = 0.40
GAIT_HIGH_VISIBILITY = 0.80
GAIT_LOW_VISIBILITY_ALPHA = 0.55
GAIT_SKELETON_HOLD_SECONDS = 0.20
LEFT_GAIT_INDICES = frozenset({
    mp_pose.PoseLandmark.LEFT_SHOULDER.value,
    mp_pose.PoseLandmark.LEFT_HIP.value,
    mp_pose.PoseLandmark.LEFT_KNEE.value,
    mp_pose.PoseLandmark.LEFT_ANKLE.value,
    mp_pose.PoseLandmark.LEFT_HEEL.value,
    mp_pose.PoseLandmark.LEFT_FOOT_INDEX.value,
})
RIGHT_GAIT_INDICES = frozenset({
    mp_pose.PoseLandmark.RIGHT_SHOULDER.value,
    mp_pose.PoseLandmark.RIGHT_HIP.value,
    mp_pose.PoseLandmark.RIGHT_KNEE.value,
    mp_pose.PoseLandmark.RIGHT_ANKLE.value,
    mp_pose.PoseLandmark.RIGHT_HEEL.value,
    mp_pose.PoseLandmark.RIGHT_FOOT_INDEX.value,
})


def gait_landmark_mapping(landmarks):
    return {
        name: {
            "x": float(landmarks.landmark[item.value].x),
            "y": float(landmarks.landmark[item.value].y),
            "visibility": float(
                getattr(landmarks.landmark[item.value], "visibility", 0.0)
            ),
        }
        for name, item in FUSION_LANDMARKS.items()
    }


def draw_gait_skeleton(frame, landmarks, *, sagittal=False):
    mapping = gait_landmark_mapping(landmarks)
    draw_gait_skeleton_mapping(frame, mapping, sagittal=sagittal)
    return mapping


def draw_gait_skeleton_mapping(frame, landmarks, *, sagittal=False):
    """Draw only connected, in-frame lower-body segments.

    MediaPipe can retain high visibility for a landmark just outside the image
    while a person enters or leaves the camera view. Drawing that point used to
    create long diagonal lines across the entire preview. Every valid segment is
    rendered independently so one briefly hidden joint no longer removes the
    other leg. In a sagittal view the left/right labels may swap as the limbs
    overlap, therefore the trunk is represented by one shoulder-to-hip centre
    line instead of two potentially crossing side rails.
    """
    height, width = frame.shape[:2]
    points = {}
    visibility = {}

    for name, index in GAIT_LANDMARK_NAMES.items():
        item = landmarks.get(name)
        if not isinstance(item, dict):
            continue
        try:
            x = float(item.get("x"))
            y = float(item.get("y"))
            score = float(item.get("visibility", 0.0))
        except (TypeError, ValueError):
            continue
        if (
            score < GAIT_MIN_VISIBILITY_TO_DRAW
            or not math.isfinite(x)
            or not math.isfinite(y)
            or x < 0.0
            or x > 1.0
            or y < 0.0
            or y > 1.0
        ):
            continue
        points[index] = (int(x * width), int(y * height))
        visibility[index] = score

    def side_color(indices):
        # Confidence must never change a limb's identity colour. Previously a
        # low-confidence left or right segment was recoloured amber, making two
        # overlapping legs look like the same limb. Confidence is now conveyed
        # only by stroke weight and opacity.
        if indices.issubset(LEFT_GAIT_INDICES):
            return GAIT_LEFT_COLOR
        if indices.issubset(RIGHT_GAIT_INDICES):
            return GAIT_RIGHT_COLOR
        return GAIT_TRUNK_COLOR

    faint_segments = []
    rendered_indices = set()
    for start_index, end_index in GAIT_CONNECTIONS:
        if sagittal and (
            (start_index == mp_pose.PoseLandmark.LEFT_SHOULDER.value
             and end_index == mp_pose.PoseLandmark.LEFT_HIP.value)
            or (start_index == mp_pose.PoseLandmark.RIGHT_SHOULDER.value
                and end_index == mp_pose.PoseLandmark.RIGHT_HIP.value)
        ):
            continue
        if start_index in points and end_index in points:
            start_point = points[start_index]
            end_point = points[end_index]
            # A valid anatomical segment cannot span almost half the image.
            # This catches the occasional in-frame identity jump without
            # drawing a conspicuous diagonal line through the preview.
            if math.dist(start_point, end_point) > height * 0.48:
                continue
            score = min(visibility[start_index], visibility[end_index])
            color = side_color(frozenset((start_index, end_index)))
            if score >= GAIT_HIGH_VISIBILITY:
                cv2.line(
                    frame,
                    start_point,
                    end_point,
                    color,
                    3,
                    cv2.LINE_AA,
                )
            else:
                faint_segments.append((start_point, end_point, color))
            rendered_indices.update((start_index, end_index))

    if sagittal:
        shoulder_indices = (
            mp_pose.PoseLandmark.LEFT_SHOULDER.value,
            mp_pose.PoseLandmark.RIGHT_SHOULDER.value,
        )
        hip_indices = (
            mp_pose.PoseLandmark.LEFT_HIP.value,
            mp_pose.PoseLandmark.RIGHT_HIP.value,
        )
        visible_shoulders = [index for index in shoulder_indices if index in points]
        visible_hips = [index for index in hip_indices if index in points]
        if visible_shoulders and visible_hips:
            shoulder_center = tuple(
                int(round(sum(points[index][axis] for index in visible_shoulders)
                          / len(visible_shoulders)))
                for axis in (0, 1)
            )
            hip_center = tuple(
                int(round(sum(points[index][axis] for index in visible_hips)
                          / len(visible_hips)))
                for axis in (0, 1)
            )
            centre_score = min(
                *(visibility[index] for index in visible_shoulders),
                *(visibility[index] for index in visible_hips),
            )
            if math.dist(shoulder_center, hip_center) <= height * 0.48:
                if centre_score >= GAIT_HIGH_VISIBILITY:
                    cv2.line(
                        frame,
                        shoulder_center,
                        hip_center,
                        GAIT_TRUNK_COLOR,
                        3,
                        cv2.LINE_AA,
                    )
                else:
                    faint_segments.append(
                        (shoulder_center, hip_center, GAIT_TRUNK_COLOR)
                    )
                rendered_indices.update(visible_shoulders)
                rendered_indices.update(visible_hips)

    # Draw all uncertain segments in one translucent pass. This keeps the
    # original left/right/trunk colour while clearly distinguishing inferred or
    # briefly occluded geometry, without repeated full-frame blending.
    if faint_segments:
        faint_overlay = frame.copy()
        for start_point, end_point, color in faint_segments:
            cv2.line(
                faint_overlay,
                start_point,
                end_point,
                color,
                1,
                cv2.LINE_AA,
            )
        cv2.addWeighted(
            faint_overlay,
            GAIT_LOW_VISIBILITY_ALPHA,
            frame,
            1.0 - GAIT_LOW_VISIBILITY_ALPHA,
            0.0,
            frame,
        )

    faint_indices = []
    for index in rendered_indices:
        point = points[index]
        color = side_color(frozenset((index,)))
        if visibility[index] >= GAIT_HIGH_VISIBILITY:
            cv2.circle(frame, point, 6, (20, 20, 20), -1, cv2.LINE_AA)
            cv2.circle(frame, point, 4, color, -1, cv2.LINE_AA)
        else:
            faint_indices.append((point, color))

    if faint_indices:
        faint_overlay = frame.copy()
        for point, color in faint_indices:
            cv2.circle(faint_overlay, point, 5, (20, 20, 20), -1, cv2.LINE_AA)
            cv2.circle(faint_overlay, point, 3, color, -1, cv2.LINE_AA)
        cv2.addWeighted(
            faint_overlay,
            GAIT_LOW_VISIBILITY_ALPHA,
            frame,
            1.0 - GAIT_LOW_VISIBILITY_ALPHA,
            0.0,
            frame,
        )
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
    "left_foot_index": mp_pose.PoseLandmark.LEFT_FOOT_INDEX,
    "right_foot_index": mp_pose.PoseLandmark.RIGHT_FOOT_INDEX,
}
GAIT_LANDMARK_NAMES = {
    name: item.value for name, item in FUSION_LANDMARKS.items()
}


def landmark_visibility(landmarks):
    return {
        name: float(getattr(landmarks.landmark[item.value], "visibility", 0.0))
        for name, item in QUALITY_LANDMARKS.items()
    }


def landmark_positions(landmarks):
    return {
        name: {
            "x": float(landmarks.landmark[item.value].x),
            "y": float(landmarks.landmark[item.value].y),
        }
        for name, item in QUALITY_LANDMARKS.items()
    }


def create_pose_detector():
    return mp_pose.Pose(
        static_image_mode=False,
        model_complexity=POSE_MODEL_COMPLEXITY,
        smooth_landmarks=False,
        enable_segmentation=False,
        min_detection_confidence=POSE_DETECTION_CONFIDENCE,
        min_tracking_confidence=POSE_TRACKING_CONFIDENCE,
    )


def prepare_pose_frame(frame, missed_frames=0):
    """Use periodic higher-detail frames to reacquire a temporarily lost body."""
    height, width = frame.shape[:2]
    missed = max(0, int(missed_frames))
    # Keep the tracked path inexpensive for two simultaneous Brio streams. A
    # larger inference frame is used only after several consecutive misses, so
    # it can recover ankles/feet without permanently dropping pose FPS.
    use_reacquire_detail = (
        missed > 0 and missed % POSE_REACQUIRE_INTERVAL == 0
    )
    requested_width = (
        POSE_REACQUIRE_INPUT_WIDTH if use_reacquire_detail else POSE_INPUT_WIDTH
    )
    pose_width = min(width, requested_width)
    pose_height = max(1, int(round(height * pose_width / width)))
    if pose_width == width and pose_height == height:
        return frame
    return cv2.resize(
        frame,
        (pose_width, pose_height),
        interpolation=cv2.INTER_AREA,
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


def pose_sample_from_landmarks(landmarks, width, height, target_side=None):

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
    r_toe = point(mp_pose.PoseLandmark.RIGHT_FOOT_INDEX)
    l_toe = point(mp_pose.PoseLandmark.LEFT_FOOT_INDEX)
    nose = point(mp_pose.PoseLandmark.NOSE)

    # Use one trunk axis, translated through each hip. Connecting either hip
    # directly to the shoulder midpoint introduces a false diagonal and biases
    # left/right hip flexion even when the subject is standing symmetrically.
    sample = {
        "right_hip": hip_flexion_from_body_axis(
            l_shoulder, r_shoulder, l_hip, r_hip, r_knee, r_hip
        ),
        "right_knee": calculate_flexion_angle(r_hip, r_knee, r_ankle),
        "right_ankle": calculate_angle(r_knee, r_ankle, r_heel),
        "left_hip": hip_flexion_from_body_axis(
            l_shoulder, r_shoulder, l_hip, r_hip, l_knee, l_hip
        ),
        "left_knee": calculate_flexion_angle(l_hip, l_knee, l_ankle),
        "left_ankle": calculate_angle(l_knee, l_ankle, l_heel),
    }
    sample["pelvic_tilt"] = math.degrees(math.atan2(
        l_hip[1] - r_hip[1], l_hip[0] - r_hip[0]
    ))
    mid_shoulder = [(l_shoulder[0] + r_shoulder[0]) / 2,
                    (l_shoulder[1] + r_shoulder[1]) / 2]
    mid_hip = [(l_hip[0] + r_hip[0]) / 2,
               (l_hip[1] + r_hip[1]) / 2]
    def pose_visibility(landmark):
        return float(getattr(lm[landmark.value], "visibility", 0.0))

    trunk_frame_angle, trunk_axis_method = sagittal_trunk_frame_angle(
        l_shoulder,
        r_shoulder,
        l_hip,
        r_hip,
        left_visibility=min(
            pose_visibility(mp_pose.PoseLandmark.LEFT_SHOULDER),
            pose_visibility(mp_pose.PoseLandmark.LEFT_HIP),
        ),
        right_visibility=min(
            pose_visibility(mp_pose.PoseLandmark.RIGHT_SHOULDER),
            pose_visibility(mp_pose.PoseLandmark.RIGHT_HIP),
        ),
    )
    def reliable_direction_point(landmark, coordinates):
        item = lm[landmark.value]
        return coordinates if float(getattr(item, "visibility", 0.0)) >= 0.35 else None

    trunk_tilt, facing_sign, facing_source = normalize_sagittal_trunk_lean(
        trunk_frame_angle,
        left_heel=reliable_direction_point(mp_pose.PoseLandmark.LEFT_HEEL, l_heel),
        left_toe=reliable_direction_point(mp_pose.PoseLandmark.LEFT_FOOT_INDEX, l_toe),
        right_heel=reliable_direction_point(mp_pose.PoseLandmark.RIGHT_HEEL, r_heel),
        right_toe=reliable_direction_point(mp_pose.PoseLandmark.RIGHT_FOOT_INDEX, r_toe),
        nose=reliable_direction_point(mp_pose.PoseLandmark.NOSE, nose),
        mid_shoulder=mid_shoulder,
    )
    sample["trunk_tilt"] = trunk_tilt
    sample["trunk_tilt_frame"] = trunk_frame_angle
    sample["trunk_axis_method"] = trunk_axis_method
    sample["sagittal_facing_sign"] = facing_sign
    sample["sagittal_facing_source"] = facing_source
    torso_length = math.dist(mid_shoulder, mid_hip)
    sample["sagittal_view_width_ratio"] = (
        abs(float(l_hip[0]) - float(r_hip[0])) / max(torso_length, 1e-6)
    )
    sample["sagittal_center_x"] = float(mid_hip[0]) / max(float(width), 1.0)
    def tracking_point(landmark, coordinates):
        item = lm[landmark.value]
        return {
            "x": round(float(coordinates[0]), 4),
            "y": round(float(coordinates[1]), 4),
            "visibility": round(float(getattr(item, "visibility", 0.0)), 4),
        }

    # Retain sagittal pixel geometry so patient-specific centimetre scaling can
    # be recalculated independently from the joint-angle signals.
    sample["footTracking"] = {
        "imageWidthPx": int(width),
        "imageHeightPx": int(height),
        "left": {
            "hip": tracking_point(mp_pose.PoseLandmark.LEFT_HIP, l_hip),
            "knee": tracking_point(mp_pose.PoseLandmark.LEFT_KNEE, l_knee),
            "ankle": tracking_point(mp_pose.PoseLandmark.LEFT_ANKLE, l_ankle),
            "heel": tracking_point(mp_pose.PoseLandmark.LEFT_HEEL, l_heel),
            "toe": tracking_point(mp_pose.PoseLandmark.LEFT_FOOT_INDEX, l_toe),
        },
        "right": {
            "hip": tracking_point(mp_pose.PoseLandmark.RIGHT_HIP, r_hip),
            "knee": tracking_point(mp_pose.PoseLandmark.RIGHT_KNEE, r_knee),
            "ankle": tracking_point(mp_pose.PoseLandmark.RIGHT_ANKLE, r_ankle),
            "heel": tracking_point(mp_pose.PoseLandmark.RIGHT_HEEL, r_heel),
            "toe": tracking_point(mp_pose.PoseLandmark.RIGHT_FOOT_INDEX, r_toe),
        },
    }
    values = tuple(
        sample[key]
        for key in (
            "right_hip", "right_knee", "right_ankle",
            "left_hip", "left_knee", "left_ankle",
            "pelvic_tilt", "trunk_tilt",
        )
    )
    if not (
        all(0.0 <= value <= 180.0 for value in values[:6])
        and all(math.isfinite(float(value)) for value in values)
    ):
        return None
    sample["poseQuality"] = assess_pose_sample(
        sample,
        landmark_visibility(landmarks),
        target_side=target_side or prosthetic_leg,
        landmark_positions=landmark_positions(landmarks),
    )
    return sample


def draw_sagittal_metrics(frame, landmarks, sample, width, height):
    # Called only for fresh detections on the logical sagittal camera. Never
    # retain numeric angles when only the previous skeleton is being held.
    draw_joint_angle_labels(frame, gait_landmark_mapping(landmarks), sample,
                           draw_knee_segments=True)


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
                sagittal_image_size=tuple(sagittal["imageSize"]),
                frontal_image_size=tuple(output["frontal"]["imageSize"]),
            )
            frontal = output["frontal"]
            by_slot = {
                int(sagittal["physicalSlot"]): sagittal,
                int(frontal["physicalSlot"]): frontal,
            }
            camera_indices = (CAMERA_FRONTAL_INDEX, CAMERA_SAGITTAL_INDEX)
            calibration_available = stereo_calibration.compatible(camera_indices)
            calibration_compatible = bool(
                0 in by_slot
                and 1 in by_slot
                and stereo_calibration.compatible(
                    camera_indices,
                    image_size_0=tuple(by_slot[0]["imageSize"]),
                    image_size_1=tuple(by_slot[1]["imageSize"]),
                )
            )
            fusion_status = fused.setdefault("cameraFusion", {})
            fusion_status["stereoCalibrated"] = calibration_compatible
            fusion_status["stereoCalibrationAvailable"] = calibration_available
            fusion_status["stereoNeedsRecalibration"] = bool(
                calibration_available and not calibration_compatible
            )
            if calibration_available and not calibration_compatible:
                fusion_status.update({
                    "stereoUsed": False,
                    "stereoError": (
                        "Live camera resolution differs from the saved calibration; "
                        "2D measurements remain available until recalibration."
                    ),
                })
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
        else:
            fused = sagittal_fallback_sample(sample, single_camera=False)
        store_sagittal_sample(fused, float(sagittal["captured_at"]))


def store_sagittal_sample(sample, frame_at):
    """Store live and optional recording data from the active sagittal source."""
    global is_recording, latest_sagittal_pose_at
    with gait_store_lock:
        with live_gait_lock:
            previous = live_gait_samples[-1] if live_gait_samples else None
            quality = sample.setdefault("poseQuality", {})
            temporal = assess_temporal_consistency(
                sample,
                previous,
                (
                    float(frame_at) - float(previous.get("time", frame_at))
                    if previous is not None
                    else 0.0
                ),
            )
            quality.update(temporal)
            temporal_jumps = temporal["temporalJumpAngles"]
            if temporal_jumps:
                quality["frameReliable"] = False
                quality["bilateralSagittalReliable"] = False
                target_knee = f"{str(quality.get('targetSide') or '').lower()}_knee"
                if target_knee in temporal_jumps:
                    quality["targetLegReliable"] = False
            live_gait_samples.append({"time": frame_at, **sample})
        latest_sagittal_pose_at = frame_at
        if not is_recording:
            return
        elapsed = frame_at - record_start_time
        if elapsed > record_duration:
            is_recording = False
            save_recorded_data_to_db()
            return
        # Retain every finite pose sample together with its quality metadata.
        # Segment analysis now gates each leg independently; dropping the whole
        # frame here caused unrecoverable holes whenever only the far leg was
        # briefly occluded.
        recorded_timestamps.append(elapsed)
        recorded_left_knee.append(sample["left_knee"])
        recorded_right_knee.append(sample["right_knee"])
        recorded_left_ankle.append(sample["left_ankle"])
        recorded_right_ankle.append(sample["right_ankle"])
        recorded_pelvic_tilt.append(sample["pelvic_tilt"])
        recorded_trunk_tilt.append(sample["trunk_tilt"])
        recorded_frontal_trunk_lean.append(
            float(sample.get("frontal_trunk_lean", float("nan")))
        )
        recorded_left_hip.append(sample["left_hip"])
        recorded_right_hip.append(sample["right_hip"])
        recorded_pose_quality.append(sample.get("poseQuality", {}))
        recorded_foot_tracking.append(sample.get("footTracking", {}))

def frame_quality_metrics(frame):
    """Cheap input-quality screening; thresholds reject only severe failures."""
    height, width = frame.shape[:2]
    scale = min(1.0, 320.0 / max(1, width))
    sample = cv2.resize(
        frame,
        (max(1, int(width * scale)), max(1, int(height * scale))),
    )
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    dark_fraction = float(np.mean(gray <= 12))
    bright_fraction = float(np.mean(gray >= 245))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    reasons = []
    if brightness < 25.0 or dark_fraction > 0.60:
        reasons.append("too_dark")
    if brightness > 235.0 or bright_fraction > 0.60:
        reasons.append("overexposed")
    if sharpness < 12.0:
        reasons.append("too_blurry")
    return {
        "width": int(width),
        "height": int(height),
        "brightness": round(brightness, 2),
        "darkFraction": round(dark_fraction, 4),
        "brightFraction": round(bright_fraction, 4),
        "sharpness": round(sharpness, 2),
        "qualityReady": not reasons,
        "qualityReasons": reasons,
        "qualityCheckedAt": time.time(),
    }


def capture_properties(capture):
    fourcc_value = int(capture.get(cv2.CAP_PROP_FOURCC) or 0)
    fourcc = "".join(chr((fourcc_value >> (8 * index)) & 0xFF) for index in range(4))
    fourcc = fourcc.strip("\x00")
    reported_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    reported_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    reported_fps = round(float(capture.get(cv2.CAP_PROP_FPS) or 0.0), 2)
    return {
        "reportedWidth": reported_width,
        "reportedHeight": reported_height,
        "reportedFps": reported_fps,
        "fourcc": fourcc,
        "requestedWidth": CAMERA_REQUEST_WIDTH,
        "requestedHeight": CAMERA_REQUEST_HEIGHT,
        "requestedFps": CAMERA_REQUEST_FPS,
        "hdProfile": reported_width >= 1280 and reported_height >= 720,
        "profileMatched": (
            reported_width == CAMERA_REQUEST_WIDTH
            and reported_height == CAMERA_REQUEST_HEIGHT
            and (reported_fps <= 0.0 or reported_fps >= CAMERA_REQUEST_FPS * 0.75)
            and (os.name != "nt" or fourcc.upper() == "MJPG")
        ),
    }


def record_camera_error(health, stage, error):
    counts = dict(health.get("errorCounts", {}))
    counts[stage] = int(counts.get(stage, 0)) + 1
    health["errorCounts"] = counts
    health["lastError"] = f"{stage}: {type(error).__name__}: {str(error)[:180]}"
    health["lastErrorAt"] = time.time()


def camera_capture_profiles():
    """Return native-first DirectShow profiles, without duplicate attempts."""
    candidates = [
        (CAMERA_REQUEST_WIDTH, CAMERA_REQUEST_HEIGHT, CAMERA_REQUEST_FPS),
        (1280, 720, 30.0),
        (CAMERA_REQUEST_WIDTH, CAMERA_REQUEST_HEIGHT, 15.0),
        (1280, 720, 15.0),
        (640, 480, 30.0),
        (640, 480, 15.0),
    ]
    profiles = []
    for width, height, fps in candidates:
        profile = (int(width), int(height), float(fps))
        if profile not in profiles:
            profiles.append(profile)
    return profiles


def configure_camera_capture(capture):
    """Negotiate the clearest supported camera profile and report fallbacks."""
    profiles = camera_capture_profiles()
    attempts = []
    selected = None
    for width, height, fps in profiles:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_FPS, fps)
        # DirectShow switches back to uncompressed YUY2 whenever resolution is
        # changed. FOURCC must therefore be the final setting for each profile;
        # doing it first caps two 720p cameras at roughly 10 FPS on this laptop.
        if os.name == "nt":
            capture.set(
                cv2.CAP_PROP_FOURCC,
                cv2.VideoWriter_fourcc(*"MJPG"),
            )
        properties = capture_properties(capture)
        attempts.append({
            "width": width,
            "height": height,
            "fps": fps,
            "reportedWidth": properties["reportedWidth"],
            "reportedHeight": properties["reportedHeight"],
            "reportedFps": properties["reportedFps"],
        })
        fps_matches = (
            properties["reportedFps"] <= 0.0
            or properties["reportedFps"] >= fps * 0.75
        )
        codec_matches = os.name != "nt" or properties["fourcc"].upper() == "MJPG"
        if (
            properties["reportedWidth"] == width
            and properties["reportedHeight"] == height
            and fps_matches
            and codec_matches
        ):
            selected = (width, height, fps)
            break
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    properties = capture_properties(capture)
    properties["profileFallback"] = selected != profiles[0]
    properties["selectedProfile"] = (
        {"width": selected[0], "height": selected[1], "fps": selected[2]}
        if selected is not None
        else None
    )
    properties["profileAttempts"] = attempts
    return properties


def open_camera(camera_index, label, *, allow_fallback=True):
    """Open a camera, optionally avoiding slow Windows fallback during discovery."""
    backends = [CAMERA_BACKEND]
    if allow_fallback and CAMERA_BACKEND != cv2.CAP_ANY:
        backends.append(cv2.CAP_ANY)
    for backend in backends:
        capture = cv2.VideoCapture(camera_index, backend)
        if capture.isOpened():
            properties = configure_camera_capture(capture)
            backend_name = 'default' if backend == cv2.CAP_ANY else 'DirectShow'
            print(
                f'[{label}] Opened device index {camera_index} with {backend_name}: '
                f'{properties["reportedWidth"]}x{properties["reportedHeight"]} '
                f'@ {properties["reportedFps"]:.1f} FPS {properties["fourcc"]}.'
            )
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

def camera_capture_loop_0():
    """Read camera 0 continuously so pose inference cannot stall the video."""
    global latest_raw_frame_0, latest_frame_0_at, latest_frame_0_ns
    global latest_capture_sequence_0
    cap = wait_for_camera(CAMERA_FRONTAL_INDEX, 'Camera 0 / frontal')
    if cap is None:
        print(f'[Camera 0] Cannot open device index {CAMERA_FRONTAL_INDEX}.')
        return
    read_failures = 0
    reconnects = 0
    last_quality_at = 0.0
    camera_health_0.update(capture_properties(cap))
    camera_health_0.update({"readFailures": 0, "reconnects": 0})
    print("[Camera 0] capture thread started.")
    while running and not camera_stop_event.is_set():
        success, frame = cap.read()
        if not success:
            read_failures += 1
            camera_health_0["readFailures"] = read_failures
            if read_failures == 1:
                print(f'[Camera 0] Device index {CAMERA_FRONTAL_INDEX} stopped returning frames.')
            if read_failures >= CAMERA_READ_FAILURE_LIMIT:
                cap.release()
                cap = wait_for_camera(CAMERA_FRONTAL_INDEX, 'Camera 0 / frontal')
                read_failures = 0
                reconnects += 1
                camera_health_0["reconnects"] = reconnects
                if cap is None:
                    break
                camera_health_0.update(capture_properties(cap))
            time.sleep(0.03)
            continue
        read_failures = 0
        captured_ns = time.perf_counter_ns()
        frame_at = time.time()
        if frame_at - last_quality_at >= 0.5:
            camera_health_0.update(frame_quality_metrics(frame))
            camera_health_0.update({
                "actualFrameWidth": int(frame.shape[1]),
                "actualFrameHeight": int(frame.shape[0]),
            })
            last_quality_at = frame_at
        camera_health_0["readFailures"] = 0
        with frame_lock_0:
            latest_raw_frame_0 = frame
            latest_frame_0_at = frame_at
            latest_frame_0_ns = captured_ns
            latest_capture_sequence_0 += 1
            capture_times_0.append(frame_at)

    if cap is not None:
        cap.release()
    print("[Camera 0] capture thread stopped.")


def camera_loop_0():
    """Run MediaPipe independently from camera-0 capture."""
    global latest_frame_0, latest_pose_0_at, latest_processed_frame_0_ns
    pose = create_pose_detector()
    identity_lock = PoseIdentityLock()
    last_sequence = 0
    last_drawable_landmarks = None
    last_drawable_at = 0.0
    consecutive_pose_errors = 0
    missed_pose_frames = 0
    print("[Camera 0] frontal pose thread started.")
    while running and not camera_stop_event.is_set():
        with frame_lock_0:
            sequence = latest_capture_sequence_0
            if latest_raw_frame_0 is None or sequence == last_sequence:
                raw_frame = None
            else:
                raw_frame = latest_raw_frame_0.copy()
                frame_at = latest_frame_0_at
                captured_ns = latest_frame_0_ns
        if raw_frame is None:
            camera_stop_event.wait(CAMERA_FRAME_DELAY_SECONDS)
            continue
        last_sequence = sequence
        inference_started = time.perf_counter()
        frame = raw_frame.copy()
        h, w, _ = frame.shape
        pose_frame = prepare_pose_frame(frame, missed_pose_frames)
        rgb = cv2.cvtColor(pose_frame, cv2.COLOR_BGR2RGB)
        try:
            results = pose.process(rgb)
            consecutive_pose_errors = 0
        except Exception as exc:
            record_camera_error(camera_health_0, "pose_inference", exc)
            consecutive_pose_errors += 1
            if consecutive_pose_errors >= 3:
                pose.close()
                pose = create_pose_detector()
                identity_lock.reset()
                consecutive_pose_errors = 0
            camera_stop_event.wait(0.05)
            continue
        pose_inference_times_0.append(time.time())
        missed_pose_frames = 0 if results.pose_landmarks else missed_pose_frames + 1
        
        locked_landmarks = None
        pose_sample = None
        pose_quality = None
        with camera_roles_lock:
            use_for_gait = camera_roles_swapped
        if results.pose_landmarks:
            locked_landmarks = identity_lock.update(results.pose_landmarks, frame_at)
            last_drawable_landmarks = draw_gait_skeleton(
                frame,
                locked_landmarks,
                sagittal=use_for_gait,
            )
            last_drawable_at = frame_at
            if use_for_gait:
                try:
                    pose_sample = pose_sample_from_landmarks(locked_landmarks, w, h)
                except Exception as exc:
                    record_camera_error(camera_health_0, "pose_measurement", exc)
                    pose_sample = None
            # Preview angles depend on each joint's landmarks, not a successful
            # full-body measurement or the visibility of the opposite leg.
            # Frontal values are image-plane knee angles only, NOT substituted
            # for sagittal flexion in saved gait measurements.
            draw_joint_angle_labels(
                frame, last_drawable_landmarks, pose_sample,
                knee_only=not use_for_gait, draw_knee_segments=True,
            )
            try:
                submit_camera_pose(
                    0, locked_landmarks, pose_sample, frame_at, captured_ns, w, h
                )
            except Exception as exc:
                record_camera_error(camera_health_0, "camera_fusion", exc)
            pose_quality = (
                pose_sample.get("poseQuality")
                if pose_sample is not None
                else assess_pose_sample(
                    {},
                    landmark_visibility(locked_landmarks),
                    landmark_positions=landmark_positions(locked_landmarks),
                )
            )
        elif (
            last_drawable_landmarks is not None
            and frame_at - last_drawable_at <= GAIT_SKELETON_HOLD_SECONDS
        ):
            draw_gait_skeleton_mapping(
                frame,
                last_drawable_landmarks,
                sagittal=use_for_gait,
            )
            
        with frame_lock_0:
            latest_frame_0 = frame.copy()
            latest_processed_frame_0_ns = captured_ns
            if locked_landmarks is not None:
                latest_pose_0_at = frame_at
                pose_times_0.append(time.time())
                if pose_quality and pose_quality.get("frameReliable"):
                    pose_reliable_times_0.append(time.time())
        remaining = max(
            CAMERA_FRAME_DELAY_SECONDS,
            1.0 / POSE_TARGET_FPS - (time.perf_counter() - inference_started),
        )
        if camera_stop_event.wait(remaining):
            break
    pose.close()
    print("[Camera 0] frontal pose thread stopped.")


def camera_capture_loop_1():
    """Read camera 1 continuously so pose inference cannot stall the video."""
    global latest_raw_frame_1, latest_frame_1_at, latest_frame_1_ns
    global latest_capture_sequence_1
    camera_index = CAMERA_FRONTAL_INDEX if SINGLE_CAMERA_MODE else CAMERA_SAGITTAL_INDEX
    cap = wait_for_camera(camera_index, 'Camera 1 / sagittal')
    if cap is None:
        print(f'[Camera 1] Cannot open device index {camera_index}.')
        return
    read_failures = 0
    reconnects = 0
    last_quality_at = 0.0
    camera_health_1.update(capture_properties(cap))
    camera_health_1.update({"readFailures": 0, "reconnects": 0})
    print("[Camera 1] capture thread started.")
    while running and not camera_stop_event.is_set():
        success, frame = cap.read()
        if not success:
            read_failures += 1
            camera_health_1["readFailures"] = read_failures
            if read_failures == 1:
                print(f'[Camera 1] Device index {camera_index} stopped returning frames.')
            if read_failures >= CAMERA_READ_FAILURE_LIMIT:
                cap.release()
                cap = wait_for_camera(camera_index, 'Camera 1 / sagittal')
                read_failures = 0
                reconnects += 1
                camera_health_1["reconnects"] = reconnects
                if cap is None:
                    break
                camera_health_1.update(capture_properties(cap))
            time.sleep(0.05)
            continue
        read_failures = 0
        captured_ns = time.perf_counter_ns()
        frame_at = time.time()
        if frame_at - last_quality_at >= 0.5:
            camera_health_1.update(frame_quality_metrics(frame))
            camera_health_1.update({
                "actualFrameWidth": int(frame.shape[1]),
                "actualFrameHeight": int(frame.shape[0]),
            })
            last_quality_at = frame_at
        camera_health_1["readFailures"] = 0
        with frame_lock_1:
            latest_raw_frame_1 = frame
            latest_frame_1_at = frame_at
            latest_frame_1_ns = captured_ns
            latest_capture_sequence_1 += 1
            capture_times_1.append(frame_at)

    if cap is not None:
        cap.release()
    print("[Camera 1] capture thread stopped.")


def camera_loop_1():
    """Run sagittal MediaPipe independently from camera-1 capture."""
    global latest_frame_1, latest_pose_1_at, latest_processed_frame_1_ns
    global is_recording, record_start_time
    pose = create_pose_detector()
    identity_lock = PoseIdentityLock()
    last_sequence = 0
    last_drawable_landmarks = None
    last_drawable_at = 0.0
    consecutive_pose_errors = 0
    missed_pose_frames = 0
    print("[Camera 1] sagittal pose thread started.")
    while running and not camera_stop_event.is_set():
        with frame_lock_1:
            sequence = latest_capture_sequence_1
            if latest_raw_frame_1 is None or sequence == last_sequence:
                raw_frame = None
            else:
                raw_frame = latest_raw_frame_1.copy()
                frame_at = latest_frame_1_at
                captured_ns = latest_frame_1_ns
        if raw_frame is None:
            camera_stop_event.wait(CAMERA_FRAME_DELAY_SECONDS)
            continue
        last_sequence = sequence
        inference_started = time.perf_counter()
        frame = raw_frame.copy()
        h, w, _ = frame.shape
        pose_frame = prepare_pose_frame(frame, missed_pose_frames)
        rgb = cv2.cvtColor(pose_frame, cv2.COLOR_BGR2RGB)
        try:
            results = pose.process(rgb)
            consecutive_pose_errors = 0
        except Exception as exc:
            record_camera_error(camera_health_1, "pose_inference", exc)
            consecutive_pose_errors += 1
            if consecutive_pose_errors >= 3:
                pose.close()
                pose = create_pose_detector()
                identity_lock.reset()
                consecutive_pose_errors = 0
            camera_stop_event.wait(0.05)
            continue
        pose_inference_times_1.append(time.time())
        missed_pose_frames = 0 if results.pose_landmarks else missed_pose_frames + 1
        
        pose_sample = None
        locked_landmarks = None
        pose_quality = None
        with camera_roles_lock:
            use_for_gait = not camera_roles_swapped

        if results.pose_landmarks:
            locked_landmarks = identity_lock.update(results.pose_landmarks, frame_at)
            last_drawable_landmarks = draw_gait_skeleton(
                frame,
                locked_landmarks,
                sagittal=use_for_gait,
            )
            last_drawable_at = frame_at
            if use_for_gait:
                try:
                    pose_sample = pose_sample_from_landmarks(locked_landmarks, w, h)
                except Exception as exc:
                    record_camera_error(camera_health_1, "pose_measurement", exc)
                    pose_sample = None
            draw_joint_angle_labels(
                frame, last_drawable_landmarks, pose_sample,
                knee_only=not use_for_gait, draw_knee_segments=True,
            )
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
            except Exception as exc:
                record_camera_error(camera_health_1, "camera_fusion", exc)
            pose_quality = (
                pose_sample.get("poseQuality")
                if pose_sample is not None
                else assess_pose_sample(
                    {},
                    landmark_visibility(locked_landmarks),
                    landmark_positions=landmark_positions(locked_landmarks),
                )
            )
            latest_pose_1_at = frame_at
        elif (
            last_drawable_landmarks is not None
            and frame_at - last_drawable_at <= GAIT_SKELETON_HOLD_SECONDS
        ):
            draw_gait_skeleton_mapping(
                frame,
                last_drawable_landmarks,
                sagittal=use_for_gait,
            )
                
        if is_recording:
            elapsed = time.time() - record_start_time
            draw_overlay_text(frame, f"REC: {elapsed:.1f}s", (20, 40), scale=0.8, color=(0, 0, 255))
            cv2.circle(frame, (w - 30, 30), 10, (0, 0, 255), -1)
            
        with frame_lock_1:
            latest_frame_1 = frame.copy()
            latest_processed_frame_1_ns = captured_ns
            if locked_landmarks is not None:
                pose_times_1.append(time.time())
                if pose_quality and pose_quality.get("frameReliable"):
                    pose_reliable_times_1.append(time.time())
        remaining = max(
            CAMERA_FRAME_DELAY_SECONDS,
            1.0 / POSE_TARGET_FPS - (time.perf_counter() - inference_started),
        )
        if camera_stop_event.wait(remaining):
            break
    pose.close()
    print("[Camera 1] sagittal pose thread stopped.")

# Camera workers start only after the setup screen commits a device selection.
thread_0 = None
thread_1 = None
capture_thread_0 = None
capture_thread_1 = None
camera_workers_started = False
camera_worker_lock = threading.Lock()
camera_stop_event = threading.Event()


def start_camera_workers():
    """Start capture threads once after camera roles have been configured."""
    global thread_0, thread_1, capture_thread_0, capture_thread_1
    global camera_workers_started
    with camera_worker_lock:
        if camera_workers_started:
            return False
        if not camera_configured or CAMERA_FRONTAL_INDEX is None:
            raise RuntimeError("Camera roles have not been configured.")
        if not SINGLE_CAMERA_MODE and CAMERA_SAGITTAL_INDEX is None:
            raise RuntimeError("A sagittal camera must be selected in two-camera mode.")
        camera_stop_event.clear()
        if not SINGLE_CAMERA_MODE:
            capture_thread_0 = threading.Thread(
                target=camera_capture_loop_0,
                name="capture-frontal",
                daemon=True,
            )
            thread_0 = threading.Thread(
                target=camera_loop_0,
                name="camera-frontal",
                daemon=True,
            )
            capture_thread_0.start()
            thread_0.start()
        else:
            capture_thread_0 = None
            thread_0 = None
        capture_thread_1 = threading.Thread(
            target=camera_capture_loop_1,
            name="capture-sagittal",
            daemon=True,
        )
        thread_1 = threading.Thread(
            target=camera_loop_1,
            name="camera-sagittal",
            daemon=True,
        )
        capture_thread_1.start()
        thread_1.start()
        camera_workers_started = True
        return True


def stop_camera_workers(timeout=6.0):
    """Stop only camera capture workers and release devices for reconfiguration."""
    global thread_0, thread_1, capture_thread_0, capture_thread_1
    global camera_workers_started
    global latest_frame_0, latest_frame_1, latest_raw_frame_0, latest_raw_frame_1
    global latest_frame_0_at, latest_frame_1_at, latest_frame_0_ns, latest_frame_1_ns
    global latest_processed_frame_0_ns, latest_processed_frame_1_ns
    global latest_pose_0_at, latest_pose_1_at, latest_sagittal_pose_at

    with camera_worker_lock:
        if not camera_workers_started:
            return False
        camera_stop_event.set()
        workers = [
            worker
            for worker in (
                capture_thread_0,
                capture_thread_1,
                thread_0,
                thread_1,
            )
            if worker is not None
        ]
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
        capture_thread_0 = None
        capture_thread_1 = None
        camera_workers_started = False
        with frame_lock_0:
            latest_frame_0 = None
            latest_raw_frame_0 = None
            latest_frame_0_at = 0.0
            latest_frame_0_ns = 0
            latest_processed_frame_0_ns = 0
            latest_pose_0_at = 0.0
            capture_times_0.clear()
            pose_times_0.clear()
            pose_inference_times_0.clear()
            pose_reliable_times_0.clear()
            camera_health_0.clear()
        with frame_lock_1:
            latest_frame_1 = None
            latest_raw_frame_1 = None
            latest_frame_1_at = 0.0
            latest_frame_1_ns = 0
            latest_processed_frame_1_ns = 0
            latest_pose_1_at = 0.0
            capture_times_1.clear()
            pose_times_1.clear()
            pose_inference_times_1.clear()
            pose_reliable_times_1.clear()
            camera_health_1.clear()
        latest_sagittal_pose_at = 0.0
        return True


if camera_configured:
    start_camera_workers()
# Optional hardware/media services are installed after camera state exists.

import sys
from realtime_services import install_realtime_services
install_realtime_services(app, sys.modules[__name__])

def gen_frames(camera_index, *, raw=False):
    last_frame_ns = 0
    frame_interval = 1.0 / STREAM_TARGET_FPS
    next_frame_at = time.monotonic()
    while True:
        wait_seconds = next_frame_at - time.monotonic()
        if wait_seconds > 0:
            time.sleep(min(wait_seconds, frame_interval))
            continue
        frame_to_send = None
        frame_ns = 0
        with camera_roles_lock:
            swapped = camera_roles_swapped
        physical_index = camera_index
        if not SINGLE_CAMERA_MODE and swapped:
            physical_index = 1 - camera_index
        if physical_index == 0 and not SINGLE_CAMERA_MODE:
            with frame_lock_0:
                source = latest_raw_frame_0 if raw else latest_frame_0
                if source is not None:
                    frame_to_send = source.copy()
                    frame_ns = (
                        latest_frame_0_ns if raw else latest_processed_frame_0_ns
                    )
        else:
            with frame_lock_1:
                source = latest_raw_frame_1 if raw else latest_frame_1
                if source is not None:
                    frame_to_send = source.copy()
                    frame_ns = (
                        latest_frame_1_ns if raw else latest_processed_frame_1_ns
                    )

        if frame_to_send is None or frame_ns <= last_frame_ns:
            time.sleep(0.005)
            continue
        ret, jpeg = cv2.imencode(
            '.jpg',
            (
                cv2.resize(
                    frame_to_send,
                    (
                        STREAM_MAX_WIDTH,
                        max(
                            1,
                            int(round(
                                frame_to_send.shape[0]
                                * STREAM_MAX_WIDTH
                                / frame_to_send.shape[1]
                            )),
                        ),
                    ),
                    interpolation=cv2.INTER_AREA,
                )
                if frame_to_send.shape[1] > STREAM_MAX_WIDTH
                else frame_to_send
            ),
            [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY],
        )
        if not ret:
            time.sleep(0.01)
            continue
        last_frame_ns = frame_ns
        # Advance from the previous deadline so JPEG encoding time is part of
        # the frame budget. Scheduling a fresh full interval after encoding
        # halved a configured 20 FPS stream to roughly 10 FPS at 720p.
        next_frame_at += frame_interval
        if next_frame_at < time.monotonic():
            next_frame_at = time.monotonic()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')

@app.get("/video_feed_0")
def video_feed_0(raw: bool = False):
    return StreamingResponse(
        gen_frames(0, raw=raw),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

@app.get("/video_feed_1")
def video_feed_1(raw: bool = False):
    return StreamingResponse(
        gen_frames(1, raw=raw),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

@app.get("/video_feed")
def video_feed(raw: bool = False):
    # Backward compatibility: point to camera index 1 (sagittal view)
    return StreamingResponse(
        gen_frames(1, raw=raw),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

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
    
    segment_id = "seg-default-" + uuid.uuid4().hex[:10]
    cursor.execute("INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (segment_id, active_session_id, start_t, end_t, 'manual', 'Ghi hình ban đầu', 'video_feed.mp4', time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    
    scan_id = "scan-" + uuid.uuid4().hex[:10]
    if active_scan_type == "baseline":
        cursor.execute("DELETE FROM scans WHERE session_id = ? AND scan_type = 'baseline'", (active_session_id,))
        cursor.execute("INSERT INTO scans (id, session_id, segment_id, scan_type, label, left_knee, right_knee, left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt, plantar_load_symmetry, cop_trajectory, cadence, stride_length, fatigue_flag, fatigue_slope, actual_adjustment_degrees, actual_adjustment_notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (scan_id, active_session_id, segment_id, "baseline", "Baseline chân lành",
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
                       (scan_id, active_session_id, segment_id, active_scan_type,
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
                "isReference": bool(s["is_reference"]),
                "baseline": baseline_data,
                "scans": scans_list
            })
            
        patients_list.append({
            "id": p_id,
            "name": p["name"],
            "age": p["age"],
            "heightCm": p["height_cm"],
            "weightKg": p["weight_kg"],
            "leftLegLengthCm": p["left_leg_length_cm"],
            "rightLegLengthCm": p["right_leg_length_cm"],
            "healthyLeg": p["healthy_leg"],
            "prostheticLeg": p["prosthetic_leg"],
            "injuryHistory": p["injury_history"],
            "treatmentGoals": p["treatment_goals"],
            "clinicalNotes": notes_list,
            "sessions": sorted(sessions_list, key=lambda x: x["createdAt"])
        })
        
    conn.close()
    return patients_list


def _validated_number(data, key, default, lower, upper, *, optional=False):
    value = data.get(key, default)
    if optional and (value is None or str(value).strip() == ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} phải là một số hợp lệ.") from exc
    if not math.isfinite(value) or not lower <= value <= upper:
        raise HTTPException(
            status_code=422,
            detail=f"{key} phải nằm trong khoảng {lower:g}–{upper:g}.",
        )
    return value


def _validated_patient_payload(data):
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Dữ liệu hồ sơ không hợp lệ.")
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 120:
        raise HTTPException(
            status_code=422,
            detail="Tên bệnh nhân không được để trống và tối đa 120 ký tự.",
        )
    age_value = _validated_number(data, "age", 30, 1, 120)
    if not age_value.is_integer():
        raise HTTPException(status_code=422, detail="Tuổi phải là số nguyên.")
    healthy = str(data.get("healthyLeg", "LEFT")).upper()
    prosthetic = str(data.get("prostheticLeg", "RIGHT")).upper()
    if healthy not in ("LEFT", "RIGHT") or prosthetic not in ("LEFT", "RIGHT"):
        raise HTTPException(status_code=422, detail="Bên chân phải là LEFT hoặc RIGHT.")
    if healthy == prosthetic:
        raise HTTPException(
            status_code=422,
            detail="Chân lành và chân giả phải ở hai bên khác nhau.",
        )
    return {
        "name": name,
        "age": int(age_value),
        "heightCm": _validated_number(data, "heightCm", 170, 80, 230),
        "weightKg": _validated_number(data, "weightKg", 60, 15, 350),
        "leftLegLengthCm": _validated_number(
            data, "leftLegLengthCm", None, 20, 150, optional=True
        ),
        "rightLegLengthCm": _validated_number(
            data, "rightLegLengthCm", None, 20, 150, optional=True
        ),
        "healthyLeg": healthy,
        "prostheticLeg": prosthetic,
        "injuryHistory": str(data.get("injuryHistory", "")).strip(),
        "treatmentGoals": str(data.get("treatmentGoals", "")).strip(),
    }

@app.post("/patients")
def create_patient(data: dict):
    values = _validated_patient_payload(data)
    new_id = "p-" + uuid.uuid4().hex[:10]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""INSERT INTO patients
                       (id, name, age, height_cm, weight_kg,
                        left_leg_length_cm, right_leg_length_cm,
                        healthy_leg, prosthetic_leg, injury_history, treatment_goals)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       (new_id, values["name"], values["age"], values["heightCm"],
                        values["weightKg"], values["leftLegLengthCm"],
                        values["rightLegLengthCm"], values["healthyLeg"],
                        values["prostheticLeg"], values["injuryHistory"],
                        values["treatmentGoals"]))
        conn.commit()
    finally:
        conn.close()
    
    return {
        "id": new_id,
        **values,
        "clinicalNotes": [],
        "sessions": []
    }

@app.put("/patients/{patient_id}")
def update_patient(patient_id: str, data: dict):
    values = _validated_patient_payload(data)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE patients SET name=?, age=?, height_cm=?, weight_kg=?, left_leg_length_cm=?, right_leg_length_cm=?, healthy_leg=?, prosthetic_leg=?, injury_history=?, treatment_goals=? WHERE id=?",
                       (values["name"], values["age"], values["heightCm"],
                        values["weightKg"], values["leftLegLengthCm"],
                        values["rightLegLengthCm"], values["healthyLeg"],
                        values["prostheticLeg"], values["injuryHistory"],
                        values["treatmentGoals"], patient_id))
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="Không tìm thấy bệnh nhân.")
        conn.commit()
    finally:
        conn.close()
    return {"status": "updated"}

@app.post("/patients/{patient_id}/sessions")
def create_session(patient_id: str, data: dict = None):
    is_practice_mode = 0
    is_reference = 0
    if data and "isPracticeMode" in data:
        is_practice_mode = 1 if data["isPracticeMode"] else 0
    if data and "isReference" in data:
        is_reference = 1 if data["isReference"] else 0
        
    new_sess_id = "s-" + uuid.uuid4().hex[:10]
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if cursor.execute(
            "SELECT 1 FROM patients WHERE id = ?", (patient_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bệnh nhân.")
        cursor.execute(
            """INSERT INTO sessions
               (id, patient_id, created_at, is_practice_mode, is_reference)
               VALUES (?, ?, ?, ?, ?)""",
            (new_sess_id, patient_id, created_at, is_practice_mode, is_reference),
        )
        conn.commit()
    finally:
        conn.close()
    
    return {
        "id": new_sess_id,
        "createdAt": created_at,
        "isPracticeMode": is_practice_mode,
        "isReference": bool(is_reference),
        "baseline": None,
        "scans": []
    }

@app.post("/scans/{session_id}/{scan_id}/adjustment")
def save_adjustment(session_id: str, scan_id: str, data: dict):
    degrees = _validated_number(data, "degrees", 0, -90, 90)
    notes = str(data.get("notes", "")).strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE scans SET actual_adjustment_degrees = ?, actual_adjustment_notes = ? WHERE session_id = ? AND id = ?",
                       (degrees, notes, session_id, scan_id))
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="Không tìm thấy lần phân tích.")
        conn.commit()
    finally:
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
    global recorded_frontal_trunk_lean
    global recorded_pose_quality, recorded_foot_tracking, active_session_id, active_scan_type, session_markers
    
    if healthy == prosthetic:
        raise HTTPException(status_code=422, detail="Chân lành và chân giả phải khác nhau.")
    if not math.isfinite(duration) or not 1.0 <= duration <= 3600.0:
        raise HTTPException(status_code=422, detail="Thời lượng ghi phải từ 1 đến 3600 giây.")
    conn = get_db_connection()
    try:
        if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy phiên đo.")
    finally:
        conn.close()

    recorded_timestamps = []
    recorded_left_knee = []
    recorded_right_knee = []
    recorded_left_ankle = []
    recorded_right_ankle = []
    recorded_pelvic_tilt = []
    recorded_trunk_tilt = []
    recorded_frontal_trunk_lean = []
    recorded_left_hip = []
    recorded_right_hip = []
    recorded_pose_quality = []
    recorded_foot_tracking = []
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
    conn = get_db_connection()
    try:
        if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy phiên đo.")
    finally:
        conn.close()
    active_session_id = session_id
    start_t = float(data.get("startOffsetSec", 0.0))
    end_t = float(data.get("endOffsetSec", 10.0))
    if not all(math.isfinite(value) for value in (start_t, end_t)):
        raise HTTPException(status_code=422, detail="Mốc thời gian không hợp lệ.")
    if start_t < 0 or end_t - start_t < 0.5:
        raise HTTPException(status_code=422, detail="Đoạn phân tích phải dài ít nhất 0,5 giây.")
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
    
    segment_id = "seg-" + uuid.uuid4().hex[:10]
    cursor.execute("INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (segment_id, session_id, start_t, end_t, 'manual', note, 'video_feed.mp4', time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    
    cursor.execute("DELETE FROM scans WHERE session_id = ? AND scan_type = ?", (session_id, scan_type))
    scan_id = "scan-" + uuid.uuid4().hex[:10]
    cursor.execute("INSERT INTO scans (id, session_id, segment_id, scan_type, label, left_knee, right_knee, left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt, plantar_load_symmetry, cop_trajectory, cadence, stride_length, fatigue_flag, fatigue_slope, actual_adjustment_degrees, actual_adjustment_notes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (scan_id, session_id, segment_id, scan_type,
                    f"Đánh giá chân giả - {scan_type.replace('scan_', 'Scan #')}" if scan_type != 'baseline' else 'Baseline chân lành',
                    json.dumps(l_knee), json.dumps(r_knee), json.dumps(l_ankle), json.dumps(r_ankle),
                    json.dumps(l_hip), json.dumps(r_hip), json.dumps(pelvic_t), load_sym, cop_traj,
                    cad, stride, fat_flag, fat_slope, 0.0, "", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    conn.commit()
    conn.close()
    
    return {
        "scanId": scan_id,
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
    new_id = "n-" + uuid.uuid4().hex[:10]
    session_id = data.get("sessionId", "")
    pinned_scan_id = data.get("pinnedScanId")
    note_type = str(data.get("noteType", "history"))
    content = str(data.get("content", "")).strip()
    if note_type not in ("history", "symptom"):
        raise HTTPException(status_code=422, detail="Loại ghi chú không hợp lệ.")
    if not content:
        raise HTTPException(status_code=422, detail="Nội dung ghi chú không được để trống.")
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        session = cursor.execute(
            "SELECT patient_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None or session["patient_id"] != patient_id:
            raise HTTPException(
                status_code=422,
                detail="Phiên đo không thuộc bệnh nhân đã chọn.",
            )
        if pinned_scan_id is not None:
            scan = cursor.execute(
                "SELECT session_id FROM scans WHERE id = ?", (pinned_scan_id,)
            ).fetchone()
            if scan is None or scan["session_id"] != session_id:
                raise HTTPException(
                    status_code=422,
                    detail="Lần phân tích được ghim không thuộc phiên đo này.",
                )
        cursor.execute("INSERT INTO clinical_notes VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (new_id, patient_id, session_id, pinned_scan_id, note_type, content, created_at))
        conn.commit()
    finally:
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
    global recorded_frontal_trunk_lean
    lateral_values = [
        float(value)
        for value in recorded_frontal_trunk_lean
        if math.isfinite(float(value))
    ]
    return {
        "left_knee": resample(recorded_left_knee),
        "right_knee": resample(recorded_right_knee),
        "left_ankle": resample(recorded_left_ankle),
        "right_ankle": resample(recorded_right_ankle),
        "pelvic_tilt": resample(recorded_pelvic_tilt),
        "trunk_tilt": resample(recorded_trunk_tilt),
        "frontal_trunk_lean": resample(lateral_values) if lateral_values else [],
        "left_hip": resample(recorded_left_hip),
        "right_hip": resample(recorded_right_hip),
        "total_frames_collected": len(recorded_left_knee)
    }

def shutdown_event():
    global running
    running = False
    camera_stop_event.set()
    # Explicitly join capture/inference workers so DirectShow handles are
    # released before the Python process exits.  Leaving daemon workers inside
    # cap.read() produced stale backend processes that kept camera resources.
    stop_camera_workers(timeout=4.0)

app.router.add_event_handler("shutdown", shutdown_event)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        access_log=False,
        timeout_graceful_shutdown=5,
    )
