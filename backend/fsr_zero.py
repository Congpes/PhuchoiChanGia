"""Robust statistics for incremental unloaded FSR calibration."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from statistics import median
from typing import Iterable, Sequence


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
    noise = [[0.02] * columns for _ in range(rows)]
    for row in range(rows):
        for column in range(columns):
            values = [float(entry["matrix"][row][column]) for entry in current_history]
            baseline[row][column] = float(median(values))
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
        "noise": noise,
        "round_count": len(current_history),
        "method": "lift_round_history_median_v3",
        "redistribution_warnings": warnings,
    }
