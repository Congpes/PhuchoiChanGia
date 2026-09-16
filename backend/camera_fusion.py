"""Temporal synchronization and conservative two-camera pose fusion.

The sagittal view remains the source of flexion angles.  A synchronized
frontal view contributes coronal-plane measurements and cross-view quality
metadata.  This avoids pretending that uncalibrated webcams are a calibrated
stereo rig while still making both cameras participate in every stored sample.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from copy import deepcopy
from typing import Any, Mapping


ESSENTIAL_LANDMARKS = (
    "left_shoulder",
    "right_shoulder",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)


def _point(
    landmarks: Mapping[str, Mapping[str, float]],
    name: str,
    image_size: tuple[int, int] | None = None,
) -> tuple[float, float]:
    item = landmarks[name]
    x, y = float(item["x"]), float(item["y"])
    if image_size is None:
        return x, y
    width, height = image_size
    return x * float(width), y * float(height)


def _midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0


def _angle(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])
    denominator = math.hypot(*ba) * math.hypot(*bc)
    if denominator <= 1e-9:
        return 180.0
    cosine = max(-1.0, min(1.0, (ba[0] * bc[0] + ba[1] * bc[1]) / denominator))
    return math.degrees(math.acos(cosine))


def _normalize_axis(angle: float) -> float:
    while angle > 90.0:
        angle -= 180.0
    while angle < -90.0:
        angle += 180.0
    return angle


def normalize_sagittal_trunk_lean(
    frame_angle: float,
    *,
    left_heel: tuple[float, float] | None,
    left_toe: tuple[float, float] | None,
    right_heel: tuple[float, float] | None,
    right_toe: tuple[float, float] | None,
    nose: tuple[float, float] | None = None,
    mid_shoulder: tuple[float, float] | None = None,
) -> tuple[float, int, str]:
    """Express sagittal lean in the subject's forward axis.

    Image-x changes sign when a patient walks in the opposite direction. Toe
    relative to heel is the primary facing cue; head direction is only a
    fallback. Positive output always means forward lean.
    """
    foot_directions = []
    for heel, toe in ((left_heel, left_toe), (right_heel, right_toe)):
        if heel is not None and toe is not None:
            foot_directions.append(float(toe[0]) - float(heel[0]))
    usable = [value for value in foot_directions if abs(value) > 1e-6]
    foot_agrees = bool(usable) and (
        all(value >= 0.0 for value in usable)
        or all(value <= 0.0 for value in usable)
    )
    if foot_agrees:
        cue = sum(usable) / len(usable)
        source = "toe_minus_heel"
    elif nose is not None and mid_shoulder is not None:
        cue = float(nose[0]) - float(mid_shoulder[0])
        source = (
            "nose_minus_shoulder_foot_conflict"
            if usable else "nose_minus_shoulder"
        )
    elif usable:
        cue = max(usable, key=abs)
        source = "strongest_foot_fallback"
    else:
        cue = 1.0
        source = "frame_axis_fallback"
    forward_sign = 1 if cue >= 0.0 else -1
    return float(frame_angle) * forward_sign, forward_sign, source


def sagittal_trunk_frame_angle(
    left_shoulder: tuple[float, float],
    right_shoulder: tuple[float, float],
    left_hip: tuple[float, float],
    right_hip: tuple[float, float],
    *,
    left_visibility: float = 1.0,
    right_visibility: float = 1.0,
) -> tuple[float, str]:
    """Estimate the sagittal trunk axis without trusting the hidden body side.

    In a true side view MediaPipe still returns both shoulders and hips, but the
    far-side landmarks are inferred and can move diagonally across the torso.
    Averaging their *positions* therefore creates visible corners in trunk lean.
    We instead average the two unit shoulder-to-hip axes, weighted by each
    side's shoulder/hip visibility. The midpoint axis remains a deterministic
    fallback when neither side has usable support.
    """
    axes: list[tuple[float, float, float]] = []
    for shoulder, hip, visibility in (
        (left_shoulder, left_hip, left_visibility),
        (right_shoulder, right_hip, right_visibility),
    ):
        horizontal = float(shoulder[0]) - float(hip[0])
        vertical = float(hip[1]) - float(shoulder[1])
        length = math.hypot(horizontal, vertical)
        weight = max(0.0, min(1.0, float(visibility))) ** 2
        if length > 1e-6 and weight >= 0.01:
            axes.append((horizontal / length, vertical / length, weight))

    if axes:
        total_weight = sum(item[2] for item in axes)
        horizontal = sum(item[0] * item[2] for item in axes) / total_weight
        vertical = sum(item[1] * item[2] for item in axes) / total_weight
        if math.hypot(horizontal, vertical) > 1e-6:
            return _normalize_axis(
                math.degrees(math.atan2(horizontal, vertical))
            ), "visibility_weighted_side_axes"

    mid_shoulder = _midpoint(left_shoulder, right_shoulder)
    mid_hip = _midpoint(left_hip, right_hip)
    return _normalize_axis(math.degrees(math.atan2(
        mid_shoulder[0] - mid_hip[0],
        mid_hip[1] - mid_shoulder[1],
    ))), "shoulder_hip_midpoint_fallback"


def hip_flexion_from_body_axis(
    left_shoulder: tuple[float, float],
    right_shoulder: tuple[float, float],
    left_hip: tuple[float, float],
    right_hip: tuple[float, float],
    knee: tuple[float, float],
    hip: tuple[float, float],
) -> float:
    """Measure hip flexion against a shared trunk axis translated through the hip."""
    mid_shoulder = _midpoint(left_shoulder, right_shoulder)
    mid_hip = _midpoint(left_hip, right_hip)
    trunk_vector = (
        mid_shoulder[0] - mid_hip[0],
        mid_shoulder[1] - mid_hip[1],
    )
    proximal = (hip[0] + trunk_vector[0], hip[1] + trunk_vector[1])
    return max(0.0, 180.0 - _angle(proximal, hip, knee))


def frontal_metrics(
    landmarks: Mapping[str, Mapping[str, float]],
    image_size: tuple[int, int] | None = None,
) -> dict[str, float]:
    """Calculate measurements that belong to the frontal/coronal view."""
    left_shoulder = _point(landmarks, "left_shoulder", image_size)
    right_shoulder = _point(landmarks, "right_shoulder", image_size)
    left_hip = _point(landmarks, "left_hip", image_size)
    right_hip = _point(landmarks, "right_hip", image_size)
    left_knee = _point(landmarks, "left_knee", image_size)
    right_knee = _point(landmarks, "right_knee", image_size)
    left_ankle = _point(landmarks, "left_ankle", image_size)
    right_ankle = _point(landmarks, "right_ankle", image_size)
    mid_shoulder = _midpoint(left_shoulder, right_shoulder)
    mid_hip = _midpoint(left_hip, right_hip)

    visibility = [
        float(landmarks[name].get("visibility", 0.0))
        for name in ESSENTIAL_LANDMARKS
    ]
    trunk_visibility = [
        float(landmarks[name].get("visibility", 0.0))
        for name in (
            "left_shoulder", "right_shoulder", "left_hip", "right_hip"
        )
    ]
    pelvis_angle = _normalize_axis(math.degrees(math.atan2(
        left_hip[1] - right_hip[1],
        left_hip[0] - right_hip[0],
    )))
    trunk_lean_frame = _normalize_axis(math.degrees(math.atan2(
        mid_shoulder[0] - mid_hip[0],
        mid_hip[1] - mid_shoulder[1],
    )))
    # MediaPipe labels anatomical sides. Their horizontal order tells whether
    # patient-right points to frame-right (back view) or frame-left (front
    # view), so the sign remains anatomical when the patient turns around.
    patient_right_frame_sign = (
        1 if right_shoulder[0] >= left_shoulder[0] else -1
    )
    trunk_lean = trunk_lean_frame * patient_right_frame_sign
    return {
        "pelvicTilt": pelvis_angle,
        "trunkLateralLean": trunk_lean,
        "trunkLateralLeanFrame": trunk_lean_frame,
        "patientRightFrameSign": patient_right_frame_sign,
        "leftKneeCoronal": max(0.0, 180.0 - _angle(left_hip, left_knee, left_ankle)),
        "rightKneeCoronal": max(0.0, 180.0 - _angle(right_hip, right_knee, right_ankle)),
        "meanVisibility": sum(visibility) / len(visibility),
        "trunkMeanVisibility": sum(trunk_visibility) / len(trunk_visibility),
    }


def _view_width_ratio(
    landmarks: Mapping[str, Mapping[str, float]],
    image_size: tuple[int, int] | None = None,
) -> float:
    left_hip = _point(landmarks, "left_hip", image_size)
    right_hip = _point(landmarks, "right_hip", image_size)
    left_shoulder = _point(landmarks, "left_shoulder", image_size)
    right_shoulder = _point(landmarks, "right_shoulder", image_size)
    torso = math.dist(_midpoint(left_hip, right_hip), _midpoint(left_shoulder, right_shoulder))
    return abs(left_hip[0] - right_hip[0]) / max(torso, 1e-6)


def fuse_synchronized_sample(
    sagittal_sample: Mapping[str, Any],
    sagittal_landmarks: Mapping[str, Mapping[str, float]],
    frontal_landmarks: Mapping[str, Mapping[str, float]],
    sync_error_ms: float,
    max_sync_error_ms: float,
    sagittal_image_size: tuple[int, int] | None = None,
    frontal_image_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Add frontal measurements and synchronization quality to a sagittal sample."""
    sample = deepcopy(dict(sagittal_sample))
    front = frontal_metrics(frontal_landmarks, frontal_image_size)
    low_front = sorted(
        f"frontal:{name}"
        for name in ESSENTIAL_LANDMARKS
        if float(frontal_landmarks[name].get("visibility", 0.0)) < 0.55
    )
    synchronized = float(sync_error_ms) <= float(max_sync_error_ms)
    frontal_width = _view_width_ratio(frontal_landmarks, frontal_image_size)
    sagittal_width = _view_width_ratio(sagittal_landmarks, sagittal_image_size)
    frontal_points = [
        _point(frontal_landmarks, name)
        for name in ESSENTIAL_LANDMARKS
    ]
    frontal_body_height = (
        max(point[1] for point in frontal_points)
        - min(point[1] for point in frontal_points)
    )
    frontal_body_in_frame = (
        frontal_body_height >= 0.42
        and all(
            0.015 <= coordinate <= 0.985
            for point in frontal_points
            for coordinate in point
        )
    )
    roles_plausible = frontal_width > sagittal_width
    balance_reliable = (
        synchronized
        and not low_front
        and frontal_body_in_frame
        and roles_plausible
    )

    # Pelvic obliquity is a coronal-plane measurement, so the frontal camera is
    # the correct source.  Flexion angles deliberately stay sagittal until a
    # physical stereo calibration is available.
    sample["pelvic_tilt"] = front["pelvicTilt"]
    sample["frontal_trunk_lean"] = front["trunkLateralLean"]
    sample["cameraFusion"] = {
        "mode": "sagittal_flexion+frontal_coronal",
        "frontalAssisted": True,
        "synchronized": synchronized,
        "syncErrorMs": round(float(sync_error_ms), 2),
        "pelvicTiltSource": "frontal",
        "flexionSource": "sagittal",
        "frontalTrunkLean": round(front["trunkLateralLean"], 2),
        "leftKneeCoronal": round(front["leftKneeCoronal"], 2),
        "rightKneeCoronal": round(front["rightKneeCoronal"], 2),
        "frontalMeanVisibility": round(front["meanVisibility"], 3),
        "frontalHipWidthRatio": round(frontal_width, 3),
        "sagittalHipWidthRatio": round(sagittal_width, 3),
        "cameraRolesPlausible": roles_plausible,
        "frontalBodyInFrame": frontal_body_in_frame,
        "balanceReliable": balance_reliable,
    }

    quality = deepcopy(dict(sample.get("poseQuality", {})))
    low_landmarks = list(quality.get("lowLandmarks", []))
    low_landmarks.extend(item for item in low_front if item not in low_landmarks)
    quality.update({
        "lowLandmarks": low_landmarks,
        "frontalMeanVisibility": round(front["meanVisibility"], 3),
        "frontalAssisted": True,
        "crossViewSynchronized": synchronized,
        "syncErrorMs": round(float(sync_error_ms), 2),
        "measurementMethod": "dual_camera_2d",
        "cameraRolesPlausible": roles_plausible,
        "frontalBodyInFrame": frontal_body_in_frame,
        "balanceReliable": balance_reliable,
        "frameReliable": bool(quality.get("frameReliable", False))
        and balance_reliable,
    })
    sample["poseQuality"] = quality
    return sample


def sagittal_fallback_sample(
    sagittal_sample: Mapping[str, Any],
    *,
    single_camera: bool,
) -> dict[str, Any]:
    """Mark a sample that could not be paired without discarding live data."""
    sample = deepcopy(dict(sagittal_sample))
    quality = deepcopy(dict(sample.get("poseQuality", {})))
    quality.update({
        "frontalAssisted": False,
        "crossViewSynchronized": bool(single_camera),
        "syncErrorMs": None,
        "measurementMethod": "single_camera_2d" if single_camera else "sagittal_only_2d",
        "frameReliable": bool(quality.get("frameReliable", False)) and bool(single_camera),
    })
    sample["poseQuality"] = quality
    sample["cameraFusion"] = {
        "mode": "single_camera" if single_camera else "sagittal_fallback",
        "frontalAssisted": False,
        "synchronized": bool(single_camera),
        "syncErrorMs": None,
        "pelvicTiltSource": "sagittal_fallback",
        "flexionSource": "sagittal",
    }
    return sample


def apply_stereo_flexion(
    sample: Mapping[str, Any],
    triangulation: Mapping[str, Any],
    *,
    max_reprojection_error_px: float,
) -> dict[str, Any]:
    """Replace 2D flexion with pelvis-aligned 3D angles when calibration is sound."""
    result = deepcopy(dict(sample))
    original_angles = {
        name: result.get(name)
        for name in (
            "left_hip", "right_hip", "left_knee", "right_knee",
            "left_ankle", "right_ankle",
        )
    }
    points = triangulation.get("points", {})
    required = {
        "left_shoulder", "right_shoulder", "left_hip", "right_hip",
        "left_knee", "right_knee", "left_ankle", "right_ankle",
        "left_heel", "right_heel",
    }
    reprojection = float(triangulation.get("reprojectionErrorPx", math.inf))
    fusion = deepcopy(dict(result.get("cameraFusion", {})))
    fusion.update({
        "stereoCalibrated": True,
        "stereoUsed": False,
        "reprojectionErrorPx": round(reprojection, 2),
        "calibrationStereoRms": round(
            float(triangulation.get("calibrationStereoRms", math.inf)),
            3,
        ),
    })
    quality = deepcopy(dict(result.get("poseQuality", {})))
    quality["reprojectionErrorPx"] = round(reprojection, 2)
    if not required.issubset(points) or reprojection > float(max_reprojection_error_px):
        quality["stereoReprojectionReliable"] = False
        quality["frameReliable"] = False
        result["poseQuality"] = quality
        result["cameraFusion"] = fusion
        return result

    def vector(a, b):
        return tuple(float(a[index]) - float(b[index]) for index in range(3))

    def midpoint(a, b):
        return tuple((float(a[index]) + float(b[index])) / 2.0 for index in range(3))

    def dot(a, b):
        return sum(a[index] * b[index] for index in range(3))

    def norm(value):
        return math.sqrt(max(0.0, dot(value, value)))

    def unit(value):
        length = norm(value)
        if length <= 1e-9:
            raise ValueError("Degenerate 3D body axis")
        return tuple(component / length for component in value)

    def project_sagittal(value, lateral):
        lateral_component = dot(value, lateral)
        return tuple(value[index] - lateral_component * lateral[index] for index in range(3))

    def inner_angle(a, b, c, lateral):
        first = project_sagittal(vector(a, b), lateral)
        second = project_sagittal(vector(c, b), lateral)
        denominator = norm(first) * norm(second)
        if denominator <= 1e-9:
            raise ValueError("Degenerate projected joint vector")
        cosine = max(-1.0, min(1.0, dot(first, second) / denominator))
        return math.degrees(math.acos(cosine))

    try:
        left_hip = points["left_hip"]
        right_hip = points["right_hip"]
        lateral = unit(vector(right_hip, left_hip))
        mid_shoulder = midpoint(points["left_shoulder"], points["right_shoulder"])
        result["left_hip"] = max(0.0, 180.0 - inner_angle(
            mid_shoulder, left_hip, points["left_knee"], lateral
        ))
        result["right_hip"] = max(0.0, 180.0 - inner_angle(
            mid_shoulder, right_hip, points["right_knee"], lateral
        ))
        result["left_knee"] = max(0.0, 180.0 - inner_angle(
            left_hip, points["left_knee"], points["left_ankle"], lateral
        ))
        result["right_knee"] = max(0.0, 180.0 - inner_angle(
            right_hip, points["right_knee"], points["right_ankle"], lateral
        ))
        result["left_ankle"] = inner_angle(
            points["left_knee"], points["left_ankle"], points["left_heel"], lateral
        )
        result["right_ankle"] = inner_angle(
            points["right_knee"], points["right_ankle"], points["right_heel"], lateral
        )
    except (KeyError, TypeError, ValueError):
        result.update(original_angles)
        quality["stereoReprojectionReliable"] = False
        quality["frameReliable"] = False
        result["poseQuality"] = quality
        result["cameraFusion"] = fusion
        return result

    screening_limits = {
        "left_hip": (0.0, 100.0),
        "right_hip": (0.0, 100.0),
        "left_knee": (0.0, 135.0),
        "right_knee": (0.0, 135.0),
        "left_ankle": (0.0, 180.0),
        "right_ankle": (0.0, 180.0),
    }
    geometry_reliable = all(
        math.isfinite(float(result[name]))
        and lower <= float(result[name]) <= upper
        for name, (lower, upper) in screening_limits.items()
    )
    if not geometry_reliable:
        result.update(original_angles)
        fusion["stereoGeometryReliable"] = False
        quality["stereoReprojectionReliable"] = True
        quality["stereoGeometryReliable"] = False
        quality["frameReliable"] = False
        result["poseQuality"] = quality
        result["cameraFusion"] = fusion
        return result

    fusion.update({
        "mode": "calibrated_stereo_3d",
        "stereoUsed": True,
        "flexionSource": "calibrated_stereo_3d",
        "stereoGeometryReliable": True,
    })
    quality.update({
        "measurementMethod": "calibrated_stereo_3d",
        "stereoReprojectionReliable": True,
        "stereoGeometryReliable": True,
    })
    result["poseQuality"] = quality
    result["cameraFusion"] = fusion
    return result


class DualCameraSynchronizer:
    """Pair frontal and sagittal observations using monotonic capture time."""

    def __init__(self, max_skew_ms: float = 40.0, queue_size: int = 16):
        self.max_skew_ms = max(1.0, float(max_skew_ms))
        self._max_skew_ns = int(self.max_skew_ms * 1_000_000)
        self._front: deque[dict[str, Any]] = deque(maxlen=max(4, int(queue_size)))
        self._sagittal: deque[dict[str, Any]] = deque(maxlen=max(4, int(queue_size)))
        self._lock = threading.Lock()
        self._paired = 0
        self._fallback = 0
        self._skews: deque[float] = deque(maxlen=120)
        # Roughly the latest 5–7 seconds at the normal dual-pose rate. Startup
        # misses must not keep a later healthy camera pair locked forever.
        self._recent_results: deque[bool] = deque(maxlen=60)
        self._last_pair_wall = 0.0

    def reset(self) -> None:
        with self._lock:
            self._front.clear()
            self._sagittal.clear()
            self._paired = 0
            self._fallback = 0
            self._skews.clear()
            self._recent_results.clear()
            self._last_pair_wall = 0.0

    def submit(self, view: str, observation: Mapping[str, Any]) -> list[dict[str, Any]]:
        if view not in ("frontal", "sagittal"):
            raise ValueError("view must be 'frontal' or 'sagittal'")
        item = dict(observation)
        item["captured_ns"] = int(item["captured_ns"])
        outputs: list[dict[str, Any]] = []
        with self._lock:
            target = self._front if view == "frontal" else self._sagittal
            target.append(item)
            watermark = max(
                self._front[-1]["captured_ns"] if self._front else 0,
                self._sagittal[-1]["captured_ns"] if self._sagittal else 0,
            )

            while self._sagittal:
                sagittal = self._sagittal[0]
                sagittal_ns = sagittal["captured_ns"]
                while (
                    self._front
                    and self._front[0]["captured_ns"]
                    < sagittal_ns - self._max_skew_ns
                ):
                    self._front.popleft()

                candidate_index = None
                candidate_skew = None
                has_future_front = False
                for index, frontal in enumerate(self._front):
                    delta = frontal["captured_ns"] - sagittal_ns
                    if delta >= 0:
                        has_future_front = True
                    absolute_delta = abs(delta)
                    if absolute_delta <= self._max_skew_ns and (
                        candidate_skew is None or absolute_delta < candidate_skew
                    ):
                        candidate_index = index
                        candidate_skew = absolute_delta

                expired = watermark - sagittal_ns >= self._max_skew_ns
                if candidate_index is not None and (has_future_front or expired):
                    self._sagittal.popleft()
                    frontal = self._front[candidate_index]
                    del self._front[candidate_index]
                    skew_ms = float(candidate_skew) / 1_000_000.0
                    self._paired += 1
                    self._recent_results.append(True)
                    self._skews.append(skew_ms)
                    self._last_pair_wall = time.time()
                    outputs.append({
                        "kind": "paired",
                        "sagittal": sagittal,
                        "frontal": frontal,
                        "syncErrorMs": skew_ms,
                    })
                    continue
                if expired:
                    self._sagittal.popleft()
                    self._fallback += 1
                    self._recent_results.append(False)
                    outputs.append({"kind": "fallback", "sagittal": sagittal})
                    continue
                break
        return outputs

    def status(self) -> dict[str, Any]:
        with self._lock:
            last_skew = self._skews[-1] if self._skews else None
            mean_skew = sum(self._skews) / len(self._skews) if self._skews else None
            paired = self._paired
            fallback = self._fallback
            recent_results = list(self._recent_results)
            last_pair_wall = self._last_pair_wall
        recent_paired = sum(recent_results)
        recent_fallback = len(recent_results) - recent_paired
        return {
            "enabled": True,
            "synchronized": bool(last_pair_wall and time.time() - last_pair_wall < 1.5),
            "toleranceMs": self.max_skew_ms,
            "lastErrorMs": round(last_skew, 2) if last_skew is not None else None,
            "meanErrorMs": round(mean_skew, 2) if mean_skew is not None else None,
            "pairedSamples": paired,
            "fallbackSamples": fallback,
            "recentPairedSamples": recent_paired,
            "recentFallbackSamples": recent_fallback,
            "recentPairRatio": round(
                recent_paired / max(1, len(recent_results)), 3
            ),
        }
