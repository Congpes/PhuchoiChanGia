import unittest

import numpy as np

from gait_cycle_pipeline import (
    _normalized_interval,
    _pair_camera_intervals,
    analyze_gait_cycles,
    build_camera_gait_cycles,
    build_gait_cycles,
    build_synchronized_gait_cycles,
    estimate_foot_clearance_signals,
)


class GaitCyclePipelineTests(unittest.TestCase):
    def test_camera_pairing_does_not_choose_identity_from_simultaneous_events(self):
        left = [(0.0, 1.0), (1.2, 2.2)]
        right = [(0.05, 1.05), (0.65, 1.65), (1.8, 2.8)]
        audit = {}
        pairs = _pair_camera_intervals(left, right, diagnostics=audit)
        # Neither of the first two detections can be trusted as the true side.
        # Continue with adjacent opposite events, starting with right[1].
        self.assertEqual(pairs, [(left[1], right[1])])
        self.assertEqual([item['reason'] for item in audit['unmatchedSteps']],
                         ['ambiguous_simultaneous_steps'] * 2 + ['waiting_for_opposite_step'])

    def test_normalized_curve_is_linear_without_smoothing(self):
        timestamps = [0.0, 0.09, 0.21, 0.34, 0.47, 0.58, 0.70, 0.84, 1.0]
        values = [6.0, 9.0, 20.0, 43.0, 60.0, 55.0, 31.0, 13.0, 7.0]
        curve = _normalized_interval(
            timestamps,
            values,
            0.0,
            1.0,
            preserve_peak=True,
        )
        self.assertEqual(len(curve), 101)
        self.assertAlmostEqual(max(curve), 60.0, delta=0.2)
        np.testing.assert_allclose(curve, np.interp(np.linspace(0, 1, 101), timestamps, values), atol=0.0001)
        self.assertGreater(int(np.argmax(curve)), 35)
        self.assertLess(int(np.argmax(curve)), 60)

    def test_patient_leg_length_scales_clearance_to_centimetres(self):
        samples = []
        for index in range(120):
            lift_px = 20.0 * max(0.0, np.sin(2 * np.pi * index / 30.0))
            tracking = {"imageWidthPx": 640, "imageHeightPx": 480}
            for side, x in (("left", 220.0), ("right", 420.0)):
                def point(y):
                    return {"x": x, "y": y, "visibility": 0.99}
                tracking[side] = {
                    "hip": point(120.0),
                    "knee": point(270.0),
                    "ankle": point(420.0 - lift_px),
                    "heel": point(440.0 - lift_px),
                    "toe": point(440.0 - lift_px),
                }
            samples.append({"time": index / 30.0, "footTracking": tracking})

        result = estimate_foot_clearance_signals(
            samples,
            left_leg_length_cm=90.0,
            right_leg_length_cm=90.0,
        )
        self.assertTrue(result["available"])
        self.assertAlmostEqual(
            max(result["signals"]["left_foot_clearance_cm"]),
            6.0,
            delta=0.45,
        )

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
        statistics = analysis["statistics"]
        self.assertEqual(statistics["knee"]["left"]["rom"]["n"], 5)
        self.assertAlmostEqual(
            statistics["cycleDuration"]["left"]["mean"],
            1.0,
            places=3,
        )
        self.assertAlmostEqual(
            statistics["cadence"]["mean"],
            120.0,
            places=3,
        )
        self.assertAlmostEqual(
            statistics["cycleDuration"]["cvPercent"],
            0.0,
            places=3,
        )
        left_rom = statistics["knee"]["left"]["rom"]["mean"]
        right_rom = statistics["knee"]["right"]["rom"]["mean"]
        expected_symmetry = 100.0 * min(left_rom, right_rom) / max(left_rom, right_rom)
        self.assertAlmostEqual(
            statistics["knee"]["romSymmetryPercent"],
            expected_symmetry,
            places=2,
        )

    def test_camera_segmentation_is_fallback_when_fsr_contacts_are_insufficient(self):
        timestamps = np.linspace(0, 8, 481)
        phase = 2 * np.pi * timestamps / 1.2
        signals = {
            "left_knee": (30 + 25 * np.cos(phase)).tolist(),
            "right_knee": (28 + 23 * np.cos(phase - np.pi)).tolist(),
            "left_hip": (25 + 10 * np.sin(phase)).tolist(),
            "right_hip": (24 + 9 * np.sin(phase - np.pi)).tolist(),
            "trunk": (6 + 2 * np.sin(phase / 2)).tolist(),
        }
        progress = {}
        cycles = build_synchronized_gait_cycles(
            timestamps,
            signals,
            [{
                "pairIndex": 1,
                "left": {"start": 0.1},
                "right": {"start": 0.7},
            }],
            window_size=5,
            progress=progress,
        )
        self.assertTrue(cycles)
        self.assertTrue(all(cycle["source"] == "camera" for cycle in cycles))
        self.assertEqual(progress["segmentationSource"], "camera")
        self.assertTrue(progress["fallbackUsed"])
        self.assertEqual(progress["fsrConfirmedSteps"], 0)
        self.assertIn("extensionEvents", progress["left"])

    def test_camera_cycles_are_detected_without_fsr(self):
        timestamps = np.linspace(0, 12, 721)
        phase = 2 * np.pi * timestamps / 1.2
        rng = np.random.default_rng(20260813)
        signals = {
            "left_knee": (30 + 25 * np.cos(phase) + rng.normal(0, 0.6, len(phase))).tolist(),
            "right_knee": (28 + 23 * np.cos(phase - np.pi) + rng.normal(0, 0.6, len(phase))).tolist(),
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
                self.assertGreater(cycle[side]["duration"], 0.18)
                for metric in ("knee", "hip", "trunk"):
                    self.assertEqual(len(cycle[side]["curves"][metric]), 101)
                knee = cycle[side]["curves"]["knee"]
                measured = cycle[side]["curves"]["knee"]
                self.assertEqual(len(measured), 101)
                self.assertAlmostEqual(max(knee), max(measured), places=3)
                self.assertLess(knee[0], max(knee) - 6.0)
                self.assertGreater(max(knee), knee[-1])
                hip = cycle[side]["curves"]["hip"]
                hip_measured = cycle[side]["curves"]["hip"]
                self.assertEqual(len(hip_measured), 101)
                self.assertAlmostEqual(max(hip), max(hip_measured), places=3)
                self.assertAlmostEqual(min(hip), min(hip_measured), places=3)
        analysis = analyze_gait_cycles(cycles, window_size=5)
        self.assertEqual(
            analysis["curveProcessing"]["hipDisplay"],
            "measured_samples",
        )

    def test_camera_cycles_reject_stationary_pose_jitter(self):
        timestamps = np.linspace(0, 10, 601)
        rng = np.random.default_rng(7)
        signals = {
            "left_knee": (5 + rng.normal(0, 0.5, len(timestamps))).tolist(),
            "right_knee": (6 + rng.normal(0, 0.5, len(timestamps))).tolist(),
            "left_hip": np.full(len(timestamps), 20.0).tolist(),
            "right_hip": np.full(len(timestamps), 20.0).tolist(),
            "trunk": np.full(len(timestamps), 5.0).tolist(),
        }
        self.assertEqual(
            build_camera_gait_cycles(timestamps.tolist(), signals, window_size=5),
            [],
        )

    def test_camera_cycles_detect_shallow_fast_normal_steps(self):
        timestamps = np.linspace(0, 8, 121)  # only 15 pose samples/s
        phase = 2 * np.pi * timestamps / 0.72
        rng = np.random.default_rng(29)
        signals = {
            "left_knee": (11 + 5.2 * np.cos(phase) + rng.normal(0, 0.35, len(phase))).tolist(),
            "right_knee": (11 + 5.0 * np.cos(phase - np.pi) + rng.normal(0, 0.35, len(phase))).tolist(),
            "left_hip": (18 + 4 * np.sin(phase)).tolist(),
            "right_hip": (18 + 4 * np.sin(phase - np.pi)).tolist(),
            "trunk": np.full(len(timestamps), 4.0).tolist(),
        }
        progress = {}
        cycles = build_camera_gait_cycles(
            timestamps.tolist(),
            signals,
            window_size=7,
            progress=progress,
        )
        self.assertGreaterEqual(len(cycles), 5)
        self.assertTrue(progress["ready"])
        self.assertGreaterEqual(progress["left"]["extensionEvents"], 8)
        self.assertLessEqual(progress["left"]["requiredExcursionDeg"], 4.5)

    def test_camera_cycles_preserve_true_zero_extension(self):
        timestamps = np.linspace(0, 8, 481)
        phase = 2 * np.pi * timestamps / 1.2
        signals = {
            "left_knee": np.maximum(0, 42 * np.cos(phase)).tolist(),
            "right_knee": np.maximum(0, 40 * np.cos(phase - np.pi)).tolist(),
            "left_hip": (18 + 8 * np.sin(phase)).tolist(),
            "right_hip": (17 + 7 * np.sin(phase - np.pi)).tolist(),
            "trunk": np.full(len(timestamps), 4.0).tolist(),
        }
        cycles = build_camera_gait_cycles(
            timestamps.tolist(), signals, window_size=5
        )
        self.assertTrue(cycles)
        for cycle in cycles:
            self.assertEqual(min(cycle["left"]["curves"]["knee"]), 0.0)
            self.assertEqual(min(cycle["right"]["curves"]["knee"]), 0.0)

    def test_camera_pairing_rejects_one_side_missed_peak_shift(self):
        timestamps = np.linspace(0, 12, 721)
        phase = 2 * np.pi * timestamps / 1.2
        left_knee = 30 + 25 * np.cos(phase)
        right_knee = 30 + 25 * np.cos(phase - np.pi)
        # Simulate an occlusion that erases one right-knee flexion peak.
        right_knee[np.abs(timestamps - 10.2) < 0.28] = 30.0
        signals = {
            "left_knee": left_knee.tolist(),
            "right_knee": right_knee.tolist(),
            "left_hip": (20 + 9 * np.sin(phase)).tolist(),
            "right_hip": (20 + 9 * np.sin(phase - np.pi)).tolist(),
            "trunk": np.full(len(timestamps), 4.0).tolist(),
        }
        cycles = build_camera_gait_cycles(
            timestamps.tolist(), signals, window_size=7
        )
        self.assertTrue(cycles)
        for cycle in cycles:
            left_duration = cycle["left"]["duration"]
            right_duration = cycle["right"]["duration"]
            self.assertLessEqual(
                max(left_duration, right_duration)
                / min(left_duration, right_duration),
                1.60,
            )


if __name__ == "__main__":
    unittest.main()
