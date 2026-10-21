from __future__ import annotations

import json
import argparse
import math
import queue
import re
import socket
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from statistics import median
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

# Embedded single-file test implementation. This file intentionally has no project-local imports.
import copy
from copy import deepcopy
from math import isfinite
from typing import Iterable, Mapping, Sequence

# Force-unit conversion and cell calibration
def apply_cell_calibration(matrix, side, profile=None):
    """Apply a specimen-specific profile to legacy Newton estimates.

    Missing cells stay uncalibrated. Never use on raw ADC or already corrected
    packets. This does not claim full-range accuracy or perform live shoe tare.
    """
    values = [list(map(float, row)) for row in matrix]
    if profile is None or side != profile.get('side'):
        return values
    cells = profile.get('cells', [])
    if len(cells) != len(values) or any(len(c) != len(v) for c, v in zip(cells, values)):
        raise ValueError('Calibration shape does not match matrix')
    for row, parameters in zip(values, cells):
        for column, cell in enumerate(parameters):
            if cell is None:
                continue
            baseline, gain = float(cell['baseline_n']), float(cell['gain'])
            if not math.isfinite(baseline) or baseline < 0 or not math.isfinite(gain) or gain <= 0:
                raise ValueError('Invalid cell calibration parameters')
            value = max(0.0, row[column] - baseline)
            if 'points_n' not in cell:
                row[column] = value * gain
                continue
            # Optional three anchors in baseline-subtracted legacy N -> target N.
            # Do not multiply by the old gain again inside the measured range.
            try:
                points = [(float(x), float(y)) for x, y in cell['points_n']]
            except (TypeError, ValueError) as exc:
                raise ValueError('Invalid cell calibration anchors') from exc
            if (len(points) != 3 or points[0] != (0.0, 0.0)
                    or any(not math.isfinite(v) for point in points for v in point)
                    or any(x1 <= x0 or y1 <= y0
                           for (x0, y0), (x1, y1) in zip(points, points[1:]))):
                raise ValueError('Calibration anchors must start at zero and increase')
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                if value <= x1:
                    row[column] = y0 + (value - x0) * (y1 - y0) / (x1 - x0)
                    break
            else:
                # Unvalidated extrapolation: retain previous gain beyond last
                # anchor, continuously; never saturate/snap to the test weight.
                x1, y1 = points[-1]
                row[column] = y1 + (value - x1) * gain
    return values


def analog_to_weight_smooth(adc: float) -> float:
    """Convert one raw ADC value to the existing estimated gram calibration."""
    value = float(adc)
    if value >= 4950.0:
        return 0.0
    if value > 680.0:
        return max(0.0, -0.0868 * value + 434.03)
    return 132728.45 * value ** (-0.889) if value > 0 else 0.0


def gram_to_newton(gram: float) -> float:
    return max(0.0, float(gram) * 9.80665 / 1000.0)


def adc_to_newton(adc: float) -> float:
    return gram_to_newton(analog_to_weight_smooth(adc))


def matrix_to_newton(
    matrix: Iterable[Iterable[float]],
    unit: str | None,
) -> tuple[list[list[float]], str, str]:
    """Normalize a received FSR matrix and return values, display unit, source.

    A packet labelled raw_adc is calibrated with the legacy formula, gram is
    converted with standard gravity, and newton is retained as sent.  The
    response names estimated values explicitly until sensor-level calibration
    is available.
    """
    normalized_unit = str(unit or "raw_adc").strip().lower()
    values = [[float(value) for value in row] for row in matrix]
    if normalized_unit == "newton":
        return [[max(0.0, value) for value in row] for row in values], "N", "packet"
    if normalized_unit == "gram":
        force_values = [[gram_to_newton(value) for value in row] for row in values]
    else:
        force_values = [[adc_to_newton(value) for value in row] for row in values]
    return force_values, "N_estimated", "formula_estimate"


def region_totals(matrix: Iterable[Iterable[float]]) -> dict:
    """Return force totals for the agreed 12×4 forefoot/midfoot/heel bands."""
    rows = [list(map(float, row)) for row in matrix]

    def total(first_row: int, last_row: int) -> float:
        return round(
            sum(sum(row) for row in rows[first_row : last_row + 1]),
            4,
        )

    return {
        "heel": total(9, 11),
        "midfoot": total(4, 8),
        "forefoot": total(0, 3),
        "total": round(sum(sum(row) for row in rows), 4),
    }


def matrix_total(matrix: Iterable[Iterable[float]]) -> float:
    return round(sum(sum(float(value) for value in row) for row in matrix), 4)


# Incremental shoe-zero statistics
Matrix = Sequence[Sequence[float]]
def _validate_matrix(matrix: Matrix) -> tuple[int, int]:
    if not matrix or not matrix[0]:
        raise ValueError("FSR matrix is empty")
    columns = len(matrix[0])
    for row in matrix:
        if len(row) != columns:
            raise ValueError("FSR matrix is not rectangular")
        if any(not isfinite(float(value)) for value in row):
            raise ValueError("FSR matrix contains non-finite values")
    return len(matrix), columns


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(1.0, max(0.0, fraction))
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _winsorized(values: Sequence[float]) -> list[float]:
    center = float(median(values))
    deviations = [abs(float(value) - center) for value in values]
    mad = float(median(deviations))
    radius = max(1.0, 6.0 * mad)
    return [min(center + radius, max(center - radius, float(value))) for value in values]


def summarize_zero_round(
    samples: Sequence[Matrix],
    *,
    spread_limit: float = 0.20,
    drift_limit: float = 0.10,
) -> dict:
    """Summarize one stable lift window without requiring a zero force value."""
    if not samples:
        return {"accepted": False, "matrix": None, "noise": None, "reason": "no_samples"}
    rows, columns = _validate_matrix(samples[0])
    for sample in samples[1:]:
        if _validate_matrix(sample) != (rows, columns):
            return {"accepted": False, "matrix": None, "noise": None, "reason": "shape_mismatch"}

    representative = [[0.0] * columns for _ in range(rows)]
    noise = [[0.0] * columns for _ in range(rows)]
    half = max(1, len(samples) // 2)
    for row in range(rows):
        for column in range(columns):
            values = [float(sample[row][column]) for sample in samples]
            center = float(median(values))
            representative[row][column] = center

            robust_values = _winsorized(values)
            low = _quantile(robust_values, 0.10)
            high = _quantile(robust_values, 0.90)
            spread = high - low
            first_center = float(median(robust_values[:half]))
            second_center = float(median(robust_values[half:]))
            drift = abs(first_center - second_center)
            allowed_spread = max(1.0, abs(center) * float(spread_limit))
            allowed_drift = max(0.3, abs(center) * float(drift_limit))
            if drift > allowed_drift:
                return {
                    "accepted": False,
                    "matrix": None,
                    "noise": None,
                    "reason": f"drift_at_{row + 1}_{column + 1}",
                }
            if spread > allowed_spread:
                return {
                    "accepted": False,
                    "matrix": None,
                    "noise": None,
                    "reason": f"spread_at_{row + 1}_{column + 1}",
                }

            deviations = [abs(value - center) for value in values]
            noise[row][column] = max(0.02, 3.0 * float(median(deviations)))
    return {
        "accepted": True,
        "matrix": representative,
        "noise": noise,
        "reason": None,
    }


def _validate_same_shape(*matrices: Matrix) -> tuple[int, int]:
    shapes = [_validate_matrix(matrix) for matrix in matrices]
    if any(shape != shapes[0] for shape in shapes[1:]):
        raise ValueError("FSR matrix shapes do not match")
    return shapes[0]


def merge_zero_round(
    history: Iterable[dict],
    round_matrix: Matrix,
    round_noise: Matrix,
    *,
    adjacency: Iterable[tuple[tuple[int, int], tuple[int, int]]] | None = None,
) -> dict:
    """Append one round and recompute a robust profile from all accepted rounds."""
    rows, columns = _validate_same_shape(round_matrix, round_noise)
    current_history = deepcopy(list(history))
    for entry in current_history:
        _validate_same_shape(entry["matrix"], entry["noise"])
    if current_history and _validate_matrix(current_history[0]["matrix"]) != (rows, columns):
        raise ValueError("FSR matrix shape changed between zero rounds")
    current_history.append({"matrix": deepcopy(round_matrix), "noise": deepcopy(round_noise)})

    baseline = [[0.0] * columns for _ in range(rows)]
    median_baseline = [[0.0] * columns for _ in range(rows)]
    noise = [[0.02] * columns for _ in range(rows)]
    for row in range(rows):
        for column in range(columns):
            values = [float(entry["matrix"][row][column]) for entry in current_history]
            median_baseline[row][column] = float(median(values))
            # The prototype retains the maximum accepted value per cell.
            # Callers choose the round value; instant tare uses the latest
            # frame, so the operator must unload the foot before clicking.
            baseline[row][column] = max(values)
            round_noise_values = [float(entry["noise"][row][column]) for entry in current_history]
            variation = median(abs(value - baseline[row][column]) for value in values)
            noise[row][column] = max(0.02, max(round_noise_values), float(variation))

    warnings = []
    if adjacency and len(current_history) >= 2:
        previous = current_history[-2]["matrix"]
        current = current_history[-1]["matrix"]
        for first, second in adjacency:
            r1, c1 = first
            r2, c2 = second
            first_delta = float(current[r1][c1]) - float(previous[r1][c1])
            second_delta = float(current[r2][c2]) - float(previous[r2][c2])
            previous_sum = float(previous[r1][c1]) + float(previous[r2][c2])
            current_sum = float(current[r1][c1]) + float(current[r2][c2])
            tolerance = max(1.0, 0.25 * max(abs(previous_sum), abs(current_sum), 1.0))
            if first_delta * second_delta < 0 and abs(current_sum - previous_sum) <= tolerance:
                warnings.append({
                    "cells": [list(first), list(second)],
                    "previous_sum": round(previous_sum, 4),
                    "current_sum": round(current_sum, 4),
                    "reason": "neighbor_redistribution",
                })

    return {
        "history": current_history,
        "baseline": baseline,
        "median_baseline": median_baseline,
        "noise": noise,
        "round_count": len(current_history),
        "method": "lift_round_history_max_v4",
        "redistribution_warnings": warnings,
    }


# FSI phase metrics
ROWS = 12
COLUMNS = 4
FOREFOOT_CELL_IDS = (6, 7, 8, 10, 11, 12, 14, 15, 16)
HEEL_CELL_IDS = (42, 43, 46, 47)
STANCE_CELL_IDS = tuple(dict.fromkeys(FOREFOOT_CELL_IDS + HEEL_CELL_IDS))


def physical_cell_to_matrix(cell_id: int, rows: int = ROWS, columns: int = COLUMNS) -> tuple[int, int]:
    """Map the label in the supplied 1..48 drawing to canonical row/column.

    The drawing numbers each row from right to left (1 is top-right and 48
    is bottom-left).  This is a physical label mapping, not a serial index.
    """
    cell = int(cell_id)
    if not 1 <= cell <= rows * columns:
        raise ValueError(f"physical cell id must be in 1..{rows * columns}")
    row, offset = divmod(cell - 1, columns)
    return row, columns - 1 - offset


def physical_ids_to_cells(cell_ids: Iterable[int]) -> list[tuple[int, int]]:
    return [physical_cell_to_matrix(cell_id) for cell_id in cell_ids]


DEFAULT_FSI_ROIS = {
    "heel": physical_ids_to_cells(HEEL_CELL_IDS),
    "forefoot": physical_ids_to_cells(FOREFOOT_CELL_IDS),
    "stance_sampled": physical_ids_to_cells(STANCE_CELL_IDS),
}
_fsi_rois = copy.deepcopy(DEFAULT_FSI_ROIS)


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def force_symmetry_index(left: float | None, right: float | None) -> float | None:
    """Return 100*min/max, with ``None`` for invalid or zero/zero values."""
    if left is None or right is None or not _finite(left) or not _finite(right):
        return None
    left_value, right_value = float(left), float(right)
    if left_value < 0 or right_value < 0:
        return None
    maximum = max(left_value, right_value)
    if maximum <= 0:
        return None
    return round(100.0 * min(left_value, right_value) / maximum, 2)


def _cell(value) -> tuple[int, int]:
    try:
        row, column = value
        return int(row), int(column)
    except (TypeError, ValueError):
        raise ValueError("ROI cells must be (row, column) pairs") from None


def validate_roi(
    roi: Mapping[str, Sequence[tuple[int, int]]],
    rows: int = ROWS,
    columns: int = COLUMNS,
    *,
    exclusive: bool = True,
) -> None:
    """Validate canonical matrix coordinates.

    ``exclusive=False`` is used for the named reporting union because
    ``stance_sampled`` intentionally contains the heel and forefoot cells.
    """
    if not isinstance(roi, Mapping) or not roi:
        raise ValueError("ROI configuration must be a non-empty mapping")
    seen: set[tuple[int, int]] = set()
    for name, cells in roi.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("ROI name must be a non-empty string")
        if not cells:
            raise ValueError(f"ROI {name!r} is empty")
        local: set[tuple[int, int]] = set()
        for raw_cell in cells:
            row, column = _cell(raw_cell)
            if not (0 <= row < rows and 0 <= column < columns):
                raise ValueError(f"ROI {name!r} contains cell outside {rows}x{columns}")
            if (row, column) in local:
                raise ValueError(f"ROI {name!r} contains a duplicate cell")
            local.add((row, column))
        if exclusive and seen.intersection(local):
            raise ValueError("ROI regions contain an overlapping cell")
        seen.update(local)


def set_fsi_rois(roi_config: Mapping[str, Sequence[tuple[int, int]]]) -> None:
    global _fsi_rois
    validate_roi(roi_config, exclusive=False)
    _fsi_rois = {name: [_cell(cell) for cell in cells] for name, cells in roi_config.items()}


def get_fsi_rois() -> dict[str, list[tuple[int, int]]]:
    return copy.deepcopy(_fsi_rois)


def _sample_matrix(sample: Mapping) -> list[list[float]] | None:
    quality = sample.get("quality")
    if sample.get("valid", True) is False or (isinstance(quality, str) and quality in {"invalid", "missing", "invalid/missing"}):
        return None
    matrix = sample.get("matrix")
    if not isinstance(matrix, Sequence) or len(matrix) != ROWS:
        return None
    normalized: list[list[float]] = []
    for row in matrix:
        if not isinstance(row, Sequence) or len(row) != COLUMNS:
            return None
        values = [float(value) for value in row]
        if not all(math.isfinite(value) and value >= 0 for value in values):
            return None
        normalized.append(values)
    return normalized


def roi_series(samples: Sequence[Mapping], roi_cells: Sequence[tuple[int, int]]) -> list[float]:
    """Return one summed ROI value per valid sample in input order."""
    cells = [_cell(cell) for cell in roi_cells]
    if not cells:
        raise ValueError("ROI cannot be empty")
    values: list[float] = []
    for sample in samples:
        matrix = _sample_matrix(sample)
        if matrix is None:
            continue
        values.append(round(sum(matrix[row][column] for row, column in cells), 10))
    return values


def _roi_value(sample: Mapping, cells: Sequence[tuple[int, int]]) -> float | None:
    matrix = _sample_matrix(sample)
    if matrix is None:
        return None
    return sum(matrix[row][column] for row, column in cells)


def phase_summary(
    samples: Sequence[Mapping],
    start: float,
    end: float,
    roi: Sequence[tuple[int, int]] | Mapping[str, Sequence[tuple[int, int]]],
) -> dict:
    """Summarize one ROI inside a side-specific phase window.

    The mean is the arithmetic mean of valid timestamp samples.  Impulse uses
    trapezoidal integration on those samples, preserving the sample timestamp
    instead of adding peaks from different timestamps.
    """
    if isinstance(roi, Mapping):
        raise ValueError("phase_summary expects one ROI cell sequence")
    cells = [_cell(cell) for cell in roi]
    if not cells:
        raise ValueError("ROI cannot be empty")
    start_value, end_value = float(start), float(end)
    if not math.isfinite(start_value) or not math.isfinite(end_value) or end_value < start_value:
        raise ValueError("phase window must have finite start <= end")
    selected: list[tuple[float, float]] = []
    had_invalid = False
    for sample in samples:
        try:
            timestamp = float(sample.get("timestamp"))
        except (AttributeError, TypeError, ValueError):
            had_invalid = True
            continue
        if timestamp < start_value or timestamp > end_value:
            continue
        value = _roi_value(sample, cells)
        if value is None:
            had_invalid = True
            continue
        selected.append((timestamp, value))
    selected.sort(key=lambda item: item[0])
    if not selected:
        return {
            "mean": None,
            "median": None,
            "peak": None,
            "peak_timestamp": None,
            "peak_position_percent": None,
            "impulse": None,
            "duration": 0.0,
            "valid_sample_count": 0,
            "quality": "invalid/missing" if had_invalid else "no_load",
            "reason": "no_valid_roi_samples",
        }
    values = [value for _, value in selected]
    peak_index = max(range(len(values)), key=values.__getitem__)
    peak_timestamp = selected[peak_index][0]
    duration = selected[-1][0] - selected[0][0]
    peak_position = 0.0 if duration <= 0 else 100.0 * (peak_timestamp - start_value) / (end_value - start_value)
    impulse = 0.0
    for (time_a, value_a), (time_b, value_b) in zip(selected, selected[1:]):
        if time_b > time_a:
            impulse += (value_a + value_b) * 0.5 * (time_b - time_a)
    return {
        "mean": round(sum(values) / len(values), 4),
        "median": round(float(median(values)), 4),
        "peak": round(max(values), 4),
        "peak_timestamp": round(peak_timestamp, 6),
        "peak_position_percent": round(max(0.0, min(100.0, peak_position)), 2),
        "impulse": round(impulse, 4),
        "duration": round(duration, 4),
        "valid_sample_count": len(selected),
        "quality": "valid",
        "reason": None,
    }


def phase_fsi(
    left_summary: Mapping,
    right_summary: Mapping,
    metric: str = "mean",
    *,
    region: str | None = None,
) -> dict:
    left = left_summary.get(metric)
    right = right_summary.get(metric)
    quality = "valid"
    reason = None
    if left_summary.get("quality") not in (None, "valid") or right_summary.get("quality") not in (None, "valid"):
        quality = "invalid/missing"
        reason = "one_or_both_side_summaries_invalid"
    elif left is None or right is None:
        quality = "invalid/missing"
        reason = "metric_missing"
    fsi = force_symmetry_index(left, right) if quality == "valid" else None
    if fsi is None and quality == "valid":
        quality = "no_load" if (left or 0) == 0 and (right or 0) == 0 else "invalid/missing"
        reason = "both_sides_zero" if quality == "no_load" else "metric_invalid"
    higher_side = None
    if fsi is not None and float(left) != float(right):
        higher_side = "left" if float(left) > float(right) else "right"
    return {
        "region": region,
        "metric": metric,
        "left": left,
        "right": right,
        "fsi": fsi,
        "higher_side": higher_side,
        "quality": quality,
        "reason": reason,
    }


def _sample_total(sample: Mapping) -> float | None:
    matrix = _sample_matrix(sample)
    if matrix is None:
        return None
    return sum(sum(row) for row in matrix)


def contact_detection_settings(samples: Sequence[Mapping], threshold: float = 5.0,
                               *, adaptive: bool = True) -> dict:
    """Estimate a per-foot load gate while retaining a fixed noise floor.

    Shoe preload can keep the sum above 5 N throughout swing.  Adapt only
    when the window contains a clear low/high separation; a steadily loaded
    foot or small standing sway must not create artificial strides.
    """
    floor = max(0.0, float(threshold))
    totals = sorted(value for sample in samples if (value := _sample_total(sample)) is not None)
    if not totals:
        return {"on_n": floor, "off_n": floor * 0.6, "baseline_n": None,
                "high_n": None, "contrast_n": 0.0, "adaptive": False,
                "reason": "no_valid_samples"}

    def quantile(fraction: float) -> float:
        position = (len(totals) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(totals) - 1)
        return totals[lower] + (totals[upper] - totals[lower]) * (position - lower)

    low, high = quantile(0.10), quantile(0.90)
    contrast = high - low
    adaptive = bool(adaptive) and len(totals) >= 12 and contrast >= 8.0 and low <= 0.5 * high
    on = max(floor, low + 0.25 * contrast) if adaptive else floor
    off = max(floor * 0.6, low + 0.10 * contrast) if adaptive else floor * 0.6
    return {"on_n": round(on, 4), "off_n": round(off, 4),
            "baseline_n": round(low, 4), "high_n": round(high, 4),
            "contrast_n": round(contrast, 4), "adaptive": adaptive,
            "reason": "adaptive_load_gate" if adaptive else "fixed_floor_low_contrast"}


def detect_contact_interval(samples: Sequence[Mapping], threshold: float, debounce: int = 2) -> dict:
    """Detect the first full-48-cell contact interval using debounce samples."""
    intervals = detect_contact_intervals(samples, threshold, debounce)
    return intervals[0] if intervals else {
        "detected": False, "ic": None, "to": None, "start": None,
        "end": None, "quality": "no_contact",
    }


def detect_contact_intervals(
    samples: Sequence[Mapping],
    threshold: float,
    debounce: int = 2,
    *,
    heel_cells: Sequence[tuple[int, int]] | None = None,
    forefoot_cells: Sequence[tuple[int, int]] | None = None,
    release_threshold: float | None = None,
    max_signal_gap_seconds: float = 0.25,
    min_contact_seconds: float = 0.15,
    min_unloaded_seconds: float = 0.06,
    mark_incomplete: bool = False,
) -> list[dict]:
    """Detect every full-48-cell contact interval and an optional heel-off.

    Heel-off is only reported when the heel ROI unloads while the forefoot
    remains loaded.  Otherwise callers must use the explicit fallback window.
    """
    threshold_value = float(threshold)
    release_value = (
        threshold_value * 0.6
        if release_threshold is None
        else float(release_threshold)
    )
    max_gap = max(0.0, float(max_signal_gap_seconds))
    minimum_duration = max(0.0, float(min_contact_seconds))
    minimum_unloaded = max(0.0, float(min_unloaded_seconds))
    required = max(1, int(debounce))
    ordered = sorted(samples, key=lambda item: float(item.get("timestamp", 0.0)))
    intervals: list[dict] = []
    active_streak: list[tuple[float, float, Mapping]] = []
    contact: list[tuple[float, float, Mapping]] = []
    release_streak: list[tuple[float, float, Mapping]] = []
    last_valid_timestamp: float | None = None
    saw_unloaded = False
    observed_onset = False

    def finish_contact(reason: str, end_timestamp: float | None = None) -> None:
        nonlocal contact, release_streak
        if not contact:
            return
        start = contact[0][0]
        end = contact[-1][0] if end_timestamp is None else end_timestamp
        if end - start < minimum_duration:
            contact = []
            release_streak = []
            return
        complete = not mark_incomplete or (reason == "released" and observed_onset)
        quality = "valid" if complete else ("signal_gap" if reason == "signal_gap" else "incomplete_contact")
        interval = {
            "detected": True,
            "ic": start,
            "to": end,
            "start": start,
            "end": end,
            "quality": quality,
            "complete": complete,
            "end_reason": reason,
            "on_threshold_n": threshold_value,
            "off_threshold_n": release_value,
            "full48": True,
        }
        if heel_cells and forefoot_cells:
            active_start = start + 0.2 * max(0.0, end - start)
            for timestamp, _total, sample in contact:
                if timestamp <= active_start:
                    continue
                heel = _roi_value(sample, heel_cells)
                fore = _roi_value(sample, forefoot_cells)
                if heel is not None and fore is not None and heel < threshold_value * 0.25 and fore >= threshold_value * 0.25:
                    interval["ho"] = timestamp
                    break
        intervals.append(interval)
        contact = []
        release_streak = []

    for sample in ordered:
        try:
            timestamp = float(sample["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(timestamp):
            continue
        total = _sample_total(sample)
        if last_valid_timestamp is not None and timestamp - last_valid_timestamp > max_gap:
            finish_contact("signal_gap")
            active_streak.clear()
            release_streak.clear()
            saw_unloaded = False
        if total is None:
            active_streak.clear()
            release_streak.clear()
            continue
        last_valid_timestamp = timestamp
        if contact:
            if total >= release_value:
                contact.append((timestamp, total, sample))
                release_streak.clear()
            else:
                release_streak.append((timestamp, total, sample))
                if (len(release_streak) >= required
                        and timestamp - release_streak[0][0] + 1e-9 >= minimum_unloaded):
                    finish_contact("released", release_streak[0][0])
                    saw_unloaded = True
            active_streak.clear()
        elif total >= threshold_value:
            active_streak.append((timestamp, total, sample))
            if len(active_streak) >= required:
                observed_onset = saw_unloaded
                contact.extend(active_streak)
                active_streak.clear()
        else:
            active_streak.clear()
            if total < release_value:
                saw_unloaded = True
    finish_contact("window_end")
    return intervals


def build_stride(contact_intervals: Sequence[Mapping] | Mapping, side: str = "unknown") -> dict:
    """Build a stride from one interval and its next same-side IC."""
    if isinstance(contact_intervals, Mapping):
        intervals = [contact_intervals]
    else:
        intervals = list(contact_intervals)
    valid = [item for item in intervals if item.get("detected", True) and item.get("ic") is not None]
    if not valid:
        return {"side": side, "quality": "invalid/missing", "ic": None, "to": None, "next_ic": None}
    first = valid[0]
    second = valid[1] if len(valid) > 1 else None
    return {
        "side": side,
        "quality": "valid" if second is not None else "incomplete_stride",
        "ic": float(first.get("ic", first.get("start"))),
        "to": float(first.get("to", first.get("end"))),
        "ho": first.get("ho"),
        "next_ic": None if second is None else float(second.get("ic", second.get("start"))),
        "contact": dict(first),
    }


def phase_windows(
    stride: Mapping,
    opposite_stride: Mapping | None = None,
    *,
    opposite_previous: Mapping | None = None,
    opposite_next: Mapping | None = None,
) -> dict:
    """Return side-specific phase windows in absolute timestamps.

    Loading response and midstance use the opposite-foot stride whose IC is
    immediately before this side's IC.  Terminal stance and pre-swing use
    the opposite-foot stride whose IC is immediately after this side's IC.
    The explicit references prevent selecting an event from the wrong
    half-cycle.

    When heel-off is unavailable, the terminal window is explicitly labelled
    as a fallback instead of pretending to be an anatomical HO event.
    """
    ic = stride.get("ic")
    to = stride.get("to")
    next_opposite = opposite_next if opposite_next is not None else opposite_stride
    opposite_ic = next_opposite.get("ic") if next_opposite else None
    opposite_previous_to = opposite_previous.get("to") if opposite_previous else None
    ho = stride.get("ho")
    result = {
        "loading": (
            ic,
            opposite_previous_to,
            "valid" if ic is not None and to is not None and opposite_previous_to is not None
            and ic <= opposite_previous_to <= to else "missing",
        ),
        "midstance": (
            opposite_previous_to,
            ho,
            "valid" if ic is not None and to is not None and opposite_previous_to is not None and ho is not None
            and ic <= opposite_previous_to <= ho <= to else "missing",
        ),
        "terminal_stance": (
            ho,
            opposite_ic,
            "valid" if ic is not None and to is not None and ho is not None and opposite_ic is not None
            and ic <= ho <= opposite_ic <= to else "missing",
        ),
        "pre_swing": (
            opposite_ic,
            to,
            "valid" if ic is not None and opposite_ic is not None and to is not None
            and ic <= opposite_ic <= to else "missing",
        ),
        "swing": (
            to,
            stride.get("next_ic"),
            "valid" if to is not None and stride.get("next_ic") is not None and stride.get("next_ic") >= to else "missing",
        ),
    }
    if ho is None and ic is not None and to is not None and to > ic:
        fallback_start = ic + 0.65 * (to - ic)
        result["terminal_stance_window"] = (fallback_start, to, "fallback_no_ho")
    return result


def _window_summary(samples: Sequence[Mapping], window, cells: Sequence[tuple[int, int]]) -> dict:
    if not window or window[0] is None or window[1] is None or window[1] < window[0] or window[2] == 'missing':
        return {"mean": None, "median": None, "peak": None, "peak_timestamp": None,
                "peak_position_percent": None, "impulse": None, "duration": 0.0,
                "valid_sample_count": 0, "quality": "invalid/missing", "reason": "phase_marker_missing"}
    return phase_summary(samples, window[0], window[1], cells)


def _phase_alignment(
    left_window, right_window, left_summary: Mapping, right_summary: Mapping,
    *, check_peak_position: bool = True,
) -> str:
    """Classify whether both sides have usable, ordered phase windows."""
    windows = (left_window, right_window)
    if any(
        not window
        or window[0] is None
        or window[1] is None
        or window[1] < window[0]
        or window[2] == "missing"
        for window in windows
    ):
        return "invalid"
    if any(summary.get("quality") != "valid" for summary in (left_summary, right_summary)):
        return "invalid"
    if any(summary.get("valid_sample_count", 0) < 2 for summary in (left_summary, right_summary)):
        return "warning"
    if any(window[2] == "fallback_no_ho" for window in windows):
        return "warning"
    left_peak = left_summary.get("peak_position_percent")
    right_peak = right_summary.get("peak_position_percent")
    if check_peak_position and left_peak is not None and right_peak is not None and abs(left_peak - right_peak) > 15.0:
        return "warning"
    return "ok"


def compare_phase_pair(
    left_samples: Sequence[Mapping],
    right_samples: Sequence[Mapping],
    left_stride: Mapping,
    right_stride: Mapping,
    *,
    pair_id: str = "",
    rois: Mapping[str, Sequence[tuple[int, int]]] | None = None,
    include_contact_summary: bool = False,
    left_previous_opposite: Mapping | None = None,
    right_previous_opposite: Mapping | None = None,
    left_next_opposite: Mapping | None = None,
    right_next_opposite: Mapping | None = None,
) -> list[dict]:
    """Calculate the planned phase/region rows for one left/right pair."""
    configured = rois or get_fsi_rois()
    validate_roi(configured, exclusive=False)
    left_windows = phase_windows(
        left_stride,
        right_stride,
        opposite_previous=left_previous_opposite,
        opposite_next=left_next_opposite,
    )
    right_windows = phase_windows(
        right_stride,
        left_stride,
        opposite_previous=right_previous_opposite,
        opposite_next=right_next_opposite,
    )
    # A complete contact can be compared even when anatomical phase markers
    # (opposite TO or heel-off) are missing. Keep these rows explicitly named
    # as whole-contact measurements, preserving the measured Newton values.
    left_windows['stance'] = (left_stride.get('ic'), left_stride.get('to'), 'valid')
    right_windows['stance'] = (right_stride.get('ic'), right_stride.get('to'), 'valid')
    rows: list[dict] = []

    def add(phase: str, region: str, window_name: str, metric: str = "mean") -> None:
        left_summary = _window_summary(left_samples, left_windows.get(window_name), configured[region])
        right_summary = _window_summary(right_samples, right_windows.get(window_name), configured[region])
        result = phase_fsi(left_summary, right_summary, metric, region=region)
        alignment = _phase_alignment(
            left_windows.get(window_name),
            right_windows.get(window_name),
            left_summary,
            right_summary,
            check_peak_position=phase != 'stance',
        )
        rows.append({
            "pair_id": pair_id,
            "phase": phase,
            "region": region,
            "metric": metric,
            "left_value": result["left"],
            "right_value": result["right"],
            "fsi": result["fsi"],
            "higher_side": result["higher_side"],
            "quality": result["quality"],
            "reason": result["reason"],
            "alignment": alignment,
            "left_peak_timestamp": left_summary.get("peak_timestamp"),
            "right_peak_timestamp": right_summary.get("peak_timestamp"),
            "left_peak_position_percent": left_summary.get("peak_position_percent"),
            "right_peak_position_percent": right_summary.get("peak_position_percent"),
            "peak_position_shift_percent": (
                None
                if left_summary.get("peak_position_percent") is None
                or right_summary.get("peak_position_percent") is None
                else round(abs(left_summary["peak_position_percent"] - right_summary["peak_position_percent"]), 2)
            ),
        })

    add("contact", "heel", "loading", "peak")
    add("midstance", "heel", "midstance", "mean")
    add("midstance", "forefoot", "midstance", "mean")
    add("midstance", "stance_sampled", "midstance", "mean")
    push_window = (
        "terminal_stance"
        if left_windows["terminal_stance"][2] == "valid" and right_windows["terminal_stance"][2] == "valid"
        else "terminal_stance_window"
    )
    add("push", "forefoot", push_window, "peak")
    if include_contact_summary:
        add("stance", "heel", "stance", "peak")
        add("stance", "forefoot", "stance", "peak")
    return rows


def summarize_phase_rows(rows: Sequence[Mapping]) -> list[dict]:
    """Aggregate valid pair FSI values without recomputing FSI from means."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        value = row.get("fsi")
        if (
            row.get("quality") == "valid"
            and row.get("alignment", "ok") == "ok"
            and value is not None
            and _finite(value)
        ):
            grouped.setdefault((str(row.get("phase")), str(row.get("region"))), []).append(float(value))
    result = []
    for (phase, region), values in sorted(grouped.items()):
        values.sort()
        count = len(values)
        mean = sum(values) / count
        middle = count // 2
        median_value = values[middle] if count % 2 else (values[middle - 1] + values[middle]) / 2
        variance = sum((value - mean) ** 2 for value in values) / (count - 1) if count > 1 else 0.0
        result.append({
            "phase": phase,
            "region": region,
            "fsi_mean": round(mean, 2),
            "fsi_median": round(median_value, 2),
            "fsi_sd": round(math.sqrt(variance), 2),
            "valid_pair_count": count,
            "max_asymmetry": round(max(100.0 - value for value in values), 2),
        })
    return result


class FsiSessionAnalyzer:
    """Bounded in-memory session recorder for V3 live and replay data."""

    def __init__(self, threshold: float = 5.0, debounce: int = 2, max_samples: int = 12000,
                 *, adaptive_contact: bool = True):
        self.threshold = float(threshold)
        self.debounce = max(1, int(debounce))
        self.max_samples = max(100, int(max_samples))
        self.adaptive_contact = bool(adaptive_contact)
        self.samples: dict[str, list[dict]] = {"left": [], "right": []}

    def reset(self) -> None:
        self.samples = {"left": [], "right": []}

    def add_sample(
        self,
        side: str,
        timestamp: float,
        matrix: Sequence[Sequence[float]],
        *,
        unit: str = "newton",
        valid: bool = True,
        quality: str = "valid",
    ) -> None:
        normalized_side = str(side).strip().lower()
        if normalized_side not in self.samples:
            raise ValueError("side must be left or right")
        sample = {
            "timestamp": float(timestamp),
            "matrix": [list(map(float, row)) for row in matrix],
            "unit": unit,
            "valid": bool(valid),
            "quality": quality,
        }
        bucket = self.samples[normalized_side]
        bucket.append(sample)
        if len(bucket) > self.max_samples:
            del bucket[: len(bucket) - self.max_samples]

    def _contact_events_for_samples(self, samples: Sequence[Mapping]) -> list[dict]:
        cells = get_fsi_rois()
        settings = contact_detection_settings(samples, self.threshold, adaptive=self.adaptive_contact)
        return detect_contact_intervals(
            samples,
            settings["on_n"],
            self.debounce,
            heel_cells=cells["heel"],
            forefoot_cells=cells["forefoot"],
            release_threshold=settings["off_n"],
            mark_incomplete=True,
        )

    def contact_events(self, side: str) -> list[dict]:
        normalized_side = str(side).strip().lower()
        if normalized_side not in self.samples:
            raise ValueError("side must be left or right")
        return self._contact_events_for_samples(self.samples[normalized_side])

    @staticmethod
    def _pair_events(left_events: Sequence[Mapping], right_events: Sequence[Mapping]) -> list[tuple[Mapping, Mapping]]:
        """Pair adjacent opposite contacts in event time, never by raw index."""
        events = sorted(
            [(float(event.get("ic")), "left", event) for event in left_events if event.get("complete", True)]
            + [(float(event.get("ic")), "right", event) for event in right_events if event.get("complete", True)],
            key=lambda item: item[0],
        )
        pending = None
        pairs: list[tuple[Mapping, Mapping]] = []
        for _timestamp, side, event in events:
            if pending is None:
                pending = (side, event)
                continue
            pending_side, pending_event = pending
            if side == pending_side:
                pending = (side, event)
                continue
            pairs.append(
                (pending_event, event)
                if pending_side == "left"
                else (event, pending_event)
            )
            pending = None
        return pairs

    def _pair_rows_for_samples(
        self,
        samples: Mapping[str, Sequence[Mapping]],
        left_events: Sequence[Mapping],
        right_events: Sequence[Mapping],
    ) -> list[dict]:
        left_events = [event for event in left_events if event.get("complete", True)]
        right_events = [event for event in right_events if event.get("complete", True)]
        valid_times = {
            side: sorted(float(sample["timestamp"]) for sample in samples[side]
                         if _finite(sample.get("timestamp")) and _sample_total(sample) is not None)
            for side in ("left", "right")
        }

        def continuous_pair(left_event: Mapping, right_event: Mapping) -> bool:
            start = min(float(left_event["ic"]), float(right_event["ic"]))
            end = max(float(left_event["to"]), float(right_event["to"]))
            # An opposite contact from another recording episode must not be
            # paired just because it is the next event in the list.
            for timestamps in valid_times.values():
                covered = [stamp for stamp in timestamps if start - 0.25 <= stamp <= end + 0.25]
                if (not covered or covered[0] > start + 0.25 or covered[-1] < end - 0.25
                        or any(second - first > 0.25 + 1e-9
                               for first, second in zip(covered, covered[1:]))):
                    return False
            return True

        rows: list[dict] = []
        for index, (left_event, right_event) in enumerate(self._pair_events(left_events, right_events), start=1):
            if not continuous_pair(left_event, right_event):
                continue
            left_index = left_events.index(left_event)
            right_index = right_events.index(right_event)
            left_stride = build_stride([left_event, *left_events[left_index + 1: left_index + 2]], "left")
            right_stride = build_stride([right_event, *right_events[right_index + 1: right_index + 2]], "right")
            # Loading response ends at the latest opposite-foot TO that
            # follows this side's IC.  Depending on which IC comes first,
            # that reference is either the previous opposite event or the
            # event in the current pair.
            if float(left_event.get("ic")) < float(right_event.get("ic")):
                left_previous_opposite = right_events[right_index - 1] if right_index > 0 else None
                left_next_opposite = right_event
                right_previous_opposite = left_event
                right_next_opposite = left_events[left_index + 1] if left_index + 1 < len(left_events) else None
            else:
                left_previous_opposite = right_event
                left_next_opposite = right_events[right_index + 1] if right_index + 1 < len(right_events) else None
                right_previous_opposite = left_events[left_index - 1] if left_index > 0 else None
                right_next_opposite = left_event
            # Phase boundaries also need continuous observations.  A valid
            # current pair cannot borrow TO/IC markers across an earlier or
            # later recording outage.
            if left_previous_opposite is not None and not continuous_pair(left_event, left_previous_opposite):
                left_previous_opposite = None
            if left_next_opposite is not None and not continuous_pair(left_event, left_next_opposite):
                left_next_opposite = None
            if right_previous_opposite is not None and not continuous_pair(right_event, right_previous_opposite):
                right_previous_opposite = None
            if right_next_opposite is not None and not continuous_pair(right_event, right_next_opposite):
                right_next_opposite = None
            rows.extend(compare_phase_pair(
                samples["left"], samples["right"],
                left_stride,
                right_stride,
                pair_id=f"BT{index}-BP{index}",
                include_contact_summary=True,
                left_previous_opposite=left_previous_opposite,
                right_previous_opposite=right_previous_opposite,
                left_next_opposite=left_next_opposite,
                right_next_opposite=right_next_opposite,
            ))
        return rows

    def pair_rows(self) -> list[dict]:
        left_events = self.contact_events("left")
        right_events = self.contact_events("right")
        return self._pair_rows_for_samples(self.samples, left_events, right_events)

    def _samples_for_window(self, window_seconds: float | None) -> dict[str, list[dict]]:
        if window_seconds is None:
            return self.samples
        window = float(window_seconds)
        if not math.isfinite(window) or window <= 0:
            raise ValueError("window_seconds must be a finite positive number")
        timestamps = [
            float(sample["timestamp"])
            for bucket in self.samples.values()
            for sample in bucket
            if _finite(sample.get("timestamp"))
        ]
        if not timestamps:
            return {side: [] for side in self.samples}
        cutoff = max(timestamps) - window
        return {
            side: [
                sample for sample in bucket
                if _finite(sample.get("timestamp")) and float(sample["timestamp"]) >= cutoff
            ]
            for side, bucket in self.samples.items()
        }

    def snapshot(self, *, window_seconds: float | None = None) -> dict:
        samples = self._samples_for_window(window_seconds)
        left_events = self._contact_events_for_samples(samples["left"])
        right_events = self._contact_events_for_samples(samples["right"])
        rows = self._pair_rows_for_samples(samples, left_events, right_events)
        return {
            "pairs": rows,
            "summary": summarize_phase_rows(rows),
            "contact_events": {"left": left_events, "right": right_events},
            "detection": {
                side: {
                    **contact_detection_settings(samples[side], self.threshold, adaptive=self.adaptive_contact),
                    "complete_contacts": sum(event.get("complete", True) for event in events),
                    "incomplete_contacts": sum(not event.get("complete", True) for event in events),
                }
                for side, events in (("left", left_events), ("right", right_events))
            },
            "sample_count": {side: len(samples[side]) for side in ("left", "right")},
            "stored_sample_count": {side: len(self.samples[side]) for side in ("left", "right")},
            "window_seconds": window_seconds,
            "threshold": self.threshold,
        }


# Timed standing reference
GRAVITY_M_S2 = 9.80665
SIDES_BY_MODE = {
    "both": ("left", "right"),
    "left": ("left",),
    "right": ("right",),
}


def _matrix_copy(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    if not isinstance(matrix, Sequence) or not matrix:
        raise ValueError("FSR matrix is empty")
    columns = None
    copied: list[list[float]] = []
    for row in matrix:
        if not isinstance(row, Sequence) or not row:
            raise ValueError("FSR matrix is not rectangular")
        if columns is None:
            columns = len(row)
        if len(row) != columns:
            raise ValueError("FSR matrix is not rectangular")
        values = [float(value) for value in row]
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("FSR matrix contains an invalid force")
        copied.append(values)
    return copied


def matrix_total(matrix: Sequence[Sequence[float]]) -> float:
    """Return the sum of all valid matrix cells in Newtons."""
    return sum(sum(row) for row in _matrix_copy(matrix))


def summarize_standing_reference(
    samples_by_side: Mapping[str, Sequence[Sequence[Sequence[float]]]],
    *,
    mode: str = "both",
    body_mass_kg: float | None = None,
) -> dict:
    """Summarize one short standing capture.

    ``representative_n`` is the sum of each selected side's median total. The
    peak is kept separately for the engineer's requested max-force check. A
    peak is not used as a calibration baseline because it is sensitive to one
    transient frame.
    """
    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in SIDES_BY_MODE:
        raise ValueError("mode must be both, left, or right")
    selected_sides = SIDES_BY_MODE[normalized_mode]
    side_result: dict[str, dict] = {}
    for side in selected_sides:
        raw_samples = samples_by_side.get(side, ())
        matrices = [_matrix_copy(sample) for sample in raw_samples]
        values = [sum(sum(row) for row in matrix) for matrix in matrices]
        if not matrices:
            return {
                "valid": False,
                "quality": f"missing_{side}",
                "mode": normalized_mode,
                "sample_count": {name: len(samples_by_side.get(name, ())) for name in ("left", "right")},
            }
        shape = (len(matrices[0]), len(matrices[0][0]))
        if any((len(matrix), len(matrix[0])) != shape for matrix in matrices):
            raise ValueError("standing reference matrices have different shapes")
        peak_matrix = [
            [round(max(matrix[row][column] for matrix in matrices), 3) for column in range(shape[1])]
            for row in range(shape[0])
        ]
        side_result[side] = {
            "sample_count": len(values),
            "median_n": round(float(median(values)), 3),
            "peak_n": round(max(values), 3),
            "min_n": round(min(values), 3),
            "peak_matrix": peak_matrix,
        }

    representative_n = sum(item["median_n"] for item in side_result.values())
    peak_n = sum(item["peak_n"] for item in side_result.values())
    expected_n = None
    if body_mass_kg is not None and str(body_mass_kg).strip() != "":
        mass = float(body_mass_kg)
        if not math.isfinite(mass) or mass <= 0:
            raise ValueError("body_mass_kg must be a positive finite number")
        expected_n = round(mass * GRAVITY_M_S2, 3)

    result = {
        "valid": True,
        "quality": "valid",
        "mode": normalized_mode,
        "sample_count": {name: len(samples_by_side.get(name, ())) for name in ("left", "right")},
        "sides": side_result,
        "representative_n": round(representative_n, 3),
        "peak_n": round(peak_n, 3),
        "expected_n": expected_n,
        "representative_ratio_percent": (
            round(100.0 * representative_n / expected_n, 2) if expected_n else None
        ),
        "peak_ratio_percent": round(100.0 * peak_n / expected_n, 2) if expected_n else None,
    }
    return result


class StandingReferenceCapture:
    """Collect a bounded, timed standing trial without touching other analyzers."""

    def __init__(self, duration_seconds: float = 5.0):
        duration = float(duration_seconds)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("duration_seconds must be a positive finite number")
        self.duration_seconds = duration
        self.active = False
        self.mode = "both"
        self.body_mass_kg: float | None = None
        self.started_at: float | None = None
        self.samples: dict[str, list[list[list[float]]]] = {"left": [], "right": []}
        self.last_result: dict | None = None

    def start(self, mode: str = "both", body_mass_kg: float | None = None, started_at: float = 0.0) -> None:
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in SIDES_BY_MODE:
            raise ValueError("mode must be both, left, or right")
        if body_mass_kg is not None:
            mass = float(body_mass_kg)
            if not math.isfinite(mass) or mass <= 0:
                raise ValueError("body_mass_kg must be a positive finite number")
            self.body_mass_kg = mass
        else:
            self.body_mass_kg = None
        self.mode = normalized_mode
        self.started_at = float(started_at)
        self.samples = {"left": [], "right": []}
        self.last_result = None
        self.active = True

    def add_sample(self, side: str, matrix: Sequence[Sequence[float]]) -> bool:
        normalized_side = str(side).strip().lower()
        if not self.active or normalized_side not in self.samples:
            return False
        if normalized_side not in SIDES_BY_MODE[self.mode]:
            return False
        self.samples[normalized_side].append(_matrix_copy(matrix))
        return True

    def ready(self, now: float) -> bool:
        return self.active and self.started_at is not None and float(now) - self.started_at >= self.duration_seconds

    def finish(self, now: float | None = None, *, force: bool = False) -> dict:
        if not self.active:
            raise ValueError("standing reference is not active")
        if not force and now is not None and not self.ready(now):
            raise ValueError("standing reference duration has not elapsed")
        result = summarize_standing_reference(
            self.samples,
            mode=self.mode,
            body_mass_kg=self.body_mass_kg,
        )
        self.active = False
        self.last_result = result
        return result

    def cancel(self) -> None:
        self.active = False
        self.started_at = None
        self.samples = {"left": [], "right": []}


DEFAULT_TARGET_IP = "127.0.0.1"
# Specimen-specific experimental calibration. NOT validated full-range force.
# Old 85 cells retained; 11 retested cells fit median of per-placement medians.
# Retest baseline: elapsed 8–25s; windows trim first 2s and last 1s of >4N runs.
# Retest source SHA256: fa6d70f994d9893835e4e2fa3963e37ac63c57d7a71f5b40dc2be7d566ba2f5c
BUILTIN_CELL_CALIBRATIONS = {
    'right': {
        'version': 1,
        'id': "right-20260928-repeat-median-v2",
        'side': "right",
        'status': "provisional_single_point_not_validated",
        'cells': [
            [{"baseline_n":0.5430203073875562,"gain":1.8013744974704866},{"baseline_n":0.5270696104787869,"gain":1.564884242034935},{"baseline_n":0.4839518626325734,"gain":1.5675683237163553},{"baseline_n":0.5434151153546811,"gain":1.6008665557551043}],
            [{"baseline_n":0.26570412789584275,"gain":1.3603235524351602},{"baseline_n":0.5905929718897815,"gain":1.1660506137019246},{"baseline_n":0.6940988165033128,"gain":1.1232186763109593},{"baseline_n":0.728401844311139,"gain":1.4677557058745}],
            [{"baseline_n":0.49955472296195863,"gain":1.3569836015003485},{"baseline_n":0.6721615393219712,"gain":1.1273455058423436},{"baseline_n":0.6678919481743208,"gain":1.1299192465070786},{"baseline_n":0.7671502706009586,"gain":1.1269080197942116}],
            [{"baseline_n":0.5181801332351436,"gain":1.3118674464354878},{"baseline_n":0.561591285443074,"gain":1.39535164968139},{"baseline_n":0.7047692372828768,"gain":0.9196655950333367},{"baseline_n":0.5423607896696118,"gain":1.1076027023753994}],
            [{"baseline_n":0.4846638466278961,"gain":1.046033111176853},{"baseline_n":0.5319404463860747,"gain":1.5316153146532927},{"baseline_n":0.5133557746012489,"gain":0.8643267473097201},{"baseline_n":0.5768396217016878,"gain":0.9018983748087714}],
            [{"baseline_n":0.4618621634481451,"gain":1.237275849522209},{"baseline_n":0.6736356082049602,"gain":0.9830445271228363},{"baseline_n":0.7194774980498975,"gain":1.2358393827655232},{"baseline_n":0.7173010386474274,"gain":0.9986097961597793}],
            [{"baseline_n":0.36255170304822415,"gain":1.2286019581624001},{"baseline_n":0.30830691040810343,"gain":1.2271102332121395},{"baseline_n":0.5907326446104195,"gain":1.1440729094919235},{"baseline_n":0.6625523393594691,"gain":0.9578127419575424}],
            [{"baseline_n":0.3969327862705283,"gain":1.250727630230439},{"baseline_n":0.5788256517653116,"gain":1.159123817826331},{"baseline_n":0.6473372872191471,"gain":1.1494744758015447},{"baseline_n":0.6941028146859205,"gain":1.141373477151277}],
            [{"baseline_n":0.45882628342558396,"gain":0.9785493092987164},{"baseline_n":0.5074731083692766,"gain":1.3436421880460516},{"baseline_n":0.6298149822299066,"gain":1.1282433342895721},{"baseline_n":0.5090087825049349,"gain":1.1407255899069726}],
            [{"baseline_n":0.5095629528286183,"gain":1.3539094542531194},{"baseline_n":0.6181493517247665,"gain":1.0407702287439655},{"baseline_n":0.6700779511275171,"gain":1.4900730614199158},{"baseline_n":0.6268323898517693,"gain":1.1777344578778153}],
            [{"baseline_n":0.41288389127063196,"gain":1.2954490088242783},{"baseline_n":0.5284537118455944,"gain":1.4234374250491602},{"baseline_n":0.8262914943962365,"gain":1.2576707270313392},{"baseline_n":0.8250167150100495,"gain":1.4953846236339419}],
            [{"baseline_n":0.47875750065882877,"gain":1.4332826326492871},{"baseline_n":0.6050177654872857,"gain":1.270663606196705},{"baseline_n":0.44600001639512393,"gain":1.2546366643795694},{"baseline_n":0.5809428208348044,"gain":1.3735846659920514}],
        ],
    },
    'left': {
        'version': 1,
        'id': "left-20260928-repeat-median-v2",
        'side': "left",
        'status': "provisional_single_point_not_validated",
        'cells': [
            [{"baseline_n":0.6747425939608492,"gain":2.2015896767379872},{"baseline_n":0.7293564252340441,"gain":1.870214316689304},{"baseline_n":0.9092848676350717,"gain":1.4917295000762558},{"baseline_n":0.7814698458101734,"gain":1.5386909517927039}],
            [{"baseline_n":0.7514151531921152,"gain":1.075874329175584},{"baseline_n":0.7156104030547352,"gain":1.4161544979147653},{"baseline_n":0.7432409188690317,"gain":1.5726115225135602},{"baseline_n":0.6598197633364733,"gain":1.5606816095650975}],
            [{"baseline_n":0.7792955572390036,"gain":1.290963330204433},{"baseline_n":0.7752298515643177,"gain":1.41868070963739},{"baseline_n":0.7490703797951669,"gain":1.6660799426394477},{"baseline_n":0.6795122597733931,"gain":1.3160971569399258}],
            [{"baseline_n":0.7746726305287819,"gain":1.077748305930369},{"baseline_n":1.6285659696224144,"gain":1.2281289813811367},{"baseline_n":0.9601863947424305,"gain":1.0765353523175751},{"baseline_n":0.6670238016332709,"gain":1.4377994112449306}],
            [{"baseline_n":0.7522853860380336,"gain":1.322559166995866},{"baseline_n":0.7328249780304796,"gain":0.9664212188101504},{"baseline_n":0.7194898408532964,"gain":1.1482205497527311},{"baseline_n":0.7334759295766622,"gain":1.3948443179957803}],
            [{"baseline_n":0.7790283866260328,"gain":1.1600315877932428},{"baseline_n":0.8050897091232136,"gain":1.2735109880224953},{"baseline_n":0.7134501222002907,"gain":1.2669196232691864},{"baseline_n":0.6572089427145351,"gain":1.3015426673607335}],
            [{"baseline_n":0.7228875582295817,"gain":1.1259507192260358},{"baseline_n":0.7095040457169591,"gain":1.3437847460808445},{"baseline_n":0.6822353087969032,"gain":1.5348804358770227},{"baseline_n":0.723991406968182,"gain":1.1988830056350632}],
            [{"baseline_n":0.7354589971085301,"gain":1.4507465239211834},{"baseline_n":0.8727116147288391,"gain":1.5020899536900616},{"baseline_n":0.7403439562692353,"gain":1.0780095521738848},{"baseline_n":1.2377455978654868,"gain":1.350456628883831}],
            [{"baseline_n":0.7885064732080234,"gain":1.3045739959593095},{"baseline_n":0.7453282179088803,"gain":1.261561849667097},{"baseline_n":0.6500113634464999,"gain":1.1374369468231464},{"baseline_n":0.6170607176872606,"gain":1.2274979324014361}],
            [{"baseline_n":0.7919427355127138,"gain":1.1877269170641123},{"baseline_n":0.7414806932906217,"gain":1.0616803390853882},{"baseline_n":0.7275988959147199,"gain":1.1345616139053516},{"baseline_n":0.7242314554132802,"gain":1.2868168535148774}],
            [{"baseline_n":0.7999246867226895,"gain":1.510591029137182},{"baseline_n":0.792103751688313,"gain":1.469825934956434},{"baseline_n":0.9983579123462586,"gain":1.1186534301311135},{"baseline_n":1.1311767021202301,"gain":1.1735022893328924}],
            [{"baseline_n":0.7553508713397734,"gain":1.3003324665777165},{"baseline_n":0.8922631851296361,"gain":1.2793985252416855},{"baseline_n":0.8083502046752187,"gain":1.3331189301577855},{"baseline_n":0.6532643421449854,"gain":1.2764652277242219}],
        ],
    },
}
RETEST_CALIBRATION_AUDIT = {
    'right': [
        {"row":1,"column":1,"windows_s":[[33.406,39.203],[44.015,46.422],[65.25,69.234],[83.328,86.531]],"trial_medians_n":[8.038301111204364,8.476684935679167,9.362187401587416,8.592886277775207],"corrected_range_n":[13.501807691375685,15.886622692422526]},
        {"row":1,"column":2,"windows_s":[[54.75,58.547],[76.125,78.14],[92.703,100.531],[105.093,107.937],[113.64,120.875]],"trial_medians_n":[11.302577593674616,10.329852690235672,8.562316701416488,8.97379721471808,9.726575754958587],"corrected_range_n":[12.574231553465461,16.862422642824797]},
        {"row":2,"column":4,"windows_s":[[127.453,137.968],[145.453,151.922],[158.453,161.062],[165.218,174.656]],"trial_medians_n":[8.290727307639491,11.637122408121316,10.253391743286961,10.819976394556999],"corrected_range_n":[11.099646348480212,16.01133685132288]},
        {"row":4,"column":2,"windows_s":[[180.968,186.218],[203.562,210.703],[226.593,238.656]],"trial_medians_n":[13.060180667211565,9.753676692331588,10.878820066651862],"corrected_range_n":[12.82619153651412,17.43992731254097]},
        {"row":4,"column":3,"windows_s":[[191.265,198.203],[215.922,221.187],[243.453,256.109]],"trial_medians_n":[15.304606495178763,16.937998777099533,16.358461489930598],"corrected_range_n":[13.4269680191727,14.929142704048221]},
        {"row":5,"column":4,"windows_s":[[261.75,269.453],[276.359,285.5],[292.156,300.703],[309.484,327.5],[339.343,356.515]],"trial_medians_n":[16.538906526470644,14.354452015477417,16.38304782294074,17.956320721117045,17.61319539551387],"corrected_range_n":[12.426006226691518,15.674525758582472]},
        {"row":10,"column":3,"windows_s":[[365.484,373.047],[393.906,398.39],[439.172,443.781],[457.437,462.875]],"trial_medians_n":[10.661414219323756,9.919694816316706,11.852681627826172,10.001501851861056],"corrected_range_n":[13.782604919273739,16.662896495183972]},
        {"row":10,"column":4,"windows_s":[[378.125,383.109],[448.547,452.922],[467.328,473.765]],"trial_medians_n":[13.696783952695487,12.259961513939263,12.850438571792603],"corrected_range_n":[13.700737022379808,15.39293231835505]},
    ],
    'left': [
        {"row":1,"column":1,"windows_s":[[481.078,488.515],[506.218,515.453],[533.578,546.359]],"trial_medians_n":[7.213727742787607,6.922017886387136,7.394752658861412],"corrected_range_n":[13.753936791546003,14.79470478646045]},
        {"row":1,"column":3,"windows_s":[[493.922,501.047],[520.531,527.531],[551.422,572.922]],"trial_medians_n":[10.559936811746976,10.267004081401904,11.54252168634013],"corrected_range_n":[13.959185804606372,15.861913043759335]},
        {"row":11,"column":2,"windows_s":[[580.062,594.859],[602.531,608.531],[622.328,632.047],[642.547,650.937],[662.328,674.312]],"trial_medians_n":[9.641150793692146,12.319712934570607,10.586571149235427,11.063144770537374,9.696329598548708],"corrected_range_n":[13.006558841986752,16.943578945042344]},
    ],
}
# Quick provisional refit from 2.jsonl: ONLY 1468g; H1C1 first placement rejected by user.
# Stable means (P90-P10)/median <= 10%; trim 3s start / 1s end; no full-range validation.
RIGHT_REFIT_20260929 = [
    {"row":1,"column":1,"old_gain":1.8013744974704866,"gain":1.4365065005780648,"measured_n":18.0527407555016,"window_s":[14.5,21.10900000000038]},
    {"row":1,"column":2,"old_gain":1.564884242034935,"gain":1.4367073196156284,"measured_n":15.680526621515458,"window_s":[26.875,30.5]},
    {"row":1,"column":4,"old_gain":1.6008665557551043,"gain":1.3431685392270685,"measured_n":17.15818523449628,"window_s":[47.01599999999962,51.01599999999962]},
    {"row":2,"column":1,"old_gain":1.3603235524351602,"gain":1.5455113592442062,"measured_n":12.671170864065056,"window_s":[60.79700000000048,63.78099999999904]},
    {"row":2,"column":2,"old_gain":1.1660506137019246,"gain":1.0339769979123605,"measured_n":16.23503598450967,"window_s":[69.9369999999999,73.84399999999914]},
    {"row":2,"column":3,"old_gain":1.1232186763109593,"gain":1.330271642825215,"measured_n":12.155440836053705,"window_s":[83.70299999999952,86.90599999999904]},
    {"row":2,"column":4,"old_gain":1.4677557058745,"gain":1.7129611154059536,"measured_n":12.335393385002318,"window_s":[93.3119999999999,97.875]},
    {"row":4,"column":2,"old_gain":1.39535164968139,"gain":1.1002386228311762,"measured_n":18.257592723986008,"window_s":[161.375,165.26599999999962]},
    {"row":4,"column":4,"old_gain":1.1076027023753994,"gain":1.2744452088276381,"measured_n":12.511505434762931,"window_s":[186.46899999999914,193.76599999999962]},
    {"row":5,"column":1,"old_gain":1.046033111176853,"gain":1.2101359353788095,"measured_n":12.443942779336378,"window_s":[199.79700000000048,206.73400000000038]},
    {"row":5,"column":2,"old_gain":1.5316153146532927,"gain":1.2860242982344152,"measured_n":17.145385610539762,"window_s":[212.79700000000048,218.53099999999904]},
    {"row":5,"column":4,"old_gain":0.9018983748087714,"gain":1.0468656383169839,"measured_n":12.402618651747202,"window_s":[240.09399999999914,245.70299999999952]},
    {"row":6,"column":3,"old_gain":1.2358393827655232,"gain":1.1469495969277146,"measured_n":15.511879733073954,"window_s":[281.125,287.03099999999904]},
    {"row":6,"column":4,"old_gain":0.9986097961597793,"gain":1.1731139013987668,"measured_n":12.25469119655275,"window_s":[292.03099999999904,300.3590000000004]},
    {"row":7,"column":1,"old_gain":1.2286019581624001,"gain":0.889373502606888,"measured_n":19.887204888722017,"window_s":[306.2029999999995,311.5159999999996]},
    {"row":7,"column":4,"old_gain":0.9578127419575424,"gain":1.08751804990221,"measured_n":12.679171248410471,"window_s":[335.7659999999996,340.9220000000005]},
    {"row":8,"column":2,"old_gain":1.159123817826331,"gain":1.0168707114538187,"measured_n":16.41008468761365,"window_s":[363.6090000000004,371.2970000000005]},
    {"row":8,"column":3,"old_gain":1.1494744758015447,"gain":1.101382406136647,"measured_n":15.02477332686384,"window_s":[377.53099999999904,383.4840000000004]},
    {"row":9,"column":1,"old_gain":0.9785493092987164,"gain":1.234976592978956,"measured_n":11.406981037091072,"window_s":[402,409.0619999999999]},
    {"row":9,"column":2,"old_gain":1.3436421880460516,"gain":1.202130843286199,"measured_n":16.090836522417284,"window_s":[414.1869999999999,423.8119999999999]},
    {"row":9,"column":3,"old_gain":1.1282433342895721,"gain":1.3131823003836878,"measured_n":12.368712277614296,"window_s":[429.0779999999995,436]},
    {"row":9,"column":4,"old_gain":1.1407255899069726,"gain":1.0424271108951562,"measured_n":15.753687184794577,"window_s":[442.0470000000005,464.4220000000005]},
    {"row":10,"column":1,"old_gain":1.3539094542531194,"gain":1.263289222802502,"measured_n":15.428850144309788,"window_s":[470.5619999999999,483.0470000000005]},
    {"row":10,"column":2,"old_gain":1.0407702287439655,"gain":1.1986073842779723,"measured_n":12.500421090726785,"window_s":[487.8119999999999,495.34399999999914]},
    {"row":11,"column":2,"old_gain":1.4234374250491602,"gain":0.9214735109774514,"measured_n":22.238334372543342,"window_s":[539.625,547.7659999999996]},
    {"row":11,"column":3,"old_gain":1.2576707270313392,"gain":1.0910354892496121,"measured_n":16.59490636091746,"window_s":[552.4369999999999,557.125]},
    {"row":11,"column":4,"old_gain":1.4953846236339419,"gain":1.2709252104420932,"measured_n":16.938683265029972,"window_s":[561.9689999999991,566.030999999999]},
    {"row":12,"column":1,"old_gain":1.4332826326492871,"gain":1.2247248394321049,"measured_n":16.847677611919643,"window_s":[572.030999999999,578.0779999999995]},
    {"row":12,"column":3,"old_gain":1.2546366643795694,"gain":1.1963720688832922,"measured_n":15.097270650370902,"window_s":[598.125,604.530999999999]},
    {"row":12,"column":4,"old_gain":1.3735846659920514,"gain":1.1326531054550906,"measured_n":17.458432376000264,"window_s":[609.5619999999999,612.5159999999996]},
]
for _fit in RIGHT_REFIT_20260929:
    BUILTIN_CELL_CALIBRATIONS['right']['cells'][_fit['row']-1][_fit['column']-1]['gain'] = _fit['gain']
BUILTIN_CELL_CALIBRATIONS['right']['id'] = 'right-20260929-single-load-v3'
# Provisional three-anchor refit: check.jsonl, filtered ADC -> legacy N minus
# existing baseline. Only the two loading holds fit the curve; unloading is
# a same-cycle check, NOT independent validation. No new live shoe tare.
# Targets assume 1468g and approximately 333.3g; small weight not certified.
# Outside the measured interval retain previous gain, not a validated range.
# Source SHA256: b91b473856b7d2a82988f9cbe89e34b10c98cf0577aa552d9f3cb5e782c9dafe
RIGHT_THREE_POINT_20260929 = [
    {"row":1,"column":1,"points_n":[[0,0],[9.360848730714954,14.3961622],[11.138778653745558,17.664718645]],"windows_s":[[10,13],[19,23],[25,27]],"return_input_n":9.465529657083524},
    {"row":1,"column":2,"points_n":[[0,0],[10.95228890695742,14.3961622],[13.446527279254138,17.664718645]],"windows_s":[[36,40],[44,48],[50,53]],"return_input_n":10.841306469025277},
    {"row":1,"column":3,"points_n":[[0,0],[9.06936886403129,14.3961622],[10.978806319801134,17.664718645]],"windows_s":[[64,68],[75,80],[83,86]],"return_input_n":9.60731440020786},
    {"row":1,"column":4,"points_n":[[0,0],[9.750660732815716,14.3961622],[12.964217215607764,17.664718645]],"windows_s":[[97,102],[108,112],[114,117]],"return_input_n":10.026271061072462},
    {"row":2,"column":2,"points_n":[[0,0],[15.303278005210892,14.3961622],[17.811387064152022,17.664718645]],"windows_s":[[160,165],[172,177],[181,185]],"return_input_n":14.719255495690785},
    {"row":2,"column":4,"points_n":[[0,0],[8.679548698323968,14.3961622],[11.147654522453768,17.664718645]],"windows_s":[[242,248],[254,260],[264,268]],"return_input_n":8.941786386325193},
    {"row":3,"column":1,"points_n":[[0,0],[11.647684112260489,14.3961622],[14.23632636429668,17.664718645]],"windows_s":[[279,283],[290,295],[300,304]],"return_input_n":11.943312050125922},
    {"row":3,"column":2,"points_n":[[0,0],[12.147310868739337,14.3961622],[14.972892849897024,17.664718645]],"windows_s":[[322,327],[332,337],[340,344]],"return_input_n":12.640077580210868},
    {"row":3,"column":3,"points_n":[[0,0],[14.404163942269767,14.3961622],[16.833834671068036,17.664718645]],"windows_s":[[353,357],[364,369],[373,377]],"return_input_n":15.018556033129153},
    {"row":3,"column":4,"points_n":[[0,0],[12.290458688098859,14.3961622],[14.523766623050351,17.664718645]],"windows_s":[[393,398],[405,410],[415,419]],"return_input_n":12.73075013503053},
    {"row":4,"column":1,"points_n":[[0,0],[8.19813054869444,14.3961622],[10.976423453994107,17.664718645]],"windows_s":[[430,435],[440,445],[449,453]],"return_input_n":8.940100608771683},
    {"row":4,"column":2,"points_n":[[0,0],[10.24632007129055,14.3961622],[13.319469827031629,17.664718645]],"windows_s":[[470,474],[478,482],[486,489]],"return_input_n":10.48904934420391},
    {"row":4,"column":3,"points_n":[[0,0],[15.939218820419802,14.3961622],[17.48691199452025,17.664718645]],"windows_s":[[502,507],[514,519],[523,527]],"return_input_n":16.125300741837634},
    {"row":4,"column":4,"points_n":[[0,0],[11.586443532095123,14.3961622],[14.912070874995232,17.664718645]],"windows_s":[[535,539],[544,548],[551,554]],"return_input_n":12.170237640459884},
    {"row":5,"column":1,"points_n":[[0,0],[12.727532573402522,14.3961622],[15.75759057304759,17.664718645]],"windows_s":[[566,570],[576,580],[582,586]],"return_input_n":13.388409941321797},
    {"row":5,"column":2,"points_n":[[0,0],[8.371156269437689,14.3961622],[11.00393055472572,17.664718645]],"windows_s":[[598,602],[611,616],[620,623]],"return_input_n":8.822749370992303},
    {"row":5,"column":3,"points_n":[[0,0],[14.447428755492831,14.3961622],[17.164376507495135,17.664718645]],"windows_s":[[634,638],[643,647],[650,654]],"return_input_n":14.110702174156314},
    {"row":6,"column":2,"points_n":[[0,0],[13.184073717035979,14.3961622],[15.409655686766007,17.664718645]],"windows_s":[[737,741],[748,753],[757,760]],"return_input_n":12.91142155080393},
]
RIGHT_THREE_POINT_RETEST_CELLS = [(2, 1), (2, 3), (5, 4), (6, 1)]
for _fit in RIGHT_THREE_POINT_20260929:
    BUILTIN_CELL_CALIBRATIONS['right']['cells'][_fit['row']-1][_fit['column']-1]['points_n'] = _fit['points_n']
BUILTIN_CELL_CALIBRATIONS['right']['id'] = 'right-20260929-three-point-v4'
BUILTIN_CELL_CALIBRATIONS['right']['status'] = 'provisional_mixed_three_point_not_validated'
CELL_CALIBRATIONS = BUILTIN_CELL_CALIBRATIONS
DEFAULT_TARGET_PORT = 8765
DEFAULT_SEND_RATE_HZ = 20
DEFAULT_BAUDRATE = 9600
DEFAULT_SERIAL_TIMEOUT = 0.5
MIN_FORCE = 30.0
MAX_FORCE = 5500.0
CHART_WINDOW_SECONDS = 30.0
CHART_MAX_POINTS = 6000
FSI_CONTACT_THRESHOLD_N = 5.0
FSI_DEBOUNCE_SAMPLES = 2
# FSI retains the full log for export, but the live table only needs recent
# gait cycles. Keeping this window bounded prevents redraw work from growing
# with the length of a test session.
FSI_LIVE_WINDOW_SECONDS = 10.0
FSI_REFRESH_INTERVAL_SECONDS = 0.5
CHART_COLORS = {
    "left": "#2563eb",
    "right": "#ef4444",
    "heel": "#2563eb",
    "midfoot": "#0f9d8a",
    "forefoot": "#ea6a14",
}


def is_outgoing_bluetooth_port(port_info):
    """Windows Bluetooth SPP uses LOCALMFG&0002 for the connect-out port."""
    return "LOCALMFG&0002" in str(getattr(port_info, "hwid", "")).upper()


def selectable_fsr_ports(port_infos):
    """Return ports that can actually connect to FSR modules, never SPP input."""
    infos = list(port_infos)
    outgoing = [item for item in infos if is_outgoing_bluetooth_port(item)]
    if outgoing:
        return outgoing
    return [
        item for item in infos
        if "LOCALMFG&0000" not in str(getattr(item, "hwid", "")).upper()
    ]

INDEX_MAP_RR = [
    [  36,     24,     12,     0  ],
    [  47,     35,     23,     11 ],
    [  37,     25,     13,     1  ],
    [  46,     34,     22,     10 ],
    [  38,     26,     14,     2  ],
    [  45,     33,     21,     9  ],
    [  39,     27,     15,     3  ],
    [  44,     32,     20,     8  ],
    [  40,     28,     16,     4  ],
    [  43,     31,     19,     7  ],
    [  41,     29,     17,     5  ],
    [  42,     30,     18,     6  ],
]

INDEX_MAP_LL = [row[::-1] for row in INDEX_MAP_RR]


def get_force_color(value, min_val=MIN_FORCE, max_val=MAX_FORCE):
    if value < min_val:
        return "#111827"

    t = min(max((value - min_val) / (max_val - min_val), 0.0), 1.0)

    if t < 0.5:
        red = 255
        green = int(255 * (t / 0.5))
        blue = 0
    else:
        red = int(255 * ((1.0 - t) / 0.5))
        green = 255
        blue = 0

    return f"#{red:02x}{green:02x}{blue:02x}"


def validate_matrix(matrix):
    if not isinstance(matrix, list) or not matrix:
        raise ValueError("Ma trận không hợp lệ")
    if not isinstance(matrix[0], list) or not matrix[0]:
        raise ValueError("Ma trận không hợp lệ")

    columns = len(matrix[0])
    normalized = []
    for row in matrix:
        if not isinstance(row, list) or len(row) != columns:
            raise ValueError("Cột không nhất quán")
        normalized_row = []
        for value in row:
            if not isinstance(value, (int, float)):
                raise ValueError("Giá trị phải là số")
            if value < 0:
                raise ValueError("Giá trị không được âm")
            normalized_row.append(float(value))
        normalized.append(normalized_row)
    return normalized


def unit_label(unit):
    return {
        'raw_adc': 'ADC thô',
        'newton': 'Newton (N, ước tính)',
    }.get(str(unit).strip().lower(), 'ADC thô')


def calibration_metadata(side, unit):
    profile = CELL_CALIBRATIONS.get(side) if unit == 'newton' else None
    return {
        'calibration_id': profile['id'] if profile else None,
        'calibration_status': profile['status'] if profile else None,
    }


def matrix_for_unit(raw_adc_matrix, unit, side=None, profile=None):
    '''Convert raw ADC values to the unit selected for preview and UDP.'''
    raw_adc_matrix = validate_matrix(raw_adc_matrix)
    if str(unit).strip().lower() == 'newton':
        force_matrix, _, _ = matrix_to_newton(raw_adc_matrix, 'raw_adc')
        selected_profile = profile if profile is not None else CELL_CALIBRATIONS.get(side)
        if selected_profile is not None and side == selected_profile.get('side'):
            return apply_cell_calibration(force_matrix, side, selected_profile)
        return force_matrix
    return [row[:] for row in raw_adc_matrix]


def color_range_for_unit(unit):
    if str(unit).strip().lower() == 'newton':
        return 0.05, 80.0
    return MIN_FORCE, MAX_FORCE


def parse_hardware_frame(values_list, side, expected_rows=None, expected_columns=None):
    total_values = len(values_list)
    if total_values == 0:
        raise ValueError("Không tìm thấy dữ liệu")

    if total_values == 48:
        mapping = INDEX_MAP_LL if side == "left" else INDEX_MAP_RR
        matrix = []
        for row_indices in mapping:
            row_vals = [values_list[idx] for idx in row_indices]
            matrix.append(row_vals)
    else:
        rows = expected_rows or 12
        cols = expected_columns or 4
        if total_values != rows * cols:
            raise ValueError(
                f"Nhận được {total_values} giá trị, cần {rows * cols}"
            )
        matrix = [
            values_list[r * cols : (r + 1) * cols]
            for r in range(rows)
        ]

    return validate_matrix(matrix), side


def matrix_summary(matrix):
    total = sum(sum(row) for row in matrix)
    if total <= 0:
        return total, None, None
    weighted_x = 0.0
    weighted_y = 0.0
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            weighted_x += x * value
            weighted_y += y * value
    return total, weighted_x / total, weighted_y / total


def matrix_region_totals(matrix):
    """Split a 12-row insole like the main backend: forefoot 0:4, mid 4:9, heel 9:12."""
    rows = validate_matrix(matrix)
    row_count = len(rows)
    forefoot_end = max(1, round(row_count * 4 / 12))
    midfoot_end = max(forefoot_end + 1, round(row_count * 9 / 12))
    midfoot_end = min(midfoot_end, row_count)

    def total(first_row, last_row):
        return sum(sum(row) for row in rows[first_row:last_row])

    heel = total(midfoot_end, row_count)
    midfoot = total(forefoot_end, midfoot_end)
    forefoot = total(0, forefoot_end)
    return {
        "heel": heel,
        "midfoot": midfoot,
        "forefoot": forefoot,
        "total": heel + midfoot + forefoot,
    }


def nice_axis_max(value, minimum):
    """Round a chart ceiling to a readable 1/2/5 × 10^n value."""
    target = max(float(value) * 1.12, float(minimum))
    exponent = 10 ** math.floor(math.log10(target)) if target > 0 else 1.0
    normalized = target / exponent
    step = 1.0 if normalized <= 1 else 2.0 if normalized <= 2 else 5.0 if normalized <= 5 else 10.0
    return step * exponent


def build_packet(device_id, side, unit, sequence, matrix):
    return {
        "type": "fsr_matrix",
        "version": 1,
        "device_id": device_id,
        "side": side,
        "unit": unit,
        "sequence": sequence,
        "timestamp_ms": int(time.time() * 1000),
        "rows": len(matrix),
        "columns": len(matrix[0]),
        "values": matrix,
    }


class ShoeZero:
    """Incremental session tare for mechanical preload in the shoe/insole.

    Each click captures the latest fresh frame immediately. Accepted rounds
    keep a per-cell maximum baseline until the operator explicitly clears it.
    All state is locked because two serial workers and Tk share this object.
    """
    fresh_seconds = 0.5
    buffer_seconds = 3.0

    def __init__(self):
        self.lock = threading.RLock()
        self.profiles = {}
        self.latest = {}
        self.recent = {'left': deque(), 'right': deque()}
        self.pending = None
        self.revision = 0

    def state(self):
        with self.lock:
            return tuple(sorted(self.profiles)), self.pending is not None

    def progress(self):
        with self.lock:
            return {
                side: int(self.profiles.get(side, {}).get('round_count', 0))
                for side in ('left', 'right')
            }

    def is_current(self, metadata):
        with self.lock:
            return metadata.get('zero_revision') == self.revision

    def reset(self):
        """Cancel a pending capture while retaining accepted calibration."""
        self.cancel_pending()

    def cancel_pending(self):
        with self.lock:
            self.pending = None
            self.revision += 1

    def clear_all(self):
        with self.lock:
            self.profiles.clear()
            self.latest.clear()
            self.recent = {'left': deque(), 'right': deque()}
            self.pending = None
            self.revision += 1

    def start(self, sides, now):
        with self.lock:
            sides = tuple(sides)
            if not sides or any(s not in ('left', 'right') for s in sides):
                raise ValueError('Chọn chân trái, phải hoặc cả hai.')
            if self.pending is not None:
                raise ValueError('Đang thu mẫu zero.')
            if any(s not in self.latest or not 0 <= now-self.latest[s] <= self.fresh_seconds
                   for s in sides):
                raise ValueError('Thiếu dữ liệu mới ở chân đã chọn. Kiểm tra kết nối FSR.')
            self.pending = {'start': now, 'sides': sides}

    def process(self, side, matrix, now):
        values = validate_matrix(matrix)
        if any(not math.isfinite(v) for row in values for v in row):
            raise ValueError('Dữ liệu FSR không hữu hạn; không thể lấy zero.')
        with self.lock:
            self.latest[side] = now
            recent = self.recent.setdefault(side, deque())
            recent.append((now, [row[:] for row in values]))
            cutoff = now - self.buffer_seconds
            while recent and recent[0][0] < cutoff:
                recent.popleft()
            profile = self.profiles.get(side)
            meta = {'zero_applied': profile is not None,
                    'zero_revision': self.revision,
                    'zero_collecting': self.pending is not None,
                    'zero_round_count': int(profile.get('round_count', 0)) if profile else 0}
            if profile is None:
                return values, meta
            baseline, noise = profile['baseline'], profile['noise']
            if len(values) != len(baseline) or any(len(a) != len(b) for a, b in zip(values, baseline)):
                raise ValueError('Kích thước FSR thay đổi; huỷ zero rồi lấy lại.')
            result = [[max(0.0, v-b) if v-b > n else 0.0
                       for v, b, n in zip(row, base, band)]
                      for row, base, band in zip(values, baseline, noise)]
            meta.update(zero_baseline_n=[r[:] for r in baseline],
                        zero_noise_n=[r[:] for r in noise],
                        zero_method=profile.get('method', 'lift_round_history_max_v4'),
                        zero_median_baseline_n=[r[:] for r in profile.get('median_baseline', baseline)],
                        zero_redistribution_warnings=profile.get('redistribution_warnings', []))
            return result, meta

    def _adjacency(self, rows, columns):
        return [
            ((row, column), (row, column + 1))
            for row in range(rows)
            for column in range(columns - 1)
        ]

    def capture_now(self, sides, now):
        """Start and commit one snapshot atomically, without waiting for frames."""
        with self.lock:
            self.start(sides, now)
            try:
                return self.record_round(now)
            finally:
                self.pending = None

    def record_round(self, now):
        with self.lock:
            pending = self.pending
            if pending is None:
                raise ValueError('Không có lượt calib đang chạy.')
            summaries = {}
            reasons = {}
            for side in pending['sides']:
                recent = self.recent.get(side, ())
                latest = next(
                    ((timestamp, matrix) for timestamp, matrix in reversed(recent)
                     if 0 <= now - timestamp <= self.fresh_seconds),
                    None,
                )
                if latest is None:
                    reasons[side] = 'không có dữ liệu mới. Kiểm tra kết nối rồi bấm lại.'
                    continue
                timestamp, matrix = latest
                summaries[side] = {
                    'matrix': [row[:] for row in matrix],
                    'noise': [[0.02 for _ in row] for row in matrix],
                    'captured_at': timestamp,
                }

            if reasons:
                result = self.progress()
                result.update(accepted=False, reasons=reasons, warnings=[])
                return result

            fitted = {}
            for side, summary in summaries.items():
                matrix = summary['matrix']
                rows, columns = len(matrix), len(matrix[0])
                merged = merge_zero_round(
                    self.profiles.get(side, {}).get('history', []),
                    matrix,
                    summary['noise'],
                    adjacency=self._adjacency(rows, columns),
                )
                fitted[side] = {
                    'baseline': merged['baseline'],
                    'median_baseline': merged['median_baseline'],
                    'noise': merged['noise'],
                    'history': merged['history'],
                    'round_count': merged['round_count'],
                    'method': 'instant_snapshot_history_max_v1',
                    'redistribution_warnings': merged['redistribution_warnings'],
                    'updated_at': now,
                }

            # Atomic: failure on either foot leaves all previous profiles intact.
            self.profiles.update(fitted)
            self.pending = None
            self.revision += 1
            result = self.progress()
            result.update(
                accepted=True,
                reasons={},
                warnings={side: fitted[side]['redistribution_warnings'] for side in fitted},
                zeroed_matrices={
                    side: [[0.0 for _ in row] for row in summary['matrix']]
                    for side, summary in summaries.items()
                },
                captured_at={side: summary['captured_at'] for side, summary in summaries.items()},
            )
            return result

    def finish(self, now):
        """Compatibility alias for callers that finish the current round."""
        return self.record_round(now)


class FSRTransmitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FSR Matrix Transmitter V3 · FSI theo pha")
        self.root.geometry("1280x700")
        self.root.minsize(1000, 600)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.serial_connections = {}
        self.serial_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.sequence = 0
        self.running = False
        self.workers = []
        self.active_channels = set()
        self.connected_channels = set()
        self.detected_sides = {}
        self.frame_counts = {1: 0, 2: 0}
        self.ema_alpha = tk.DoubleVar(value=0.20)
        self.ema_alpha_value = 0.20
        self.ema_label_text = tk.StringVar(value='EMA alpha: 0.20')
        self.smoothed_matrices = {}
        self.last_raw_matrices = {}
        self.shoe_zero = ShoeZero()
        self.zero_button_text = tk.StringVar(value='Calib/Zero cả hai chân')
        self.zero_status = tk.StringVar(value='Nhấc chân khỏi sàn rồi bấm Ghi lại / Zero ngay (Newton)')
        self.chart_history = {
            "left": deque(maxlen=CHART_MAX_POINTS),
            "right": deque(maxlen=CHART_MAX_POINTS),
        }
        self.chart_started_at = time.monotonic()
        self.chart_unit = "newton"
        self.chart_redraw_pending = False
        self.total_chart_canvas = None
        self.region_chart_canvas = None
        self.fsi_analyzer = (
            FsiSessionAnalyzer(FSI_CONTACT_THRESHOLD_N, FSI_DEBOUNCE_SAMPLES)
            if FsiSessionAnalyzer is not None else None
        )
        self.fsi_last_refresh = 0.0
        self.fsi_last_result = None
        self.fsi_status = tk.StringVar(value="FSI: đang chờ đủ cặp bước")
        self.fsi_register_text = tk.StringVar(value="Đăng ký ROI sau khi căn dấu chân")
        self.fsi_roi_registered = False
        self.fsi_tree = None
        self.fsi_summary_tree = None
        self.fsi_trend_canvas = None

        self.standing_reference = (
            StandingReferenceCapture(duration_seconds=5.0)
            if StandingReferenceCapture is not None else None
        )
        self.standing_reference_after_id = None
        self.standing_mass_kg = tk.StringVar(value="")
        self.standing_status = tk.StringVar(
            value="Đứng kiểm tra 5 giây · tuỳ chọn nhập cân nặng để xem tỷ lệ"
        )
        self.standing_result = None
        self.standing_reference_history = []

        self.log_lock = threading.Lock()
        self.log_handle = None
        self.log_path = None
        self.log_started_at = None
        self.log_sample_count = 0

        self.playback_records = []
        self.playback_index = 0
        self.playback_after_id = None
        self.playback_path = None

        self.preview_state = {
            "left": {"rects": [], "texts": [], "shape": (0, 0), "size": (0, 0)},
            "right": {"rects": [], "texts": [], "shape": (0, 0), "size": (0, 0)},
        }

        self.target_ip = tk.StringVar(value=DEFAULT_TARGET_IP)
        self.target_port = tk.StringVar(value=str(DEFAULT_TARGET_PORT))
        self.device_id = tk.StringVar(value="fsr-device-01")
        self.side = tk.StringVar(value="right")
        self.unit = tk.StringVar(value="newton")
        self._selected_unit = self.unit.get()
        self.preview_unit_label = tk.StringVar(
            value=f'Đơn vị hiển thị/gửi: {unit_label(self._selected_unit)}'
        )
        self.unit.trace_add('write', self._on_unit_change)
        self.rate_hz = tk.StringVar(value=str(DEFAULT_SEND_RATE_HZ))

        self.com_port_1 = tk.StringVar()
        self.com_port_2 = tk.StringVar()
        self.baudrate = tk.StringVar(value=str(DEFAULT_BAUDRATE))
        self.matrix_rows = tk.StringVar(value="12")
        self.matrix_columns = tk.StringVar(value="4")

        self.status = tk.StringVar(value="Sẵn sàng")
        self.summary_left = tk.StringVar(value="12\u00d74 | Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u")
        self.summary_right = tk.StringVar(value="12\u00d74 | Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u")
        self.bt_button_text = tk.StringVar(value="Kết nối 2 FSR")
        self.module_code = tk.StringVar(value="--")
        self.channel_status_1 = tk.StringVar(value="Chưa kết nối")
        self.channel_status_2 = tk.StringVar(value="Chưa kết nối")
        self.log_button_text = tk.StringVar(value="Bắt đầu lưu log")
        self.log_status = tk.StringVar(value="Chưa lưu log")
        self.playback_status = tk.StringVar(value="Chưa mở log")
        self.connection_toggle_text = tk.StringVar(value="▼ Thu gọn thiết lập kết nối")
        self.connection_panel_collapsed = False
        self.connection_settings_body = None
        self.main_notebook = None
        self.total_chart_tab = None

        self._configure_ui_style()
        self._build_ui()
        self.refresh_com_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    DISABLED_PORT_OPTION = "-- Không dùng (Tắt kênh này) --"

    def _configure_ui_style(self):
        """Apply the compact FSR Gait Monitor dashboard visual system."""
        self.root.configure(background="#f8fafc")
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f8fafc")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Header.TFrame", background="#1e3a8a")
        style.configure("Status.TFrame", background="#f1f5f9")
        style.configure("TLabel", background="#f8fafc", foreground="#1e3a8a", font=("Segoe UI", 9))
        style.configure("Card.TLabel", background="#ffffff", foreground="#1e3a8a", font=("Segoe UI", 9))
        style.configure("Muted.TLabel", background="#f1f5f9", foreground="#334155", font=("Segoe UI", 8))
        style.configure("TLabelframe", background="#ffffff", foreground="#1e3a8a", bordercolor="#dbeafe", relief="solid")
        style.configure("TLabelframe.Label", background="#ffffff", foreground="#1e3a8a", font=("Segoe UI", 9, "bold"))
        style.configure("TButton", background="#1e40af", foreground="#ffffff", bordercolor="#1e40af", padding=(10, 4), font=("Segoe UI", 9, "bold"))
        style.map("TButton", background=[("active", "#2563eb"), ("pressed", "#1e3a8a"), ("disabled", "#e2e8f0")], foreground=[("disabled", "#94a3b8")])
        style.configure("Header.TButton", background="#2563eb", foreground="#ffffff", bordercolor="#3b82f6", padding=(10, 4), font=("Segoe UI", 9, "bold"))
        style.map("Header.TButton", background=[("active", "#3b82f6"), ("pressed", "#1d4ed8")])
        style.configure("Connect.TButton", background="#059669", foreground="#ffffff", bordercolor="#10b981", padding=(10, 4), font=("Segoe UI", 9, "bold"))
        style.map("Connect.TButton", background=[("active", "#10b981"), ("pressed", "#047857")])
        style.configure("Secondary.TButton", background="#e2e8f0", foreground="#1e293b", bordercolor="#cbd5e1", padding=(8, 4), font=("Segoe UI", 9, "bold"))
        style.map("Secondary.TButton", background=[("active", "#cbd5e1"), ("pressed", "#94a3b8")], foreground=[("disabled", "#94a3b8")])
        style.configure("TNotebook", background="#f8fafc", borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background="#e2e8f0", foreground="#475569", padding=(14, 6), font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#1e40af")], foreground=[("selected", "#ffffff")])
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground="#1e3a8a", rowheight=25, bordercolor="#dbeafe", font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#1e40af", foreground="#ffffff", relief="flat", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#1e3a8a")])
        style.configure("TEntry", fieldbackground="#ffffff", foreground="#1e3a8a", bordercolor="#cbd5e1", padding=4)
        style.configure("TCombobox", fieldbackground="#ffffff", foreground="#1e3a8a", bordercolor="#cbd5e1", padding=3)
        style.configure("Horizontal.TScale", background="#ffffff", troughcolor="#dbeafe")
        style.configure("Header.TLabel", background="#1e3a8a", foreground="#ffffff", font=("Segoe UI", 12, "bold"))
        style.configure("Subheader.TLabel", background="#1e3a8a", foreground="#bfdbfe", font=("Segoe UI", 8))
        style.configure("Badge.TLabel", background="#1e3a8a", foreground="#93c5fd", font=("Segoe UI", 9, "bold"))

    def _popup_menu_below(self, button, items):
        """Show a dropdown popup menu right below the given button."""
        menu = tk.Menu(
            self.root,
            tearoff=0,
            font=("Segoe UI", 9),
            background="#ffffff",
            foreground="#1e293b",
            activebackground="#dbeafe",
            activeforeground="#1e3a8a",
            relief="solid",
            bd=1,
        )
        for item in items:
            if item == "---":
                menu.add_separator()
            else:
                label, command, state = item
                menu.add_command(label=label, command=command, state=state)
        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height() + 2
        menu.tk_popup(x, y)

    def _build_ui(self):
        self._ports_initialized = False
        self._ui_frame_pending = {1: False, 2: False}
        self._last_reported_module = {1: None, 2: None}
        self.standing_button_text = tk.StringVar(value="⏱ Đo đứng 5s ▾")
        self.zero_button_text.set("🎯 Calib / Zero ▾")
        self.bt_button_text.set("🔌 Kết nối FSR ▾")
        self.connection_panel_collapsed = True
        self.connection_toggle_text.set("⚙ Hiện thiết lập kết nối ▾")
        self.json_panel_visible = False
        self.json_toggle_text = tk.StringVar(value="🧪 Mở gửi thử JSON")

        container = ttk.Frame(self.root, padding=6)
        container.pack(fill=tk.BOTH, expand=True)
        self.main_container = container

        # 1. HEADER GỌN (Tiêu đề bên trái + Nút Kết nối nhanh 1/2 chân & Nút Thiết lập bên phải)
        header = ttk.Frame(container, style="Header.TFrame", padding=(12, 6))
        header.pack(fill=tk.X, pady=(0, 6))

        title_box = ttk.Frame(header, style="Header.TFrame")
        title_box.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(title_box, text="FSR GAIT MONITOR / V3", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="Theo dõi tải 1 hoặc 2 chân · FSI theo pha · dữ liệu 48 ô",
            style="Subheader.TLabel",
        ).pack(anchor="w")

        header_right = ttk.Frame(header, style="Header.TFrame")
        header_right.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Button(
            header_right,
            textvariable=self.connection_toggle_text,
            style="Header.TButton",
            command=self._toggle_connection_panel,
        ).pack(side=tk.RIGHT, padx=(6, 0), pady=2)
        self.header_bt_button = ttk.Button(
            header_right,
            textvariable=self.bt_button_text,
            style="Connect.TButton",
            command=lambda: self._on_connect_button_click(self.header_bt_button),
        )
        self.header_bt_button.pack(side=tk.RIGHT, padx=(8, 0), pady=2)
        ttk.Label(header_right, textvariable=self.module_code, style="Badge.TLabel").pack(
            side=tk.RIGHT, padx=(4, 6)
        )
        ttk.Label(header_right, text="Đã nhận:", style="Subheader.TLabel").pack(side=tk.RIGHT)

        # 2. PANEL THIẾT LẬP KẾT NỐI (Gắn trực tiếp vào container, mặc định ẩn để không chiếm chỗ)
        self.connection_settings_body = ttk.Frame(container)
        self.connection_settings_body.columnconfigure(0, weight=1)
        self.connection_settings_body.columnconfigure(1, weight=1)

        bluetooth = ttk.LabelFrame(
            self.connection_settings_body,
            text="Bluetooth Serial - hỗ trợ 1 chân hoặc đồng thời 2 chân",
            padding=8,
        )
        bluetooth.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 2))
        bluetooth.columnconfigure(1, weight=1)

        ttk.Label(bluetooth, text="FSR 1", style="Card.TLabel").grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.com_box_1 = ttk.Combobox(bluetooth, textvariable=self.com_port_1, width=26, state="readonly")
        self.com_box_1.grid(row=0, column=1, padx=(0, 6), sticky="ew")
        ttk.Label(bluetooth, textvariable=self.channel_status_1, width=18, style="Card.TLabel").grid(
            row=0, column=2, padx=(0, 6), sticky="w"
        )
        ttk.Button(bluetooth, text="Quét lại", style="Secondary.TButton", command=self.refresh_com_ports).grid(
            row=0, column=3, sticky="ew"
        )

        ttk.Label(bluetooth, text="FSR 2", style="Card.TLabel").grid(
            row=1, column=0, padx=(0, 6), pady=(6, 0), sticky="w"
        )
        self.com_box_2 = ttk.Combobox(bluetooth, textvariable=self.com_port_2, width=26, state="readonly")
        self.com_box_2.grid(row=1, column=1, padx=(0, 6), pady=(6, 0), sticky="ew")
        ttk.Label(bluetooth, textvariable=self.channel_status_2, width=18, style="Card.TLabel").grid(
            row=1, column=2, padx=(0, 6), pady=(6, 0), sticky="w"
        )
        self.bt_button = ttk.Button(
            bluetooth,
            textvariable=self.bt_button_text,
            command=lambda: self._on_connect_button_click(self.bt_button),
        )
        self.bt_button.grid(row=1, column=3, pady=(6, 0), sticky="ew")

        bt_extra = ttk.Frame(bluetooth, style="Card.TFrame")
        bt_extra.grid(row=2, column=0, columnspan=4, pady=(6, 0), sticky="w")
        ttk.Label(bt_extra, text="Baudrate:", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Combobox(
            bt_extra,
            textvariable=self.baudrate,
            values=("9600", "19200", "38400", "57600", "115200"),
            width=8,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 14))
        ttk.Label(bt_extra, text="Hàng:", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Entry(bt_extra, textvariable=self.matrix_rows, width=4).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(bt_extra, text="Cột:", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Entry(bt_extra, textvariable=self.matrix_columns, width=4).pack(side=tk.LEFT, padx=(4, 0))

        connection = ttk.LabelFrame(
            self.connection_settings_body,
            text="Đích nhận UDP & Bộ lọc",
            padding=8,
        )
        connection.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 2))
        connection.columnconfigure(1, weight=1)
        connection.columnconfigure(3, weight=1)

        ttk.Label(connection, text="IP:", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(connection, textvariable=self.target_ip, width=14).grid(
            row=0, column=1, padx=(4, 10), sticky="ew"
        )
        ttk.Label(connection, text="Port:", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(connection, textvariable=self.target_port, width=7).grid(
            row=0, column=3, padx=(4, 10), sticky="ew"
        )
        ttk.Label(connection, text="Tần số (Hz):", style="Card.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Entry(connection, textvariable=self.rate_hz, width=6).grid(
            row=0, column=5, padx=(4, 0), sticky="ew"
        )

        ttk.Label(connection, text="Device ID:", style="Card.TLabel").grid(
            row=1, column=0, pady=(6, 0), sticky="w"
        )
        ttk.Entry(connection, textvariable=self.device_id, width=14).grid(
            row=1, column=1, padx=(4, 10), pady=(6, 0), sticky="ew"
        )
        ttk.Label(connection, text="Đơn vị:", style="Card.TLabel").grid(
            row=1, column=2, pady=(6, 0), sticky="w"
        )
        ttk.Combobox(
            connection, textvariable=self.unit, values=("raw_adc", "newton"), width=10, state="readonly"
        ).grid(row=1, column=3, padx=(4, 10), pady=(6, 0), sticky="ew")
        ttk.Label(connection, text="Chân thử:", style="Card.TLabel").grid(
            row=1, column=4, pady=(6, 0), sticky="w"
        )
        ttk.Combobox(
            connection, textvariable=self.side, values=("left", "right"), width=7, state="readonly"
        ).grid(row=1, column=5, padx=(4, 0), pady=(6, 0), sticky="ew")

        filter_row = ttk.Frame(connection, style="Card.TFrame")
        filter_row.grid(row=2, column=0, columnspan=6, pady=(6, 0), sticky="ew")
        ttk.Label(filter_row, textvariable=self.preview_unit_label, style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Scale(
            filter_row,
            from_=0.01,
            to=1.0,
            variable=self.ema_alpha,
            command=self._on_alpha_change,
            length=130,
        ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Label(filter_row, textvariable=self.ema_label_text, style="Card.TLabel").pack(side=tk.RIGHT)

        # 3. THANH CÔNG CỤ HỢP NHẤT 1 HÀNG (Gom Log + Calib Zero + Đo đứng 5s)
        toolbar = ttk.LabelFrame(container, text="Bảng điều khiển nhanh", padding=(8, 5))
        toolbar.pack(fill=tk.X, pady=(0, 4))
        self.toolbar = toolbar

        # Cụm 1: Log & Biểu đồ
        ttk.Button(toolbar, textvariable=self.log_button_text, command=self.toggle_logging).pack(side=tk.LEFT)
        self.log_menu_button = ttk.Button(
            toolbar,
            text="📂 Phát & Xóa Log ▾",
            style="Secondary.TButton",
            command=self._on_log_menu_click,
        )
        self.log_menu_button.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=12, pady=2)

        # Calib menu selects a side; the adjacent button records zero now.
        self.zero_menu_button = ttk.Button(
            toolbar,
            textvariable=self.zero_button_text,
            command=self._on_zero_button_click,
        )
        self.zero_menu_button.pack(side=tk.LEFT)
        self.zero_record_button = ttk.Button(
            toolbar,
            text="✔ Ghi lại / Zero ngay",
            style="Secondary.TButton",
            command=self._record_zero_round,
            state="disabled",
        )
        self.zero_record_button.pack(side=tk.LEFT, padx=(6, 0))
        # Giữ tham chiếu tương thích ngược
        self.zero_left_button = self.zero_menu_button
        self.zero_right_button = self.zero_menu_button
        self.zero_clear_button = self.zero_menu_button

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=12, pady=2)

        # Cụm 3: Kiểm tra đứng 5s (Ô nhập cân nặng + 1 nút chọn menu duy nhất)
        ttk.Label(toolbar, text="Cân nặng (kg):", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Entry(toolbar, textvariable=self.standing_mass_kg, width=6).pack(side=tk.LEFT, padx=(4, 6))
        self.standing_menu_button = ttk.Button(
            toolbar,
            textvariable=self.standing_button_text,
            command=self._on_standing_button_click,
        )
        self.standing_menu_button.pack(side=tk.LEFT)
        self.standing_both_button = self.standing_menu_button
        self.standing_left_button = self.standing_menu_button
        self.standing_right_button = self.standing_menu_button
        self.standing_cancel_button = self.standing_menu_button

        # Trạng thái Log nằm gọn bên phải thanh công cụ
        ttk.Label(toolbar, textvariable=self.playback_status, style="Card.TLabel").pack(side=tk.RIGHT)
        ttk.Label(toolbar, text="·", style="Card.TLabel").pack(side=tk.RIGHT, padx=4)
        ttk.Label(toolbar, textvariable=self.log_status, style="Card.TLabel").pack(side=tk.RIGHT)

        # 4. THANH TRẠNG THÁI GỌN (Hiển thị trạng thái Zero, Đo đứng và Cổng COM)
        status_strip = ttk.Frame(container, style="Status.TFrame", padding=(8, 4))
        status_strip.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(status_strip, text="Zero:", style="Muted.TLabel", font=("Segoe UI", 8, "bold")).pack(
            side=tk.LEFT
        )
        ttk.Label(status_strip, textvariable=self.zero_status, style="Muted.TLabel").pack(
            side=tk.LEFT, padx=(4, 14)
        )
        ttk.Label(status_strip, text="|  Đo đứng:", style="Muted.TLabel", font=("Segoe UI", 8, "bold")).pack(
            side=tk.LEFT
        )
        ttk.Label(status_strip, textvariable=self.standing_status, style="Muted.TLabel").pack(
            side=tk.LEFT, padx=(4, 10)
        )
        ttk.Label(status_strip, textvariable=self.status, style="Muted.TLabel").pack(side=tk.RIGHT)

        # 5. NOTEBOOK CHÍNH (Chiếm toàn bộ không gian còn lại)
        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True)
        self.main_notebook = notebook

        map_tab = ttk.Frame(notebook, padding=4)
        total_chart_tab = ttk.Frame(notebook, padding=6)
        region_chart_tab = ttk.Frame(notebook, padding=6)
        fsi_tab = ttk.Frame(notebook, padding=6)
        self.total_chart_tab = total_chart_tab
        notebook.add(map_tab, text="Bản đồ lực")
        notebook.add(total_chart_tab, text="Tổng tải")
        notebook.add(region_chart_tab, text="Ba vùng bàn chân")
        notebook.add(fsi_tab, text="FSI theo pha")

        # Tab FSI theo pha
        fsi_controls = ttk.LabelFrame(
            fsi_tab,
            text="FSI theo pha · vùng cố định trên 48 ô",
            padding=6,
        )
        fsi_controls.pack(fill=tk.BOTH, expand=True)
        fsi_top = ttk.Frame(fsi_controls, style="Card.TFrame")
        fsi_top.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(
            fsi_top,
            textvariable=self.fsi_register_text,
            command=self._toggle_fsi_registration,
        ).pack(side=tk.LEFT)
        ttk.Label(
            fsi_top,
            text="Gót: 42,43,46,47 · Mũi: 6,7,8,10,11,12,14,15,16 · 100% = cân bằng",
            style="Card.TLabel",
        ).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(fsi_controls, textvariable=self.fsi_status, style="Card.TLabel").pack(fill=tk.X, pady=(0, 4))

        fsi_body = ttk.Frame(fsi_controls, style="Card.TFrame")
        fsi_body.pack(fill=tk.X)
        fsi_columns = ("pair", "phase", "region", "left", "right", "fsi", "quality")
        self.fsi_tree = ttk.Treeview(fsi_body, columns=fsi_columns, show="headings", height=6)
        fsi_headers = {
            "pair": "Cặp bước", "phase": "Pha", "region": "Vùng",
            "left": "Trái", "right": "Phải", "fsi": "FSI %", "quality": "Chất lượng",
        }
        for column in fsi_columns:
            self.fsi_tree.heading(column, text=fsi_headers[column])
            self.fsi_tree.column(column, width=92 if column not in ("phase", "region") else 140, anchor="center")
        self.fsi_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.fsi_summary_tree = ttk.Treeview(
            fsi_body,
            columns=("phase", "region", "mean", "median", "count"),
            show="headings",
            height=6,
        )
        for column, title in (
            ("phase", "Pha"), ("region", "Vùng"), ("mean", "TB"), ("median", "Trung vị"), ("count", "n")
        ):
            self.fsi_summary_tree.heading(column, text=title)
            self.fsi_summary_tree.column(column, width=88 if column != "phase" else 115, anchor="center")
        self.fsi_summary_tree.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        self.fsi_trend_canvas = tk.Canvas(
            fsi_controls,
            height=130,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#cbd5e1",
        )
        self.fsi_trend_canvas.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        # Tab Bản đồ lực (Có nút ẩn/hiện khung JSON gửi thử)
        self.map_toolbar = ttk.Frame(map_tab)
        self.map_toolbar.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(
            self.map_toolbar,
            textvariable=self.json_toggle_text,
            style="Secondary.TButton",
            command=self._toggle_json_panel,
        ).pack(side=tk.LEFT)
        self.insole_display_mode = "force_active"
        self.insole_mirror_swapped = False
        self.insole_mode_text = tk.StringVar(value="🔥 Hiển thị: Số lực (khi có tải) ▾")
        self.insole_mode_button = ttk.Button(
            self.map_toolbar,
            textvariable=self.insole_mode_text,
            command=self._on_insole_mode_click,
        )
        self.insole_mode_button.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(
            self.map_toolbar,
            text="⇄ Đảo chiều đối xứng 2 chân",
            style="Secondary.TButton",
            command=self._toggle_insole_mirror,
        ).pack(side=tk.LEFT, padx=(6, 0))
        self.map_toolbar_hint = ttk.Label(
            self.map_toolbar,
            text="Bản đồ tấm cảm ứng bàn chân + Tâm áp lực CoP trực quan.",
        )
        self.map_toolbar_hint.pack(side=tk.LEFT, padx=(8, 0))

        body = ttk.Frame(map_tab)
        body.pack(fill=tk.BOTH, expand=True)

        self.editor_frame = ttk.LabelFrame(body, text="Ma trận FSR dạng JSON (gửi thử)", padding=8)
        editor_actions = ttk.Frame(self.editor_frame, style="Card.TFrame")
        editor_actions.pack(fill=tk.X, pady=(0, 6))
        self.json_action_button = ttk.Button(
            editor_actions,
            text="⚡ Thao tác gửi thử ▾",
            command=self._on_json_action_click,
        )
        self.json_action_button.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.matrix_text = tk.Text(self.editor_frame, width=26, wrap=tk.NONE, font=("Consolas", 10))
        self.matrix_text.pack(fill=tk.BOTH, expand=True)
        sample_12x4 = "[\n" + ",\n".join(["  [0, 0, 0, 0]"] * 12) + "\n]"
        self.matrix_text.insert("1.0", sample_12x4)

        self.preview_frame = ttk.LabelFrame(
            body, text="Xem trước lực từng điểm - 2 chân", padding=8
        )
        self.preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.preview_frame.columnconfigure(0, weight=1)
        self.preview_frame.columnconfigure(1, weight=1)
        self.preview_frame.rowconfigure(0, weight=1)

        left_preview = ttk.LabelFrame(self.preview_frame, text="CHÂN TRÁI (LL)", padding=5)
        left_preview.grid(row=0, column=0, padx=(0, 4), sticky="nsew")
        self.canvas_left = tk.Canvas(left_preview, background="#111827", highlightthickness=0)
        left_preview.columnconfigure(0, weight=1)
        left_preview.rowconfigure(0, weight=1)
        self.canvas_left.configure(width=1, height=1)
        self.canvas_left.grid(row=0, column=0, sticky="nsew")
        self.canvas_left.bind("<Configure>", lambda event: self._resize_matrix("left"))
        ttk.Label(
            left_preview, textvariable=self.summary_left, anchor="w", justify=tk.LEFT, style="Card.TLabel"
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))

        right_preview = ttk.LabelFrame(self.preview_frame, text="CHÂN PHẢI (RR)", padding=5)
        right_preview.grid(row=0, column=1, padx=(4, 0), sticky="nsew")
        self.canvas_right = tk.Canvas(right_preview, background="#111827", highlightthickness=0)
        right_preview.columnconfigure(0, weight=1)
        right_preview.rowconfigure(0, weight=1)
        self.canvas_right.configure(width=1, height=1)
        self.canvas_right.grid(row=0, column=0, sticky="nsew")
        self.canvas_right.bind("<Configure>", lambda event: self._resize_matrix("right"))
        ttk.Label(
            right_preview, textvariable=self.summary_right, anchor="w", justify=tk.LEFT, style="Card.TLabel"
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))

        # Tab Biểu đồ
        self.total_chart_canvas = tk.Canvas(
            total_chart_tab,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#cbd5e1",
        )
        self.total_chart_canvas.pack(fill=tk.BOTH, expand=True)
        self.total_chart_canvas.bind("<Configure>", self._on_chart_resize)

        self.region_chart_canvas = tk.Canvas(
            region_chart_tab,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#cbd5e1",
        )
        self.region_chart_canvas.pack(fill=tk.BOTH, expand=True)
        self.region_chart_canvas.bind("<Configure>", self._on_chart_resize)

        empty_matrix = [[0.0] * 4 for _ in range(12)]
        self.root.after(80, self.draw_matrix, empty_matrix, "left")
        self.root.after(80, self.draw_matrix, empty_matrix, "right")
        self.root.after(120, self._redraw_charts)

    def _refresh_layout_after_toggle(self):
        self.root.update_idletasks()
        self._resize_matrix("left")
        self._resize_matrix("right")
        self._schedule_chart_redraw()

    def _on_connect_button_click(self, button=None):
        if self.running:
            self._stop_stream("Đã ngắt kết nối FSR")
            return
        target_btn = button or self.header_bt_button
        dev1 = self._selected_com_device(self.com_port_1, allow_empty=True)
        dev2 = self._selected_com_device(self.com_port_2, allow_empty=True)
        label1 = f"1️⃣ Chỉ kết nối FSR 1 ({dev1})" if dev1 else "1️⃣ Chỉ kết nối FSR 1 (chưa chọn cổng)"
        label2 = f"2️⃣ Chỉ kết nối FSR 2 ({dev2})" if dev2 else "2️⃣ Chỉ kết nối FSR 2 (chưa chọn cổng)"
        state1 = "normal" if dev1 else "disabled"
        state2 = "normal" if dev2 else "disabled"
        both_state = "normal" if (dev1 or dev2) else "disabled"
        self._popup_menu_below(
            target_btn,
            [
                ("👣 Kết nối cả 2 cổng (Tự bỏ qua chân tắt)", lambda: self.start_stream((1, 2)), both_state),
                (label1, lambda: self.start_stream((1,)), state1),
                (label2, lambda: self.start_stream((2,)), state2),
                "---",
                ("🔄 Quét lại cổng COM Bluetooth", self.refresh_com_ports, "normal"),
            ],
        )

    def _toggle_json_panel(self):
        self.json_panel_visible = not self.json_panel_visible
        if self.json_panel_visible:
            self.editor_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 6), before=self.preview_frame)
            self.json_toggle_text.set("🧪 Ẩn gửi thử JSON")
        else:
            self.editor_frame.pack_forget()
            self.json_toggle_text.set("🧪 Mở gửi thử JSON")
        self.root.after_idle(self._refresh_layout_after_toggle)

    def _on_json_action_click(self):
        self._popup_menu_below(
            self.json_action_button,
            [
                ("👁 Xem ma trận trên bản đồ", self.preview_manual_matrix, "normal"),
                ("📤 Gửi 1 frame qua UDP", self.send_manual_once, "normal"),
            ],
        )

    def _on_log_menu_click(self):
        stop_state = "normal" if self.playback_after_id is not None else "disabled"
        self._popup_menu_below(
            self.log_menu_button,
            [
                ("▶ Mở và chạy file log...", self.open_and_play_log, "normal"),
                ("⏹ Dừng phát log", self.stop_playback, stop_state),
                "---",
                ("🧹 Xóa dữ liệu biểu đồ", self.clear_charts, "normal"),
                ("🗑️ Xóa file log trên đĩa...", self.delete_log_file, "normal"),
            ],
        )

    def _on_zero_button_click(self):
        sides, _pending = self.shoe_zero.state()
        clear_state = "normal" if sides else "disabled"
        self._popup_menu_below(
            self.zero_menu_button,
            [
                ("👣 Calib / Zero (Tự nhận 1 hoặc 2 chân)", lambda: self._start_zero(("left", "right")), "normal"),
                ("⬅ Calib riêng chân trái", lambda: self._start_zero(("left",)), "normal"),
                ("➡ Calib riêng chân phải", lambda: self._start_zero(("right",)), "normal"),
                "---",
                ("🗑️ Xóa hết calib nền đã lưu", self._clear_all_zero, clear_state),
            ],
        )

    def _on_standing_button_click(self):
        if self.standing_reference and self.standing_reference.active:
            self._cancel_standing_reference()
            return
        self._popup_menu_below(
            self.standing_menu_button,
            [
                ("👣 Đứng 2 chân (hoặc chân đang bật) · 5s", lambda: self._start_standing_reference("both"), "normal"),
                ("⬅ Đứng chân trái · 5 giây", lambda: self._start_standing_reference("left"), "normal"),
                ("➡ Đứng chân phải · 5 giây", lambda: self._start_standing_reference("right"), "normal"),
            ],
        )

    def _toggle_connection_panel(self):
        self._set_connection_panel_collapsed(not self.connection_panel_collapsed)

    def _set_connection_panel_collapsed(self, collapsed):
        if self.connection_settings_body is None:
            return
        self.connection_panel_collapsed = bool(collapsed)
        if self.connection_panel_collapsed:
            self.connection_settings_body.pack_forget()
            self.connection_toggle_text.set("⚙ Hiện thiết lập kết nối ▾")
        else:
            if not self.connection_settings_body.winfo_manager():
                self.connection_settings_body.pack(fill=tk.X, pady=(0, 6), before=self.toolbar)
            self.connection_toggle_text.set("▲ Thu gọn thiết lập kết nối")
        self.root.after_idle(self._refresh_layout_after_toggle)

    def _refresh_zero_controls(self):
        self.zero_button_text.set("🎯 Calib / Zero ▾")
        enabled = self.running and self._selected_unit == 'newton'
        self.zero_record_button.configure(state="normal" if enabled else "disabled")

    def _reset_zero(self, reason='Đã hủy lượt calib · baseline cũ vẫn được giữ'):
        self.shoe_zero.reset()
        self.zero_status.set(reason)
        self._refresh_zero_controls()

    def _toggle_zero(self):
        self._on_zero_button_click()

    def _start_zero(self, sides):
        self._record_zero_round(sides=sides)

    def _record_zero_round(self, sides=None):
        """Zero the latest received frame and redraw within this click handler."""
        if not self.running or self._selected_unit != 'newton':
            messagebox.showwarning('Lấy zero', 'Kết nối FSR trực tiếp và chọn Newton trước khi lấy zero.')
            return
        sides = tuple(sides) if sides is not None else ('left', 'right')
        try:
            with self.shoe_zero.lock:
                now = time.monotonic()
                if len(sides) == 2:
                    sides = tuple(
                        side for side in sides
                        if side in self.shoe_zero.latest
                        and 0 <= now - self.shoe_zero.latest[side] <= self.shoe_zero.fresh_seconds
                    )
                if not sides:
                    raise ValueError('Chưa có dữ liệu FSR mới để zero. Kiểm tra kết nối rồi bấm lại.')
                result = self.shoe_zero.capture_now(sides, now)
        except ValueError as exc:
            self.zero_status.set(str(exc))
            self._refresh_zero_controls()
            return
        if not result.get('accepted'):
            details = '; '.join(
                f'{side}: {reason}' for side, reason in result.get('reasons', {}).items()
            )
            self.zero_status.set(f'Chưa ghi zero · {details}')
            self._refresh_zero_controls()
            return
        counts = result.get('left', 0), result.get('right', 0)
        warnings = [
            side for side, rows in result.get('warnings', {}).items() if rows
        ]
        warning_text = f' · cảnh báo chuyển tải: {", ".join(warnings)}' if warnings else ''
        self.zero_status.set(
            f'Đã zero ngay · trái {counts[0]} lượt · phải {counts[1]} lượt{warning_text}'
        )
        self.clear_charts()
        # Do not wait for the serial worker or redraw an old queued frame.
        # capture_now increments the revision so pre-click frames are ignored.
        for side, matrix in result['zeroed_matrices'].items():
            self.draw_matrix(matrix, side, 'newton')
            self._append_chart_sample(side, matrix, unit='newton')
        self._refresh_zero_controls()

    def _clear_all_zero(self):
        sides, pending = self.shoe_zero.state()
        if not sides and not pending:
            return
        if not messagebox.askyesno(
                'Xóa toàn bộ calib nền',
                'Xóa tất cả các lượt calib nền đã ghi cho hai chân?',
                parent=self.root):
            return
        self.shoe_zero.clear_all()
        self.clear_charts()
        self.zero_status.set('Đã xóa toàn bộ calib nền · trở về lực trước zero')
        self._refresh_zero_controls()

    def _parse_standing_mass(self):
        text = self.standing_mass_kg.get().strip()
        if not text:
            return None
        try:
            mass = float(text.replace(',', '.'))
        except ValueError as exc:
            raise ValueError('Cân nặng phải là số kg hợp lệ.') from exc
        if not math.isfinite(mass) or mass <= 0:
            raise ValueError('Cân nặng phải lớn hơn 0 kg.')
        return mass

    def _refresh_standing_controls(self):
        active = bool(self.standing_reference and self.standing_reference.active)
        self.standing_button_text.set("⏹ Hủy đo đứng (5s)" if active else "⏱ Đo đứng 5s ▾")
    def _start_standing_reference(self, mode):
        if self.standing_reference is None:
            self.standing_status.set('Không tải được bộ kiểm tra đứng.')
            return
        if not self.running or self._selected_unit != 'newton':
            messagebox.showwarning(
                'Kiểm tra đứng',
                'Kết nối FSR trực tiếp và chọn Newton trước khi đo.',
                parent=self.root,
            )
            return
        if mode == 'both' and len(self.last_raw_matrices) == 1:
            mode = next(iter(self.last_raw_matrices))
        try:
            mass = self._parse_standing_mass()
            self.standing_reference.start(mode, mass, time.monotonic())
        except ValueError as exc:
            self.standing_status.set(str(exc))
            return
        label = {'both': '2 chân', 'left': 'chân trái', 'right': 'chân phải'}[mode]
        self.standing_status.set(
            f'Đang ghi {label} trong 5 giây · giữ tư thế ổn định'
        )
        if self.standing_reference_after_id is not None:
            try:
                self.root.after_cancel(self.standing_reference_after_id)
            except tk.TclError:
                pass
        self.standing_reference_after_id = self.root.after(
            int(self.standing_reference.duration_seconds * 1000),
            self._finish_standing_reference,
        )
        self._refresh_standing_controls()
    def _cancel_standing_reference(self):
        if self.standing_reference_after_id is not None:
            try:
                self.root.after_cancel(self.standing_reference_after_id)
            except tk.TclError:
                pass
            self.standing_reference_after_id = None
        if self.standing_reference is not None:
            self.standing_reference.cancel()
        self.standing_status.set('Đã hủy kiểm tra đứng · chưa lưu kết quả')
        self._refresh_standing_controls()

    def _append_standing_reference_sample(self, side, matrix, unit):
        if self.standing_reference is None or not self.standing_reference.active:
            return
        if str(unit).strip().lower() != 'newton':
            return
        try:
            self.standing_reference.add_sample(side, matrix)
        except (TypeError, ValueError):
            # A malformed frame must not interrupt the serial/UI callback.
            return

    def _write_standing_reference_log(self, result):
        with self.log_lock:
            handle = self.log_handle
            if handle is None:
                return
            try:
                handle.write(json.dumps({
                    "type": "standing_reference",
                    "recorded_at": time.time(),
                    "result": result,
                }, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
            except OSError:
                # The regular sample writer owns the visible log error path.
                return

    def _finish_standing_reference(self):
        self.standing_reference_after_id = None
        if self.standing_reference is None or not self.standing_reference.active:
            self._refresh_standing_controls()
            return
        try:
            result = self.standing_reference.finish(force=True)
        except ValueError as exc:
            self.standing_status.set(str(exc))
            self._refresh_standing_controls()
            return
        self.standing_result = result
        self.standing_reference_history.append({
            "recorded_at": time.time(),
            "result": result,
        })
        self._write_standing_reference_log(result)
        self._reset_fsi()
        if not result.get('valid'):
            self.standing_status.set(
                f'Kiểm tra đứng chưa đủ dữ liệu ({result.get("quality", "invalid")})'
            )
        else:
            ratio = result.get('representative_ratio_percent')
            ratio_text = f' · đại diện {ratio:.1f}% cân nặng' if ratio is not None else ''
            side_labels = {'left': 'trái', 'right': 'phải'}
            side_peaks = ' · '.join(
                f'{side_labels.get(side, side)} đỉnh {details["peak_n"]:.1f} N'
                for side, details in result.get('sides', {}).items()
            )
            side_text = f' · {side_peaks}' if side_peaks else ''
            self.standing_status.set(
                f'Đã lưu {result["mode"]} · đại diện {result["representative_n"]:.1f} N'
                f' · đỉnh {result["peak_n"]:.1f} N{side_text}{ratio_text}'
            )
        self._refresh_standing_controls()

    def _finish_standing_on_shutdown(self):
        if self.standing_reference is not None and self.standing_reference.active:
            self._cancel_standing_reference()

    def _on_unit_change(self, *_args):
        if self.standing_reference is not None and self.standing_reference.active:
            self._cancel_standing_reference()
        self._reset_zero('Đổi đơn vị · lượt calib đang ghi đã hủy, baseline được giữ')
        selected = self.unit.get().strip().lower()
        self._selected_unit = selected if selected in ('raw_adc', 'newton') else 'raw_adc'
        self._refresh_zero_controls()
        self.clear_charts()
        self.preview_unit_label.set(
            f'Đơn vị hiển thị/gửi: {unit_label(self._selected_unit)}'
        )
        for side, raw_matrix in list(self.last_raw_matrices.items()):
            self.draw_matrix(
                matrix_for_unit(raw_matrix, self._selected_unit, side),
                side,
                self._selected_unit,
            )
            self._append_chart_sample(
                side,
                matrix_for_unit(raw_matrix, self._selected_unit, side),
                unit=self._selected_unit,
            )
        if self.last_raw_matrices:
            self.status.set(f'Đã đổi sang {unit_label(self._selected_unit)}')

    def _on_alpha_change(self, value):
        if hasattr(self, 'zero_left_button'):
            self._reset_zero('Đổi bộ lọc · lượt calib đang ghi đã hủy, baseline được giữ')
        self.ema_alpha_value = min(max(float(value), 0.01), 1.0)
        self.ema_label_text.set(f'EMA alpha: {self.ema_alpha_value:.2f}')

    def _apply_ema_filter(self, channel_id, matrix):
        matrix = validate_matrix(matrix)
        if any(not math.isfinite(v) for row in matrix for v in row):
            raise ValueError('ADC không hữu hạn; bỏ frame, giữ nguyên bộ lọc.')
        previous = self.smoothed_matrices.get(channel_id)
        if (
            previous is None
            or len(previous) != len(matrix)
            or len(previous[0]) != len(matrix[0])
        ):
            filtered = [row[:] for row in matrix]
        else:
            alpha = self.ema_alpha_value
            filtered = [
                [
                    alpha * value
                    + (1.0 - alpha) * previous[row_index][column_index]
                    for column_index, value in enumerate(row)
                ]
                for row_index, row in enumerate(matrix)
            ]
        self.smoothed_matrices[channel_id] = filtered
        return [row[:] for row in filtered]

    @staticmethod
    def _chart_unit_label(unit):
        return "N" if str(unit).lower() == "newton" else "ADC"

    def _append_chart_sample(self, side, matrix, sample_time=None, unit=None):
        if side not in self.chart_history:
            return
        matrix = validate_matrix(matrix)
        unit = str(unit or self._selected_unit).lower()
        if self.chart_unit is not None and self.chart_unit != unit:
            for history in self.chart_history.values():
                history.clear()
            self.chart_started_at = time.monotonic()
        self.chart_unit = unit
        regions = matrix_region_totals(matrix)
        timestamp = (
            float(sample_time)
            if sample_time is not None
            else time.monotonic() - self.chart_started_at
        )
        self.chart_history[side].append(
            {
                "time": max(0.0, timestamp),
                "total": regions["total"],
                "heel": regions["heel"],
                "midfoot": regions["midfoot"],
                "forefoot": regions["forefoot"],
            }
        )
        self._schedule_chart_redraw()

    def _reset_fsi(self):
        if self.fsi_analyzer is not None:
            self.fsi_analyzer.reset()
        self.fsi_last_refresh = 0.0
        self.fsi_last_result = None
        if self.fsi_tree is not None:
            for item in self.fsi_tree.get_children():
                self.fsi_tree.delete(item)
        if self.fsi_summary_tree is not None:
            for item in self.fsi_summary_tree.get_children():
                self.fsi_summary_tree.delete(item)
        self.fsi_status.set("FSI: đang chờ đủ cặp bước")

    def _toggle_fsi_registration(self):
        self.fsi_roi_registered = not self.fsi_roi_registered
        self._reset_fsi()
        if self.fsi_roi_registered:
            self.fsi_register_text.set("ROI đã đăng ký hai chân · bấm để huỷ")
            self.fsi_status.set("FSI: đã đăng ký ROI; đang chờ cặp bước")
        else:
            self.fsi_register_text.set("Đăng ký ROI sau khi căn dấu chân")
            self.fsi_status.set("FSI: chưa đăng ký ROI hai chân")

    def _append_fsi_sample(self, side, matrix, unit, sample_time=None):
        """Detect steps from Newton data; registration gates the comparison view."""
        self._append_standing_reference_sample(side, matrix, unit)
        if self.standing_reference is not None and self.standing_reference.active:
            # A static standing trial is a separate check; do not turn it into
            # gait contacts or make the FSI view recompute during capture.
            return
        if self.fsi_analyzer is None:
            return
        timestamp = float(sample_time) if sample_time is not None else time.monotonic()
        is_force = str(unit).strip().lower() == "newton"
        self.fsi_analyzer.add_sample(
            side,
            timestamp,
            matrix,
            unit=unit,
            valid=is_force,
            quality="valid" if is_force else "unit_not_force",
        )
        if timestamp - self.fsi_last_refresh < FSI_REFRESH_INTERVAL_SECONDS:
            return
        self.fsi_last_refresh = timestamp
        self._refresh_fsi_view()

    def _refresh_fsi_view(self):
        if self.fsi_analyzer is None or self.fsi_tree is None:
            return
        snapshot = self.fsi_analyzer.snapshot(window_seconds=FSI_LIVE_WINDOW_SECONDS)
        showing_previous = False
        if not self.fsi_roi_registered:
            snapshot['pairs'] = []
            snapshot['summary'] = []
        elif snapshot['summary']:
            self.fsi_last_result = {
                'pairs': copy.deepcopy(snapshot['pairs']),
                'summary': copy.deepcopy(snapshot['summary']),
            }
        elif not snapshot['pairs'] and self.fsi_last_result:
            # Keep the last usable comparisons visible after walking stops;
            # raw-sample processing remains bounded to the recent window.
            snapshot.update(self.fsi_last_result)
            showing_previous = True
        for item in self.fsi_tree.get_children():
            self.fsi_tree.delete(item)
        for row in snapshot["pairs"][-12:]:
            metric_label = {
                "peak": "đỉnh",
                "mean": "TB",
                "median": "trung vị",
            }.get(row.get("metric"), row.get("metric", ""))
            phase_label = {
                "contact": "Tiếp đất gót",
                "midstance": "Pha giữa",
                "push": "Tải mũi cuối stance",
                "stance": "Trong bước",
            }.get(row["phase"], row["phase"])
            phase_label = f"{phase_label} · {metric_label}"
            region_label = {
                "heel": "Gót",
                "forefoot": "Mũi",
                "stance_sampled": "Gót–mũi mẫu",
            }.get(row["region"], row["region"])
            values = [
                row["pair_id"], phase_label, region_label,
                "--" if row["left_value"] is None else f'{row["left_value"]:.2f}',
                "--" if row["right_value"] is None else f'{row["right_value"]:.2f}',
                "--" if row["fsi"] is None else f'{row["fsi"]:.2f}',
                f'{row["quality"]} / {row.get("alignment", "--")}',
            ]
            self.fsi_tree.insert("", tk.END, values=values)
        if self.fsi_summary_tree is not None:
            for item in self.fsi_summary_tree.get_children():
                self.fsi_summary_tree.delete(item)
            for row in snapshot["summary"]:
                self.fsi_summary_tree.insert(
                    "", tk.END,
                    values=(row["phase"], row["region"], row["fsi_mean"], row["fsi_median"], row["valid_pair_count"]),
                )
        self._draw_fsi_trend(snapshot["pairs"])
        pair_count = len({row["pair_id"] for row in snapshot["pairs"]})
        valid_count = sum(
            row["quality"] == "valid" and row.get("alignment") == "ok"
            for row in snapshot["pairs"]
        )
        detection = snapshot['detection']
        left_count = detection['left']['complete_contacts']
        right_count = detection['right']['complete_contacts']
        counts_text = f'Bước hoàn tất: trái {left_count} / phải {right_count}'
        if self._selected_unit != 'newton':
            self.fsi_status.set('Chọn Newton để bắt bước và so sánh FSI')
        elif not self.fsi_roi_registered:
            self.fsi_status.set(f'{counts_text} · bấm Đăng ký ROI để bật so sánh')
        else:
            missing = [
                label for side, label in (('left', 'trái'), ('right', 'phải'))
                if snapshot['sample_count'][side] == 0
            ]
            detail = f'chờ dữ liệu chân {", ".join(missing)}' if missing else (
                f'ngưỡng T {detection["left"]["on_n"]:.1f}/{detection["left"]["off_n"]:.1f} N'
                f' · P {detection["right"]["on_n"]:.1f}/{detection["right"]["off_n"]:.1f} N'
            )
            self.fsi_status.set(
                f'{counts_text} · {pair_count} cặp · {valid_count} so sánh hợp lệ'
                f'{" (kết quả gần nhất)" if showing_previous else ""} · {detail}'
            )

    def _draw_fsi_trend(self, rows):
        if self.fsi_trend_canvas is None:
            return
        canvas = self.fsi_trend_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 520)
        height = max(canvas.winfo_height(), 115)
        left, right, top, bottom = 42, 18, 18, 24
        x0, x1, y0, y1 = left, width - right, top, height - bottom
        canvas.create_text(left, 8, text="FSI theo cặp bước", anchor="w", fill="#334155", font=("Segoe UI", 9, "bold"))
        for tick in (0, 50, 100):
            y = y1 - tick / 100 * (y1 - y0)
            canvas.create_line(x0, y, x1, y, fill="#e2e8f0")
            canvas.create_text(x0 - 5, y, text=str(tick), anchor="e", fill="#64748b", font=("Segoe UI", 8))
        groups = {
            ("contact", "heel"): ("Tiếp đất gót", "#2563eb"),
            ("midstance", "heel"): ("Giữa gót", "#0f766e"),
            ("midstance", "forefoot"): ("Giữa mũi", "#ea6a14"),
            ("push", "forefoot"): ("Tải mũi", "#7c3aed"),
            ("stance", "heel"): ("Gót trong bước", "#0891b2"),
            ("stance", "forefoot"): ("Mũi trong bước", "#be185d"),
        }
        pair_ids = []
        for row in rows:
            if row.get("pair_id") not in pair_ids:
                pair_ids.append(row.get("pair_id"))
        if not pair_ids:
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="Chưa đủ cặp bước", fill="#64748b")
            return
        x_step = (x1 - x0) / max(1, len(pair_ids) - 1)
        for (phase, region), (label, color) in groups.items():
            by_pair = {(row.get("pair_id")): row.get("fsi") for row in rows
                       if row.get("phase") == phase and row.get("region") == region
                       and row.get('quality') == 'valid' and row.get('alignment') == 'ok'}
            points = []
            for index, pair_id in enumerate(pair_ids):
                value = by_pair.get(pair_id)
                if value is None:
                    continue
                points.extend((x0 + index * x_step, y1 - float(value) / 100 * (y1 - y0)))
            if len(points) >= 2:
                canvas.create_line(*points, fill=color, width=2)
            if points:
                canvas.create_oval(points[0] - 2, points[1] - 2, points[0] + 2, points[1] + 2, fill=color, outline=color)
            legend_x = x0 + 8 + list(groups).index((phase, region)) * max(96, (x1 - x0) / len(groups))
            canvas.create_line(legend_x, height - 10, legend_x + 14, height - 10, fill=color, width=2)
            canvas.create_text(legend_x + 18, height - 10, text=label, anchor="w", fill="#475569", font=("Segoe UI", 8))

    def _on_chart_resize(self, _event=None):
        self._schedule_chart_redraw()

    def _schedule_chart_redraw(self):
        if self.chart_redraw_pending:
            return
        self.chart_redraw_pending = True
        self.root.after(80, self._redraw_charts)

    def _redraw_charts(self):
        self.chart_redraw_pending = False
        if self.total_chart_canvas is not None:
            self._draw_total_chart()
        if self.region_chart_canvas is not None:
            self._draw_region_chart()

    @staticmethod
    def _visible_history(history, x_start, x_end):
        return [point for point in history if x_start <= point["time"] <= x_end]

    @staticmethod
    def _draw_chart_line(canvas, points, x_map, y_map, color, dash=None):
        segment = []
        previous_time = None
        for point in points:
            timestamp, value = point
            if previous_time is not None and timestamp - previous_time > 0.6:
                if len(segment) >= 4:
                    canvas.create_line(
                        *segment, fill=color, width=2.5, dash=dash, smooth=False
                    )
                segment = []
            segment.extend((x_map(timestamp), y_map(value)))
            previous_time = timestamp
        if len(segment) >= 4:
            canvas.create_line(
                *segment, fill=color, width=2.5, dash=dash, smooth=False
            )

    def _draw_chart_frame(self, canvas, title, series, legend, minimum_y):
        canvas.delete("all")
        width = max(canvas.winfo_width(), 360)
        height = max(canvas.winfo_height(), 260)
        left, right, top, bottom = 76, 24, 82, 58
        plot_left, plot_top = left, top
        plot_right, plot_bottom = width - right, height - bottom

        canvas.create_text(
            width / 2, 23, text=title, fill="#172033", font=("Segoe UI", 14, "bold")
        )

        all_times = [
            point["time"]
            for side in ("left", "right")
            for point in self.chart_history[side]
        ]
        latest_time = max(all_times, default=0.0)
        x_end = max(CHART_WINDOW_SECONDS, latest_time)
        x_start = max(0.0, x_end - CHART_WINDOW_SECONDS)

        visible_by_side = {
            side: self._visible_history(self.chart_history[side], x_start, x_end)
            for side in ("left", "right")
        }
        visible_values = []
        for item in series:
            for point in visible_by_side[item["side"]]:
                visible_values.append(point[item["field"]])
        y_max = nice_axis_max(max(visible_values, default=0.0), minimum_y)

        def x_map(value):
            span = max(x_end - x_start, 1e-6)
            return plot_left + (value - x_start) / span * (plot_right - plot_left)

        def y_map(value):
            return plot_bottom - max(0.0, value) / y_max * (plot_bottom - plot_top)

        for index in range(6):
            fraction = index / 5
            x = plot_left + fraction * (plot_right - plot_left)
            y = plot_bottom - fraction * (plot_bottom - plot_top)
            canvas.create_line(x, plot_top, x, plot_bottom, fill="#e2e8f0")
            canvas.create_line(plot_left, y, plot_right, y, fill="#e2e8f0")
            canvas.create_text(
                x,
                plot_bottom + 20,
                text=f"{x_start + fraction * (x_end - x_start):.0f}",
                fill="#5e6b7a",
                font=("Segoe UI", 9),
            )
            canvas.create_text(
                plot_left - 12,
                y,
                text=f"{fraction * y_max:.0f}",
                anchor="e",
                fill="#5e6b7a",
                font=("Segoe UI", 9),
            )

        canvas.create_rectangle(
            plot_left, plot_top, plot_right, plot_bottom, outline="#9eacbb", width=1
        )
        canvas.create_text(
            (plot_left + plot_right) / 2,
            height - 18,
            text="Thời gian (s)",
            fill="#334155",
            font=("Segoe UI", 10),
        )
        canvas.create_text(
            19,
            (plot_top + plot_bottom) / 2,
            text=f"Lực ({self._chart_unit_label(self.chart_unit)})",
            angle=90,
            fill="#334155",
            font=("Segoe UI", 10),
        )

        legend_x = plot_left
        legend_y = 52
        for label, color, dash in legend:
            canvas.create_line(
                legend_x, legend_y, legend_x + 28, legend_y,
                fill=color, width=3, dash=dash,
            )
            canvas.create_text(
                legend_x + 35,
                legend_y,
                text=label,
                anchor="w",
                fill="#334155",
                font=("Segoe UI", 9),
            )
            label_width = max(54, len(label) * 7)
            legend_x += 48 + label_width

        for item in series:
            points = [
                (point["time"], point[item["field"]])
                for point in visible_by_side[item["side"]]
            ]
            self._draw_chart_line(
                canvas,
                points,
                x_map,
                y_map,
                item["color"],
                item.get("dash"),
            )

        if not visible_values:
            canvas.create_text(
                (plot_left + plot_right) / 2,
                (plot_top + plot_bottom) / 2,
                text="Chưa có dữ liệu FSR",
                fill="#64748b",
                font=("Segoe UI", 12),
            )

    def _draw_total_chart(self):
        self._draw_chart_frame(
            self.total_chart_canvas,
            "TỔNG TẢI TRÊN TỪNG CHÂN",
            [
                {"side": "left", "field": "total", "color": CHART_COLORS["left"]},
                {
                    "side": "right",
                    "field": "total",
                    "color": CHART_COLORS["right"],
                    "dash": (8, 4),
                },
            ],
            [
                ("Chân trái", CHART_COLORS["left"], None),
                ("Chân phải", CHART_COLORS["right"], (8, 4)),
            ],
            100.0 if self.chart_unit == "newton" else 1000.0,
        )

    def _draw_region_chart(self):
        series = []
        for side, dash in (("left", None), ("right", (8, 4))):
            for field in ("heel", "midfoot", "forefoot"):
                series.append(
                    {
                        "side": side,
                        "field": field,
                        "color": CHART_COLORS[field],
                        "dash": dash,
                    }
                )
        self._draw_chart_frame(
            self.region_chart_canvas,
            "PHÂN BỐ LỰC THEO BA VÙNG BÀN CHÂN",
            series,
            [
                ("Gót", CHART_COLORS["heel"], None),
                ("Giữa", CHART_COLORS["midfoot"], None),
                ("Mũi", CHART_COLORS["forefoot"], None),
                ("Trái: liền", "#475569", None),
                ("Phải: đứt", "#475569", (8, 4)),
            ],
            50.0 if self.chart_unit == "newton" else 500.0,
        )

    def clear_charts(self):
        for history in self.chart_history.values():
            history.clear()
        self._reset_fsi()
        self.chart_started_at = time.monotonic()
        self.chart_unit = self._selected_unit
        self._schedule_chart_redraw()
        self.status.set("Đã xóa dữ liệu đang vẽ trên biểu đồ")

    def _default_log_directory(self):
        directory = Path(__file__).resolve().parent / "fsr_logs"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def toggle_logging(self):
        if self.log_handle is not None:
            self._stop_logging()
            return

        directory = self._default_log_directory()
        default_name = time.strftime("fsr_%Y%m%d_%H%M%S.jsonl")
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Lưu FSR log",
            initialdir=str(directory),
            initialfile=default_name,
            defaultextension=".jsonl",
            filetypes=(("FSR JSON Lines", "*.jsonl"), ("Tất cả file", "*.*")),
            confirmoverwrite=True,
        )
        if not selected:
            return

        try:
            handle = open(selected, "w", encoding="utf-8", buffering=1)
            header = {
                "type": "fsr_log",
                "version": 1,
                "created_at": time.time(),
                "description": "Raw ADC, EMA ADC and displayed FSR matrix",
            }
            handle.write(json.dumps(header, ensure_ascii=False) + "\n")
        except OSError as exc:
            messagebox.showerror("Không lưu được log", str(exc))
            return

        with self.log_lock:
            self.log_handle = handle
            self.log_path = Path(selected).resolve()
            self.log_started_at = time.monotonic()
            self.log_sample_count = 0
        self.log_button_text.set("Dừng và đóng log")
        self.log_status.set(f"Đang lưu: {Path(selected).name}")

    def _stop_logging(self, status_text=None):
        with self.log_lock:
            handle = self.log_handle
            path = self.log_path
            count = self.log_sample_count
            self.log_handle = None
            self.log_started_at = None
        if handle is not None:
            try:
                handle.flush()
                handle.close()
            except OSError:
                pass
        self.log_button_text.set("Bắt đầu lưu log")
        if status_text is not None:
            self.log_status.set(status_text)
        elif path is not None:
            self.log_status.set(f"Đã lưu {count} mẫu: {path.name}")
        else:
            self.log_status.set("Chưa lưu log")

    def _write_log_sample(
        self,
        side,
        raw_matrix,
        filtered_raw_matrix,
        display_matrix,
        unit,
        received_monotonic,
        zero_metadata=None,
    ):
        with self.log_lock:
            handle = self.log_handle
            started_at = self.log_started_at
            if handle is None or started_at is None:
                return
            record = {
                "type": "fsr_sample",
                "elapsed": max(0.0, received_monotonic - started_at),
                "received_at": time.time(),
                "side": side,
                "unit": unit,
                "rows": len(display_matrix),
                "columns": len(display_matrix[0]),
                "raw_values": raw_matrix,
                "filtered_raw_values": filtered_raw_matrix,
                "values": display_matrix,
                **calibration_metadata(side, unit),
                **(zero_metadata or {'zero_applied': False, 'zero_collecting': False}),
            }
            try:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                self.log_sample_count += 1
                count = self.log_sample_count
                if count % 20 == 0:
                    handle.flush()
                    self.root.after(
                        0,
                        self.log_status.set,
                        f"Đang lưu: {self.log_path.name} · {count} mẫu",
                    )
            except OSError as exc:
                self.log_handle = None
                self.log_started_at = None
                try:
                    handle.close()
                except OSError:
                    pass
                self.root.after(0, self._log_failed, str(exc))

    def _log_failed(self, error_message):
        self.log_button_text.set("Bắt đầu lưu log")
        self.log_status.set("Lỗi ghi log")
        messagebox.showerror("Lỗi ghi FSR log", error_message)

    def open_and_play_log(self):
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Mở FSR log",
            initialdir=str(self._default_log_directory()),
            filetypes=(("FSR JSON Lines", "*.jsonl"), ("Tất cả file", "*.*")),
        )
        if not selected:
            return

        records = []
        try:
            with open(selected, "r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Dòng {line_number}: JSON không hợp lệ") from exc
                    if record.get("type") == "fsr_log":
                        continue
                    side = str(record.get("side", "")).lower()
                    if side not in ("left", "right"):
                        continue
                    matrix = record.get("values")
                    unit = str(record.get("unit", "raw_adc")).lower()
                    if record.get("forceValues") and unit.lower().startswith("n"):
                        matrix = record["forceValues"]
                        unit = "newton"
                    matrix = validate_matrix(matrix)
                    elapsed = float(record.get("elapsed", record.get("time", 0.0)))
                    records.append(
                        {
                            "elapsed": max(0.0, elapsed),
                            "side": side,
                            "unit": "newton" if unit in ("n", "n_estimated") else unit,
                            "values": matrix,
                            "raw_values": record.get("raw_values", record.get("rawAdcValues")),
                        }
                    )
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("Không mở được FSR log", str(exc))
            return

        if not records:
            messagebox.showwarning("FSR log trống", "Không tìm thấy mẫu FSR hợp lệ trong file.")
            return

        records.sort(key=lambda item: item["elapsed"])
        if self.running:
            self._stop_stream("Đã ngắt FSR thật để chạy log")
        self._stop_logging()
        self.stop_playback(silent=True)
        self.clear_charts()
        self.playback_records = records
        self.playback_index = 0
        self.playback_path = Path(selected).resolve()
        self.chart_unit = records[0]["unit"]
        self.playback_status.set(f"Đang chạy: {self.playback_path.name}")
        self._playback_step()

    def _playback_step(self):
        self.playback_after_id = None
        if self.playback_index >= len(self.playback_records):
            name = self.playback_path.name if self.playback_path else "log"
            self.playback_status.set(f"Đã chạy xong: {name}")
            return

        record = self.playback_records[self.playback_index]
        matrix = record["values"]
        side = record["side"]
        unit = record["unit"]
        raw_values = record.get("raw_values")
        if isinstance(raw_values, list):
            try:
                self.last_raw_matrices[side] = validate_matrix(raw_values)
            except ValueError:
                pass
        self.draw_matrix(matrix, side, unit)
        self._append_chart_sample(side, matrix, record["elapsed"], unit)
        self._append_fsi_sample(side, matrix, unit, record["elapsed"])
        self.playback_index += 1

        if self.playback_index < len(self.playback_records):
            next_record = self.playback_records[self.playback_index]
            delay_seconds = max(0.0, next_record["elapsed"] - record["elapsed"])
            delay_ms = max(1, min(2000, round(delay_seconds * 1000)))
            self.playback_after_id = self.root.after(delay_ms, self._playback_step)
        else:
            self.playback_status.set(f"Đã chạy xong: {self.playback_path.name}")

    def stop_playback(self, silent=False):
        if self.playback_after_id is not None:
            try:
                self.root.after_cancel(self.playback_after_id)
            except tk.TclError:
                pass
        was_running = self.playback_after_id is not None
        self.playback_after_id = None
        self.playback_records = []
        self.playback_index = 0
        if not silent:
            self.playback_status.set("Đã dừng phát log" if was_running else "Chưa chạy log")

    def delete_log_file(self):
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Chọn FSR log cần xóa",
            initialdir=str(self._default_log_directory()),
            filetypes=(("FSR JSON Lines", "*.jsonl"), ("Tất cả file", "*.*")),
        )
        if not selected:
            return
        path = Path(selected).resolve()
        if not messagebox.askyesno(
            "Xóa FSR log",
            f"Xóa vĩnh viễn file này?\n\n{path}",
            parent=self.root,
        ):
            return

        if self.log_path == path and self.log_handle is not None:
            self._stop_logging("Đã đóng log trước khi xóa")
        if self.playback_path == path:
            self.stop_playback(silent=True)
        try:
            path.unlink()
        except OSError as exc:
            messagebox.showerror("Không xóa được log", str(exc))
            return
        self.log_status.set(f"Đã xóa: {path.name}")
        self.playback_status.set("Chưa mở log")

    def refresh_com_ports(self):
        boxes = (self.com_box_1, self.com_box_2)
        variables = (self.com_port_1, self.com_port_2)
        if list_ports is None:
            for box in boxes:
                box["values"] = (self.DISABLED_PORT_OPTION,)
            for variable in variables:
                variable.set(self.DISABLED_PORT_OPTION)
            self.status.set("Thiếu pyserial – chạy: py -m pip install pyserial")
            return

        raw_values = [variable.get().strip() for variable in variables]
        explicitly_disabled = [val.startswith("--") for val in raw_values]
        current_devices = [
            self._selected_com_device(variable, allow_empty=True)
            for variable in variables
        ]
        all_ports = list(list_ports.comports())
        ports = sorted(
            selectable_fsr_ports(all_ports),
            key=lambda port: self._com_sort_key(port.device),
        )
        display_values = [
            f"{port.device} - {port.description or 'Serial device'}"
            for port in ports
        ]
        combo_values = [self.DISABLED_PORT_OPTION, *display_values]
        for box in boxes:
            box["values"] = combo_values

        if not display_values:
            for variable in variables:
                variable.set(self.DISABLED_PORT_OPTION)
            self.status.set("Không quét thấy cổng COM")
            return

        by_device = {item.split(" - ", 1)[0]: item for item in display_values}
        preferred_devices = [port.device for port in ports]

        selected = []
        for idx, current in enumerate(current_devices):
            if explicitly_disabled[idx] and getattr(self, "_ports_initialized", False):
                selected.append(None)
            elif current in by_device and current not in selected:
                selected.append(current)
            else:
                selected.append("")

        for index in range(2):
            if selected[index] is None or selected[index]:
                continue
            candidate = next(
                (device for device in preferred_devices if device not in selected),
                None,
            )
            selected[index] = candidate if candidate else None

        self._ports_initialized = True
        for variable, device in zip(variables, selected):
            if device is None:
                variable.set(self.DISABLED_PORT_OPTION)
            else:
                variable.set(by_device.get(device, device))

        chosen = ", ".join(device for device in selected if device) or "chưa chọn"
        ignored = max(0, len(all_ports) - len(ports))
        ignored_text = f"; bỏ qua {ignored} cổng chiều vào" if ignored else ""
        self.status.set(
            f"Tìm thấy {len(display_values)} cổng FSR; đang chọn {chosen}{ignored_text}"
        )

    def _refresh_com_ports_from_event(self, _event=None):
        pass

    @staticmethod
    def _com_sort_key(device):
        match = re.fullmatch(r"COM(\d+)", device.strip(), flags=re.IGNORECASE)
        return (0, int(match.group(1))) if match else (1, device.casefold())

    def _selected_com_device(self, variable, allow_empty=False):
        value = variable.get().strip()
        if not value or value.startswith("--"):
            if allow_empty:
                return ""
            raise ValueError("Chưa chọn cổng COM")
        return value.split(" - ", 1)[0].strip()

    def _serial_settings(self, allowed_channels=(1, 2)):
        if serial is None:
            raise ValueError("Chưa cài pyserial")

        raw_devices = [
            self._selected_com_device(self.com_port_1, allow_empty=True),
            self._selected_com_device(self.com_port_2, allow_empty=True),
        ]
        devices = [
            dev if (idx + 1) in allowed_channels else ""
            for idx, dev in enumerate(raw_devices)
        ]
        if not any(devices):
            raise ValueError("Chưa chọn cổng COM cho kênh FSR đã chọn.")
        if devices[0] and devices[0] == devices[1]:
            raise ValueError("FSR 1 và FSR 2 đang chọn cùng một cổng COM")

        available = {
            str(getattr(port, "device", ""))
            for port in selectable_fsr_ports(list_ports.comports())
        }
        missing = [device for device in devices if device and device not in available]
        if missing:
            raise ValueError(
                "Cổng không còn sẵn sàng hoặc là cổng Bluetooth chiều vào: "
                + ", ".join(missing)
                + ". Hãy bấm Quét lại."
            )

        baudrate = int(self.baudrate.get())
        if baudrate <= 0:
            raise ValueError("Baudrate phải lớn hơn 0")

        rows_text = self.matrix_rows.get().strip()
        columns_text = self.matrix_columns.get().strip()
        rows = int(rows_text) if rows_text else None
        columns = int(columns_text) if columns_text else None
        if (rows is None) != (columns is None):
            raise ValueError("Phải nhập cả số hàng và số cột")
        if rows is not None and (rows <= 0 or columns <= 0):
            raise ValueError("Số hàng và số cột phải lớn hơn 0")

        settings = []
        fallback_sides = ("left", "right")
        for channel_id, (device, fallback_side) in enumerate(
            zip(devices, fallback_sides), start=1
        ):
            if device:
                settings.append(
                    (channel_id, device, baudrate, rows, columns, fallback_side)
                )
        return settings
    def _connection_settings(self):
        ip = self.target_ip.get().strip()
        if not ip:
            raise ValueError("IP đích không được rỗng")
        port = int(self.target_port.get())
        if not 1 <= port <= 65535:
            raise ValueError("Port không hợp lệ")
        rate = float(self.rate_hz.get())
        if rate <= 0 or rate > 200:
            raise ValueError("Tần số không hợp lệ")
        return ip, port, rate

    def _packet_settings(self):
        return (
            self.device_id.get().strip() or "fsr-device-01",
            self.side.get(),
            self._selected_unit,
        )

    def _manual_matrix(self):
        try:
            return validate_matrix(json.loads(self.matrix_text.get("1.0", tk.END)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON không hợp lệ: {exc.msg}") from exc

    def preview_manual_matrix(self):
        if self.running:
            messagebox.showwarning('Gửi thử', 'Ngắt FSR trực tiếp trước khi thử ma trận thủ công.')
            return
        try:
            side = self.side.get()
            raw_matrix = self._manual_matrix()
            matrix = matrix_for_unit(raw_matrix, self._selected_unit, side)
            self.last_raw_matrices[side] = [row[:] for row in raw_matrix]
            self.draw_matrix(
                matrix,
                side,
                self._selected_unit,
            )
            self._append_chart_sample(side, matrix, unit=self._selected_unit)
            self._append_fsi_sample(side, matrix, self._selected_unit)
        except ValueError as exc:
            messagebox.showerror("Lỗi", str(exc))

    def send_manual_once(self):
        if self.running:
            messagebox.showwarning('Gửi thử', 'Ngắt FSR trực tiếp trước khi thử ma trận thủ công.')
            return
        try:
            raw_matrix = self._manual_matrix()
            matrix = matrix_for_unit(raw_matrix, self._selected_unit, self.side.get())
            ip, port, _ = self._connection_settings()
            packet_settings = self._packet_settings()
            status = self._send_matrix_udp(matrix, ip, port, packet_settings)
            self.status.set(status)
            side = self.side.get()
            self.last_raw_matrices[side] = [row[:] for row in raw_matrix]
            self.draw_matrix(matrix, side, self._selected_unit)
            now = time.monotonic()
            self._append_chart_sample(side, matrix, unit=self._selected_unit)
            self._append_fsi_sample(side, matrix, self._selected_unit, now)
            self._write_log_sample(
                side,
                raw_matrix,
                raw_matrix,
                matrix,
                self._selected_unit,
                now,
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Lỗi", str(exc))

    def _convert_live_matrix(self, raw_matrix, unit, side, now):
        raw_matrix = validate_matrix(raw_matrix)
        if any(not math.isfinite(v) for row in raw_matrix for v in row):
            raise ValueError('ADC không hữu hạn; không thể tính lực/zero.')
        matrix = matrix_for_unit(raw_matrix, unit, side)
        if unit == 'newton':
            return self.shoe_zero.process(side, matrix, now)
        return matrix, {'zero_applied': False, 'zero_collecting': False}

    def _send_matrix_udp(self, matrix, ip, port, packet_settings, zero_metadata=None):
        matrix = validate_matrix(matrix)
        device_id, side, unit = packet_settings
        with self.send_lock:
            packet = build_packet(device_id, side, unit, self.sequence, matrix)
            packet.update(zero_metadata or {'zero_applied': False, 'zero_collecting': False})
            encoded = json.dumps(packet, separators=(",", ":")).encode("utf-8")
            if len(encoded) > 60000:
                raise ValueError("Gói tin quá lớn")
            self.socket.sendto(encoded, (ip, port))
            self.sequence += 1
        return f"{side.upper()} frame #{packet['sequence']} -> {ip}:{port}"

    def toggle_stream(self):
        if self.running:
            self._stop_stream("Đã ngắt kết nối FSR")
            return
        self.start_stream((1, 2))

    def start_stream(self, channels=(1, 2)):
        if self.running:
            self._stop_stream("Đã ngắt kết nối FSR")
            return

        try:
            serial_settings_list = self._serial_settings(allowed_channels=channels)
            ip, port, rate = self._connection_settings()
            packet_settings = self._packet_settings()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Lỗi", str(exc))
            return

        self.stop_playback(silent=True)
        self.clear_charts()
        self._reset_fsi()
        self._reset_zero('Kết nối mới · baseline calib được giữ, có thể ghi thêm lượt')
        self.running = True
        self._refresh_zero_controls()
        self.smoothed_matrices.clear()
        self.last_raw_matrices.clear()
        self.detected_sides.clear()
        self.connected_channels.clear()
        self.frame_counts = {1: 0, 2: 0}
        self._ui_frame_pending = {1: False, 2: False}
        self._last_reported_module = {1: None, 2: None}
        self.active_channels = {settings[0] for settings in serial_settings_list}
        self.workers = []
        self.module_code.set("Đang chờ LL/RR...")
        self.bt_button_text.set("⏹ Ngắt kết nối FSR")

        active_ids = {s[0] for s in serial_settings_list}
        for cid in (1, 2):
            if cid not in active_ids:
                self._channel_status_var(cid).set("Không dùng (1 chân)")

        devices = ", ".join(settings[1] for settings in serial_settings_list)
        self.status.set(f"Đang kết nối {devices}...")
        for index, (channel_id, device, baudrate, rows, columns, fallback_side) in enumerate(serial_settings_list):
            self._channel_status_var(channel_id).set(f"Đang mở {device}...")
            worker = threading.Thread(
                target=self._hardware_loop,
                args=(
                    channel_id,
                    (device, baudrate, rows, columns, fallback_side),
                    (ip, port, rate),
                    packet_settings,
                    index * 0.15,
                ),
                daemon=True,
                name=f"fsr-serial-{channel_id}",
            )
            self.workers.append(worker)
            worker.start()

    def _channel_status_var(self, channel_id):
        return self.channel_status_1 if channel_id == 1 else self.channel_status_2

    def _stop_stream(self, status_text=None):
        self.running = False
        self._finish_standing_on_shutdown()
        self._reset_zero('Đã ngắt FSR · baseline calib được giữ')
        self._reset_fsi()
        self.smoothed_matrices.clear()
        with self.serial_lock:
            connections = list(self.serial_connections.values())
            self.serial_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
        self.active_channels.clear()
        self.connected_channels.clear()
        self.workers = []
        self.bt_button_text.set("🔌 Kết nối FSR ▾")
        self.module_code.set("--")
        self.channel_status_1.set("Đã ngắt")
        self.channel_status_2.set("Đã ngắt")
        if self.log_handle is not None:
            self._stop_logging()
        if status_text:
            self.status.set(status_text)

    def _hardware_loop(self, channel_id, serial_settings, udp_settings, packet_settings, open_delay=0.0):
        device, baudrate, rows, columns, fallback_side = serial_settings
        ip, port, rate = udp_settings
        min_period = 1.0 / rate
        last_send_time = 0.0
        last_ui_time = 0.0
        buffer_tokens = []
        detected_side = None
        status = f"Đang nhận dữ liệu {device}"
        ser = None

        try:
            if open_delay > 0:
                time.sleep(open_delay)
            if not self.running:
                return
            ser = serial.Serial()
            ser.port = device
            ser.baudrate = baudrate
            ser.bytesize = serial.EIGHTBITS
            ser.parity = serial.PARITY_NONE
            ser.stopbits = serial.STOPBITS_ONE
            ser.timeout = DEFAULT_SERIAL_TIMEOUT
            ser.write_timeout = DEFAULT_SERIAL_TIMEOUT
            ser.rtscts = False
            ser.dsrdtr = False
            # Chỉ mở 1 lần duy nhất, KHÔNG lặp 3 lần để tránh treo card Bluetooth 35 giây khi 1 chân đang tắt
            ser.open()
            time.sleep(0.2)

            with self.serial_lock:
                self.serial_connections[channel_id] = ser
            ser.reset_input_buffer()
            self.root.after(0, self._on_connected, channel_id, device)

            while self.running:
                if ser.in_waiting > 2048:
                    ser.reset_input_buffer()
                    buffer_tokens.clear()
                    continue

                raw_line = ser.readline()
                if not raw_line:
                    continue

                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                tokens = line.split()
                if not tokens:
                    continue

                if tokens[0].upper() in ("RR", "LL"):
                    raw_module = tokens[0].upper()
                    detected_side = "left" if raw_module == "RR" else "right"
                    buffer_tokens = tokens[1:]

                    if self._last_reported_module.get(channel_id) != raw_module:
                        self._last_reported_module[channel_id] = raw_module
                        self.root.after(0, self._on_module_detected, channel_id, raw_module, device)
                else:
                    buffer_tokens.extend(tokens)

                target_count = (rows * columns) if (rows and columns) else 48
                if len(buffer_tokens) > target_count * 8:
                    buffer_tokens = buffer_tokens[-target_count * 2:]
                if len(buffer_tokens) < target_count:
                    continue

                frame_tokens = buffer_tokens[:target_count]
                buffer_tokens = buffer_tokens[target_count:]
                try:
                    values = [float(value) for value in frame_tokens]
                    active_side = detected_side or fallback_side
                    matrix, frame_side = parse_hardware_frame(
                        values, active_side, rows, columns
                    )
                    incoming_raw_matrix = [row[:] for row in matrix]
                    raw_matrix = self._apply_ema_filter(channel_id, matrix)
                    selected_unit = self._selected_unit
                    now = time.monotonic()
                    matrix, zero_metadata = self._convert_live_matrix(
                        raw_matrix, selected_unit, frame_side, now)
                    self.last_raw_matrices[frame_side] = [row[:] for row in raw_matrix]
                    current_packet_settings = (
                        packet_settings[0], frame_side, selected_unit
                    )
                except (ValueError, TypeError) as exc:
                    self.root.after(
                        0,
                        self._channel_status_var(channel_id).set,
                        f"Lỗi frame: {exc}",
                    )
                    continue

                self.frame_counts[channel_id] += 1
                self._write_log_sample(
                    frame_side,
                    incoming_raw_matrix,
                    raw_matrix,
                    matrix,
                    selected_unit,
                    now,
                    zero_metadata,
                )

                if now - last_send_time >= min_period:
                    status = self._send_matrix_udp(
                        matrix, ip, port, current_packet_settings, zero_metadata
                    )
                    last_send_time = now

                if now - last_ui_time >= 0.04 and not self._ui_frame_pending.get(channel_id, False):
                    self._ui_frame_pending[channel_id] = True
                    self.root.after(
                        0,
                        self._update_after_frame,
                        channel_id,
                        frame_side,
                        matrix,
                        selected_unit,
                        status,
                        zero_metadata,
                        now,
                    )
                    last_ui_time = now

        except (serial.SerialException, OSError, ValueError) as exc:
            if self.running:
                self.root.after(
                    0, self._stream_failed, channel_id, device, str(exc)
                )
        finally:
            with self.serial_lock:
                current = self.serial_connections.get(channel_id)
                if current is ser:
                    self.serial_connections.pop(channel_id, None)
            if ser is not None:
                try:
                    ser.close()
                except (serial.SerialException, OSError):
                    pass
            self.root.after(0, self._channel_finished, channel_id)

    def _on_connected(self, channel_id, device):
        self.connected_channels.add(channel_id)
        self._channel_status_var(channel_id).set(f"{device}: chờ LL/RR")
        self.bt_button_text.set("⏹ Ngắt kết nối FSR")
        self.status.set(f"Đã mở {device}; đang chờ dữ liệu")
        if self.active_channels and self.active_channels.issubset(self.connected_channels):
            self._set_connection_panel_collapsed(True)

    def _on_module_detected(self, channel_id, raw_module, device):
        # Giữ đúng quy ước phần cứng: RR là chân trái (Left), LL là chân phải (Right)
        side = "left" if raw_module == "RR" else "right"
        self.detected_sides[channel_id] = side
        side_label = "Chân trái" if side == "left" else "Chân phải"
        self._channel_status_var(channel_id).set(f"{device}: {raw_module} ({side_label})")

        labels = []
        for current_channel in sorted(self.detected_sides):
            current_side = self.detected_sides[current_channel]
            actual_leg = "Left" if current_side == "left" else "Right"
            code = "RR" if current_side == "left" else "LL"
            labels.append(f"{code} ({actual_leg})")
        duplicate = len(self.detected_sides) > 1 and len(set(self.detected_sides.values())) < len(
            self.detected_sides
        )
        self.module_code.set(" | ".join(labels) + (" (TRÙNG CHÂN)" if duplicate else ""))
        if duplicate:
            self.status.set("Cảnh báo: cả hai cổng đang gửi cùng một bên chân")

    def _update_after_frame(
        self,
        channel_id,
        frame_side,
        matrix,
        unit,
        status,
        zero_metadata=None,
        sample_time=None,
    ):
        self._ui_frame_pending[channel_id] = False
        if not self.running:
            return
        if unit != self._selected_unit:
            return
        if unit == 'newton' and zero_metadata is not None and not self.shoe_zero.is_current(zero_metadata):
            return
        side_code = "LL" if frame_side == "left" else "RR"
        count = self.frame_counts[channel_id]
        self._channel_status_var(channel_id).set(f"{side_code}: đã nhận {count} frame")
        self.status.set(status)
        self.draw_matrix(matrix, frame_side, unit)
        self._append_chart_sample(frame_side, matrix, unit=unit)
        self._append_fsi_sample(frame_side, matrix, unit, sample_time)

    def _stream_failed(self, channel_id, device, error_message):
        self.connected_channels.discard(channel_id)
        self.active_channels.discard(channel_id)
        self._channel_status_var(channel_id).set(f"{device}: đang tắt / bỏ qua")

        # Nếu chân còn lại vẫn đang hoạt động hoặc đang mở: KHÔNG bật popup làm đơ app, KHÔNG reset zero!
        if self.active_channels or self.connected_channels:
            self.status.set(f"Đã bỏ qua {device} (không phản hồi); đang chạy 1 chân bình thường")
            if self.active_channels and self.active_channels.issubset(self.connected_channels):
                self._set_connection_panel_collapsed(True)
            return

        # Chỉ khi CẢ 2 chân đều không kết nối được mới dừng và báo lỗi
        self._reset_zero('Không mở được cổng FSR · baseline calib vẫn được giữ')
        self.running = False
        self.bt_button_text.set("🔌 Kết nối FSR ▾")
        self.module_code.set("--")
        self._set_connection_panel_collapsed(False)
        self.status.set(f"Lỗi {device}: {error_message}")
        messagebox.showwarning(
            "Không kết nối được FSR",
            f"Không mở được {device}.\n\nChi tiết: {error_message}\n\n"
            "Mẹo: Nếu bạn chỉ bật 1 chân, hãy bấm nút '🔌 Kết nối FSR ▾' rồi chọn "
            "'Chỉ kết nối FSR 1' hoặc 'Chỉ kết nối FSR 2' để kết nối tức thì.",
            parent=self.root,
        )

    def _channel_finished(self, channel_id):
        self.active_channels.discard(channel_id)
        self.connected_channels.discard(channel_id)
        if self.running and not self.active_channels and not self.connected_channels:
            self._reset_zero('Cổng FSR đã đóng · baseline calib được giữ')
            self.running = False
            self.bt_button_text.set("🔌 Kết nối FSR ▾")
            self.status.set("Không còn cổng FSR nào đang chạy")
            if self.log_handle is not None:
                self._stop_logging()
    # Tọa độ chuẩn hóa (0..1) của viền tấm lót giày theo đúng hình mẫu
    INSOLE_OUTLINE_TEMPLATE = (
        (0.33, 0.030),
        (0.45, 0.025),
        (0.56, 0.040),
        (0.66, 0.075),
        (0.74, 0.125),
        (0.79, 0.190),
        (0.81, 0.270),
        (0.81, 0.360),
        (0.80, 0.450),
        (0.78, 0.540),
        (0.76, 0.630),
        (0.75, 0.720),
        (0.75, 0.810),
        (0.73, 0.888),
        (0.66, 0.940),
        (0.56, 0.962),
        (0.44, 0.958),
        (0.34, 0.932),
        (0.28, 0.878),
        (0.27, 0.795),
        (0.27, 0.705),
        (0.27, 0.615),
        (0.25, 0.525),
        (0.21, 0.435),
        (0.17, 0.345),
        (0.14, 0.255),
        (0.14, 0.175),
        (0.18, 0.105),
        (0.25, 0.055),
    )

    # Tọa độ tâm 48 ô cảm biến [hàng 0..11][cột 0..3]
    INSOLE_PAD_CENTERS_TEMPLATE = (
        ((0.235, 0.118), (0.365, 0.090), (0.495, 0.100), (0.625, 0.130)),
        ((0.210, 0.194), (0.360, 0.174), (0.510, 0.184), (0.660, 0.206)),
        ((0.230, 0.268), (0.380, 0.256), (0.530, 0.262), (0.680, 0.276)),
        ((0.250, 0.340), (0.400, 0.333), (0.550, 0.338), (0.695, 0.346)),
        ((0.295, 0.410), (0.432, 0.408), (0.568, 0.410), (0.700, 0.414)),
        ((0.320, 0.480), (0.450, 0.480), (0.578, 0.482), (0.700, 0.484)),
        ((0.350, 0.552), (0.467, 0.553), (0.583, 0.554), (0.695, 0.555)),
        ((0.350, 0.622), (0.467, 0.623), (0.583, 0.623), (0.695, 0.623)),
        ((0.350, 0.692), (0.467, 0.694), (0.583, 0.694), (0.695, 0.692)),
        ((0.345, 0.760), (0.462, 0.764), (0.578, 0.764), (0.690, 0.760)),
        ((0.340, 0.825), (0.456, 0.835), (0.572, 0.835), (0.686, 0.823)),
        ((0.346, 0.888), (0.454, 0.908), (0.566, 0.908), (0.674, 0.884)),
    )

    def _on_insole_mode_click(self):
        self._popup_menu_below(
            self.insole_mode_button,
            [
                ("🔥 Bàn chân: Hiện số lực khi có tải", lambda: self._set_insole_display_mode("force_active"), "normal"),
                ("🔢 Bàn chân: Luôn hiện số lực (cả 0)", lambda: self._set_insole_display_mode("force_all"), "normal"),
                ("🎨 Bàn chân: Chỉ hiện màu nhiệt (ẩn số)", lambda: self._set_insole_display_mode("color_only"), "normal"),
                "---",
                ("▦ Chuyển về lưới chữ nhật 12×4 cổ điển", lambda: self._set_insole_display_mode("grid"), "normal"),
            ],
        )

    def _set_insole_display_mode(self, mode):
        self.insole_display_mode = mode
        labels = {
            "force_active": "🔥 Hiển thị: Số lực (khi có tải) ▾",
            "force_all": "🔢 Hiển thị: Luôn hiện số lực ▾",
            "color_only": "🎨 Hiển thị: Chỉ màu nhiệt ▾",
            "grid": "▦ Hiển thị: Lưới 12×4 ▾",
        }
        self.insole_mode_text.set(labels.get(mode, "🔥 Hiển thị: Số lực (khi có tải) ▾"))
        for side in ("left", "right"):
            self.preview_state[side]["shape"] = (0, 0)
            self._resize_matrix(side)

    def _toggle_insole_mirror(self):
        self.insole_mirror_swapped = not getattr(self, "insole_mirror_swapped", False)
        for side in ("left", "right"):
            self.preview_state[side]["shape"] = (0, 0)
            self._resize_matrix(side)

    def _is_mirrored_insole(self, side):
        swapped = getattr(self, "insole_mirror_swapped", False)
        if not swapped:
            return side == "left"
        return side == "right"

    def _resize_matrix(self, side):
        state = self.preview_state[side]
        self.draw_matrix(
            state.get("matrix", [[0.0] * 4 for _ in range(12)]),
            side,
            state.get("unit", self._selected_unit),
        )

    def draw_matrix(self, matrix, side=None, unit=None):
        matrix = validate_matrix(matrix)
        unit = unit or self._selected_unit
        min_force, max_force = color_range_for_unit(unit)
        side = side if side in ("left", "right") else self.side.get()
        canvas = self.canvas_left if side == "left" else self.canvas_right
        summary = self.summary_left if side == "left" else self.summary_right
        state = self.preview_state[side]
        state["matrix"] = [row[:] for row in matrix]
        state["unit"] = unit

        rows = len(matrix)
        columns = len(matrix[0])
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        display_mode = getattr(self, "insole_display_mode", "force_active")
        mirrored = self._is_mirrored_insole(side)
        render_key = (rows, columns, display_mode, mirrored)

        # Fallback về lưới chữ nhật nếu không phải 12x4 hoặc đang chọn chế độ lưới
        if rows != 12 or columns != 4 or display_mode == "grid":
            if (
                state.get("shape") != render_key
                or state.get("size") != (width, height)
                or len(state.get("rects", ())) != rows * columns
            ):
                canvas.delete("all")
                state["rects"] = []
                state["texts"] = []
                state["cop_items"] = []
                state["shape"] = render_key
                state["size"] = (width, height)

                cell_width = width / columns
                cell_height = height / rows
                for y in range(rows):
                    for x in range(columns):
                        x0, y0 = x * cell_width, y * cell_height
                        x1, y1 = x0 + cell_width, y0 + cell_height
                        state["rects"].append(
                            canvas.create_rectangle(
                                x0, y0, x1, y1, fill="#111827", outline="#374151"
                            )
                        )
                        state["texts"].append(
                            canvas.create_text(
                                (x0 + x1) / 2,
                                (y0 + y1) / 2,
                                text="",
                                fill="#d1d5db",
                                font=("Consolas", 8),
                            )
                        )

            cell_width = width / columns
            cell_height = height / rows
            index = 0
            for row in matrix:
                for value in row:
                    canvas.itemconfig(
                        state["rects"][index],
                        fill=get_force_color(value, min_force, max_force),
                    )
                    if cell_width >= 20 and cell_height >= 14:
                        text_color = (
                            "#111827"
                            if value >= (min_force + max_force) / 3
                            else "#ffffff"
                        )
                        value_text = f"{value:.2f}" if unit == "newton" else f"{value:g}"
                        canvas.itemconfig(
                            state["texts"][index], text=value_text, fill=text_color
                        )
                    else:
                        canvas.itemconfig(state["texts"][index], text="")
                    index += 1
        else:
            # Chế độ vẽ tấm cảm ứng bàn chân 48 ô (Đã xoá hoàn toàn số thứ tự ô 1..48 để không nhầm với số lực)
            if (
                state.get("shape") != render_key
                or state.get("size") != (width, height)
                or len(state.get("rects", ())) != 48
            ):
                canvas.delete("all")
                state["rects"] = []
                state["texts"] = []
                state["pad_centers"] = []
                state["cop_items"] = []
                state["shape"] = render_key
                state["size"] = (width, height)

                avail_h = max(height - 12, 60)
                avail_w = max(width - 16, 40)
                insole_h = avail_h
                insole_w = min(avail_w, max(insole_h * 0.68, 220.0))
                x_offset = (width - insole_w) / 2.0
                y_offset = 6.0

                def to_canvas_xy(nx, ny):
                    tx = (1.0 - nx) if mirrored else nx
                    return x_offset + tx * insole_w, y_offset + ny * insole_h

                # 1. Vẽ nền tấm lót giày màu xanh ngọc
                outline_pts = []
                for nx, ny in self.INSOLE_OUTLINE_TEMPLATE:
                    cx, cy = to_canvas_xy(nx, ny)
                    outline_pts.extend((cx, cy))
                canvas.create_polygon(
                    *outline_pts,
                    fill="#009b77",
                    outline="#065f46",
                    width=2.5,
                    smooth=True,
                    splinesteps=24,
                )

                # 2. Tính tâm 48 ô cảm biến trên tấm lót
                pad_centers_grid = []
                for r in range(12):
                    row_centers = []
                    template_row = self.INSOLE_PAD_CENTERS_TEMPLATE[r]
                    for c in range(4):
                        src_col = (3 - c) if mirrored else c
                        nx, ny = template_row[src_col]
                        row_centers.append(to_canvas_xy(nx, ny))
                    pad_centers_grid.append(row_centers)

                # 3. Vẽ đường mạch dẫn nối giữa các ô cảm biến
                for c in range(4):
                    col_line = []
                    for r in range(12):
                        col_line.extend(pad_centers_grid[r][c])
                    canvas.create_line(*col_line, fill="#99f6e4", width=1.2)
                for r in range(12):
                    row_line = []
                    for c in range(4):
                        row_line.extend(pad_centers_grid[r][c])
                    canvas.create_line(*row_line, fill="#5eead4", width=1.0)

                # 4. Vẽ 48 ô cảm biến và chỉ hiển thị giá trị lực ở chính giữa ô
                min_dx = min(
                    abs(pad_centers_grid[r][c + 1][0] - pad_centers_grid[r][c][0])
                    for r in range(12)
                    for c in range(3)
                )
                row_dy = abs(pad_centers_grid[1][0][1] - pad_centers_grid[0][0][1])
                pad_w = max(12.0, min(min_dx * 0.82, 34.0))
                pad_h = max(10.0, min(row_dy * 0.78, 24.0))
                font_size_main = max(7, min(9, int(pad_h * 0.48)))

                for r in range(12):
                    for c in range(4):
                        cx, cy = pad_centers_grid[r][c]
                        state["pad_centers"].append((cx, cy))
                        x0, y0 = cx - pad_w / 2.0, cy - pad_h / 2.0
                        x1, y1 = cx + pad_w / 2.0, cy + pad_h / 2.0
                        rect_id = canvas.create_rectangle(
                            x0,
                            y0,
                            x1,
                            y1,
                            fill="#e7e2d3",
                            outline="#1e293b",
                            width=1.2,
                        )
                        state["rects"].append(rect_id)
                        val_item = canvas.create_text(
                            cx,
                            cy,
                            text="",
                            fill="#111827",
                            font=("Consolas", font_size_main, "bold"),
                        )
                        state["texts"].append(val_item)

                # Điểm đánh dấu trọng tâm lực CoP trên bàn chân
                cop_ring = canvas.create_oval(
                    0, 0, 0, 0, outline="#38bdf8", width=2.2, state="hidden"
                )
                cop_dot = canvas.create_oval(
                    0, 0, 0, 0, fill="#ffffff", outline="#0284c7", width=1.5, state="hidden"
                )
                state["cop_items"] = [cop_ring, cop_dot]

            # Cập nhật màu sắc và giá trị lực trên 48 ô cảm biến
            index = 0
            weighted_px = 0.0
            weighted_py = 0.0
            total_force = 0.0

            for r, row in enumerate(matrix):
                for c, value in enumerate(row):
                    has_load = value >= min_force
                    if has_load:
                        fill_color = get_force_color(value, min_force, max_force)
                        border_color = "#ffffff"
                    else:
                        fill_color = "#e7e2d3"
                        border_color = "#1e293b"

                    canvas.itemconfig(
                        state["rects"][index],
                        fill=fill_color,
                        outline=border_color,
                    )

                    value_text = f"{value:.1f}" if unit == "newton" else f"{value:.0f}"

                    if display_mode == "color_only":
                        text_to_show = ""
                        text_color = "#111827"
                    elif display_mode == "force_all":
                        text_to_show = value_text if has_load else "0"
                        text_color = (
                            "#111827"
                            if (not has_load or value >= (min_force + max_force) / 3)
                            else "#ffffff"
                        )
                    else:
                        # Mặc định ("force_active"): Chỉ hiện số lực khi ô đang chịu tải, ô không tải để trống hoàn toàn
                        text_to_show = value_text if has_load else ""
                        text_color = (
                            "#111827"
                            if value >= (min_force + max_force) / 3
                            else "#ffffff"
                        )

                    canvas.itemconfig(
                        state["texts"][index],
                        text=text_to_show,
                        fill=text_color,
                    )

                    if value > 0 and index < len(state.get("pad_centers", ())):
                        px, py = state["pad_centers"][index]
                        weighted_px += px * value
                        weighted_py += py * value
                        total_force += value
                    index += 1

            # Cập nhật vị trí tâm áp lực (CoP) trực tiếp trên hình bàn chân
            if state.get("cop_items"):
                cop_ring, cop_dot = state["cop_items"]
                if total_force >= min_force:
                    cx = weighted_px / total_force
                    cy = weighted_py / total_force
                    canvas.coords(cop_ring, cx - 8, cy - 8, cx + 8, cy + 8)
                    canvas.coords(cop_dot, cx - 3, cy - 3, cx + 3, cy + 3)
                    canvas.itemconfig(cop_ring, state="normal")
                    canvas.itemconfig(cop_dot, state="normal")
                else:
                    canvas.itemconfig(cop_ring, state="hidden")
                    canvas.itemconfig(cop_dot, state="hidden")

        total, cop_x, cop_y = matrix_summary(matrix)
        cop_text = "--" if cop_x is None else f"({cop_x:.2f}, {cop_y:.2f})"
        side_code = "LL" if side == "left" else "RR"
        summary.set(
            f"{side_code} | {rows}×{columns} | Tổng: {total:.2f} "
            f"{unit_label(unit)}\nCoP: {cop_text}"
        )
    def close(self):
        self.running = False
        self._finish_standing_on_shutdown()
        self._reset_zero()
        self.stop_playback(silent=True)
        self._stop_logging("Đã đóng log")
        with self.serial_lock:
            connections = list(self.serial_connections.values())
            self.serial_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
        self.socket.close()
        self.root.destroy()



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='FSR transmitter; built-in experimental profiles for the measured pair.')
    parser.add_argument('--no-calibration', action='store_true', help='Use original force formula without cell correction')
    parser.add_argument('--right-calibration', type=Path)
    parser.add_argument('--left-calibration', type=Path)
    args = parser.parse_args()
    if args.no_calibration:
        CELL_CALIBRATIONS = {}
    elif args.right_calibration or args.left_calibration:
        # Explicit profile flags retain their original opt-in semantics.
        CELL_CALIBRATIONS = {}
    for side, profile_path in (('right', args.right_calibration), ('left', args.left_calibration)):
        if profile_path is None:
            continue
        with profile_path.open(encoding='utf-8') as handle:
            profile = json.load(handle)
        if (profile.get('version') != 1 or profile.get('side') != side
                or not profile.get('id') or not profile.get('status')):
            raise ValueError(f'Unsupported {side} calibration profile')
        apply_cell_calibration([[0.0]*4 for _ in range(12)], side, profile)
        CELL_CALIBRATIONS[side] = profile
    window = tk.Tk()
    app = FSRTransmitterApp(window)
    if CELL_CALIBRATIONS:
        notes = []
        for side, profile in CELL_CALIBRATIONS.items():
            pending = [(r+1, c+1) for r, row in enumerate(profile['cells'])
                       for c, cell in enumerate(row) if cell is None]
            label = 'Phải' if side == 'right' else 'Trái'
            notes.append(f'{label}: các ô (hàng, cột) CHƯA hiệu chỉnh: {pending}')
            if profile.get('id') == 'right-20260929-three-point-v4':
                notes.append('Phải: 18 ô thử ba mốc 0 / 14,4 / 17,66 N; còn lại giữ hệ số cũ.')
                notes.append(f'Phải: cần đo lại (hàng, cột): {RIGHT_THREE_POINT_RETEST_CELLS}')
        window.title(window.title() + ' | HIỆU CHỈNH THỬ: ' + ', '.join(CELL_CALIBRATIONS))
        messagebox.showinfo('Hiệu chỉnh sơ bộ FSR',
                            'Chỉ dùng với đúng các miếng đã đo và cùng cách lắp.\n'
                            'Chọn Newton để áp dụng. ADC và bên không nạp profile giữ nguyên.\n'
                            'Chưa kiểm chứng toàn dải lực. Dùng nút Zero khi mang giày, chân không chịu tải.\n'
                            'Hiệu chỉnh sơ bộ; cần cân lại cả lúc tăng và giảm tải.\n'
                            'Mở với --no-calibration để trở về công thức cũ.\n'
                            + '\n'.join(notes))
    window.mainloop()
