"""Quality checks for 2D gait-pose data.

The thresholds are screening guards for camera-demo data quality, not clinical
reference ranges or diagnostic criteria.
"""

from __future__ import annotations

from collections import Counter
import math
from typing import Any, Iterable, Mapping


# MediaPipe's visibility is a model confidence, not a calibrated probability.
# Requiring 0.80 on every moving joint discarded too many valid frames during
# ordinary brisk walking.  Keep a stricter 0.70 gate for the near/target leg
# and the standard 0.50 gate for the remaining bilateral comparison points.
VISIBILITY_THRESHOLD = 0.50
TARGET_LEG_VISIBILITY_THRESHOLD = 0.70
MIN_SAMPLES_FOR_QUALITY = 18
MIN_CYCLES_FOR_RELIABLE_ANALYSIS = 2
MIN_BODY_HEIGHT_RATIO = 0.42
FRAME_MARGIN = 0.015
MIN_BILATERAL_LEG_SEPARATION = 0.018

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
TEMPORAL_RATE_LIMITS_DEG_PER_SEC = {
    "left_knee": 650.0,
    "right_knee": 650.0,
    "left_hip": 450.0,
    "right_hip": 450.0,
    "pelvic_tilt": 300.0,
    "trunk_tilt": 300.0,
}


def assess_temporal_consistency(
    sample: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    dt_seconds: float,
) -> dict[str, Any]:
    """Reject isolated landmark jumps without smoothing away genuine peaks."""
    dt = float(dt_seconds)
    jumps: list[str] = []
    if previous is not None and 0.02 <= dt <= 0.5:
        for name, limit in TEMPORAL_RATE_LIMITS_DEG_PER_SEC.items():
            if name not in sample or name not in previous:
                continue
            try:
                current = float(sample[name])
                prior = float(previous[name])
            except (TypeError, ValueError):
                jumps.append(name)
                continue
            if (
                not math.isfinite(current)
                or not math.isfinite(prior)
                or abs(current - prior) / dt > limit
            ):
                jumps.append(name)
    return {
        "temporalReliable": not jumps,
        "temporalJumpAngles": jumps,
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
    "body_out_of_frame": (
        "Toàn thân chưa nằm gọn trong khung hình hoặc người đang đứng quá xa camera."
    ),
    "temporal_pose_jump": (
        "Landmark hoặc góc khớp thay đổi đột ngột vượt quá vận tốc sinh học hợp lý."
    ),
    "leg_identity_ambiguous": (
        "Hai chân đang chồng hình nên mô hình chưa phân biệt ổn định chân trái–phải."
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
        "hông–gối–cổ chân từ 0,70 trở lên."
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
    "body_out_of_frame": (
        "Lùi camera hoặc điều chỉnh độ cao để thấy trọn vai, hông, gối và hai cổ chân; "
        "chiều cao cơ thể nên chiếm ít nhất 42% khung hình."
    ),
    "temporal_pose_jump": (
        "Tăng ánh sáng, tránh quần áo che chân và giữ camera cố định; frame nhảy sẽ "
        "bị loại khỏi biểu đồ thay vì làm lệch đường cong."
    ),
    "leg_identity_ambiguous": (
        "Quay đúng mặt phẳng dọc, đặt chân cần đo gần camera và không để hai chân "
        "chồng kín nhau; các frame mơ hồ sẽ được loại khỏi đường cong."
    ),
}


def assess_pose_sample(
    sample: Mapping[str, Any],
    visibility: Mapping[str, float],
    *,
    target_side: str | None = None,
    landmark_positions: Mapping[str, Mapping[str, float]] | None = None,
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
    framing_reliable = True
    body_height_ratio = None
    leg_identity_reliable = True
    leg_pair_separation = None
    if landmark_positions:
        points = []
        for name in visibility:
            item = landmark_positions.get(name)
            if not isinstance(item, Mapping):
                framing_reliable = False
                continue
            try:
                x = float(item["x"])
                y = float(item["y"])
            except (KeyError, TypeError, ValueError):
                framing_reliable = False
                continue
            points.append((x, y))
            if not (
                FRAME_MARGIN <= x <= 1.0 - FRAME_MARGIN
                and FRAME_MARGIN <= y <= 1.0 - FRAME_MARGIN
            ):
                framing_reliable = False
        if points:
            body_height_ratio = max(y for _, y in points) - min(y for _, y in points)
            framing_reliable = (
                framing_reliable and body_height_ratio >= MIN_BODY_HEIGHT_RATIO
            )
        else:
            framing_reliable = False
        try:
            left_knee = landmark_positions["left_knee"]
            right_knee = landmark_positions["right_knee"]
            left_ankle = landmark_positions["left_ankle"]
            right_ankle = landmark_positions["right_ankle"]
            knee_separation = math.hypot(
                float(left_knee["x"]) - float(right_knee["x"]),
                float(left_knee["y"]) - float(right_knee["y"]),
            )
            ankle_separation = math.hypot(
                float(left_ankle["x"]) - float(right_ankle["x"]),
                float(left_ankle["y"]) - float(right_ankle["y"]),
            )
            leg_pair_separation = min(knee_separation, ankle_separation)
            # Reject only near-complete overlap at both joints. Brief ordinary
            # crossings remain valid when either knee or ankle stays distinct.
            leg_identity_reliable = not (
                knee_separation < MIN_BILATERAL_LEG_SEPARATION
                and ankle_separation < MIN_BILATERAL_LEG_SEPARATION
            )
        except (KeyError, TypeError, ValueError):
            leg_identity_reliable = False
    return {
        # Keep the underlying confidences so downstream gait processing can
        # validate each leg independently. Rejecting a whole sagittal frame
        # when only the far leg is briefly weak creates long holes and flat,
        # interpolated plateaus in the otherwise visible leg's curve.
        "landmarkVisibility": {
            str(name): round(float(value), 4)
            for name, value in visibility.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        },
        "meanVisibility": mean_visibility,
        "lowLandmarks": low_landmarks,
        "targetSide": normalized_target or None,
        "targetVisibilityThreshold": TARGET_LEG_VISIBILITY_THRESHOLD,
        "lowTargetLandmarks": low_target_landmarks,
        "targetLegReliable": (
            not low_target_landmarks
            and target_angle_reliable
            and leg_identity_reliable
        ),
        "legIdentityReliable": leg_identity_reliable,
        "legPairSeparation": (
            round(leg_pair_separation, 4)
            if leg_pair_separation is not None
            else None
        ),
        "bodyInFrame": framing_reliable,
        "bodyHeightRatio": (
            round(body_height_ratio, 3) if body_height_ratio is not None else None
        ),
        # Bilateral comparison must never accept a frame merely because the
        # prosthetic-side landmarks are visible. Both legs and the trunk need
        # to be reliable, otherwise the healthy-side curve can jump wildly
        # during an occlusion or landmark identity swap.
        "bilateralSagittalReliable": (
            not low_landmarks
            and not out_of_range
            and framing_reliable
            and leg_identity_reliable
        ),
        "outOfRangeAngles": out_of_range,
        "frameReliable": (
            not low_landmarks
            and not low_target_landmarks
            and not out_of_range
            and framing_reliable
            and leg_identity_reliable
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
    framing_error_frames = 0
    temporal_jump_frames = 0
    ambiguous_leg_frames = 0
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
        if item.get("bodyInFrame") is False:
            framing_error_frames += 1
        if item.get("temporalReliable") is False:
            temporal_jump_frames += 1
        if item.get("legIdentityReliable") is False:
            ambiguous_leg_frames += 1

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
    if framing_error_frames / denominator >= 0.15:
        reasons.append("body_out_of_frame")
    if temporal_jump_frames / denominator >= 0.10:
        reasons.append("temporal_pose_jump")
    if ambiguous_leg_frames / denominator >= 0.10:
        reasons.append("leg_identity_ambiguous")

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
