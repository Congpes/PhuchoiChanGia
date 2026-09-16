"""Normalize camera joint signals into FSR-synchronized gait cycles."""

from __future__ import annotations

from typing import Dict, Iterable, List

import numpy as np
from step_events import (
    camera_step_intervals as _camera_step_intervals,
    pair_step_intervals as _pair_camera_intervals,
)


METRICS = ("knee", "hip", "trunk", "lateral_trunk")
REQUIRED_METRICS = ("knee",)


def estimate_step_motion_signals(samples: List[dict]) -> dict:
    """Build scale-free foot-lift and ankle-reach signals for step detection.

    Joint-angle-only segmentation misses ordinary shallow steps and becomes
    brittle when one knee landmark is briefly occluded. The heel/toe height
    and ankle position relative to the hip provide two independent cues. All
    distances are divided by observed leg length, so calibration is not needed.
    """
    output: dict[str, list[float]] = {}
    for side in ("left", "right"):
        raw_reach: list[float] = []
        raw_foot_y: list[float] = []
        for sample in samples:
            tracking = sample.get("footTracking", {})
            side_data = tracking.get(side, {}) if isinstance(tracking, dict) else {}
            hip = _point(side_data, "hip", min_visibility=0.35)
            knee = _point(side_data, "knee", min_visibility=0.35)
            ankle = _point(side_data, "ankle", min_visibility=0.35)
            heel = _point(side_data, "heel", min_visibility=0.30)
            toe = _point(side_data, "toe", min_visibility=0.30)
            if hip is None or knee is None or ankle is None:
                raw_reach.append(float("nan"))
                raw_foot_y.append(float("nan"))
                continue
            leg_px = float(np.linalg.norm(hip - knee) + np.linalg.norm(knee - ankle))
            if leg_px <= 20.0:
                raw_reach.append(float("nan"))
                raw_foot_y.append(float("nan"))
                continue
            raw_reach.append(float((ankle[0] - hip[0]) / leg_px))
            foot_points = [point for point in (heel, toe, ankle) if point is not None]
            raw_foot_y.append(
                float((max(point[1] for point in foot_points) - hip[1]) / leg_px)
                if foot_points else float("nan")
            )

        output[f"{side}_ankle_reach"] = raw_reach
        ground_history = []
        lift = []
        for index, value in enumerate(raw_foot_y):
            timestamp = float(samples[index].get('time', index / 30.0))
            ground_history = [(t, y) for t, y in ground_history if timestamp - t <= 1.5]
            if not np.isfinite(value):
                lift.append(float('nan'))
                continue
            ground_history.append((timestamp, value))
            lift.append(max(0.0, max(y for _, y in ground_history) - value))
        output[f"{side}_foot_lift"] = lift
    return output


def _point(side_data: dict, name: str, min_visibility: float = 0.65):
    item = side_data.get(name) if isinstance(side_data, dict) else None
    if not isinstance(item, dict):
        return None
    try:
        x = float(item["x"])
        y = float(item["y"])
        visibility = float(item.get("visibility", 0.0))
    except (KeyError, TypeError, ValueError):
        return None
    if visibility < min_visibility or not np.isfinite([x, y]).all():
        return None
    return np.asarray([x, y], dtype=float)


def estimate_foot_clearance_signals(
    samples: List[dict],
    *,
    left_leg_length_cm: float | None,
    right_leg_length_cm: float | None,
) -> dict:
    """Convert sagittal toe/heel pixels to patient-scaled clearance in cm.

    The scale is estimated independently for each side from the visible
    hip-knee-ankle chain. The ground line is fitted from the lowest reliable
    heel/toe observations across both feet, which also tolerates small camera
    roll. Values remain estimates until a physical calibration object is used.
    """
    lengths = {
        "left": left_leg_length_cm,
        "right": right_leg_length_cm,
    }
    ground_points = []
    for sample in samples:
        tracking = sample.get("footTracking", {})
        for side in ("left", "right"):
            side_data = tracking.get(side, {}) if isinstance(tracking, dict) else {}
            for name in ("heel", "toe"):
                point = _point(side_data, name)
                if point is not None:
                    ground_points.append(point)

    if len(ground_points) < 8:
        return {
            "available": False,
            "reason": "insufficient_foot_landmarks",
            "signals": {},
        }
    points = np.asarray(ground_points, dtype=float)
    bottom_threshold = float(np.percentile(points[:, 1], 75))
    ground = points[points[:, 1] >= bottom_threshold]
    if len(ground) >= 4 and float(np.ptp(ground[:, 0])) >= 20.0:
        slope, intercept = np.polyfit(ground[:, 0], ground[:, 1], 1)
        slope = float(np.clip(slope, -0.25, 0.25))
        intercept = float(np.median(ground[:, 1] - slope * ground[:, 0]))
    else:
        slope = 0.0
        intercept = float(np.median(ground[:, 1]))
    denominator = float(np.sqrt(slope * slope + 1.0))

    output = {}
    calibration = {
        "method": "patient_leg_length_pixel_scale",
        "groundLine": {"slope": round(slope, 6), "interceptPx": round(intercept, 3)},
        "estimated": True,
    }
    available_sides = 0
    for side in ("left", "right"):
        actual_length = lengths[side]
        observed_lengths = []
        for sample in samples:
            tracking = sample.get("footTracking", {})
            side_data = tracking.get(side, {}) if isinstance(tracking, dict) else {}
            hip = _point(side_data, "hip")
            knee = _point(side_data, "knee")
            ankle = _point(side_data, "ankle")
            if hip is None or knee is None or ankle is None:
                continue
            pixels = float(np.linalg.norm(hip - knee) + np.linalg.norm(knee - ankle))
            if pixels > 20.0:
                observed_lengths.append(pixels)
        valid_length = (
            actual_length is not None
            and np.isfinite(float(actual_length))
            and 20.0 <= float(actual_length) <= 150.0
            and bool(observed_lengths)
        )
        if not valid_length:
            calibration[side] = {"available": False, "reason": "missing_leg_length"}
            output[f"{side}_foot_clearance_cm"] = [float("nan")] * len(samples)
            output[f"{side}_toe_clearance_cm"] = [float("nan")] * len(samples)
            continue
        observed_px = float(np.median(observed_lengths))
        cm_per_px = float(actual_length) / observed_px
        calibration[side] = {
            "available": True,
            "legLengthCm": round(float(actual_length), 2),
            "observedLegLengthPx": round(observed_px, 3),
            "cmPerPx": round(cm_per_px, 6),
            "sampleCount": len(observed_lengths),
        }
        available_sides += 1
        foot_values = []
        toe_values = []
        for sample in samples:
            tracking = sample.get("footTracking", {})
            side_data = tracking.get(side, {}) if isinstance(tracking, dict) else {}
            heel = _point(side_data, "heel")
            toe = _point(side_data, "toe")
            def clearance(point):
                if point is None:
                    return float("nan")
                pixels = max(0.0, (slope * point[0] + intercept - point[1]) / denominator)
                return pixels * cm_per_px
            heel_cm = clearance(heel)
            toe_cm = clearance(toe)
            toe_values.append(toe_cm)
            finite = [value for value in (heel_cm, toe_cm) if np.isfinite(value)]
            # The lowest shoe point is the clinically relevant obstacle clearance.
            foot_values.append(min(finite) if finite else float("nan"))
        output[f"{side}_foot_clearance_cm"] = foot_values
        output[f"{side}_toe_clearance_cm"] = toe_values

    return {
        "available": available_sides == 2,
        "reason": "" if available_sides == 2 else "missing_leg_length",
        "signals": output,
        "calibration": calibration,
    }


def _clearance_summary(foot_curve: List[float], toe_curve: List[float], knee_curve: List[float]):
    if not foot_curve or not toe_curve:
        return None
    foot = np.asarray(foot_curve, dtype=float)
    toe = np.asarray(toe_curve, dtype=float)
    knee = np.asarray(knee_curve, dtype=float)
    finite_foot = foot[np.isfinite(foot)]
    if not len(finite_foot):
        return None
    peak = float(np.max(finite_foot))
    threshold = max(0.4, peak * 0.08)
    swing_mask = np.isfinite(toe) & (foot > threshold)
    if len(knee) == len(foot):
        swing_mask &= np.isfinite(knee) & (knee > 8.0)
    swing_toe = toe[swing_mask]
    mtc = float(np.percentile(swing_toe, 15)) if len(swing_toe) >= 3 else None
    return {
        "peakCm": round(peak, 3),
        "mtcCm": round(mtc, 3) if mtc is not None else None,
        "estimated": True,
        "method": "lowest_shoe_peak_and_swing_toe_p15",
    }


def _mean_sd(values: Iterable[float]) -> dict:
    finite = np.asarray(
        [float(value) for value in values if np.isfinite(value)],
        dtype=float,
    )
    if not len(finite):
        return {"mean": None, "sd": None, "n": 0}
    return {
        "mean": round(float(np.mean(finite)), 4),
        "sd": round(
            float(np.std(finite, ddof=1)) if len(finite) > 1 else 0.0,
            4,
        ),
        "n": int(len(finite)),
    }


def _symmetry_percent(left: dict, right: dict) -> float | None:
    left_mean = left.get("mean")
    right_mean = right.get("mean")
    if left_mean is None or right_mean is None:
        return None
    larger = max(abs(float(left_mean)), abs(float(right_mean)))
    if larger <= 1e-9:
        return 100.0
    return round(
        100.0 * min(abs(float(left_mean)), abs(float(right_mean))) / larger,
        2,
    )


def _cycle_statistics(cycles: List[dict]) -> dict:
    """Return report-ready descriptive statistics for paired camera cycles."""
    if not cycles:
        return {}
    statistics = {}
    for metric in ("knee", "hip"):
        result = {}
        for side in ("left", "right"):
            curve_key = {
                "knee": "kneeMeasured",
                "hip": "hipMeasured",
            }.get(metric, metric)
            curves = [
                np.asarray(
                    [point["value"] for point in item[side].get("rawSamples", {}).get(metric, [])]
                    or item[side]["curves"].get(
                        curve_key,
                        item[side]["curves"].get(metric, []),
                    ),
                    dtype=float,
                )
                for item in cycles
            ]
            curves = [curve[np.isfinite(curve)] for curve in curves if len(curve)]
            result[side] = {
                "peak": _mean_sd(float(np.max(curve)) for curve in curves if len(curve)),
                "minimum": _mean_sd(float(np.min(curve)) for curve in curves if len(curve)),
                "rom": _mean_sd(
                    float(np.max(curve) - np.min(curve))
                    for curve in curves
                    if len(curve)
                ),
            }
        result["romSymmetryPercent"] = _symmetry_percent(
            result["left"]["rom"],
            result["right"]["rom"],
        )
        statistics[metric] = result

    lateral = {}
    for side in ("left", "right"):
        curves = [
            np.asarray(
                item[side]["curves"].get(
                    "lateralTrunkMeasured",
                    item[side]["curves"].get("lateral_trunk", []),
                ),
                dtype=float,
            )
            for item in cycles
        ]
        curves = [curve[np.isfinite(curve)] for curve in curves if len(curve)]
        lateral[side] = {
            "meanOffset": _mean_sd(float(np.mean(curve)) for curve in curves if len(curve)),
            "peakAbsolute": _mean_sd(
                float(np.max(np.abs(curve))) for curve in curves if len(curve)
            ),
            "rom": _mean_sd(
                float(np.max(curve) - np.min(curve)) for curve in curves if len(curve)
            ),
        }
    statistics["lateral_trunk"] = lateral

    duration = {
        side: _mean_sd(
            item.get(side, {}).get("duration")
            for item in cycles
            if item.get(side, {}).get("duration") is not None
        )
        for side in ("left", "right")
    }
    duration["symmetryPercent"] = _symmetry_percent(
        duration["left"],
        duration["right"],
    )
    paired_durations = []
    for item in cycles:
        left_duration = item.get("left", {}).get("duration")
        right_duration = item.get("right", {}).get("duration")
        if left_duration is None or right_duration is None:
            continue
        pair_duration = (float(left_duration) + float(right_duration)) / 2.0
        if np.isfinite(pair_duration) and pair_duration > 1e-9:
            paired_durations.append(pair_duration)
    duration["paired"] = _mean_sd(paired_durations)
    paired_mean = duration["paired"].get("mean")
    paired_sd = duration["paired"].get("sd")
    duration["cvPercent"] = (
        round(100.0 * float(paired_sd) / float(paired_mean), 2)
        if paired_mean is not None and paired_sd is not None and paired_mean > 1e-9
        else None
    )
    statistics["cycleDuration"] = duration
    camera_cadences = [
        float(item["cadenceSpm"])
        for item in cycles
        if item.get("cadenceSpm") is not None
        and np.isfinite(float(item["cadenceSpm"]))
    ]
    statistics["cadence"] = (
        _mean_sd(camera_cadences)
        if camera_cadences
        else _mean_sd(
            120.0 / (float(b[side]['end']) - float(a[side]['end']))
            for a, b in zip(cycles, cycles[1:]) for side in ('left', 'right')
            if 0.3 <= float(b[side]['end']) - float(a[side]['end']) <= 4.0
        )
    )
    if camera_cadences:
        statistics["contralateralStepGap"] = _mean_sd(
            float(item["contralateralStepGap"])
            for item in cycles
            if item.get("contralateralStepGap") is not None
        )
    return statistics




def _normalized_interval(
    timestamps: Iterable[float],
    values: Iterable[float],
    start: float,
    end: float,
    target_len: int = 101,
    preserve_peak: bool = False,
) -> List[float]:
    points = [
        (float(timestamp), float(value))
        for timestamp, value in zip(timestamps, values)
        if start <= float(timestamp) <= end and np.isfinite(value)
    ]
    # Three sparse points are mathematically interpolatable but not enough to
    # describe a clinical gait curve; they produced the long flat roofs seen
    # when one leg was briefly occluded. Require temporal coverage and density
    # before drawing rather than fabricating the missing movement.
    if len(points) < 4 or end <= start:
        return []
    points.sort(key=lambda point: point[0])
    x = np.asarray([item[0] for item in points], dtype=float)
    y = np.asarray([item[1] for item in points], dtype=float)
    _, reverse_indices = np.unique(x[::-1], return_index=True)
    keep = np.sort(len(x) - 1 - reverse_indices)
    x, y = x[keep], y[keep]
    if len(x) < 4:
        return []
    duration = float(end - start)
    if float(x[-1] - x[0]) < 0.70 * duration:
        return []
    if float(np.max(np.diff(x))) > max(0.25, 0.30 * duration):
        return []
    target = np.linspace(start, end, target_len)
    normalized = np.interp(target, x, y)
    return normalized.round(4).tolist()




def build_gait_cycles(
    timestamps: Iterable[float],
    signals: Dict[str, Iterable[float]],
    anchors: List[dict],
    *,
    window_size: int,
    min_cycle_seconds: float = 0.45,
    max_cycle_seconds: float = 2.5,
) -> List[dict]:
    """Build camera curves between consecutive, measured FSR contacts.

    Each side keeps its own contact-onset boundaries.  In particular, the
    right interval is never copied from the left interval (or vice versa), so
    a genuine temporal asymmetry remains present in both the curves and the
    reported durations.
    """
    times = list(timestamps)
    source = {name: list(values) for name, values in signals.items()}
    cycles = []
    for previous, current in zip(anchors, anchors[1:]):
        cycle = {
            "pairIndex": current.get("pairIndex"),
            "source": "fsr",
            "event": "consecutive_same_foot_fsr_contacts",
            "pairingMethod": "paired_fsr_contact_anchors",
            "fsrAnchorPairIndexes": [
                previous.get("pairIndex"),
                current.get("pairIndex"),
            ],
            "left": {"curves": {}},
            "right": {"curves": {}},
        }
        valid = True
        for side in ("left", "right"):
            try:
                start = float(previous[side]["start"])
                end = float(current[side]["start"])
            except (KeyError, TypeError, ValueError):
                valid = False
                break
            duration = end - start
            if (
                not np.isfinite([start, end]).all()
                or duration < float(min_cycle_seconds)
                or duration > float(max_cycle_seconds)
            ):
                valid = False
                break
            cycle[side]["start"] = round(start, 4)
            cycle[side]["end"] = round(end, 4)
            cycle[side]["duration"] = round(duration, 4)
            metric_sources = {
                "knee": source.get(f"{side}_knee", []),
                "hip": source.get(f"{side}_hip", []),
                "trunk": source.get("trunk", []),
                "lateral_trunk": source.get("lateral_trunk", []),
            }
            for metric, values in metric_sources.items():
                curve = _normalized_interval(
                    times,
                    values,
                    start,
                    end,
                    preserve_peak=metric == "knee",
                )
                cycle[side]["curves"][metric] = curve
                if metric in REQUIRED_METRICS:
                    valid = valid and bool(curve)
            foot_curve = _normalized_interval(
                times, source.get(f"{side}_foot_clearance_cm", []), start, end
            )
            toe_curve = _normalized_interval(
                times, source.get(f"{side}_toe_clearance_cm", []), start, end
            )
            if foot_curve and toe_curve:
                cycle[side]["curves"]["footClearanceCm"] = foot_curve
                cycle[side]["curves"]["toeClearanceCm"] = toe_curve
                summary = _clearance_summary(
                    foot_curve,
                    toe_curve,
                    cycle[side]["curves"].get(
                        "kneeMeasured",
                        cycle[side]["curves"].get("knee", []),
                    ),
                )
                if summary is not None:
                    cycle[side]["footClearance"] = summary
        if valid:
            cycles.append(cycle)
    return cycles[-int(window_size):]


def _valid_fsr_contact_anchors(anchors: List[dict] | None) -> List[dict]:
    """Return paired, strictly ordered FSR contacts without altering timing."""
    candidates = []
    for source in anchors or []:
        if not isinstance(source, dict):
            continue
        try:
            left_start = float(source["left"]["start"])
            right_start = float(source["right"]["start"])
        except (KeyError, TypeError, ValueError):
            continue
        if not np.isfinite([left_start, right_start]).all():
            continue
        anchor = dict(source)
        anchor["left"] = dict(source["left"])
        anchor["right"] = dict(source["right"])
        anchor["left"]["start"] = left_start
        anchor["right"]["start"] = right_start
        candidates.append(anchor)
    candidates.sort(
        key=lambda item: (
            (float(item["left"]["start"]) + float(item["right"]["start"]))
            / 2.0
        )
    )
    ordered = []
    for candidate in candidates:
        if ordered and any(
            float(candidate[side]["start"])
            <= float(ordered[-1][side]["start"])
            for side in ("left", "right")
        ):
            continue
        ordered.append(candidate)
    return ordered


def build_synchronized_gait_cycles(
    timestamps, signals, fsr_anchors, *, window_size,
    min_cycle_seconds=0.18, max_cycle_seconds=2.5,
    min_flexion_excursion=4.0, progress=None, fsr_contacts=None, consumed_until=None,
):
    """Complete camera steps immediately; FSR confirms or recovers their timing.

    FSR stance curves and camera movement curves remain distinct. A completed
    force stance is NOT relabelled as a full heel-strike-to-heel-strike cycle.
    """
    contacts = list(fsr_contacts or [])
    previous_release = {}
    for anchor in _valid_fsr_contact_anchors(fsr_anchors):
        for side in ("left", "right"):
            step = anchor[side]
            contacts.append({"side": side, "start": previous_release.get(side),
                             "end": float(step["start"])})
            if isinstance(step.get("end"), (int, float)):
                previous_release[side] = float(step["end"])
    return build_camera_gait_cycles(
        timestamps, signals, window_size=window_size,
        min_cycle_seconds=min_cycle_seconds, max_cycle_seconds=max_cycle_seconds,
        min_flexion_excursion=min_flexion_excursion, progress=progress,
        fsr_contacts=contacts, consumed_until=consumed_until,
    )


def build_camera_gait_cycles(
    timestamps: Iterable[float],
    signals: Dict[str, Iterable[float]],
    *,
    window_size: int,
    min_cycle_seconds: float = 0.18,
    max_cycle_seconds: float = 2.5,
    min_flexion_excursion: float = 4.0,
    progress: dict | None = None,
    fsr_contacts: List[dict] | None = None,
    consumed_until: dict | None = None,
) -> List[dict]:
    """Build paired movements, with optional measured FSR landing events.

    Both sides are segmented independently, normalized to 101 points and then
    paired by completion order. These are movement phases, not full same-foot
    heel-strike cycles; phaseDefinition explicitly records that distinction.
    """
    times = list(timestamps)
    source = {name: list(values) for name, values in signals.items()}
    requested_window = max(1, len(times)) if int(window_size) == 0 else max(1, int(window_size))
    side_progress = {"left": {}, "right": {}}
    intervals = {
        side: _camera_step_intervals(
            times,
            source.get(f"{side}_knee", []),
            source.get(f"{side}_foot_lift", []),
            source.get(f"{side}_ankle_reach", []),
            min_step_seconds=float(min_cycle_seconds),
            max_step_seconds=float(max_cycle_seconds),
            min_flexion_excursion=float(min_flexion_excursion),
            progress=side_progress[side],
        )
        for side in ("left", "right")
    }
    confirmations = {"left": {}, "right": {}}
    latest_time = max(times, default=0.0)
    for contact in fsr_contacts or []:
        side = contact.get("side")
        if side not in intervals:
            continue
        try:
            end = float(contact["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not np.isfinite(end) or end > latest_time:
            continue
        match = min(intervals[side], key=lambda pair: abs(pair[1] - end), default=None)
        if match is not None and abs(match[1] - end) <= 0.30:
            confirmations[side][match] = {"confirmed": True, "contactAt": end}
            continue
        try:
            start = float(contact["start"])
        except (KeyError, TypeError, ValueError):
            continue
        if np.isfinite(start) and min_cycle_seconds <= end - start <= max_cycle_seconds:
            interval = (start, end)
            # Never add a second event for the same movement.
            if any(min(end, b) - max(start, a) > 0.5 * min(end-start, b-a)
                   for a, b in intervals[side]):
                continue
            intervals[side].append(interval)
            confirmations[side][interval] = {"confirmed": True, "contactAt": end, "recovered": True}
    if consumed_until:
        intervals = {side: [pair for pair in values
                           if pair[1] > consumed_until.get(side, float('-inf')) + 0.12]
                     for side, values in intervals.items()}
    pairing_diagnostics = {}
    paired_intervals = _pair_camera_intervals(
        intervals["left"],
        intervals["right"],
        diagnostics=pairing_diagnostics,
    )

    def pair_quality(pair):
        left_interval, right_interval = pair
        start = min(float(left_interval[0]), float(right_interval[0]))
        end = max(float(left_interval[1]), float(right_interval[1]))

        def interval_values(name):
            values = source.get(name, [])
            return np.asarray([
                float(value)
                for timestamp, value in zip(times, values)
                if start <= float(timestamp) <= end and np.isfinite(value)
            ], dtype=float)

        reasons = []
        facing = interval_values("facing_sign")
        facing_consistency = None
        if len(facing) >= 4:
            positive = float(np.mean(facing >= 0.0))
            facing_consistency = max(positive, 1.0 - positive)
            if facing_consistency < 0.80:
                reasons.append("direction_change")

        widths = interval_values("view_width_ratio")
        median_width = None
        width_p80 = None
        if len(widths) >= 4:
            median_width = float(np.median(widths))
            width_p80 = float(np.percentile(widths, 80))
            # This ratio approaches the frontal-camera distribution while the
            # patient turns. Keep a generous upper percentile so a mildly
            # oblique but measurable gait is not discarded.
            if median_width > 0.30 or width_p80 > 0.42:
                reasons.append("outside_sagittal_plane")

        centers = interval_values("body_center_x")
        travel = (
            abs(float(centers[-1] - centers[0]))
            if len(centers) >= 4 else None
        )
        metadata_available = len(facing) >= 4 or len(widths) >= 4
        return {
            "available": metadata_available,
            "steadyWalking": not reasons,
            "reasons": reasons,
            "directionConsistency": (
                round(facing_consistency, 3)
                if facing_consistency is not None else None
            ),
            "medianSagittalWidthRatio": (
                round(median_width, 3) if median_width is not None else None
            ),
            "sagittalWidthP80": (
                round(width_p80, 3) if width_p80 is not None else None
            ),
            "bodyTravelRatio": round(travel, 3) if travel is not None else None,
        }

    pair_entries = [
        {
            "pair": pair,
            "quality": pair_quality(pair),
            "originalIndex": index + 1,
        }
        for index, pair in enumerate(paired_intervals)
    ]
    # Count every distinct pair; plane/turn warnings are not aesthetic filters.
    eligible_entries = pair_entries
    pair_count = len(eligible_entries)
    if progress is not None:
        for side in ("left", "right"):
            side_progress[side]["intervals"] = [
                {
                    "start": round(float(start), 4),
                    "end": round(float(end), 4),
                    "midpoint": round((float(start) + float(end)) / 2.0, 4),
                    "duration": round(float(end) - float(start), 4),
                }
                for start, end in intervals[side]
            ]
        progress.update({
            "event": "completed_step_from_knee_and_foot_motion",
            **pairing_diagnostics,
            "minimumContralateralGapSeconds": 0.12,
            "segmentationSource": "camera_fsr" if any(confirmations.values()) else "camera",
            "fallbackUsed": not any(confirmations.values()),
            "fsrConfirmedSteps": sum(len(v) for v in confirmations.values()),
            "left": side_progress["left"],
            "right": side_progress["right"],
            "pairedCycles": pair_count,
            "candidatePairedCycles": len(pair_entries),
            "turnTransitionRejectedPairs": len(pair_entries) - pair_count,
            "ready": pair_count > 0,
        })
    if pair_count == 0:
        return []
    selected_count = min(pair_count, requested_window)
    selected_entries = eligible_entries[-selected_count:]
    cycles: List[dict] = []
    for offset in range(selected_count):
        entry = selected_entries[offset]
        left_interval, right_interval = entry["pair"]
        left_midpoint = (float(left_interval[0]) + float(left_interval[1])) / 2.0
        right_midpoint = (float(right_interval[0]) + float(right_interval[1])) / 2.0
        contralateral_gap = abs(right_midpoint - left_midpoint)
        cycle = {
            "pairIndex": entry["originalIndex"],
            "source": "camera",
            "event": "completed_step_from_knee_and_foot_motion",
            "pairingMethod": pairing_diagnostics["pairingMethod"],
            "phaseDefinition": "observed_movement_start_to_return_or_fsr_contact",
            "contralateralStepGap": round(contralateral_gap, 4),
            "cadenceSpm": None,
            "cameraCycleQuality": entry["quality"],
            "left": {"curves": {}},
            "right": {"curves": {}},
        }
        valid = True
        for side in ("left", "right"):
            interval_index = 0 if side == "left" else 1
            start, end = entry["pair"][interval_index]
            cycle[side]["start"] = round(start, 4)
            cycle[side]["end"] = round(end, 4)
            cycle[side]["duration"] = round(end - start, 4)
            cycle[side]["fsrTiming"] = confirmations[side].get((start, end), {"confirmed": False})
            cycle[side]["rawSamples"] = {}
            for metric, values in {
                "knee": source.get(f"{side}_knee", []),
                "hip": source.get(f"{side}_hip", []),
                "trunk": source.get("trunk", []),
                "lateral_trunk": source.get("lateral_trunk", []),
            }.items():
                curve = _normalized_interval(
                    times,
                    values,
                    start,
                    end,
                    preserve_peak=metric in ("knee", "hip"),
                )
                cycle[side]["rawSamples"][metric] = [
                    {"time": float(t), "value": float(v)}
                    for t, v in zip(times, values)
                    if start <= t <= end and np.isfinite(v)
                ]
                cycle[side]["curves"][metric] = curve
                # A valid camera knee step must not be discarded merely
                # because the upper-body landmarks were briefly hidden. Each
                # secondary chart already handles its empty curve separately.
                if metric == "knee":
                    valid = valid and bool(curve)
            foot_curve = _normalized_interval(
                times, source.get(f"{side}_foot_clearance_cm", []), start, end
            )
            toe_curve = _normalized_interval(
                times, source.get(f"{side}_toe_clearance_cm", []), start, end
            )
            if foot_curve and toe_curve:
                cycle[side]["curves"]["footClearanceCm"] = foot_curve
                cycle[side]["curves"]["toeClearanceCm"] = toe_curve
                summary = _clearance_summary(
                    foot_curve,
                    toe_curve,
                    cycle[side]["curves"].get(
                        "kneeMeasured",
                        cycle[side]["curves"].get("knee", []),
                    ),
                )
                if summary is not None:
                    cycle[side]["footClearance"] = summary
        cycle["measurementComplete"] = valid
        cycles.append(cycle)
    return cycles


def analyze_gait_cycles(
    cycles: List[dict],
    *,
    window_size: int,
    healthy_leg: str = "LEFT",
    prosthetic_leg: str = "RIGHT",
) -> dict:
    selected = cycles[-int(window_size):]
    metrics = {}
    for metric in METRICS:
        result = {}
        for side in ("left", "right"):
            curves = [
                item[side]["curves"].get(metric, []) for item in selected
                if item[side]["curves"].get(metric)
            ]
            if not curves:
                result[side] = {"mean": [], "sd": [], "cycles": 0}
                continue
            stack = np.asarray(curves, dtype=float)
            result[side] = {
                "mean": np.mean(stack, axis=0).round(4).tolist(),
                "sd": (
                    np.std(stack, axis=0, ddof=1).round(4).tolist()
                    if len(curves) > 1
                    else np.zeros(101).tolist()
                ),
                "cycles": len(curves),
            }
        metrics[metric] = result
    return {
        "unit": "degree",
        "windowSize": int(window_size),
        "windowOptions": [0, 5, 7],
        "cycleCount": len(selected),
        "pairingMethod": (
            "adjacent_opposite_events_no_skipped_side"
            if all(cycle.get('pairingMethod') == 'adjacent_opposite_events_no_skipped_side'
                   for cycle in selected) else "legacy_unknown"
        ),
        "healthySide": healthy_leg.lower(),
        "prostheticSide": prosthetic_leg.lower(),
        "cycles": selected,
        "metrics": metrics,
        "statistics": _cycle_statistics(selected),
        "curveProcessing": {
            "interpolation": "linear_time",
            "outlierFilter": "none",
            "smoothing": "none",
            "cameraStepDisplay": "measured_samples_no_template",
            "trunkDisplay": "measured_samples",
            "hipDisplay": "measured_samples",
            "statisticsSource": "raw_per_step_samples",
        },
    }
