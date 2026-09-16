"""Display-only healthy gait demo derived from a recorded FSR sample."""
from copy import deepcopy

import numpy as np

from fsr_step_pipeline import FsrStepPipeline, REGION_ROWS, force_symmetry_index

UNIT = "N_demo60"
REGIONS = ("heel", "midfoot", "forefoot")
BODY_WEIGHT = 60 * 9.80665
STANDING_FOOT_FORCE = BODY_WEIGHT / 2
RIGHT_PEAK = 610.0
LEFT_REGION_SCALES = np.array([.98, .97, .95])
PAIR_VARIATIONS = {
    "left": (1.0, .993, 1.007),
    "right": (1.0, .992, 1.008),
}
CHART_MAX = 650.0
REGION_CHART_MAX = 350.0


def _smoothstep(value):
    value = np.clip(value, 0, 1)
    return value * value * (3 - 2 * value)


def _force_envelope():
    """One stance: heel strike 0, single support near 600, toe-off 0."""
    phase = np.linspace(0, 1, 101)
    knots = np.array([0, .08, .18, .45, .65, .82, .92, 1.0])
    loads = np.array([0, 250, 320, RIGHT_PEAK, 560, 380, 285, 0])
    envelope = np.zeros_like(phase)
    for index in range(len(knots) - 1):
        selected = (phase >= knots[index]) & (phase <= knots[index + 1])
        local = _smoothstep(
            (phase[selected] - knots[index])
            / (knots[index + 1] - knots[index])
        )
        envelope[selected] = (
            loads[index] + (loads[index + 1] - loads[index]) * local
        )
    return phase, envelope


def _reference_weights(original):
    """Retain the recording's heel-to-midfoot-to-forefoot transfer pattern."""
    relative_curves = []
    for pair in original:
        for side in ("left", "right"):
            curves = pair.get(side, {}).get("curves", {})
            if not all(len(curves.get(region, [])) == 101 for region in REGIONS):
                continue
            values = np.maximum(
                0, np.asarray([curves[region] for region in REGIONS], dtype=float)
            )
            if not np.isfinite(values).all():
                continue
            total = values.sum(axis=0)
            relative = values / np.maximum(total, 1e-9)
            relative[:, total <= 1e-9] = np.array([[.45], [.20], [.35]])
            relative_curves.append(relative)
    if not relative_curves:
        raise ValueError("Demo requires finite reference region curves")
    weights = np.mean(relative_curves, axis=0)
    return weights / weights.sum(axis=0)


def _recording_timing(original):
    """Estimate alternating cadence and stance from accepted recording contacts."""
    starts = sorted(
        float(pair[side]["start"])
        for pair in original
        for side in ("left", "right")
        if np.isfinite(float(pair.get(side, {}).get("start", float("nan"))))
    )
    differences = np.diff(starts)
    usable_differences = differences[
        (differences >= .35) & (differences <= 1.2)
    ]
    step_interval = float(
        np.median(usable_differences) if usable_differences.size else .65
    )
    durations = np.asarray(
        [
            float(pair[side].get("duration", float("nan")))
            for pair in original
            for side in ("left", "right")
        ],
        dtype=float,
    )
    usable_durations = durations[
        np.isfinite(durations) & (durations >= .65) & (durations <= 1.35)
    ]
    stance = float(np.median(usable_durations) if usable_durations.size else 1.0)
    stance = float(np.clip(max(stance, step_interval * 1.35), .80, 1.20))
    first_contact = starts[0] if starts else 3.0
    return first_contact, step_interval, stance


def demo_force_analysis(source, window=0):
    """Build one internally consistent demo without changing persisted source data."""
    original = source.get("pairs", [])
    if not original:
        return {
            "unit": UNIT,
            "regions": {},
            "pairs": [],
            "replayFrames": [],
            "demoProfile": "healthy60-gait-v3",
            "displaySourceLabel": "Dữ liệu hai chân ",
        }

    phase, base_total = _force_envelope()
    weights = _reference_weights(original)
    first_contact, step_interval, stance = _recording_timing(original)
    cycle = step_interval * 2
    count = len(original)
    pairs = []

    for index in range(count):
        pair = {
            "pairIndex": index + 1,
            "pairingMethod": "demo_alternating_recording_cadence",
        }
        for side, shift in (
            ("left", step_interval),
            ("right", 0.0),
        ):
            variation = PAIR_VARIATIONS[side][index % 3]
            region_scales = LEFT_REGION_SCALES if side == "left" else np.ones(3)
            region_values = (
                weights * base_total * variation * region_scales[:, None]
            )
            total = region_values.sum(axis=0)
            curves = {
                region: region_values[region_index].round(4).tolist()
                for region_index, region in enumerate(REGIONS)
            }
            curves["total"] = region_values.sum(axis=0).round(4).tolist()
            contact = first_contact + index * cycle + shift
            fore_index = int(np.argmax(region_values[2, 65:])) + 65
            pair[side] = {
                "side": side,
                "sideIndex": index + 1,
                "pairIndex": index + 1,
                "start": contact,
                "end": contact + stance,
                "duration": stance,
                "sampleCount": 101,
                "curves": curves,
                "displayCurves": deepcopy(curves),
                "peakActivity": float(total.max()),
                "loadImpulse": float(
                    np.sum((total[:-1] + total[1:]) / 2) * stance / 100
                ),
                "peakFore": float(region_values[2, fore_index]),
                "peakForePhasePercent": fore_index,
                "quality": {"accepted": True},
                "source": "demo_recording_shape_not_calibrated",
            }
        pair["peakForeLeft"] = pair["left"]["peakFore"]
        pair["peakForeRight"] = pair["right"]["peakFore"]
        pair["fsi"] = force_symmetry_index(
            pair["peakForeLeft"], pair["peakForeRight"]
        )
        pair["asymmetry"] = 100 - pair["fsi"]
        pairs.append(pair)

    pipeline = FsrStepPipeline(window_size=window)
    pipeline.set_force_metadata(UNIT, "demo_recording_region_transfer")
    result = pipeline.analysis(
        healthy_leg="both", prosthetic_leg="none", pairs=pairs
    )

    standing_weights = weights[:, 50] / weights[:, 50].sum()
    standing_regions = standing_weights * STANDING_FOOT_FORCE
    right_origin = first_contact
    left_origin = first_contact + step_interval
    walk_start = first_contact - step_interval
    walk_end = pairs[-1]["left"]["end"]
    transition = min(.6, step_interval)

    def periodic_values(time_value, side):
        origin = left_origin if side == "left" else right_origin
        cycle_index = int(np.floor((time_value - origin) / cycle))
        elapsed = (time_value - origin) % cycle
        if elapsed > stance:
            return np.zeros(3)
        local_phase = elapsed / stance
        region_scales = LEFT_REGION_SCALES if side == "left" else np.ones(3)
        variation = PAIR_VARIATIONS[side][
            min(max(cycle_index, 0), count - 1) % 3
        ]
        return np.array(
            [
                np.interp(local_phase, phase, weights[index] * base_total)
                for index in range(3)
            ]
        ) * region_scales * variation

    def replay_values(time_value, side):
        if time_value < walk_start - transition:
            return standing_regions.copy()
        if time_value < walk_start:
            blend = float(
                _smoothstep((time_value - (walk_start - transition)) / transition)
            )
            return (
                (1 - blend) * standing_regions
                + blend * periodic_values(time_value, side)
            )
        if time_value <= walk_end:
            return periodic_values(time_value, side)
        if time_value <= walk_end + transition:
            blend = float(_smoothstep((time_value - walk_end) / transition))
            return (
                (1 - blend) * periodic_values(time_value, side)
                + blend * standing_regions
            )
        return standing_regions.copy()

    source_duration = max(
        (
            float(frame.get("time", 0))
            for frame in source.get("replayFrames", [])
            if np.isfinite(float(frame.get("time", float("nan"))))
        ),
        default=walk_end + transition + 2,
    )
    duration = max(source_duration, walk_end + transition + 2)
    event_times = [
        pair[side]["start"] + float(value) * stance
        for pair in pairs
        for side in ("left", "right")
        for value in phase
    ]
    times = sorted(
        set(np.arange(0, duration, 1 / 30).tolist() + event_times + [duration])
    )
    frames = []
    for time_value in times:
        for side in ("left", "right"):
            values = replay_values(time_value, side)
            matrix = np.zeros((12, 4))
            for region_index, region in enumerate(REGIONS):
                low, high = REGION_ROWS[region]
                spatial = np.array([[1, 2, 2, 1]] * (high - low + 1), dtype=float)
                matrix[low : high + 1] = (
                    spatial / spatial.sum() * values[region_index]
                )
            regions = {
                region: float(values[index])
                for index, region in enumerate(REGIONS)
            }
            regions["total"] = float(values.sum())
            frames.append(
                {
                    "time": time_value,
                    "side": side,
                    "unit": UNIT,
                    "regions": regions,
                    "forceValues": matrix.tolist(),
                    "source": "demo_recording_shape_not_calibrated",
                }
            )

    result.update(
        unit=UNIT,
        demoProfile="healthy60-gait-v3",
        weightKg=60,
        standingFootForceN=STANDING_FOOT_FORCE,
        peakFootForceN=RIGHT_PEAK,
        chartMaxN=CHART_MAX,
        regionChartMaxN=REGION_CHART_MAX,
        healthySide="both",
        prostheticSide="none",
        needsReanalysis=False,
        displaySourceLabel="Dữ liệu hai chân ",
        qualityPolicy="",
        acquisitionQuality={},
        replayFrames=frames,
        replaySampleRateHz=30,
        demoDurationSec=duration,
        synchronization={
            "cameraSynchronized": False,
            "note": "Cadence estimated from recording; demo force is not calibrated.",
        },
        demoAssumptions={
            "standingFootForceN": STANDING_FOOT_FORCE,
            "rightPeakN": RIGHT_PEAK,
            "leftPeakN": pairs[0]["left"]["peakActivity"],
            "regionalFsiTargets": dict(zip(REGIONS, (98, 97, 95))),
            "stepVariationPercentBySide": {"left": .7, "right": .8},
            "doubleSupportTargetNPerFoot": 300,
            "chartMaxN": CHART_MAX,
            "regionalTransfer": "averaged from accepted recording FSR curves",
            "stepIntervalSec": step_interval,
            "stanceSec": stance,
            "note": (
                "Contact cadence and regional transfer reference the recording. "
                "Force magnitude is a labeled demonstration, not calibrated measurement."
            ),
        },
    )
    result["forceSummary"]["source"] = "demo_recording_shape_not_calibrated"
    for row in result["forceSummary"]["rows"]:
        row["unit"] = f"{UNIT}·s" if row["key"] == "loadImpulse" else UNIT
    return result
