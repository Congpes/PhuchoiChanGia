import copy
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from pose_angle_overlay import (
    draw_joint_angle_labels, joint_angle_labels, pose_frame_matches_source,
    frontal_trunk_label, draw_frontal_trunk_label,
    sagittal_trunk_label, draw_sagittal_trunk_label,
)


def standing_pose():
    return {
        f'{side}_{joint}': {'x': x, 'y': y, 'visibility': 0.95}
        for side, x in (('left', 0.4), ('right', 0.6))
        for joint, y in (('shoulder', 0.2), ('hip', 0.45), ('knee', 0.65), ('ankle', 0.85))
    }


class JointAngleOverlayTests(unittest.TestCase):
    def sagittal_pose(self):
        pose = standing_pose()
        for side in ('left', 'right'):
            pose[f'{side}_shoulder']['x'] += .1
            pose[f'{side}_heel'] = dict(x=.4, y=.9, visibility=.95)
            pose[f'{side}_foot_index'] = dict(x=.5, y=.9, visibility=.95)
        return pose

    def test_sagittal_trunk_forward_sign_and_mirror(self):
        pose = self.sagittal_pose()
        angle = sagittal_trunk_label(pose, 1280, 720).value
        self.assertGreater(angle, 0)
        self.assertAlmostEqual(angle, np.degrees(np.arctan2(128, 180)))
        for p in pose.values():
            p['x'] = 1 - p['x']
        self.assertAlmostEqual(sagittal_trunk_label(pose, 1280, 720).value, angle)

    def test_sagittal_trunk_withholds_ambiguous_direction(self):
        pose = self.sagittal_pose()
        pose['right_foot_index']['x'] = .3
        self.assertIsNone(sagittal_trunk_label(pose, 1280, 720).value)
        for side in ('left', 'right'):
            pose[f'{side}_shoulder']['visibility'] = .2
        self.assertIsNone(sagittal_trunk_label(pose, 1280, 720))
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        draw_sagittal_trunk_label(frame, {})
        self.assertFalse(frame.any())

    def test_sagittal_trunk_ignores_hidden_far_torso(self):
        pose = self.sagittal_pose()
        expected = sagittal_trunk_label(pose, 1280, 720).value
        pose['right_shoulder'].update(x=.1, visibility=.2)
        self.assertAlmostEqual(sagittal_trunk_label(pose, 1280, 720).value, expected)

    def test_frontal_trunk_upright_and_pixel_aspect(self):
        pose = standing_pose()
        self.assertAlmostEqual(frontal_trunk_label(pose, 1280, 720).value, 0)
        for side in ('left', 'right'):
            pose[f'{side}_shoulder']['x'] += .25 * 720 / 1280
        self.assertAlmostEqual(frontal_trunk_label(pose, 1280, 720).value, 45)
        for point in pose.values():
            point['x'] = 1 - point['x']
        self.assertAlmostEqual(frontal_trunk_label(pose, 1280, 720).value, 45)

    def test_frontal_trunk_gates_and_missing_frame(self):
        pose = standing_pose()
        pose['left_shoulder']['visibility'] = .5
        self.assertIsNone(frontal_trunk_label(pose, 1280, 720).value)
        pose['left_shoulder']['x'] = float('nan')
        self.assertIsNone(frontal_trunk_label(pose, 1280, 720))
        self.assertIsNone(frontal_trunk_label({}, 1280, 720))
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        draw_frontal_trunk_label(frame, {})
        self.assertFalse(frame.any())

    def test_frontal_trunk_label_draws_signed_degrees(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch('pose_angle_overlay.cv2.putText', wraps=cv2.putText) as texts:
            draw_frontal_trunk_label(frame, standing_pose())
        self.assertEqual(texts.call_args.args[1], 'NT +0.0')

    def test_one_closeup_leg_needs_no_shoulders_or_opposite_leg(self):
        pose = {name: {'x': x, 'y': y, 'visibility': .95}
                for name, x, y in (('left_hip', .1, .1), ('left_knee', .8, .1), ('left_ankle', .8, .9))}
        values = self.values(pose)
        self.assertAlmostEqual(values['left_knee'], 90)
        self.assertIsNone(values['left_hip'])
        self.assertNotIn('right_knee', values)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch('pose_angle_overlay.cv2.line', wraps=cv2.line) as lines:
            draw_joint_angle_labels(frame, pose, knee_only=True, draw_knee_segments=True)
        # Only the thigh and shank; angle tags must not add leader lines.
        self.assertEqual(lines.call_count, 2)

    def test_closeup_cannot_guess_an_out_of_frame_hip(self):
        pose = {k: v for k, v in standing_pose().items() if k.startswith('left_')}
        pose['left_hip']['x'] = -0.1
        self.assertIsNone(self.values(pose)['left_knee'])

    def test_replay_angles_require_the_current_source_frame(self):
        frame = {'time': 1.0, 'sourceFrameIndex': 20}
        self.assertTrue(pose_frame_matches_source(frame, 20, 1.0))
        self.assertFalse(pose_frame_matches_source(frame, 21, 1.0))
        old_frame = {'time': 11.5931}
        self.assertTrue(pose_frame_matches_source(old_frame, 162, 11.59315))
        self.assertFalse(pose_frame_matches_source(old_frame, 163, 11.65))

    def values(self, pose, sample=None):
        return {item.name: item.value for item in joint_angle_labels(pose, 1280, 720, sample)}

    def test_straight_is_zero_not_inside_angle_180(self):
        self.assertEqual(self.values(standing_pose()), {
            'left_hip': 0, 'right_hip': 0, 'left_knee': 0, 'right_knee': 0,
        })

    def test_right_angle_hip_and_knee(self):
        pose = standing_pose()
        pose['right_knee'].update(x=0.75, y=0.45)
        pose['right_ankle'].update(x=0.75, y=0.70)
        values = self.values(pose)
        self.assertAlmostEqual(values['right_hip'], 90)
        self.assertAlmostEqual(values['right_knee'], 90)
        self.assertAlmostEqual(values['left_hip'], 0)

    def test_non_square_frame_uses_pixel_geometry(self):
        pose = standing_pose()
        pose['right_ankle'].update(x=0.6 + 0.2 * 720 / 1280)
        self.assertAlmostEqual(self.values(pose)['right_knee'], 45, places=3)

    def test_live_numbers_are_unfiltered_current_sample(self):
        pose = standing_pose()
        sample = dict(left_knee=21.37, right_knee=43.29, left_hip=8.5, right_hip=12.9)
        before = copy.deepcopy((pose, sample))
        self.assertEqual(self.values(pose, sample), sample)
        self.assertEqual((pose, sample), before)

    def test_occluded_ankle_withholds_only_its_knee(self):
        pose = standing_pose()
        pose['left_ankle']['visibility'] = 0.2
        values = self.values(pose)
        self.assertIsNone(values['left_knee'])
        self.assertEqual(values['right_knee'], 0)
        self.assertEqual(values['left_hip'], 0)

    def test_no_number_for_nonfinite_outside_or_collapsed_points(self):
        for invalid in ({'x': float('nan')}, {'y': 1.2}, {'x': 0.4, 'y': 0.65}):
            pose = standing_pose()
            pose['left_ankle'].update(invalid)
            self.assertIsNone(self.values(pose)['left_knee'])
        sample = dict(left_knee=float('nan'), right_knee=None, left_hip=181, right_hip=-1)
        self.assertTrue(all(value is None for value in self.values(standing_pose(), sample).values()))

    def test_missing_pose_does_not_reuse_previous_angles(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        draw_joint_angle_labels(frame, standing_pose())
        self.assertTrue(frame.any())
        new_frame = np.zeros_like(frame)
        draw_joint_angle_labels(new_frame, {})
        self.assertFalse(new_frame.any())

    def test_labels_fit_frame_edges_and_do_not_overlap(self):
        for center_x in (0.01, 0.5, 0.99):
            pose = standing_pose()
            for point in pose.values():
                point['x'] = center_x
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            with patch('pose_angle_overlay.cv2.putText', wraps=cv2.putText) as texts:
                draw_joint_angle_labels(frame, pose)
            boxes = []
            for call in texts.call_args_list:
                if call.args[6] != 1:  # Skip the duplicate dark text outline.
                    continue
                _, text, (x, y), font, scale, *_ = call.args
                (tw, th), baseline = cv2.getTextSize(text, font, scale, 1)
                boxes.append(((x - 2, y - th - 2), (x + tw + 7, y + baseline + 2)))
            self.assertEqual(len(boxes), 4)
            for i, ((x, y), (right, bottom)) in enumerate(boxes):
                self.assertTrue(0 <= x < right < 1280 and 0 <= y < bottom < 720)
                for ((ox, oy), (oright, obottom)) in boxes[:i]:
                    self.assertFalse(x < oright and right > ox and y < obottom and bottom > oy)

    def test_compact_floating_labels_have_no_leaders_or_background_boxes(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        sample = dict(left_hip=6.6, right_hip=8.3, left_knee=15.7, right_knee=58.1)
        with patch('pose_angle_overlay.cv2.putText', wraps=cv2.putText) as texts, \
             patch('pose_angle_overlay.cv2.line', wraps=cv2.line) as lines, \
             patch('pose_angle_overlay.cv2.rectangle', wraps=cv2.rectangle) as boxes, \
             patch('pose_angle_overlay.cv2.circle', wraps=cv2.circle) as circles:
            draw_joint_angle_labels(frame, standing_pose(), sample)
        labels = [call.args[1] for call in texts.call_args_list if call.args[6] == 1]
        self.assertEqual(labels, ['HT 6.6', 'GT 15.7', 'HP 8.3', 'GP 58.1'])
        lines.assert_not_called()
        boxes.assert_not_called()
        self.assertEqual(sum(call.args[4] == 1 for call in circles.call_args_list), 4)

    def test_unreliable_angle_retains_compact_missing_label(self):
        pose = standing_pose()
        pose['right_knee']['visibility'] = .6
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch('pose_angle_overlay.cv2.putText', wraps=cv2.putText) as texts:
            draw_joint_angle_labels(frame, pose)
        labels = [call.args[1] for call in texts.call_args_list if call.args[6] == 1]
        self.assertIn('GP --', labels)
        self.assertIn('HP --', labels)


if __name__ == '__main__':
    unittest.main()
