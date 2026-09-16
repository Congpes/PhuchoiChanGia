"""Realtime FSR stance segmentation, left/right pairing, and window analysis."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Optional

import numpy as np

from step_events import pair_step_intervals


REGIONS = ("total", "heel", "midfoot", "forefoot")
REGION_ROWS = {
    "forefoot": (0, 3),
    "midfoot": (4, 8),
    "heel": (9, 11),
}
VALID_WINDOWS = (0, 5, 7)
PEAK_FORE_FALLBACK_START_PERCENT = 65.0
MAX_PAIR_CONTACT_GAP_SECONDS = 1.6
MIN_PAIRS_FOR_STEADY_STATE_FILTER = 5


def force_symmetry_index(left_peak: float, right_peak: float) -> Optional[float]:
    """Return a force symmetry score where 100% means perfectly symmetric."""
    maximum = max(float(left_peak), float(right_peak))
    if maximum <= 0:
        return None
    return round(100.0 * min(float(left_peak), float(right_peak)) / maximum, 2)


def _peak_fore_metrics(curve: List[float], timestamps=None) -> dict:
    """Measure forefoot peak in terminal stance when heel-off is unavailable.

    The current FSR stream does not explicitly label heel-off.  We therefore
    use the final 35% of the normalised stance as the documented fallback for
    push-off and keep the method in the returned record.
    """
    if not curve:
        return {
            "peakFore": 0.0,
            "peakForePhasePercent": None,
            "peakForeStartPercent": PEAK_FORE_FALLBACK_START_PERCENT,
            "peakForeMethod": "terminal_stance_fallback",
        }
    final_index = max(0, len(curve) - 1)
    phases = (
        [100.0 * (float(t) - timestamps[0]) / (timestamps[-1] - timestamps[0]) for t in timestamps]
        if timestamps is not None and len(timestamps) == len(curve) and timestamps[-1] > timestamps[0]
        else [100.0 * i / max(1, final_index) for i in range(len(curve))]
    )
    start_index = next((i for i, phase in enumerate(phases) if phase >= PEAK_FORE_FALLBACK_START_PERCENT), final_index)
    push_off_curve = curve[start_index:] or curve
    peak_value = max(push_off_curve)
    peak_index = start_index + push_off_curve.index(peak_value)
    phase_percent = phases[peak_index]
    return {
        "peakFore": round(float(peak_value), 4),
        "peakForePhasePercent": round(phase_percent, 2),
        "peakForeStartPercent": PEAK_FORE_FALLBACK_START_PERCENT,
        "peakForeMethod": "terminal_stance_fallback",
    }


def _descriptive_force_stats(values: Iterable[float]) -> dict:
    """Return report-ready descriptive statistics for one force metric."""
    finite = np.asarray([
        float(value) for value in values
        if value is not None and np.isfinite(float(value))
    ], dtype=float)
    if finite.size == 0:
        return {
            "mean": None,
            "sd": None,
            "min": None,
            "max": None,
            "n": 0,
        }
    return {
        "mean": round(float(np.mean(finite)), 4),
        "sd": round(
            float(np.std(finite, ddof=1)) if finite.size > 1 else 0.0,
            4,
        ),
        "min": round(float(np.min(finite)), 4),
        "max": round(float(np.max(finite)), 4),
        "n": int(finite.size),
    }


def _curve_peak(step: dict, region: str) -> Optional[float]:
    curves = step.get("curves") if isinstance(step, dict) else None
    curve = curves.get(region) if isinstance(curves, dict) else None
    if isinstance(step, dict):
        curve = step.get('rawRegionValues', {}).get(region, curve)
    if not isinstance(curve, list):
        return None
    finite = [float(value) for value in curve if np.isfinite(float(value))]
    return max(finite) if finite else None


def _step_force_metrics(step: dict) -> dict:
    """Extract quantitative values from raw, baseline-corrected step data.

    Display-only curves are deliberately ignored here so that smoothing or
    chart styling can never alter the values used in the report table.
    """
    duration = step.get("duration")
    impulse = step.get("loadImpulse")
    peak_total = step.get("peakActivity")
    if peak_total is None:
        peak_total = _curve_peak(step, "total")
    peak_fore = step.get("peakFore")
    if peak_fore is None:
        fore_curve = step.get("curves", {}).get("forefoot", [])
        peak_fore = _peak_fore_metrics(fore_curve).get("peakFore")
    mean_stance = None
    if (
        duration is not None
        and impulse is not None
        and float(duration) > 1e-9
    ):
        mean_stance = float(impulse) / float(duration)
    return {
        "peakTotal": peak_total,
        "meanStanceForce": mean_stance,
        "peakHeel": _curve_peak(step, "heel"),
        "peakMidfoot": _curve_peak(step, "midfoot"),
        "peakFore": peak_fore,
        "loadImpulse": impulse,
    }


def _force_summary(pairs: List[dict], force_unit: str) -> dict:
    """Aggregate total/regional force and left-right symmetry for a report."""
    metric_specs = (
        ("peakTotal", "Peak tổng lực", force_unit),
        ("peakHeel", "Peak vùng gót", force_unit),
        ("peakMidfoot", "Peak vùng giữa bàn chân", force_unit),
        ("peakFore", "Peak Fore (mũi / đẩy chân)", force_unit),
        ("meanStanceForce", "Lực trung bình pha chống", force_unit),
        ("loadImpulse", "Xung lực tải", f"{force_unit}·s"),
    )
    side_metrics = {"left": [], "right": []}
    pair_rows = []
    for pair in pairs:
        measured = {
            side: _step_force_metrics(pair.get(side, {}))
            for side in ("left", "right")
        }
        side_metrics["left"].append(measured["left"])
        side_metrics["right"].append(measured["right"])
        pair_rows.append({
            "pairIndex": pair.get("pairIndex"),
            "left": measured["left"],
            "right": measured["right"],
            "fsi": {
                key: force_symmetry_index(
                    measured["left"].get(key) or 0.0,
                    measured["right"].get(key) or 0.0,
                )
                for key, _, _ in metric_specs
            },
        })

    rows = []
    for key, label, unit in metric_specs:
        left = _descriptive_force_stats(
            item.get(key) for item in side_metrics["left"]
        )
        right = _descriptive_force_stats(
            item.get(key) for item in side_metrics["right"]
        )
        left_mean = left.get("mean")
        right_mean = right.get("mean")
        fsi = (
            force_symmetry_index(left_mean, right_mean)
            if left_mean is not None and right_mean is not None
            else None
        )
        pair_fsi = _descriptive_force_stats(
            row["fsi"].get(key) for row in pair_rows
        )
        rows.append({
            "key": key,
            "label": label,
            "unit": unit,
            "left": left,
            "right": right,
            "fsi": fsi,
            "asymmetry": None if fsi is None else round(100.0 - fsi, 2),
            "pairFsi": pair_fsi,
        })
    return {
        "pairCount": len(pairs),
        "source": "raw_baseline_corrected_steps",
        "fsiFormula": "100 * min(left, right) / max(left, right)",
        "fsiInterpretation": "100_percent_is_equal_loading",
        "rows": rows,
        "pairRows": pair_rows,
    }


def _normalize(values: Iterable[float], target_len: int = 101, timestamps=None) -> List[float]:
    """Time-normalize measured samples linearly, without amplitude filtering."""
    source_values = np.asarray(list(values), dtype=float)
    if source_values.size == 0 or not np.isfinite(source_values).all():
        return []
    if source_values.size == 1:
        return np.repeat(source_values[0], target_len).round(4).tolist()
    source = np.asarray(list(timestamps), dtype=float) if timestamps is not None else np.arange(len(source_values), dtype=float)
    if len(source) != len(source_values) or np.any(np.diff(source) <= 0):
        return []
    return np.interp(np.linspace(source[0], source[-1], target_len),
                     source, source_values).round(4).tolist()


def _step_measurement_quality(
    samples: List[dict],
    baseline: Dict[str, float],
    display_curves: Dict[str, List[float]],
) -> dict:
    """Score acquisition quality without rejecting genuine abnormal gait."""
    reasons: List[str] = []
    warnings: List[str] = []
    times = np.asarray([float(item["time"]) for item in samples], dtype=float)
    activity = np.asarray([
        max(0.0, float(item["regions"]["total"]) - baseline.get("total", 0.0))
        for item in samples
    ])
    peak = float(np.max(activity)) if activity.size else 0.0
    sample_rate = 0.0
    max_gap_ratio = 1.0
    max_gap_seconds = 0.0
    if times.size >= 2:
        gaps = np.diff(times)
        positive = gaps[gaps > 0]
        if positive.size:
            median_gap = float(np.median(positive))
            sample_rate = 1.0 / median_gap if median_gap > 0 else 0.0
            max_gap_seconds = float(np.max(positive))
            max_gap_ratio = float(max_gap_seconds / median_gap)
    if sample_rate < 8.0:
        reasons.append("sample_rate_out_of_range")
    duration = float(times[-1] - times[0]) if times.size >= 2 else 0.0
    if (
        max_gap_ratio > 12.0
        and max_gap_seconds > max(0.60, duration * 0.45)
    ):
        reasons.append("serial_packet_gap")
    elif max_gap_ratio > 4.5:
        # Short Bluetooth pauses can be interpolated safely for display. Keep
        # the step and expose a warning instead of discarding most real walks.
        warnings.append("short_packet_gap_interpolated")

    spike_ratio = 0.0
    jump_fraction = 0.0
    if activity.size >= 5 and peak > 0:
        padded = np.pad(activity, 2, mode="edge")
        median_trace = np.asarray([
            np.median(padded[index:index + 5])
            for index in range(activity.size)
        ])
        spike_ratio = float(np.percentile(np.abs(activity - median_trace), 95) / peak)
        jumps = np.abs(np.diff(activity))
        jump_fraction = float(np.mean(jumps > max(10.0, peak * 0.45)))
        # A real heel strike can rise sharply; only repeated/large deviations
        # beyond that physiological edge are treated as acquisition noise.
        if spike_ratio > 0.38 or jump_fraction > 0.18:
            reasons.append("force_spike_noise")

    phases = {}
    max_roughness = 0.0
    for region in ("heel", "midfoot", "forefoot"):
        curve = np.asarray(display_curves.get(region, []), dtype=float)
        if curve.size < 3 or not np.all(np.isfinite(curve)):
            continue
        amplitude = max(float(np.ptp(curve)), 1e-6)
        roughness = float(np.sum(np.abs(np.diff(curve, n=2))) / amplitude)
        max_roughness = max(max_roughness, roughness)
        phases[region] = int(np.argmax(curve))
    if max_roughness > 0.45:
        # Curve shape itself may be clinically meaningful. Preserve it and
        # warn, but never discard a step on roughness
        # alone without an independent packet/spike acquisition failure.
        warnings.append("raw_signal_roughness")
    if all(name in phases for name in ("heel", "midfoot", "forefoot")):
        if not phases["heel"] < phases["midfoot"] < phases["forefoot"]:
            # An atypical rollover can be clinically real, so report it but do
            # not silently remove it from analysis as a measurement failure.
            warnings.append("atypical_regional_peak_order")

    score = max(
        0.0,
        100.0
        - 25.0 * len(set(reasons))
        - min(20.0, spike_ratio * 60.0)
        - min(15.0, max_roughness * 20.0),
    )
    return {
        "accepted": not reasons,
        "score": round(score, 1),
        "reasons": list(dict.fromkeys(reasons)),
        "warnings": warnings,
        "sampleRateHz": round(sample_rate, 2),
        "maxGapRatio": round(max_gap_ratio, 2),
        "maxGapSeconds": round(max_gap_seconds, 4),
        "spikeRatio": round(spike_ratio, 4),
        "roughness": round(max_roughness, 4),
        "regionalPeakPhases": phases,
    }




@dataclass
class _SideState:
    active: bool = False
    above_count: int = 0
    below_count: int = 0
    baseline: Optional[Dict[str, float]] = None
    baseline_matrix: Optional[np.ndarray] = None
    prebuffer: Deque[dict] = field(default_factory=lambda: deque(maxlen=3))
    current: List[dict] = field(default_factory=list)
    last_time: Optional[float] = None
    release_at: Optional[float] = None
    contact_at: Optional[float] = None
    contact_emitted: bool = False


class FsrStepPipeline:
    """Convert continuous FSR region totals into paired normalized stances.

    Input region totals are relative loads (larger means more pressure). The
    detector tracks an unloaded baseline independently for each foot and uses
    hysteresis, so noise near the threshold does not repeatedly start/end a
    stance.
    """

    def __init__(
        self,
        *,
        window_size: int = 5,
        # Thresholds are applied after subtracting the unloaded baseline. The
        # old 68.65/34.32 N values came from a gram-era constant and were too
        # high for the calibrated 48-cell hardware (a real step never opened).
        # In-shoe validation is intentionally used here instead of unloaded
        # bench noise: shoe preload left 62-80 N during swing while stance was
        # 190-206 N. Relative hysteresis at 65/50 N separates those states and
        # an 80 N peak floor prevents light pressure/noise becoming a step while
        # retaining weaker prosthetic/rehabilitation contacts.
        contact_on: float = 65.0,
        contact_off: float = 50.0,
        min_peak_activity: float = 80.0,
        min_duration: float = 0.18,
        max_duration: float = 3.0,
        min_samples: int = 4,
        debounce_frames: int = 2,
    ) -> None:
        self.contact_on = float(contact_on)
        self.contact_off = float(contact_off)
        self.min_peak_activity = max(float(min_peak_activity), self.contact_on)
        self.min_duration = float(min_duration)
        self.max_duration = float(max_duration)
        self.min_samples = int(min_samples)
        self.debounce_frames = int(debounce_frames)
        self.window_size = 5
        self.set_window_size(window_size)
        self.reset()

    def set_force_metadata(self, unit: str, source: str) -> None:
        """Describe the force values supplied to the detector."""
        self.force_unit = "N" if str(unit).strip() == "N" else "N_estimated"
        self.force_source = (
            "packet" if str(source).strip().lower() == "packet"
            else "formula_estimate"
        )

    def reset(self, *, keep_baseline: bool = False) -> None:
        baselines = (
            {
                side: (
                    dict(state.baseline)
                    if state.baseline is not None
                    else None
                )
                for side, state in self._sides.items()
            }
            if keep_baseline and hasattr(self, "_sides")
            else {}
        )
        matrix_baselines = (
            {
                side: (
                    state.baseline_matrix.copy()
                    if state.baseline_matrix is not None
                    else None
                )
                for side, state in self._sides.items()
            }
            if keep_baseline and hasattr(self, "_sides")
            else {}
        )
        self._sides = {"left": _SideState(), "right": _SideState()}
        for side, baseline in baselines.items():
            self._sides[side].baseline = baseline
        for side, baseline_matrix in matrix_baselines.items():
            self._sides[side].baseline_matrix = baseline_matrix
        self._unpaired = {"left": deque(), "right": deque()}
        self._incomplete_steps = []
        self._invalid_contacts = set()
        self._pairs: Deque[dict] = deque()
        self._contacts: Deque[dict] = deque()
        self._completed_steps = {"left": 0, "right": 0}
        self._rejected_steps = {"left": 0, "right": 0}
        self._quality_rejected_steps = {"left": 0, "right": 0}
        self._quality_rejection_reasons = {"left": {}, "right": {}}
        self._discarded_unpaired = {"left": 0, "right": 0}
        self._pair_sequence = 0
        self.force_unit = "N_estimated"
        self.force_source = "formula_estimate"

    def set_window_size(self, value: int) -> int:
        value = int(value)
        if value not in VALID_WINDOWS:
            raise ValueError(f"window_size must be one of {VALID_WINDOWS}")
        self.window_size = value
        return value

    def add_sample(
        self,
        side: str,
        timestamp: float,
        regions: Dict[str, float],
        force_matrix: Optional[Iterable[Iterable[float]]] = None,
    ) -> None:
        side = side.lower()
        if side not in self._sides:
            raise ValueError("side must be left or right")
        sample = {
            "time": float(timestamp),
            "regions": {name: max(0.0, float(regions.get(name, 0.0))) for name in REGIONS},
            "forceMatrix": (
                [list(map(float, row)) for row in force_matrix]
                if force_matrix is not None
                else None
            ),
        }
        state = self._sides[side]
        if not np.isfinite(sample['time']) or not all(np.isfinite(v) for v in sample['regions'].values()):
            return
        if state.last_time is not None:
            if sample['time'] <= state.last_time:
                return
            if sample['time'] - state.last_time > 0.35:
                if state.active:
                    self._reject_contact(side)
                state.active = False
                state.current.clear()
                state.prebuffer.clear()
                state.above_count = state.below_count = 0
                state.release_at = None
        state.last_time = sample['time']
        self._update_baseline(state, sample)
        baseline_total = (state.baseline or {}).get("total", 0.0)
        activity = max(0.0, sample["regions"]["total"] - baseline_total)

        if not state.active:
            state.prebuffer.append(sample)
            if activity >= self.contact_on:
                state.above_count += 1
            else:
                state.above_count = 0
            if state.above_count >= self.debounce_frames:
                state.active = True
                state.below_count = 0
                state.current = list(state.prebuffer)
                state.contact_at = state.current[-self.debounce_frames]['time']
                state.contact_emitted = False
                state.prebuffer.clear()
                self._record_contact(side, state, activity)
            return

        state.current.append(sample)
        self._record_contact(side, state, activity)
        if activity <= self.contact_off:
            state.below_count += 1
        else:
            state.below_count = 0
        if state.below_count >= self.debounce_frames:
            # Retain the confirmed below-threshold samples. They are genuine
            # toe-off observations and let the baseline-corrected display curve
            # return naturally toward zero instead of ending abruptly.
            stance = list(state.current)
            state.release_at = stance[-self.debounce_frames]['time']
            self._complete_step(
                side,
                stance,
                state.baseline or {},
                state.baseline_matrix,
            )
            state.active = False
            state.above_count = 0
            state.below_count = 0
            state.current = []
            state.prebuffer.clear()

    def _record_contact(self, side, state, activity):
        if not state.contact_emitted and activity >= self.min_peak_activity:
            self._contacts.append({'side': side, 'start': state.release_at,
                                   'end': state.contact_at})
            state.contact_emitted = True
            self._pair_available_steps()

    def contact_events(self):
        """Confirmed landing events, available without waiting for toe-off."""
        return [dict(event) for event in self._contacts]

    def _update_baseline(self, state: _SideState, sample: dict) -> None:
        values = sample["regions"]
        previous_total = (state.baseline or {}).get("total", values["total"])
        matrix = sample.get("forceMatrix")
        if matrix is not None:
            current_matrix = np.asarray(matrix, dtype=float)
            if current_matrix.shape == (12, 4):
                if state.baseline_matrix is None:
                    state.baseline_matrix = current_matrix.copy()
                elif (
                    not state.active
                    and values["total"] - previous_total < self.contact_on * 0.45
                ):
                    alpha = np.where(current_matrix < state.baseline_matrix, 0.22, 0.008)
                    state.baseline_matrix += alpha * (
                        current_matrix - state.baseline_matrix
                    )
        if state.baseline is None:
            state.baseline = dict(values)
            return
        if state.active:
            return
        for name in REGIONS:
            old = state.baseline[name]
            current = values[name]
            # Unloaded load is the lower envelope. Follow decreases quickly
            # and slow quiet drift upward without absorbing a real contact.
            alpha = 0.22 if current < old else 0.008
            if current - old < self.contact_on * 0.45:
                state.baseline[name] = old + alpha * (current - old)

    def _complete_step(
        self,
        side: str,
        samples: List[dict],
        baseline: Dict[str, float],
        baseline_matrix: Optional[np.ndarray],
    ) -> None:
        if len(samples) < self.min_samples:
            self._rejected_steps[side] += 1
            self._reject_contact(side)
            return
        start = samples[0]["time"]
        end = samples[-1]["time"]
        duration = end - start
        if duration < self.min_duration or duration > self.max_duration:
            self._rejected_steps[side] += 1
            self._reject_contact(side)
            return
        peak_activity = max(
            max(0.0, item["regions"]["total"] - baseline.get("total", 0.0))
            for item in samples
        )
        activity_trace = np.asarray([
            max(0.0, item["regions"]["total"] - baseline.get("total", 0.0))
            for item in samples
        ])
        sample_times = np.asarray([float(item["time"]) for item in samples])
        load_impulse = float(np.trapezoid(activity_trace, sample_times))
        # Contact onset remains sensitive so its timing is not delayed, but a
        # completed stance must contain a clear load peak. Idle sensor drift can
        # therefore never become a displayed left-right step pair.
        if peak_activity < self.min_peak_activity:
            self._rejected_steps[side] += 1
            self._reject_contact(side)
            return

        curves = {}
        raw_regions = {}
        for name in REGIONS:
            zero = baseline.get(name, 0.0)
            raw_regions[name] = [max(0.0, item['regions'][name] - zero) for item in samples]
            curves[name] = _normalize(
                raw_regions[name],
                timestamps=sample_times,
            )
        quality = _step_measurement_quality(samples, baseline, curves)
        if not quality["accepted"]:
            self._rejected_steps[side] += 1
            self._quality_rejected_steps[side] += 1
            for reason in quality["reasons"]:
                counts = self._quality_rejection_reasons[side]
                counts[reason] = int(counts.get(reason, 0)) + 1
            self._reject_contact(side)
            return
        self._completed_steps[side] += 1
        step = {
            "side": side,
            "sideIndex": self._completed_steps[side],
            "contactAt": self._sides[side].contact_at,
            "start": round(start, 4),
            "end": round(end, 4),
            "duration": round(duration, 4),
            "sampleCount": len(samples),
            "peakActivity": round(peak_activity, 4),
            "loadImpulse": round(load_impulse, 4),
            "curves": curves,
            "rawRegionValues": raw_regions,
            "displayCurves": curves,
            "rawSamples": [{"time": item["time"], "regions": dict(item["regions"])} for item in samples],
            "quality": quality,
            **_peak_fore_metrics(raw_regions["forefoot"], sample_times),
        }
        self._unpaired[side].append(step)
        self._pair_available_steps()

    def _reject_contact(self, side):
        contact_at = self._sides[side].contact_at
        if contact_at is not None:
            self._invalid_contacts.add((side, contact_at))
        self._pair_available_steps()

    def _pair_available_steps(self) -> None:
        # Pair LANDINGS first, not the order in which stance curves finish.
        # A known landing with a rejected/missing force curve still occupies its
        # place in the sequence: its partner cannot be reused in a later cycle.
        intervals = {side: [(event['end'] - 0.001, event['end'])
                            for event in self._contacts if event['side'] == side]
                     for side in ('left', 'right')}
        diagnostics = {}
        contact_pairs = pair_step_intervals(
            intervals['left'], intervals['right'], diagnostics=diagnostics,
            max_gap_seconds=MAX_PAIR_CONTACT_GAP_SECONDS,
        )
        unmatched = {(item['side'], item['end']): item['reason']
                     for item in diagnostics['unmatchedSteps']}
        partners = {}
        for left_contact, right_contact in contact_pairs:
            lk, rk = ('left', left_contact[1]), ('right', right_contact[1])
            partners[lk], partners[rk] = rk, lk
        available = {}
        for side in ('left', 'right'):
            retained = deque()
            for step in self._unpaired[side]:
                key = (side, step['contactAt'])
                reason = unmatched.get(key)
                if partners.get(key) in self._invalid_contacts:
                    reason = 'opposite_force_measurement_missing'
                if reason and reason != 'waiting_for_opposite_step':
                    self._incomplete_steps.append({**step, 'unpairedReason': reason})
                    self._discarded_unpaired[side] += 1
                else:
                    retained.append(step)
                    available[key] = step
            self._unpaired[side] = retained
        for left_contact, right_contact in contact_pairs:
            left_key, right_key = ('left', left_contact[1]), ('right', right_contact[1])
            if left_key not in available or right_key not in available:
                continue
            left, right = available.pop(left_key), available.pop(right_key)
            self._unpaired['left'].remove(left)
            self._unpaired['right'].remove(right)
            self._pair_sequence += 1
            pair_index = self._pair_sequence
            left["pairIndex"] = pair_index
            right["pairIndex"] = pair_index
            left_peak = float(left.get("peakFore", 0.0))
            right_peak = float(right.get("peakFore", 0.0))
            fsi = force_symmetry_index(left_peak, right_peak)
            self._pairs.append({
                "pairIndex": pair_index,
                "pairingMethod": "adjacent_opposite_contacts_no_skipped_side",
                "left": left,
                "right": right,
                "peakForeLeft": round(left_peak, 4),
                "peakForeRight": round(right_peak, 4),
                "fsi": fsi,
                "asymmetry": None if fsi is None else round(100.0 - fsi, 2),
            })

    def all_pairs(self) -> List[dict]:
        """Return every completed stance pair retained in this session."""
        return list(self._pairs)

    def snapshot(self, *, healthy_leg: str = "LEFT", prosthetic_leg: str = "RIGHT") -> dict:
        transition_exclusions = []
        pairs = list(self._pairs)[-self.window_size :]
        latest_pair = pairs[-1] if pairs else None
        return {
            "unit": self.force_unit,
            "forceSource": self.force_source,
            "windowSize": self.window_size,
            "windowOptions": list(VALID_WINDOWS),
            "availablePairs": len(pairs),
            "latestPairIndex": latest_pair["pairIndex"] if latest_pair else None,
            "totalPairs": self._pair_sequence,
            "contactEvents": self.contact_events(),
            "pairingMethod": "adjacent_opposite_contacts_no_skipped_side",
            "incompleteSteps": [
                {key: step[key] for key in ('side', 'sideIndex', 'start', 'end', 'contactAt', 'unpairedReason')}
                for step in self._incomplete_steps
            ],
            "healthySide": healthy_leg.lower(),
            "prostheticSide": prosthetic_leg.lower(),
            "peakFore": {
                "left": latest_pair.get("peakForeLeft", 0.0) if latest_pair else 0.0,
                "right": latest_pair.get("peakForeRight", 0.0) if latest_pair else 0.0,
            },
            "fsi": latest_pair.get("fsi") if latest_pair else None,
            "pairs": pairs,
            "status": {
                "active": {name: side.active for name, side in self._sides.items()},
                "completedSteps": dict(self._completed_steps),
                "rejectedSteps": dict(self._rejected_steps),
                "unpairedSteps": {name: len(items) for name, items in self._unpaired.items()},
                "discardedUnpairedSteps": dict(self._discarded_unpaired),
                "qualityRejectedSteps": dict(self._quality_rejected_steps),
                "qualityRejectionReasons": {
                    side: dict(reasons)
                    for side, reasons in self._quality_rejection_reasons.items()
                },
                "steadyStateExcludedPairs": len(transition_exclusions),
                "steadyStateExclusions": transition_exclusions,
            },
        }

    def analysis(
        self,
        *,
        healthy_leg: str = "LEFT",
        prosthetic_leg: str = "RIGHT",
        pairs: Optional[List[dict]] = None,
    ) -> dict:
        candidates = pairs if pairs is not None else list(self._pairs)
        quality_pairs = [
            pair
            for pair in candidates
            if all(
                not isinstance(pair.get(side), dict)
                or not isinstance(pair[side].get("quality"), dict)
                or pair[side]["quality"].get("accepted", True)
                for side in ("left", "right")
            )
        ]
        transition_exclusions = []
        selected = quality_pairs[-self.window_size :]
        regions = {}
        for region in REGIONS:
            region_result = {}
            for side in ("left", "right"):
                curves = []
                for item in selected:
                    step = item[side]
                    # Mean/SD and realtime both use the measured regional
                    # curves, never the former presentation-only curves.
                    source_curve = step["curves"][region]
                    curves.append(source_curve)
                if not curves:
                    region_result[side] = {"mean": [], "sd": [], "steps": 0}
                    continue
                stack = np.asarray(curves, dtype=float)
                region_result[side] = {
                    "mean": np.mean(stack, axis=0).round(4).tolist(),
                    "sd": (
                        np.std(stack, axis=0, ddof=1).round(4).tolist()
                        if len(curves) > 1
                        else np.zeros(101).tolist()
                    ),
                    "steps": len(curves),
                }
            regions[region] = region_result
        peak_fore_pairs = [
            {
                "pairIndex": pair["pairIndex"],
                "left": {
                    "stepIndex": pair["left"].get("sideIndex"),
                    "peakFore": pair.get("peakForeLeft", 0.0),
                    "peakForePhasePercent": pair["left"].get("peakForePhasePercent"),
                },
                "right": {
                    "stepIndex": pair["right"].get("sideIndex"),
                    "peakFore": pair.get("peakForeRight", 0.0),
                    "peakForePhasePercent": pair["right"].get("peakForePhasePercent"),
                },
                "fsi": pair.get("fsi"),
                "asymmetry": pair.get("asymmetry"),
            }
            for pair in selected
        ]
        force_summary = _force_summary(selected, self.force_unit)
        return {
            "unit": self.force_unit,
            "forceSource": self.force_source,
            "windowSize": self.window_size,
            "windowOptions": list(VALID_WINDOWS),
            "pairCount": len(selected),
            "pairingMethod": (
                "adjacent_opposite_contacts_no_skipped_side"
                if all(pair.get('pairingMethod') == 'adjacent_opposite_contacts_no_skipped_side'
                       for pair in selected) else "legacy_unknown"
            ),
            "incompleteSteps": [
                {key: step[key] for key in ('side', 'sideIndex', 'start', 'end', 'contactAt', 'unpairedReason')}
                for step in self._incomplete_steps
            ],
            "qualityExcludedPairCount": len(candidates) - len(quality_pairs),
            "steadyStateExcludedPairCount": len(transition_exclusions),
            "qualityPolicy": "measurement_artifacts_only_v2",
            "selectionPolicy": "all_acquired_pairs_no_shape_selection",
            "curveProcessing": {"smoothing": "none", "interpolation": "linear_time"},
            "contactEvents": self.contact_events(),
            "acquisitionQuality": {
                "acceptedPairCount": len(selected),
                "rejectedSteps": dict(self._quality_rejected_steps),
                "rejectionReasons": {
                    side: dict(reasons)
                    for side, reasons in self._quality_rejection_reasons.items()
                },
                "steadyStateExclusions": transition_exclusions,
            },
            "healthySide": healthy_leg.lower(),
            "prostheticSide": prosthetic_leg.lower(),
            # Keep normalized pairs so saved clips can be recalculated for 5/7.
            "pairs": selected,
            "regions": regions,
            "peakForePairs": peak_fore_pairs,
            "forceSummary": force_summary,
        }
