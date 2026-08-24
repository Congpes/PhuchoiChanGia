"""Quality checks for 2D gait-pose data.

The thresholds are screening guards for camera-demo data quality, not clinical
reference ranges or diagnostic criteria.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


VISIBILITY_THRESHOLD = 0.55
TARGET_LEG_VISIBILITY_THRESHOLD = 0.80
MIN_SAMPLES_FOR_QUALITY = 18
MIN_CYCLES_FOR_RELIABLE_ANALYSIS = 2

# Conservative guardrails for 2D flexion during ordinary walking. Values outside
# these ranges remain visible but are flagged because they often indicate a bad
# camera plane, occlusion or a mistaken landmark.
ANGLE_LIMITS = {
    "left_knee": (0.0, 135.0),
    "right_knee": (0.0, 135.0),
    "left_hip": (0.0, 100.0),
    "right_hip": (0.0, 100.0),
    "trunk_tilt": (-45.0, 45.0),
}

REASON_TEXT = {
    "pose_not_detected": "Camera chưa nhận diện được pose mặt phẳng dọc ổn định.",
    "insufficient_samples": "Chưa có đủ mẫu pose liên tiếp để đánh giá ổn định.",
    "landmark_occluded": "Một hoặc nhiều landmark trọng yếu bị che khuất hoặc theo dõi kém.",
    "target_leg_landmark_occluded": (
        "Hông–gối–cổ chân của chân giả chưa đủ rõ để đo góc chính xác."
    ),
    "angle_out_of_screening_range": "Có góc gập vượt ngưỡng kiểm tra của mô hình 2D.",
    "insufficient_cycles": "Chưa có đủ hai chu kỳ hợp lệ liên tiếp để phân tích dáng đi.",
    "cross_camera_unsynchronized": (
        "Hai camera chưa ghép được các khung hình cùng thời điểm ổn định."
    ),
    "camera_roles_misaligned": (
        "Góc đặt camera chính diện và camera mặt phẳng dọc chưa đúng vai trò."
    ),
    "stereo_reprojection_error": (
        "Sai số chiếu ngược stereo đang cao nên góc 3D không được sử dụng."
    ),
}

GUIDANCE_TEXT = {
    "pose_not_detected": (
        "Đặt camera mặt phẳng dọc, lùi máy để thấy liên tục từ vai đến "
        "mũi bàn chân và tăng ánh sáng."
    ),
    "insufficient_samples": "Giữ người đi trong khung hình và đi liên tục thêm ít nhất 2–3 chu kỳ.",
    "landmark_occluded": (
        "Không để tay, quần áo rộng hoặc vật thể che hông–gối–cổ chân; "
        "đi ngang qua camera, không đi chéo vào ống kính."
    ),
    "target_leg_landmark_occluded": (
        "Đặt chân giả phía gần camera mặt phẳng dọc và giữ visibility "
        "hông–gối–cổ chân từ 0,80 trở lên."
    ),
    "angle_out_of_screening_range": (
        "Đặt camera ngang tầm hông, cố định máy, giữ trục quang vuông góc "
        "mặt phẳng đi và kiểm tra lại skeleton trước khi ghi."
    ),
    "insufficient_cycles": (
        "Bắt đầu ghi trước khi bước đi và giữ chuyển động liên tục tối thiểu "
        "2–3 chu kỳ hoàn chỉnh."
    ),
    "cross_camera_unsynchronized": (
        "Đóng ứng dụng khác đang dùng camera, dùng cùng mức 30 FPS và giữ "
        "sai lệch đồng bộ dưới ngưỡng hiển thị."
    ),
    "camera_roles_misaligned": (
        "Đặt camera chính diện vuông góc hướng đi và camera dọc vuông góc "
        "bên hông; dùng nút Đảo cam nếu chọn nhầm."
    ),
    "stereo_reprojection_error": (
        "Kiểm tra hai camera không bị xê dịch sau hiệu chuẩn; nếu đã xê "
        "dịch, chụp lại bảng ChArUco và hiệu chuẩn lại."
    ),
}


def assess_pose_sample(
    sample: Mapping[str, Any],
    visibility: Mapping[str, float],
    *,
    target_side: str | None = None,
) -> dict[str, Any]:
    """Assess one frame while preserving the underlying values for display."""
    normalized_target = str(target_side or "").strip().lower()
    if normalized_target not in ("left", "right"):
        normalized_target = ""
    low_landmarks = sorted(
        name
        for name, value in visibility.items()
        if float(value) < VISIBILITY_THRESHOLD
    )
    target_landmarks = (
        [
            f"{normalized_target}_hip",
            f"{normalized_target}_knee",
            f"{normalized_target}_ankle",
        ]
        if normalized_target
        else []
    )
    low_target_landmarks = sorted(
        name
        for name in target_landmarks
        if float(visibility.get(name, 0.0)) < TARGET_LEG_VISIBILITY_THRESHOLD
    )
    visibility_values = [float(value) for value in visibility.values()]
    mean_visibility = (
        round(sum(visibility_values) / len(visibility_values), 3)
        if visibility_values
        else 0.0
    )

    out_of_range = sorted(
        name
        for name, (lower, upper) in ANGLE_LIMITS.items()
        if name in sample
        and (
            not isinstance(sample[name], (int, float))
            or float(sample[name]) < lower
            or float(sample[name]) > upper
        )
    )

    target_angle_name = f"{normalized_target}_knee" if normalized_target else ""
    target_angle_reliable = target_angle_name not in out_of_range
    return {
        "meanVisibility": mean_visibility,
        "lowLandmarks": low_landmarks,
        "targetSide": normalized_target or None,
        "targetVisibilityThreshold": TARGET_LEG_VISIBILITY_THRESHOLD,
        "lowTargetLandmarks": low_target_landmarks,
        "targetLegReliable": not low_target_landmarks and target_angle_reliable,
        "outOfRangeAngles": out_of_range,
        "frameReliable": (
            not low_landmarks and not low_target_landmarks and not out_of_range
        ),
    }


def summarize_pose_quality(
    quality_samples: Iterable[Mapping[str, Any]],
    *,
    pose_detected: bool,
    sample_count: int,
    cycle_count: int,
) -> dict[str, Any]:
    """Return a UI-ready quality status without discarding any gait curve."""
    samples = [dict(item) for item in quality_samples if isinstance(item, Mapping)]
    reasons: list[str] = []
    if not pose_detected:
        reasons.append("pose_not_detected")
    if sample_count < MIN_SAMPLES_FOR_QUALITY:
        reasons.append("insufficient_samples")

    low_landmark_counter: Counter[str] = Counter()
    low_target_counter: Counter[str] = Counter()
    angle_counter: Counter[str] = Counter()
    unreliable_frames = 0
    unsynchronized_frames = 0
    implausible_role_frames = 0
    stereo_error_frames = 0
    for item in samples:
        low_landmark_counter.update(item.get("lowLandmarks", []))
        low_target_counter.update(item.get("lowTargetLandmarks", []))
        angle_counter.update(item.get("outOfRangeAngles", []))
        if not item.get("frameReliable", False):
            unreliable_frames += 1
        if (
            item.get("crossViewSynchronized") is False
            and item.get("measurementMethod") == "sagittal_only_2d"
        ):
            unsynchronized_frames += 1
        if item.get("cameraRolesPlausible") is False:
            implausible_role_frames += 1
        if (
            item.get("stereoReprojectionReliable") is False
            or item.get("stereoGeometryReliable") is False
        ):
            stereo_error_frames += 1

    denominator = max(1, len(samples))
    if low_landmark_counter and sum(low_landmark_counter.values()) / denominator >= 0.15:
        reasons.append("landmark_occluded")
    if low_target_counter and sum(low_target_counter.values()) / denominator >= 0.15:
        reasons.append("target_leg_landmark_occluded")
    if angle_counter and sum(angle_counter.values()) / denominator >= 0.10:
        reasons.append("angle_out_of_screening_range")
    if cycle_count < MIN_CYCLES_FOR_RELIABLE_ANALYSIS:
        reasons.append("insufficient_cycles")
    if unsynchronized_frames / denominator >= 0.15:
        reasons.append("cross_camera_unsynchronized")
    if implausible_role_frames / denominator >= 0.5:
        reasons.append("camera_roles_misaligned")
    if stereo_error_frames / denominator >= 0.15:
        reasons.append("stereo_reprojection_error")

    reasons = list(dict.fromkeys(reasons))
    status = "reliable" if not reasons else "unreliable"
    return {
        "status": status,
        "label": (
            "Dữ liệu camera đáng tin cậy"
            if status == "reliable"
            else "Dữ liệu camera chưa tin cậy"
        ),
        "reasons": reasons,
        "reasonTexts": [REASON_TEXT[reason] for reason in reasons],
        "guidance": [GUIDANCE_TEXT[reason] for reason in reasons],
        "sampleCount": int(sample_count),
        "cycleCount": int(cycle_count),
        "meanVisibility": round(
            sum(float(item.get("meanVisibility", 0.0)) for item in samples) / denominator,
            3,
        ) if samples else None,
        "unreliableFrameRate": round(unreliable_frames / denominator, 3) if samples else None,
        "lowLandmarks": [name for name, _ in low_landmark_counter.most_common()],
        "lowTargetLandmarks": [
            name for name, _ in low_target_counter.most_common()
        ],
        "outOfRangeAngles": [name for name, _ in angle_counter.most_common()],
        "note": (
            "Ngưỡng này là kiểm tra chất lượng dữ liệu camera 2D, không phải "
            "tiêu chuẩn chẩn đoán lâm sàng."
        ),
    }
