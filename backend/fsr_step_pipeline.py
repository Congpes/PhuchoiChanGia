"""Realtime FSR stance segmentation, left/right pairing, and window analysis."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Optional

import numpy as np


REGIONS = ("total", "heel", "midfoot", "forefoot")
VALID_WINDOWS = (5, 7)
PEAK_FORE_FALLBACK_START_PERCENT = 65.0


def force_symmetry_index(left_peak: float, right_peak: float) -> Optional[float]:
    """Return a force symmetry score where 100% means perfectly symmetric."""
    maximum = max(float(left_peak), float(right_peak))
    if maximum <= 0:
        return None
    return round(100.0 * min(float(left_peak), float(right_peak)) / maximum, 2)


def _peak_fore_metrics(curve: List[float]) -> dict:
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
    start_index = int(round(final_index * PEAK_FORE_FALLBACK_START_PERCENT / 100.0))
    push_off_curve = curve[start_index:] or curve
    peak_value = max(push_off_curve)
    peak_index = start_index + push_off_curve.index(peak_value)
    phase_percent = 0.0 if final_index == 0 else 100.0 * peak_index / final_index
    return {
        "peakFore": round(float(peak_value), 4),
        "peakForePhasePercent": round(phase_percent, 2),
        "peakForeStartPercent": PEAK_FORE_FALLBACK_START_PERCENT,
        "peakForeMethod": "terminal_stance_fallback",
    }


def _normalize(values: Iterable[float], target_len: int = 101) -> List[float]:
    source_values = np.asarray(list(values), dtype=float)
    if source_values.size == 0:
        return []
    if source_values.size == 1:
        return np.repeat(source_values[0], target_len).round(4).tolist()
    source = np.linspace(0.0, 1.0, source_values.size)
    target = np.linspace(0.0, 1.0, target_len)
    return np.interp(target, source, source_values).round(4).tolist()


@dataclass
class _SideState:
    active: bool = False
    above_count: int = 0
    below_count: int = 0
    baseline: Optional[Dict[str, float]] = None
    prebuffer: Deque[dict] = field(default_factory=lambda: deque(maxlen=3))
    current: List[dict] = field(default_factory=list)


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
        # Legacy thresholds were 7000 g / 3500 g. Input is now Newton.
        contact_on: float = 68.65,
        contact_off: float = 34.32,
        min_duration: float = 0.25,
        max_duration: float = 2.0,
        min_samples: int = 5,
        debounce_frames: int = 2,
    ) -> None:
        self.contact_on = float(contact_on)
        self.contact_off = float(contact_off)
        self.min_duration = float(min_duration)
        self.max_duration = float(max_duration)
        self.min_samples = int(min_samples)
        self.debounce_frames = int(debounce_frames)
        self.window_size = 5
        self.set_window_size(window_size)
        self.reset()

    def reset(self) -> None:
        self._sides = {"left": _SideState(), "right": _SideState()}
        self._unpaired = {"left": deque(), "right": deque()}
        self._pairs: Deque[dict] = deque(maxlen=8)
        self._completed_steps = {"left": 0, "right": 0}
        self._rejected_steps = {"left": 0, "right": 0}
        self._pair_sequence = 0

    def set_window_size(self, value: int) -> int:
        value = int(value)
        if value not in VALID_WINDOWS:
            raise ValueError(f"window_size must be one of {VALID_WINDOWS}")
        self.window_size = value
        return value

    def add_sample(self, side: str, timestamp: float, regions: Dict[str, float]) -> None:
        side = side.lower()
        if side not in self._sides:
            raise ValueError("side must be left or right")
        sample = {
            "time": float(timestamp),
            "regions": {name: max(0.0, float(regions.get(name, 0.0))) for name in REGIONS},
        }
        state = self._sides[side]
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
                state.prebuffer.clear()
            return

        state.current.append(sample)
        if activity <= self.contact_off:
            state.below_count += 1
        else:
            state.below_count = 0
        if state.below_count >= self.debounce_frames:
            trailing = state.below_count
            stance = state.current[:-trailing] if len(state.current) > trailing else state.current
            self._complete_step(side, stance, state.baseline or {})
            state.active = False
            state.above_count = 0
            state.below_count = 0
            state.current = []
            state.prebuffer.clear()

    def _update_baseline(self, state: _SideState, sample: dict) -> None:
        values = sample["regions"]
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

    def _complete_step(self, side: str, samples: List[dict], baseline: Dict[str, float]) -> None:
        if len(samples) < self.min_samples:
            self._rejected_steps[side] += 1
            return
        start = samples[0]["time"]
        end = samples[-1]["time"]
        duration = end - start
        if duration < self.min_duration or duration > self.max_duration:
            self._rejected_steps[side] += 1
            return

        curves = {}
        for name in REGIONS:
            zero = baseline.get(name, 0.0)
            curves[name] = _normalize(
                max(0.0, item["regions"][name] - zero) for item in samples
            )
        self._completed_steps[side] += 1
        step = {
            "side": side,
            "sideIndex": self._completed_steps[side],
            "start": round(start, 4),
            "end": round(end, 4),
            "duration": round(duration, 4),
            "sampleCount": len(samples),
            "curves": curves,
            **_peak_fore_metrics(curves["forefoot"]),
        }
        self._unpaired[side].append(step)
        self._pair_available_steps()

    def _pair_available_steps(self) -> None:
        while self._unpaired["left"] and self._unpaired["right"]:
            left = self._unpaired["left"].popleft()
            right = self._unpaired["right"].popleft()
            self._pair_sequence += 1
            pair_index = self._pair_sequence
            left["pairIndex"] = pair_index
            right["pairIndex"] = pair_index
            left_peak = float(left.get("peakFore", 0.0))
            right_peak = float(right.get("peakFore", 0.0))
            fsi = force_symmetry_index(left_peak, right_peak)
            self._pairs.append({
                "pairIndex": pair_index,
                "left": left,
                "right": right,
                "peakForeLeft": round(left_peak, 4),
                "peakForeRight": round(right_peak, 4),
                "fsi": fsi,
                "asymmetry": None if fsi is None else round(100.0 - fsi, 2),
            })

    def all_pairs(self) -> List[dict]:
        """Return retained anchors; one extra pair supports seven full cycles."""
        return list(self._pairs)

    def snapshot(self, *, healthy_leg: str = "LEFT", prosthetic_leg: str = "RIGHT") -> dict:
        pairs = list(self._pairs)[-self.window_size :]
        latest_pair = pairs[-1] if pairs else None
        return {
            "unit": "N_estimated",
            "forceSource": "formula_estimate",
            "windowSize": self.window_size,
            "windowOptions": list(VALID_WINDOWS),
            "availablePairs": len(pairs),
            "latestPairIndex": latest_pair["pairIndex"] if latest_pair else None,
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
            },
        }

    def analysis(
        self,
        *,
        healthy_leg: str = "LEFT",
        prosthetic_leg: str = "RIGHT",
        pairs: Optional[List[dict]] = None,
    ) -> dict:
        selected = (pairs if pairs is not None else list(self._pairs))[-self.window_size :]
        regions = {}
        for region in REGIONS:
            region_result = {}
            for side in ("left", "right"):
                curves = [item[side]["curves"][region] for item in selected]
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
        return {
            "unit": "N_estimated",
            "forceSource": "formula_estimate",
            "windowSize": self.window_size,
            "windowOptions": list(VALID_WINDOWS),
            "pairCount": len(selected),
            "healthySide": healthy_leg.lower(),
            "prostheticSide": prosthetic_leg.lower(),
            # Keep normalized pairs so saved clips can be recalculated for 5/7.
            "pairs": selected,
            "regions": regions,
            "peakForePairs": peak_fore_pairs,
        }
