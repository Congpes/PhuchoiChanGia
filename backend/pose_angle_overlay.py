"""Small, frame-local 2D flexion labels. Never used as analysis input."""

import math
from dataclasses import dataclass

import cv2

from algorithms import calculate_angle
from camera_fusion import (
    hip_flexion_from_body_axis, sagittal_trunk_frame_angle,
    normalize_sagittal_trunk_lean,
)
from pose_quality import TARGET_LEG_VISIBILITY_THRESHOLD


@dataclass(frozen=True)
class JointAngleLabel:
    name: str
    anchor: tuple[int, int]
    value: float | None


def frontal_trunk_label(landmarks, width, height):
    """Frame-local coronal lean; positive is anatomical right, in pixel space."""
    points = []
    for name in ('left_shoulder', 'right_shoulder', 'left_hip', 'right_hip'):
        item = landmarks.get(name) or {}
        try:
            x, y, visibility = (float(item[k]) for k in ('x', 'y', 'visibility'))
        except (KeyError, TypeError, ValueError):
            return None
        if not all(math.isfinite(v) for v in (x, y, visibility)):
            return None
        if not (0 <= x <= 1 and 0 <= y <= 1 and visibility >= .40):
            return None
        points.append((x * width, y * height, visibility))
    ls, rs, lh, rh = points
    shoulder = ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2)
    hip = ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2)
    value = None
    if (min(p[2] for p in points) >= TARGET_LEG_VISIBILITY_THRESHOLD
            and 2 <= math.dist(shoulder, hip) <= height * .48
            and hip[1] > shoulder[1]
            and abs(rs[0] - ls[0]) >= 2):
        angle = math.degrees(math.atan2(shoulder[0] - hip[0], hip[1] - shoulder[1]))
        value = angle * (1 if rs[0] >= ls[0] else -1)
    return JointAngleLabel('trunk_lateral', (round(max(ls[0], rs[0], lh[0], rh[0])),
        round((shoulder[1] + hip[1]) / 2)), value)


def draw_frontal_trunk_label(frame, landmarks):
    """Floating NT label, display only; no guessed or held measurements."""
    height, width = frame.shape[:2]
    label = frontal_trunk_label(landmarks, width, height)
    _draw_trunk_label(frame, label, 'NT')


def sagittal_trunk_label(landmarks, width, height):
    """Forward-positive 2D lean, using reliable torso axes and facing cues."""
    def point(name, threshold=TARGET_LEG_VISIBILITY_THRESHOLD):
        item = landmarks.get(name) or {}
        try:
            x, y, visibility = (float(item[k]) for k in ('x', 'y', 'visibility'))
        except (KeyError, TypeError, ValueError):
            return None
        if (not all(math.isfinite(v) for v in (x, y, visibility))
                or not (0 <= x <= 1 and 0 <= y <= 1 and visibility >= threshold)):
            return None
        return (x * width, y * height)

    axes = {}
    for side in ('left', 'right'):
        shoulder, hip = point(f'{side}_shoulder'), point(f'{side}_hip')
        if (shoulder is not None and hip is not None
                and hip[1] > shoulder[1]
                and 2 <= math.dist(shoulder, hip) <= height * .48):
            axes[side] = (shoulder, hip, min(
                float(landmarks[f'{side}_{joint}']['visibility'])
                for joint in ('shoulder', 'hip')))
    if not axes:
        return None
    fallback = next(iter(axes.values()))
    ls, lh, lv = axes.get('left', (fallback[0], fallback[1], 0))
    rs, rh, rv = axes.get('right', (fallback[0], fallback[1], 0))
    frame_angle, _ = sagittal_trunk_frame_angle(
        ls, rs, lh, rh, left_visibility=lv, right_visibility=rv)
    shoulders = [axis[0] for axis in axes.values()]
    hips = [axis[1] for axis in axes.values()]
    shoulder_mid = tuple(sum(p[i] for p in shoulders) / len(shoulders) for i in (0, 1))
    hip_mid = tuple(sum(p[i] for p in hips) / len(hips) for i in (0, 1))
    cues = {}
    directions = []
    for side in ('left', 'right'):
        heel, toe = point(f'{side}_heel'), point(f'{side}_foot_index')
        if heel is None or toe is None or abs(toe[0] - heel[0]) < 2:
            heel = toe = None
        else:
            directions.append(toe[0] - heel[0])
        cues[f'{side}_heel'], cues[f'{side}_toe'] = heel, toe
    nose = point('nose')
    if nose is not None and abs(nose[0] - shoulder_mid[0]) < 2:
        nose = None
    value = None
    foot_agrees = directions and (all(d > 0 for d in directions) or all(d < 0 for d in directions))
    # Withhold the sign when facing is ambiguous, rather than use frame-right.
    if foot_agrees or nose is not None:
        value, _, _ = normalize_sagittal_trunk_lean(
            frame_angle, **cues, nose=nose, mid_shoulder=shoulder_mid)
    return JointAngleLabel('trunk_sagittal', (
        round(max(p[0] for p in shoulders + hips)),
        round(shoulder_mid[1] + .3 * (hip_mid[1] - shoulder_mid[1]))), value)


def draw_sagittal_trunk_label(frame, landmarks):
    height, width = frame.shape[:2]
    _draw_trunk_label(frame, sagittal_trunk_label(landmarks, width, height), 'NTS')


def _draw_trunk_label(frame, label, prefix):
    height, width = frame.shape[:2]
    if label is None:
        return
    scale = max(.42, min(.72, height / 1000.0))
    number = '--' if label.value is None else f'{label.value:+.1f}'
    text = f'{prefix} {number}'
    (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x = max(4, min(width - tw - 12, label.anchor[0] + 12))
    y = max(th + 4, min(height - baseline - 4, label.anchor[1]))
    color = (100, 230, 80) if label.value is not None else (175, 175, 175)
    for ink, thickness in (((20, 26, 34), 3), (color, 1)):
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    ink, thickness, cv2.LINE_AA)
        if label.value is not None:
            cv2.circle(frame, (x + tw + 3, y - th + 2), 2, ink, thickness, cv2.LINE_AA)


def pose_frame_matches_source(pose_frame, source_frame_index, timestamp):
    """Exact source index, or rounded timestamp for pre-index archives."""
    if 'sourceFrameIndex' in pose_frame:
        return pose_frame['sourceFrameIndex'] == source_frame_index
    return abs(float(pose_frame['time']) - timestamp) <= 0.001


def joint_angle_labels(landmarks, width, height, sample=None, *, knee_only=False):
    """Use pixel aspect ratio and the same knee/hip definitions as live Scan.

    Numbers are withheld independently per joint when any required landmark is
    hidden, outside the image, non-finite, or forms a degenerate segment. This
    does not change pose detection, skeleton visibility, or saved measurements.
    """
    def point(name, threshold=TARGET_LEG_VISIBILITY_THRESHOLD):
        item = landmarks.get(name) or {}
        try:
            x, y, visibility = (float(item[k]) for k in ('x', 'y', 'visibility'))
        except (KeyError, TypeError, ValueError):
            return None
        if not all(math.isfinite(v) for v in (x, y, visibility)):
            return None
        if not (0 <= x <= 1 and 0 <= y <= 1 and visibility >= threshold):
            return None
        return (x * width, y * height)

    labels = []
    for side in ('left', 'right'):
        for joint in (('knee',) if knee_only else ('hip', 'knee')):
            name = f'{side}_{joint}'
            anchor = point(name, threshold=0.40)
            if anchor is None:
                continue
            names = (
                (f'{side}_hip', f'{side}_knee', f'{side}_ankle')
                if joint == 'knee' else
                ('left_shoulder', 'right_shoulder', 'left_hip', 'right_hip',
                 f'{side}_knee', f'{side}_hip')
            )
            points = [point(key) for key in names]
            value = None
            if all(p is not None for p in points):
                if joint == 'knee':
                    a, b, c = points
                    # A close-up leg can occupy most of the image. The old
                    # full-body segment-size cap incorrectly hid its knee.
                    # Keep the in-frame/visibility/degeneracy gates above.
                    valid = all(2.0 <= distance <= math.hypot(width, height) for distance in
                                (math.dist(a, b), math.dist(b, c)))
                    calculated = 180.0 - calculate_angle(a, b, c) if valid else None
                else:
                    ls, rs, lh, rh, knee, hip = points
                    shoulder_mid = ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2)
                    hip_mid = ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2)
                    valid = all(2.0 <= distance <= height * 0.48 for distance in
                                (math.dist(shoulder_mid, hip_mid), math.dist(knee, hip)))
                    calculated = hip_flexion_from_body_axis(*points) if valid else None
                # Live uses the actual, unfiltered sample from this exact frame;
                # replay recomputes from its corresponding stored landmarks.
                candidate = sample.get(name) if sample is not None else calculated
                try:
                    candidate = float(candidate)
                    if valid and math.isfinite(candidate) and 0 <= candidate <= 180:
                        value = candidate
                except (TypeError, ValueError):
                    pass
            labels.append(JointAngleLabel(name, (round(anchor[0]), round(anchor[1])), value))
    return labels


def draw_joint_angle_labels(frame, landmarks, sample=None, *, knee_only=False,
                           draw_knee_segments=False):
    """Draw compact floating HT/HP/GT/GP labels without leader lines."""
    height, width = frame.shape[:2]
    scale = max(0.42, min(0.72, height / 1000.0))
    padding, gap = 4, 12
    occupied = []
    for label in joint_angle_labels(landmarks, width, height, sample, knee_only=knee_only):
        left = label.name.startswith('left_')
        joint = 'H' if label.name.endswith('_hip') else 'G'
        number = '--' if label.value is None else f'{label.value:.1f}'
        text = f"{joint}{'T' if left else 'P'} {number}"
        color = (255, 170, 30) if left else (20, 220, 255)
        if label.value is None:
            color = (175, 175, 175)
        elif draw_knee_segments and label.name.endswith('_knee'):
            side = 'left' if left else 'right'
            points = [landmarks[f'{side}_{name}'] for name in ('hip', 'knee', 'ankle')]
            points = [(round(p['x'] * width), round(p['y'] * height)) for p in points]
            for a, b in zip(points, points[1:]):
                cv2.line(frame, a, b, color, 2, cv2.LINE_AA)
            for point in points:
                cv2.circle(frame, point, 4, color, -1, cv2.LINE_AA)
        (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        degree_space = 7 if label.value is not None else 0
        box_w, box_h = tw + degree_space + 2 * padding, th + baseline + 2 * padding
        ax, ay = label.anchor
        x = ax - gap - box_w if left else ax + gap
        x = max(1, min(width - box_w - 1, x))
        y = max(1, min(height - box_h - 1, ay - box_h // 2))
        # Near the frame edge, clamping can place both sides in the same area.
        for _ in range(8):
            collision = next((r for r in occupied if
                x < r[2] + 2 and x + box_w + 2 > r[0] and
                y < r[3] + 2 and y + box_h + 2 > r[1]), None)
            if collision is None:
                break
            y = collision[3] + 3
            if y + box_h >= height:
                y = max(1, collision[1] - box_h - 3)
        occupied.append((x, y, x + box_w, y + box_h))
        origin = (x + padding, y + padding + th)
        # A thin dark outline keeps floating text readable on either clothing
        # or bright backgrounds without covering the video with filled boxes.
        cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, (20, 26, 34), 3, cv2.LINE_AA)
        cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)
        if label.value is not None:
            # Hershey fonts do not contain Unicode degree glyphs.
            degree = (origin[0] + tw + 3, origin[1] - th + 2)
            cv2.circle(frame, degree, 2, (20, 26, 34), 3, cv2.LINE_AA)
            cv2.circle(frame, degree, 2, color, 1, cv2.LINE_AA)
