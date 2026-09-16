import unittest
from copy import deepcopy

import numpy as np

from demo_force_profile import (
    LEFT_REGION_SCALES,
    REGIONS,
    RIGHT_PEAK,
    STANDING_FOOT_FORCE,
    demo_force_analysis,
)
from fsr_step_pipeline import REGION_ROWS


def fixture():
    phase = np.linspace(0, 1, 101)
    pairs = []
    for index in range(3):
        pair = {"pairIndex": index + 1}
        for side, shift, scale in (
            ("right", 0, 1.02),
            ("left", .7, 1.0),
        ):
            curves = {
                "heel": ((75 * (1 - phase) + 8) * scale).tolist(),
                "midfoot": ((12 + 34 * np.sin(np.pi * phase)) * scale).tolist(),
                "forefoot": ((7 + 55 * phase) * scale).tolist(),
            }
            curves["total"] = np.sum(list(curves.values()), axis=0).tolist()
            start = 3 + index * 1.4 + shift
            pair[side] = {
                "start": start,
                "end": start + 1,
                "duration": 1,
                "curves": deepcopy(curves),
            }
        pairs.append(pair)
    return {
        "pairs": pairs,
        "replayFrames": [
            {"time": time, "side": side, "regions": {}}
            for time in (0, 8)
            for side in ("left", "right")
        ],
        "replaySampleRateHz": 15,
    }


class DemoForceTests(unittest.TestCase):
    def setUp(self):
        self.source = fixture()
        self.result = demo_force_analysis(self.source)

    def test_source_unchanged_and_result_deterministic(self):
        self.assertEqual(self.source, fixture())
        self.assertEqual(self.result, demo_force_analysis(self.source))
        self.assertEqual(self.result["demoProfile"], "healthy60-gait-v3")

    def test_stance_curve_has_requested_landmarks(self):
        right = self.result["pairs"][0]["right"]["curves"]["total"]
        expected = {0: 0, 8: 250, 18: 320, 45: 610, 65: 560,
                    82: 380, 92: 285, 100: 0}
        for index, value in expected.items():
            self.assertAlmostEqual(right[index], value)
        left_curves = self.result["pairs"][0]["left"]["curves"]
        right_curves = self.result["pairs"][0]["right"]["curves"]
        for index, region in enumerate(REGIONS):
            np.testing.assert_allclose(
                left_curves[region],
                np.asarray(right_curves[region]) * LEFT_REGION_SCALES[index],
                atol=1e-4,
            )

    def test_healthy_feet_are_nearly_equal(self):
        pairs = self.result["pairs"]
        self.assertAlmostEqual(
            np.mean([pair["right"]["peakActivity"] for pair in pairs]),
            RIGHT_PEAK,
        )
        for pair in pairs:
            self.assertGreaterEqual(pair["fsi"], 94.9)
            self.assertLessEqual(pair["fsi"], 95.1)
        fsi_values = [row["fsi"] for row in self.result["forceSummary"]["rows"]]
        self.assertGreaterEqual(min(fsi_values), 95)
        self.assertLessEqual(max(fsi_values), 98)
        self.assertGreaterEqual(len(set(fsi_values)), 4)
        self.assertEqual(self.result["healthySide"], "both")
        self.assertEqual(self.result["prostheticSide"], "none")

    def test_every_report_table_value_comes_from_the_plotted_steps(self):
        def metric(step, key):
            if key == "peakTotal":
                return max(step["curves"]["total"])
            if key == "peakHeel":
                return max(step["curves"]["heel"])
            if key == "peakMidfoot":
                return max(step["curves"]["midfoot"])
            if key == "peakFore":
                return step["peakFore"]
            if key == "meanStanceForce":
                return step["loadImpulse"] / step["duration"]
            if key == "loadImpulse":
                return step["loadImpulse"]
            raise AssertionError(key)

        for row in self.result["forceSummary"]["rows"]:
            for side in ("left", "right"):
                expected = np.mean([
                    metric(pair[side], row["key"])
                    for pair in self.result["pairs"]
                ])
                self.assertAlmostEqual(row[side]["mean"], expected, places=3)
                self.assertGreaterEqual(row[side]["sd"], 1)
                self.assertLessEqual(row[side]["sd"], 5)
            self.assertGreaterEqual(row["fsi"], 95)
            self.assertLessEqual(row["fsi"], 98)
        for source, displayed in zip(
            self.result["pairs"], self.result["peakForePairs"]
        ):
            self.assertEqual(displayed["left"]["peakFore"], source["peakForeLeft"])
            self.assertEqual(displayed["right"]["peakFore"], source["peakForeRight"])
        for region in REGIONS:
            for side in ("left", "right"):
                self.assertGreater(max(self.result["regions"][region][side]["sd"]), 0)

    def test_regions_sum_to_total_and_impulse_matches(self):
        for pair in self.result["pairs"]:
            for side in ("left", "right"):
                step = pair[side]
                total = np.sum([step["curves"][region] for region in REGIONS], axis=0)
                np.testing.assert_allclose(total, step["curves"]["total"], atol=1e-4)
                impulse = np.sum((total[:-1] + total[1:]) / 2) * step["duration"] / 100
                self.assertAlmostEqual(impulse, step["loadImpulse"], places=3)
                self.assertEqual(total[0], 0)
                self.assertEqual(total[-1], 0)

    def test_replay_standing_cycles_and_heatmap_are_consistent(self):
        frames = self.result["replayFrames"]
        for frame in frames:
            matrix = np.asarray(frame["forceValues"])
            self.assertAlmostEqual(matrix.sum(), frame["regions"]["total"])
            for region, (low, high) in REGION_ROWS.items():
                self.assertAlmostEqual(
                    matrix[low : high + 1].sum(), frame["regions"][region]
                )
        for side in ("left", "right"):
            first = next(frame for frame in frames if frame["time"] == 0 and frame["side"] == side)
            last = next(frame for frame in reversed(frames) if frame["side"] == side)
            self.assertAlmostEqual(first["regions"]["total"], STANDING_FOOT_FORCE)
            self.assertAlmostEqual(last["regions"]["total"], STANDING_FOOT_FORCE)
        for pair in self.result["pairs"]:
            for side in ("left", "right"):
                step = pair[side]
                contact = next(
                    frame for frame in frames
                    if frame["side"] == side and frame["time"] == step["start"]
                )
                peak = next(
                    frame for frame in frames
                    if frame["side"] == side
                    and frame["time"] == step["start"] + .45 * step["duration"]
                )
                toe_off = next(
                    frame for frame in frames
                    if frame["side"] == side and frame["time"] == step["end"]
                )
                self.assertAlmostEqual(contact["regions"]["total"], 0)
                self.assertAlmostEqual(
                    peak["regions"]["total"], step["curves"]["total"][45], places=4
                )
                self.assertAlmostEqual(toe_off["regions"]["total"], 0, places=4)

    def test_cadence_comes_from_recording_and_window_does_not_rescale(self):
        assumptions = self.result["demoAssumptions"]
        self.assertAlmostEqual(assumptions["stepIntervalSec"], .7)
        self.assertAlmostEqual(assumptions["stanceSec"], 1.0)
        short = demo_force_analysis(self.source, 5)
        self.assertEqual(short["pairs"], self.result["pairs"][-5:])
        self.assertEqual(short["replayFrames"], self.result["replayFrames"])


if __name__ == "__main__":
    unittest.main()
