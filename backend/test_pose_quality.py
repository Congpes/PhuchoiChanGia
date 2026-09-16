import unittest

from pose_quality import (
    assess_pose_sample,
    assess_temporal_consistency,
    summarize_pose_quality,
)


class PoseQualityTests(unittest.TestCase):
    def setUp(self):
        self.sample = {
            "left_knee": 35.0,
            "right_knee": 40.0,
            "left_hip": 20.0,
            "right_hip": 24.0,
            "trunk_tilt": 4.0,
        }
        self.visibility = {
            "left_shoulder": 0.9,
            "right_shoulder": 0.9,
            "left_hip": 0.9,
            "right_hip": 0.9,
            "left_knee": 0.9,
            "right_knee": 0.9,
            "left_ankle": 0.9,
            "right_ankle": 0.9,
        }

    def test_reliable_pose_summary(self):
        assessment = assess_pose_sample(self.sample, self.visibility)
        summary = summarize_pose_quality(
            [assessment] * 24,
            pose_detected=True,
            sample_count=24,
            cycle_count=2,
        )
        self.assertEqual(summary["status"], "reliable")
        self.assertEqual(summary["reasons"], [])

    def test_flags_low_visibility_angle_and_cycle_count(self):
        low_visibility = dict(self.visibility)
        low_visibility["right_ankle"] = 0.20
        noisy_sample = dict(self.sample)
        noisy_sample["left_knee"] = 152.0
        assessment = assess_pose_sample(noisy_sample, low_visibility)
        summary = summarize_pose_quality(
            [assessment] * 24,
            pose_detected=True,
            sample_count=24,
            cycle_count=1,
        )
        self.assertEqual(summary["status"], "unreliable")
        self.assertIn("landmark_occluded", summary["reasons"])
        self.assertIn("angle_out_of_screening_range", summary["reasons"])
        self.assertIn("insufficient_cycles", summary["reasons"])
        self.assertTrue(summary["guidance"])

    def test_flags_dual_camera_samples_that_cannot_be_synchronized(self):
        assessment = assess_pose_sample(self.sample, self.visibility)
        assessment.update({
            "frameReliable": False,
            "crossViewSynchronized": False,
            "measurementMethod": "sagittal_only_2d",
        })
        summary = summarize_pose_quality(
            [assessment] * 24,
            pose_detected=True,
            sample_count=24,
            cycle_count=2,
        )
        self.assertIn("cross_camera_unsynchronized", summary["reasons"])

    def test_prosthetic_leg_requires_seventy_percent_visibility(self):
        visibility = dict(self.visibility)
        visibility["right_knee"] = 0.69

        assessment = assess_pose_sample(
            self.sample,
            visibility,
            target_side="RIGHT",
        )
        summary = summarize_pose_quality(
            [assessment] * 24,
            pose_detected=True,
            sample_count=24,
            cycle_count=2,
        )

        self.assertFalse(assessment["targetLegReliable"])
        self.assertEqual(assessment["lowTargetLandmarks"], ["right_knee"])
        self.assertIn("target_leg_landmark_occluded", summary["reasons"])

        visibility["right_knee"] = 0.70
        boundary = assess_pose_sample(
            self.sample,
            visibility,
            target_side="RIGHT",
        )
        self.assertTrue(boundary["targetLegReliable"])
        self.assertEqual(boundary["landmarkVisibility"]["right_knee"], 0.7)

    def test_rejects_implausible_single_frame_angle_jump(self):
        previous = {**self.sample, "left_knee": 20.0}
        current = {**self.sample, "left_knee": 100.0}
        quality = assess_temporal_consistency(current, previous, 0.05)
        self.assertFalse(quality["temporalReliable"])
        self.assertEqual(quality["temporalJumpAngles"], ["left_knee"])

    def test_rejects_nearly_overlapped_leg_landmarks(self):
        positions = {
            "left_shoulder": {"x": 0.46, "y": 0.15},
            "right_shoulder": {"x": 0.54, "y": 0.15},
            "left_hip": {"x": 0.48, "y": 0.43},
            "right_hip": {"x": 0.52, "y": 0.43},
            "left_knee": {"x": 0.500, "y": 0.65},
            "right_knee": {"x": 0.506, "y": 0.654},
            "left_ankle": {"x": 0.500, "y": 0.90},
            "right_ankle": {"x": 0.507, "y": 0.906},
        }
        assessment = assess_pose_sample(
            self.sample,
            self.visibility,
            target_side="RIGHT",
            landmark_positions=positions,
        )
        summary = summarize_pose_quality(
            [assessment] * 24,
            pose_detected=True,
            sample_count=24,
            cycle_count=2,
        )
        self.assertFalse(assessment["legIdentityReliable"])
        self.assertFalse(assessment["bilateralSagittalReliable"])
        self.assertIn("leg_identity_ambiguous", summary["reasons"])


if __name__ == "__main__":
    unittest.main()
