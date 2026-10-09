"""Pure FSR phase and force-symmetry metrics used by transmitter V3.

The module deliberately keeps all 48 cells in each sample.  A configured ROI
is only a reporting view; it is never used to decide whether the foot is in
contact with the plate.
"""

from __future__ import annotations

import copy
import math
from typing import Iterable, Mapping, Sequence


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
            "peak": None,
            "impulse": None,
            "duration": 0.0,
            "valid_sample_count": 0,
            "quality": "invalid/missing" if had_invalid else "no_load",
            "reason": "no_valid_roi_samples",
        }
    values = [value for _, value in selected]
    impulse = 0.0
    for (time_a, value_a), (time_b, value_b) in zip(selected, selected[1:]):
        if time_b > time_a:
            impulse += (value_a + value_b) * 0.5 * (time_b - time_a)
    return {
        "mean": round(sum(values) / len(values), 4),
        "peak": round(max(values), 4),
        "impulse": round(impulse, 4),
        "duration": round(selected[-1][0] - selected[0][0], 4),
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
) -> list[dict]:
    """Detect every full-48-cell contact interval and an optional heel-off.

    Heel-off is only reported when the heel ROI unloads while the forefoot
    remains loaded.  Otherwise callers must use the explicit fallback window.
    """
    threshold_value = float(threshold)
    required = max(1, int(debounce))
    ordered = sorted(samples, key=lambda item: float(item.get("timestamp", 0.0)))
    intervals: list[dict] = []
    active_streak: list[tuple[float, float, Mapping]] = []
    contact: list[tuple[float, float, Mapping]] = []

    def finish_contact() -> None:
        nonlocal contact
        if not contact:
            return
        start, end = contact[0][0], contact[-1][0]
        interval = {
            "detected": True,
            "ic": start,
            "to": end,
            "start": start,
            "end": end,
            "quality": "valid",
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

    for sample in ordered:
        try:
            timestamp = float(sample["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        total = _sample_total(sample)
        if total is not None and total >= threshold_value:
            if contact:
                contact.append((timestamp, total, sample))
            else:
                active_streak.append((timestamp, total, sample))
                if len(active_streak) >= required:
                    contact.extend(active_streak)
                    active_streak.clear()
        elif contact:
            finish_contact()
            active_streak.clear()
        else:
            active_streak.clear()
    finish_contact()
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


def phase_windows(stride: Mapping, opposite_stride: Mapping | None = None) -> dict:
    """Return side-specific phase windows in absolute timestamps.

    When heel-off is unavailable, the terminal window is explicitly labelled
    as a fallback instead of pretending to be an anatomical HO event.
    """
    ic = stride.get("ic")
    to = stride.get("to")
    opposite_ic = opposite_stride.get("ic") if opposite_stride else None
    opposite_to = opposite_stride.get("to") if opposite_stride else None
    ho = stride.get("ho")
    result = {
        "loading": (ic, opposite_to, "valid" if ic is not None and opposite_to is not None else "missing"),
        "midstance": (opposite_to, ho, "valid" if opposite_to is not None and ho is not None else "missing"),
        "terminal_stance": (ho, opposite_ic, "valid" if ho is not None and opposite_ic is not None else "missing"),
        "pre_swing": (opposite_ic, to, "valid" if opposite_ic is not None and to is not None else "missing"),
        "swing": (to, stride.get("next_ic"), "valid" if to is not None and stride.get("next_ic") is not None else "missing"),
    }
    if ho is None and ic is not None and to is not None and to > ic:
        fallback_start = ic + 0.65 * (to - ic)
        result["terminal_stance_window"] = (fallback_start, to, "fallback_no_ho")
    return result


def _window_summary(samples: Sequence[Mapping], window, cells: Sequence[tuple[int, int]]) -> dict:
    if not window or window[0] is None or window[1] is None or window[1] < window[0]:
        return {"mean": None, "peak": None, "impulse": None, "duration": 0.0,
                "valid_sample_count": 0, "quality": "invalid/missing", "reason": "phase_marker_missing"}
    return phase_summary(samples, window[0], window[1], cells)


def compare_phase_pair(
    left_samples: Sequence[Mapping],
    right_samples: Sequence[Mapping],
    left_stride: Mapping,
    right_stride: Mapping,
    *,
    pair_id: str = "",
    rois: Mapping[str, Sequence[tuple[int, int]]] | None = None,
) -> list[dict]:
    """Calculate the planned phase/region rows for one left/right pair."""
    configured = rois or get_fsi_rois()
    validate_roi(configured, exclusive=False)
    left_windows = phase_windows(left_stride, right_stride)
    right_windows = phase_windows(right_stride, left_stride)
    rows: list[dict] = []

    def add(phase: str, region: str, window_name: str, metric: str = "mean") -> None:
        left_summary = _window_summary(left_samples, left_windows.get(window_name), configured[region])
        right_summary = _window_summary(right_samples, right_windows.get(window_name), configured[region])
        result = phase_fsi(left_summary, right_summary, metric, region=region)
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
        })

    add("contact", "heel", "loading", "mean")
    add("midstance", "heel", "midstance", "mean")
    add("midstance", "forefoot", "midstance", "mean")
    add("midstance", "stance_sampled", "midstance", "mean")
    push_window = "terminal_stance" if "terminal_stance" in left_windows and left_windows["terminal_stance"][2] == "valid" else "terminal_stance_window"
    add("push", "forefoot", push_window, "mean")
    return rows


def summarize_phase_rows(rows: Sequence[Mapping]) -> list[dict]:
    """Aggregate valid pair FSI values without recomputing FSI from means."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        value = row.get("fsi")
        if row.get("quality") == "valid" and value is not None and _finite(value):
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

    def __init__(self, threshold: float = 5.0, debounce: int = 2, max_samples: int = 12000):
        self.threshold = float(threshold)
        self.debounce = max(1, int(debounce))
        self.max_samples = max(100, int(max_samples))
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

    def contact_events(self, side: str) -> list[dict]:
        normalized_side = str(side).strip().lower()
        cells = get_fsi_rois()
        return detect_contact_intervals(
            self.samples[normalized_side],
            self.threshold,
            self.debounce,
            heel_cells=cells["heel"],
            forefoot_cells=cells["forefoot"],
        )

    @staticmethod
    def _pair_events(left_events: Sequence[Mapping], right_events: Sequence[Mapping]) -> list[tuple[Mapping, Mapping]]:
        """Pair adjacent opposite contacts in event time, never by raw index."""
        events = sorted(
            [(float(event.get("ic")), "left", event) for event in left_events]
            + [(float(event.get("ic")), "right", event) for event in right_events],
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

    def pair_rows(self) -> list[dict]:
        left_events = self.contact_events("left")
        right_events = self.contact_events("right")
        rows: list[dict] = []
        for index, (left_event, right_event) in enumerate(self._pair_events(left_events, right_events), start=1):
            left_index = left_events.index(left_event)
            right_index = right_events.index(right_event)
            left_stride = build_stride([left_event, *left_events[left_index + 1: left_index + 2]], "left")
            right_stride = build_stride([right_event, *right_events[right_index + 1: right_index + 2]], "right")
            rows.extend(compare_phase_pair(
                self.samples["left"], self.samples["right"],
                left_stride, right_stride, pair_id=f"BT{index}-BP{index}",
            ))
        return rows

    def snapshot(self) -> dict:
        rows = self.pair_rows()
        return {
            "pairs": rows,
            "summary": summarize_phase_rows(rows),
            "contact_events": {side: self.contact_events(side) for side in ("left", "right")},
            "sample_count": {side: len(self.samples[side]) for side in ("left", "right")},
            "threshold": self.threshold,
        }
