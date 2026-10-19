import unittest
import math

from camera_fusion import (
    DualCameraSynchronizer,
    apply_stereo_flexion,
    frontal_metrics,
    fuse_synchronized_sample,
    hip_flexion_from_body_axis,
    normalize_sagittal_trunk_lean,
    sagittal_fallback_sample,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _landmarks(*, hip_drop=0.0, hip_width=0.24):
    center = 0.5
    return {
        "left_shoulder": {"x": center - 0.14, "y": 0.2, "visibility": 0.95},
        "right_shoulder": {"x": center + 0.14, "y": 0.2, "visibility": 0.95},
        "left_hip": {"x": center - hip_width / 2, "y": 0.46 + hip_drop, "visibility": 0.95},
        "right_hip": {"x": center + hip_width / 2, "y": 0.46, "visibility": 0.95},
        "left_knee": {"x": center - 0.11, "y": 0.68, "visibility": 0.95},
        "right_knee": {"x": center + 0.11, "y": 0.68, "visibility": 0.95},
        "left_ankle": {"x": center - 0.10, "y": 0.9, "visibility": 0.95},
        "right_ankle": {"x": center + 0.10, "y": 0.9, "visibility": 0.95},
    }


class CameraFusionTests(unittest.TestCase):
    def test_sagittal_trunk_lean_keeps_forward_positive_after_turnaround(self):
        walking_right = normalize_sagittal_trunk_lean(
            6.0,
            left_heel=(0.0, 1.0), left_toe=(1.0, 1.0),
            right_heel=(0.0, 1.0), right_toe=(1.0, 1.0),
        )
        walking_left = normalize_sagittal_trunk_lean(
            -6.0,
            left_heel=(1.0, 1.0), left_toe=(0.0, 1.0),
            right_heel=(1.0, 1.0), right_toe=(0.0, 1.0),
        )
        self.assertEqual(walking_right[0], 6.0)
        self.assertEqual(walking_left[0], 6.0)

    def test_sagittal_facing_uses_head_when_feet_disagree(self):
        normalized = normalize_sagittal_trunk_lean(
            -5.0,
            left_heel=(0.0, 1.0), left_toe=(1.0, 1.0),
            right_heel=(1.0, 1.0), right_toe=(0.0, 1.0),
            nose=(0.0, 0.0), mid_shoulder=(1.0, 0.0),
        )
        self.assertEqual(normalized[0], 5.0)
        self.assertEqual(normalized[2], "nose_minus_shoulder_foot_conflict")

    def test_frontal_trunk_lean_keeps_patient_right_positive_after_turnaround(self):
        back_view = _landmarks()
        back_view["left_shoulder"]["x"] -= 0.04
        back_view["right_shoulder"]["x"] += 0.12
        front_view = _landmarks()
        front_view["left_shoulder"]["x"] = 0.64
        front_view["right_shoulder"]["x"] = 0.28
        front_view["left_hip"]["x"] = 0.62
        front_view["right_hip"]["x"] = 0.38
        back_lean = frontal_metrics(back_view)["trunkLateralLean"]
        front_lean = frontal_metrics(front_view)["trunkLateralLean"]
        self.assertGreater(back_lean, 0.0)
        self.assertGreater(front_lean, 0.0)

    def test_hip_flexion_uses_translated_trunk_axis_without_diagonal_bias(self):
        shoulders = ((0.0, 0.0), (2.0, 0.0))
        hips = ((0.0, 1.0), (2.0, 1.0))
        left = hip_flexion_from_body_axis(
            *shoulders, *hips, (0.0, 2.0), hips[0]
        )
        right = hip_flexion_from_body_axis(
            *shoulders, *hips, (2.0, 2.0), hips[1]
        )
        self.assertAlmostEqual(left, 0.0, places=6)
        self.assertAlmostEqual(right, 0.0, places=6)

    def test_hip_flexion_known_thirty_degree_geometry(self):
        knee = (math.sin(math.radians(30)), 1.0 + math.cos(math.radians(30)))
        measured = hip_flexion_from_body_axis(
            (0.0, 0.0), (2.0, 0.0),
            (0.0, 1.0), (2.0, 1.0),
            knee, (0.0, 1.0),
        )
        self.assertAlmostEqual(measured, 30.0, places=6)

    def test_frontal_angles_account_for_image_aspect_ratio(self):
        landmarks = _landmarks(hip_drop=0.03, hip_width=0.24)
        normalized = frontal_metrics(landmarks)["pelvicTilt"]
        pixel_corrected = frontal_metrics(landmarks, (640, 480))["pelvicTilt"]
        expected = math.degrees(math.atan2(0.03 * 480, -0.24 * 640))
        while expected > 90:
            expected -= 180
        while expected < -90:
            expected += 180
        self.assertNotAlmostEqual(normalized, pixel_corrected, places=3)
        self.assertAlmostEqual(pixel_corrected, expected, places=6)

    def test_frontal_view_supplies_pelvic_obliquity(self):
        metrics = frontal_metrics(_landmarks(hip_drop=0.03))
        self.assertGreater(abs(metrics["pelvicTilt"]), 1.0)
        self.assertGreater(metrics["meanVisibility"], 0.9)

    def test_fusion_preserves_flexion_and_replaces_pelvic_source(self):
        sample = {
            "left_knee": 35.0,
            "right_knee": 40.0,
            "left_hip": 20.0,
            "right_hip": 22.0,
            "pelvic_tilt": 88.0,
            "poseQuality": {"frameReliable": True, "lowLandmarks": []},
        }
        fused = fuse_synchronized_sample(
            sample,
            _landmarks(hip_width=0.03),
            _landmarks(hip_drop=0.03, hip_width=0.24),
            12.5,
            40.0,
        )
        self.assertEqual(fused["left_knee"], 35.0)
        self.assertNotEqual(fused["pelvic_tilt"], 88.0)
        self.assertTrue(fused["poseQuality"]["frameReliable"])
        self.assertEqual(fused["cameraFusion"]["pelvicTiltSource"], "frontal")
        self.assertTrue(fused["cameraFusion"]["cameraRolesPlausible"])

    def test_synchronizer_pairs_out_of_order_arrivals(self):
        sync = DualCameraSynchronizer(max_skew_ms=40, clock=FakeClock())
        sagittal = {"captured_ns": 1_000_000_000, "sample": {}}
        self.assertEqual(sync.submit("sagittal", sagittal), [])
        outputs = sync.submit("frontal", {"captured_ns": 1_012_000_000})
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["kind"], "paired")
        self.assertAlmostEqual(outputs[0]["syncErrorMs"], 12.0)

    def test_synchronizer_retains_pair_when_sagittal_inference_finishes_first(self):
        sync = DualCameraSynchronizer(max_skew_ms=40, clock=FakeClock())
        self.assertEqual(sync.submit("sagittal", {"captured_ns": 1_000_000_000}), [])
        self.assertEqual(sync.submit("sagittal", {"captured_ns": 1_100_000_000}), [])

        first = sync.submit("frontal", {"captured_ns": 1_005_000_000})
        second = sync.submit("frontal", {"captured_ns": 1_105_000_000})

        self.assertEqual([item["kind"] for item in first + second], ["paired", "paired"])
        self.assertEqual(
            [item["sagittal"]["captured_ns"] for item in first + second],
            [1_000_000_000, 1_100_000_000],
        )
        self.assertEqual([item["syncErrorMs"] for item in first + second], [5.0, 5.0])

    def test_synchronizer_releases_unpaired_sagittal_sample(self):
        clock = FakeClock()
        sync = DualCameraSynchronizer(max_skew_ms=40, clock=clock)
        self.assertEqual(sync.submit("sagittal", {"captured_ns": 1_000_000_000}), [])
        clock.advance(0.05)
        self.assertEqual(sync.submit("sagittal", {"captured_ns": 1_050_000_000}), [])
        clock.advance(0.199)
        self.assertEqual(sync.drain(), [])
        clock.advance(0.001)
        outputs = sync.drain()
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["kind"], "fallback")
        self.assertEqual(outputs[0]["sagittal"]["captured_ns"], 1_000_000_000)
        self.assertEqual(sync.drain(), [])
        clock.advance(0.05)
        remaining = sync.drain()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["sagittal"]["captured_ns"], 1_050_000_000)
        self.assertEqual(sync.drain(), [])
        fallback = sagittal_fallback_sample(
            {"poseQuality": {"frameReliable": True}},
            single_camera=False,
        )
        self.assertFalse(fallback["poseQuality"]["frameReliable"])

    def test_synchronizer_arrival_wait_preserves_strict_capture_tolerance(self):
        for delta_ms in (-41, -40, 40, 41):
            with self.subTest(delta_ms=delta_ms):
                clock = FakeClock()
                sync = DualCameraSynchronizer(max_skew_ms=40, clock=clock)
                sync.submit("sagittal", {"captured_ns": 1_000_000_000})
                clock.advance(0.2)
                outputs = sync.submit("frontal", {
                    "captured_ns": 1_000_000_000 + delta_ms * 1_000_000,
                })
                clock.advance(0.05)
                outputs.extend(sync.drain())
                self.assertEqual(len(outputs), 1)
                self.assertEqual(
                    outputs[0]["kind"], "paired" if abs(delta_ms) <= 40 else "fallback",
                )
                if outputs[0]["kind"] == "paired":
                    self.assertEqual(outputs[0]["syncErrorMs"], abs(delta_ms))

    def test_synchronizer_frontal_watermark_releases_without_arrival_timeout(self):
        clock = FakeClock()
        sync = DualCameraSynchronizer(max_skew_ms=40, clock=clock)
        sync.submit("sagittal", {"captured_ns": 1_000_000_000})
        outputs = sync.submit("frontal", {"captured_ns": 1_041_000_000})
        self.assertEqual(outputs, [{
            "kind": "fallback", "sagittal": {"captured_ns": 1_000_000_000},
        }])
        self.assertEqual(clock.now, 0.0)

    def test_synchronizer_waits_for_closer_future_frontal_candidate(self):
        sync = DualCameraSynchronizer(max_skew_ms=40, clock=FakeClock())
        sync.submit("frontal", {"captured_ns": 980_000_000})
        self.assertEqual(sync.submit("sagittal", {"captured_ns": 1_000_000_000}), [])
        self.assertEqual(sync.submit("sagittal", {"captured_ns": 1_100_000_000}), [])
        outputs = sync.submit("frontal", {"captured_ns": 1_005_000_000})
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["kind"], "paired")
        self.assertEqual(outputs[0]["frontal"]["captured_ns"], 1_005_000_000)
        self.assertEqual(outputs[0]["syncErrorMs"], 5.0)

    def test_synchronizer_timeout_pairs_earlier_candidate_without_reusing_it(self):
        clock = FakeClock()
        sync = DualCameraSynchronizer(max_skew_ms=40, clock=clock)
        sync.submit("frontal", {"captured_ns": 990_000_000})
        sync.submit("sagittal", {"captured_ns": 1_000_000_000})
        sync.submit("sagittal", {"captured_ns": 1_001_000_000})
        clock.advance(0.25)
        outputs = sync.drain()
        self.assertEqual([item["kind"] for item in outputs], ["paired", "fallback"])
        self.assertEqual(outputs[0]["syncErrorMs"], 10.0)
        self.assertEqual(outputs[1]["sagittal"]["captured_ns"], 1_001_000_000)
        self.assertEqual(sync.drain(), [])
        self.assertEqual(sync.status()["pairedSamples"], 1)
        self.assertEqual(sync.status()["fallbackSamples"], 1)

    def test_synchronizer_force_drain_settles_pending_without_wait_or_reuse(self):
        clock = FakeClock()
        sync = DualCameraSynchronizer(max_skew_ms=40, clock=clock)
        sync.submit("frontal", {"captured_ns": 980_000_000})
        sync.submit("frontal", {"captured_ns": 990_000_000})
        sync.submit("sagittal", {"captured_ns": 1_000_000_000})
        sync.submit("sagittal", {"captured_ns": 1_001_000_000})
        sync.submit("sagittal", {"captured_ns": 1_002_000_000})
        self.assertEqual(sync.drain(), [])

        outputs = sync.drain(force=True)

        self.assertEqual(clock.now, 0.0)
        self.assertEqual([item["kind"] for item in outputs], ["paired", "paired", "fallback"])
        self.assertEqual(
            [item["frontal"]["captured_ns"] for item in outputs[:2]],
            [990_000_000, 980_000_000],
        )
        self.assertEqual([item["syncErrorMs"] for item in outputs[:2]], [10.0, 21.0])
        self.assertEqual(sync.drain(force=True), [])
        self.assertEqual(sync.status()["pairedSamples"], 2)
        self.assertEqual(sync.status()["fallbackSamples"], 1)

        self.assertEqual(sync.submit("sagittal", {"captured_ns": 1_100_000_000}), [])
        clock.advance(0.249)
        self.assertEqual(sync.drain(), [])
        clock.advance(0.001)
        remaining = sync.drain()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["kind"], "fallback")

    def test_synchronizer_queue_capacity_conserves_sagittal_samples(self):
        clock = FakeClock()
        sync = DualCameraSynchronizer(max_skew_ms=40, queue_size=4, clock=clock)
        outputs = []
        captures = [1_000_000_000 + index * 10_000_000 for index in range(12)]
        for captured_ns in captures:
            outputs.extend(sync.submit("sagittal", {"captured_ns": captured_ns}))
            self.assertLessEqual(len(sync._sagittal), 4)
            self.assertEqual(len(sync._sagittal_deadlines), len(sync._sagittal))
        self.assertEqual(len(outputs), 8)
        clock.advance(0.25)
        outputs.extend(sync.drain())
        self.assertEqual([item["sagittal"]["captured_ns"] for item in outputs], captures)
        self.assertTrue(all(item["kind"] == "fallback" for item in outputs))
        self.assertEqual(sync.status()["fallbackSamples"], len(captures))
        self.assertEqual(sync.drain(), [])
        for captured_ns in captures:
            sync.submit("frontal", {"captured_ns": captured_ns})
            self.assertLessEqual(len(sync._front), 4)

    def test_synchronizer_reset_clears_pending_deadlines_and_frontal_watermark(self):
        clock = FakeClock()
        sync = DualCameraSynchronizer(max_skew_ms=40, clock=clock)
        sync.submit("sagittal", {"captured_ns": 1_000_000_000})
        sync.submit("frontal", {"captured_ns": 1_005_000_000})
        sync.submit("sagittal", {"captured_ns": 1_100_000_000})
        sync.submit("frontal", {"captured_ns": 1_200_000_000})
        sync.submit("sagittal", {"captured_ns": 1_300_000_000})
        sync.reset()
        status = sync.status()
        self.assertEqual(status["pairedSamples"], 0)
        self.assertEqual(status["fallbackSamples"], 0)
        self.assertEqual(status["recentPairedSamples"], 0)
        self.assertEqual(status["recentFallbackSamples"], 0)
        self.assertIsNone(status["lastErrorMs"])
        self.assertFalse(status["synchronized"])
        clock.advance(0.25)
        self.assertEqual(sync.drain(), [])
        self.assertEqual(sync.submit("sagittal", {"captured_ns": 100_000_000}), [])
        outputs = sync.submit("frontal", {"captured_ns": 105_000_000})
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["kind"], "paired")

    def test_synchronizer_recent_ratio_recovers_after_startup_misses(self):
        clock = FakeClock()
        sync = DualCameraSynchronizer(max_skew_ms=40, clock=clock)
        captured_ns = 1_000_000_000
        for _ in range(70):
            sync.submit("sagittal", {"captured_ns": captured_ns, "sample": {}})
            clock.advance(0.05)
            sync.drain()
            captured_ns += 50_000_000
        for _ in range(60):
            sync.submit("sagittal", {"captured_ns": captured_ns, "sample": {}})
            sync.submit("frontal", {"captured_ns": captured_ns + 5_000_000})
            captured_ns += 50_000_000
        status = sync.status()
        self.assertGreater(status["fallbackSamples"], 0)
        self.assertGreaterEqual(status["recentPairRatio"], 0.95)
        self.assertGreaterEqual(status["recentPairedSamples"], 57)

    def test_calibrated_stereo_flexion_replaces_2d_angles(self):
        points = {
            "left_shoulder": [-0.2, 1.0, 0.0],
            "right_shoulder": [0.2, 1.0, 0.0],
            "left_hip": [-0.15, 0.6, 0.0],
            "right_hip": [0.15, 0.6, 0.0],
            "left_knee": [-0.15, 0.1, 0.2],
            "right_knee": [0.15, 0.1, 0.2],
            "left_ankle": [-0.15, -0.35, 0.0],
            "right_ankle": [0.15, -0.35, 0.0],
            "left_heel": [-0.15, -0.38, -0.12],
            "right_heel": [0.15, -0.38, -0.12],
        }
        sample = {
            "left_knee": 99.0,
            "right_knee": 99.0,
            "poseQuality": {"frameReliable": True},
            "cameraFusion": {},
        }
        result = apply_stereo_flexion(
            sample,
            {"points": points, "reprojectionErrorPx": 1.2, "calibrationStereoRms": 0.8},
            max_reprojection_error_px=8.0,
        )
        self.assertNotEqual(result["left_knee"], 99.0)
        self.assertTrue(result["cameraFusion"]["stereoUsed"])
        self.assertEqual(result["poseQuality"]["measurementMethod"], "calibrated_stereo_3d")

        rejected = apply_stereo_flexion(
            sample,
            {"points": points, "reprojectionErrorPx": 12.0, "calibrationStereoRms": 0.8},
            max_reprojection_error_px=8.0,
        )
        self.assertEqual(rejected["left_knee"], 99.0)
        self.assertFalse(rejected["cameraFusion"]["stereoUsed"])


if __name__ == "__main__":
    unittest.main()
