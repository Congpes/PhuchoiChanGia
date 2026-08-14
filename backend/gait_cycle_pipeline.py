"""Normalize camera joint signals into FSR-synchronized gait cycles."""

from __future__ import annotations

from typing import Dict, Iterable, List

import numpy as np


METRICS = ("knee", "hip", "trunk")


def _normalized_interval(
    timestamps: Iterable[float],
    values: Iterable[float],
    start: float,
    end: float,
    target_len: int = 101,
) -> List[float]:
    points = [
        (float(timestamp), float(value))
        for timestamp, value in zip(timestamps, values)
        if start <= float(timestamp) <= end and np.isfinite(value) and float(value) != 0.0
    ]
    if len(points) < 3 or end <= start:
        return []
    x = np.asarray([item[0] for item in points], dtype=float)
    y = np.asarray([item[1] for item in points], dtype=float)
    target = np.linspace(start, end, target_len)
    return np.interp(target, x, y).round(4).tolist()


def build_gait_cycles(
    timestamps: Iterable[float],
    signals: Dict[str, Iterable[float]],
    anchors: List[dict],
    *,
    window_size: int,
) -> List[dict]:
    """Build left/right full gait cycles from consecutive same-foot contacts."""
    times = list(timestamps)
    source = {name: list(values) for name, values in signals.items()}
    cycles = []
    for previous, current in zip(anchors, anchors[1:]):
        cycle = {
            "pairIndex": current.get("pairIndex"),
            "left": {"curves": {}},
            "right": {"curves": {}},
        }
        valid = True
        for side in ("left", "right"):
            start = float(previous[side]["start"])
            end = float(current[side]["start"])
            cycle[side]["start"] = round(start, 4)
            cycle[side]["end"] = round(end, 4)
            cycle[side]["duration"] = round(end - start, 4)
            metric_sources = {
                "knee": source.get(f"{side}_knee", []),
                "hip": source.get(f"{side}_hip", []),
                "trunk": source.get("trunk", []),
            }
            for metric, values in metric_sources.items():
                curve = _normalized_interval(times, values, start, end)
                cycle[side]["curves"][metric] = curve
                valid = valid and bool(curve)
        if valid:
            cycles.append(cycle)
    return cycles[-int(window_size):]


def _camera_cycle_intervals(
    timestamps: Iterable[float],
    knee_angles: Iterable[float],
    *,
    min_cycle_seconds: float,
    max_cycle_seconds: float,
    min_flexion_excursion: float,
) -> List[tuple[float, float]]:
    """Return consecutive peak-flexion intervals for one leg."""
    points = [
        (float(timestamp), float(value))
        for timestamp, value in zip(timestamps, knee_angles)
        if np.isfinite(timestamp) and np.isfinite(value) and float(value) != 0.0
    ]
    if len(points) < 7:
        return []
    points.sort(key=lambda item: item[0])
    x = np.asarray([item[0] for item in points], dtype=float)
    y = np.asarray([item[1] for item in points], dtype=float)
    _, reverse_indices = np.unique(x[::-1], return_index=True)
    keep = np.sort(len(x) - 1 - reverse_indices)
    x, y = x[keep], y[keep]
    if len(x) < 7 or x[-1] <= x[0]:
        return []
    positive_steps = np.diff(x)
    positive_steps = positive_steps[positive_steps > 0]
    if not len(positive_steps):
        return []
    median_step = float(np.median(positive_steps))
    smooth_points = max(3, min(11, int(round(0.12 / max(median_step, 1e-3)))))
    if smooth_points % 2 == 0:
        smooth_points += 1
    kernel = np.ones(smooth_points, dtype=float) / smooth_points
    padded = np.pad(y, smooth_points // 2, mode="edge")
    smoothed = np.convolve(padded, kernel, mode="valid")
    overall_excursion = float(np.percentile(smoothed, 90) - np.percentile(smoothed, 10))
    if overall_excursion < float(min_flexion_excursion):
        return []
    median_angle = float(np.median(smoothed))
    local_radius = max(2, int(round(0.35 / max(median_step, 1e-3))))
    candidates: List[int] = []
    for index in range(1, len(smoothed) - 1):
        if not (
            smoothed[index] <= smoothed[index - 1]
            and smoothed[index] < smoothed[index + 1]
            and smoothed[index] <= median_angle
        ):
            continue
        start = max(0, index - local_radius)
        end = min(len(smoothed), index + local_radius + 1)
        if float(np.max(smoothed[start:end]) - smoothed[index]) >= float(min_flexion_excursion):
            candidates.append(index)
    selected: List[int] = []
    for candidate in candidates:
        if not selected or x[candidate] - x[selected[-1]] >= min_cycle_seconds:
            selected.append(candidate)
        elif smoothed[candidate] < smoothed[selected[-1]]:
            selected[-1] = candidate
    intervals = []
    for previous, current in zip(selected, selected[1:]):
        duration = float(x[current] - x[previous])
        if min_cycle_seconds <= duration <= max_cycle_seconds:
            intervals.append((float(x[previous]), float(x[current])))
    return intervals


def build_camera_gait_cycles(
    timestamps: Iterable[float],
    signals: Dict[str, Iterable[float]],
    *,
    window_size: int,
    min_cycle_seconds: float = 0.55,
    max_cycle_seconds: float = 2.5,
    min_flexion_excursion: float = 6.0,
) -> List[dict]:
    """Build camera-only cycles from same-side peak knee-flexion events.

    Both sides are segmented independently, normalized to 101 points and then
    paired by latest order. The schema matches :func:`build_gait_cycles`.
    """
    times = list(timestamps)
    source = {name: list(values) for name, values in signals.items()}
    requested_window = max(0, int(window_size))
    if requested_window == 0:
        return []
    intervals = {
        side: _camera_cycle_intervals(
            times,
            source.get(f"{side}_knee", []),
            min_cycle_seconds=float(min_cycle_seconds),
            max_cycle_seconds=float(max_cycle_seconds),
            min_flexion_excursion=float(min_flexion_excursion),
        )
        for side in ("left", "right")
    }
    pair_count = min(len(intervals["left"]), len(intervals["right"]))
    if pair_count == 0:
        return []
    selected_count = min(pair_count, requested_window)
    selected_intervals = {
        side: intervals[side][-selected_count:] for side in ("left", "right")
    }
    first_pair_index = pair_count - selected_count + 1
    cycles: List[dict] = []
    for offset in range(selected_count):
        cycle = {
            "pairIndex": first_pair_index + offset,
            "source": "camera",
            "event": "peak_knee_flexion",
            "left": {"curves": {}},
            "right": {"curves": {}},
        }
        valid = True
        for side in ("left", "right"):
            start, end = selected_intervals[side][offset]
            cycle[side]["start"] = round(start, 4)
            cycle[side]["end"] = round(end, 4)
            cycle[side]["duration"] = round(end - start, 4)
            for metric, values in {
                "knee": source.get(f"{side}_knee", []),
                "hip": source.get(f"{side}_hip", []),
                "trunk": source.get("trunk", []),
            }.items():
                curve = _normalized_interval(times, values, start, end)
                cycle[side]["curves"][metric] = curve
                valid = valid and bool(curve)
        if valid:
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
            curves = [item[side]["curves"][metric] for item in selected]
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
        "windowOptions": [5, 7],
        "cycleCount": len(selected),
        "healthySide": healthy_leg.lower(),
        "prostheticSide": prosthetic_leg.lower(),
        "cycles": selected,
        "metrics": metrics,
    }
