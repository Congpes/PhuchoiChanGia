import unittest

import numpy as np

from gait_cycle_pipeline import analyze_gait_cycles, build_camera_gait_cycles, build_gait_cycles


class GaitCyclePipelineTests(unittest.TestCase):
    def test_builds_normalized_cycles_and_analysis(self):
        timestamps = np.linspace(0, 8, 241).tolist()
        signals = {
            "left_knee": (35 + 20 * np.sin(np.asarray(timestamps) * np.pi)).tolist(),
            "right_knee": (33 + 18 * np.sin(np.asarray(timestamps) * np.pi)).tolist(),
            "left_hip": (25 + 10 * np.cos(np.asarray(timestamps) * np.pi)).tolist(),
            "right_hip": (24 + 9 * np.cos(np.asarray(timestamps) * np.pi)).tolist(),
            "trunk": (5 + 2 * np.sin(np.asarray(timestamps) * np.pi)).tolist(),
        }
        anchors = [
            {
                "pairIndex": index + 1,
                "left": {"start": float(index)},
                "right": {"start": float(index) + 0.5},
            }
            for index in range(8)
        ]
        cycles = build_gait_cycles(timestamps, signals, anchors, window_size=5)
        self.assertEqual(len(cycles), 5)
        self.assertEqual(len(cycles[-1]["left"]["curves"]["knee"]), 101)
        analysis = analyze_gait_cycles(cycles, window_size=5)
        self.assertEqual(analysis["cycleCount"], 5)
        self.assertEqual(len(analysis["metrics"]["trunk"]["right"]["sd"]), 101)

    def test_camera_cycles_are_detected_without_fsr(self):
        timestamps = np.linspace(0, 12, 721)
        phase = 2 * np.pi * timestamps / 1.2
        rng = np.random.default_rng(20260813)
        signals = {
            "left_knee": (155 + 25 * np.cos(phase) + rng.normal(0, 0.6, len(phase))).tolist(),
            "right_knee": (153 + 23 * np.cos(phase - np.pi) + rng.normal(0, 0.6, len(phase))).tolist(),
            "left_hip": (25 + 10 * np.sin(phase)).tolist(),
            "right_hip": (24 + 9 * np.sin(phase - np.pi)).tolist(),
            "trunk": (6 + 2 * np.sin(phase / 2)).tolist(),
        }
        cycles = build_camera_gait_cycles(timestamps.tolist(), signals, window_size=5)
        self.assertEqual(len(cycles), 5)
        self.assertEqual([item["pairIndex"] for item in cycles], sorted(item["pairIndex"] for item in cycles))
        for cycle in cycles:
            self.assertEqual(cycle["source"], "camera")
            for side in ("left", "right"):
                self.assertAlmostEqual(cycle[side]["duration"], 1.2, delta=0.08)
                for metric in ("knee", "hip", "trunk"):
                    self.assertEqual(len(cycle[side]["curves"][metric]), 101)

    def test_camera_cycles_reject_stationary_pose_jitter(self):
        timestamps = np.linspace(0, 10, 601)
        rng = np.random.default_rng(7)
        signals = {
            "left_knee": (175 + rng.normal(0, 0.5, len(timestamps))).tolist(),
            "right_knee": (174 + rng.normal(0, 0.5, len(timestamps))).tolist(),
            "left_hip": np.full(len(timestamps), 20.0).tolist(),
            "right_hip": np.full(len(timestamps), 20.0).tolist(),
            "trunk": np.full(len(timestamps), 5.0).tolist(),
        }
        self.assertEqual(
            build_camera_gait_cycles(timestamps.tolist(), signals, window_size=5),
            [],
        )


if __name__ == "__main__":
    unittest.main()
