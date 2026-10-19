"""Exercise the real stream generator without starting database/hardware services."""

import ast
from collections import deque
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from camera_preview import PreviewJpegCache
from performance_metrics import PerformanceMonitor
from pose_identity_lock import PoseIdentityLock
from camera_fusion import DualCameraSynchronizer, sagittal_fallback_sample
from pose_quality import assess_temporal_consistency


class _StopStream(Exception):
    pass


class _PublishedFrame(np.ndarray):
    copies = 0

    def copy(self, *args, **kwargs):
        type(self).copies += 1
        return super().copy(*args, **kwargs)


class CameraStreamTests(unittest.TestCase):
    def setUp(self):
        # Execute the actual production function, not a duplicated algorithm.
        tree = ast.parse(Path(__file__).with_name('main.py').read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'gen_frames')
        self.frame = np.zeros((48, 64, 3), dtype=np.uint8).view(_PublishedFrame)
        _PublishedFrame.copies = 0
        self.monitor = Mock()
        self.clock = Mock()
        self.clock.monotonic.return_value = 1.0
        self.clock.perf_counter.side_effect = [1.0 + i*.001 for i in range(100)]
        self.clock.sleep.side_effect = _StopStream
        self.cache = PreviewJpegCache()
        self.state = dict(
            cv2=cv2, time=self.clock, performance_monitor=self.monitor,
            preview_jpeg_cache=self.cache,
            camera_roles_lock=threading.Lock(), camera_roles_swapped=False,
            frame_lock_0=threading.Lock(), frame_lock_1=threading.Lock(),
            SINGLE_CAMERA_MODE=False, STREAM_TARGET_FPS=20,
            STREAM_MAX_WIDTH=854, STREAM_JPEG_QUALITY=78,
            latest_raw_frame_0=self.frame, latest_raw_frame_1=self.frame,
            latest_frame_0=self.frame, latest_frame_1=self.frame,
            latest_frame_0_ns=100, latest_frame_1_ns=200,
            latest_processed_frame_0_ns=100, latest_processed_frame_1_ns=200,
        )
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'main.py', 'exec'), self.state)

    def test_two_clients_share_one_encode_and_no_published_frame_copy(self):
        first = self.state['gen_frames'](0)
        second = self.state['gen_frames'](0)
        self.assertEqual(next(first), next(second))
        self.assertEqual(self.monitor.record_stage.call_count, 1)
        self.assertEqual(_PublishedFrame.copies, 0)

    def test_waiting_for_new_frame_does_not_copy_or_encode_it_again(self):
        stream = self.state['gen_frames'](0)
        next(stream)
        self.clock.monotonic.return_value = 2.0
        with self.assertRaises(_StopStream):
            next(stream)
        self.assertEqual(self.monitor.record_stage.call_count, 1)
        self.assertEqual(_PublishedFrame.copies, 0)

    def test_swapping_roles_reuses_physical_cache_and_keeps_views_distinct(self):
        next(self.state['gen_frames'](0))
        next(self.state['gen_frames'](1))
        self.state['camera_roles_swapped'] = True
        next(self.state['gen_frames'](0))
        self.assertEqual(self.monitor.record_stage.call_count, 2)

    def test_raw_and_processed_frames_have_separate_encodes(self):
        next(self.state['gen_frames'](0, raw=True))
        next(self.state['gen_frames'](0))
        self.assertEqual(self.monitor.record_stage.call_count, 2)

    def test_single_camera_views_share_physical_slot_one(self):
        self.state['SINGLE_CAMERA_MODE'] = True
        first = next(self.state['gen_frames'](0))
        second = next(self.state['gen_frames'](1))
        self.assertEqual(first, second)
        self.assertEqual(self.monitor.record_stage.call_count, 1)
        self.assertEqual(self.cache.snapshot()['streams']['camera1.processed']['encodes'], 1)


class CameraPosePipelineTests(unittest.TestCase):
    def test_recording_boundary_saves_pending_result_before_turning_storage_off(self):
        tree = ast.parse(Path(__file__).with_name('main.py').read_text(encoding='utf-8'))
        names = {'finalize_camera_pose_recording', '_consume_camera_pose_outputs',
                 'store_sagittal_sample'}
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual(len(functions), 3)
        sync = DualCameraSynchronizer(clock=lambda: 0.0)
        sample = dict(left_knee=14., right_knee=15., left_hip=5., right_hip=6.,
                      left_ankle=80., right_ankle=81., pelvic_tilt=1., trunk_tilt=2.,
                      poseQuality={'frameReliable': True})
        sync.submit('sagittal', dict(captured_ns=1_000_000_000,
                                    captured_at=1000.1, sample=sample))
        state = dict(camera_synchronizer=sync, camera_pose_output_lock=threading.Lock(),
                     SINGLE_CAMERA_MODE=False, is_recording=True,
                     record_start_time=1000., record_duration=300.,
                     gait_store_lock=threading.Lock(), live_gait_lock=threading.Lock(),
                     live_gait_samples=deque(),
                     sagittal_fallback_sample=sagittal_fallback_sample,
                     assess_temporal_consistency=assess_temporal_consistency)
        for key in ('timestamps', 'left_knee', 'right_knee', 'left_hip', 'right_hip',
                    'left_ankle', 'right_ankle', 'pelvic_tilt', 'trunk_tilt',
                    'frontal_trunk_lean', 'pose_quality', 'foot_tracking'):
            state[f'recorded_{key}'] = []
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), state)
        state['finalize_camera_pose_recording']()
        self.assertFalse(state['is_recording'])
        self.assertAlmostEqual(state['recorded_timestamps'][0], .1)
        self.assertEqual(state['recorded_left_knee'], [14.])
        self.assertEqual(sync.drain(force=True), [])
        self.assertFalse(state['recorded_pose_quality'][0]['frameReliable'])
        state['finalize_camera_pose_recording']()
        self.assertEqual(len(state['recorded_timestamps']), 1)

    def test_both_live_workers_measure_whole_pipeline_and_keep_raw_pixels(self):
        tree = ast.parse(Path(__file__).with_name('main.py').read_text(encoding='utf-8'))
        for slot in (0, 1):
            with self.subTest(slot=slot):
                now = [1.0]

                def tick():
                    now[0] += .01
                    return now[0]

                monitor = PerformanceMonitor(clock=lambda: now[0], memory_reader=lambda: 0)
                detector = SimpleNamespace(closed=False, input_writeable=None)

                def process(rgb):
                    detector.input_writeable = rgb.flags.writeable
                    return SimpleNamespace(pose_landmarks=None)

                detector.process = process
                detector.close = lambda: setattr(detector, 'closed', True)
                source = np.full((48, 64, 3), 37, dtype=np.uint8)
                synchronizer = DualCameraSynchronizer(clock=lambda: now[0])
                synchronizer.submit('sagittal', {'captured_ns': 1_000_000_000, 'sample': {}})
                now[0] += 1.0
                drained = []

                def drain():
                    drained.extend(synchronizer.drain())
                state = dict(
                    cv2=cv2, time=SimpleNamespace(perf_counter=tick, time=lambda: 1000),
                    performance_monitor=monitor, PoseIdentityLock=PoseIdentityLock,
                    create_pose_detector=lambda: detector,
                    prepare_pose_frame=lambda frame, _: frame,
                    flush_camera_pose_results=drain,
                    running=True, is_recording=False, camera_roles_swapped=False,
                    camera_roles_lock=threading.Lock(),
                    camera_stop_event=SimpleNamespace(is_set=lambda: False, wait=lambda _: True),
                    CAMERA_FRAME_DELAY_SECONDS=.005, POSE_TARGET_FPS=12,
                    **{f'frame_lock_{slot}': threading.Lock(),
                       f'latest_capture_sequence_{slot}': 1,
                       f'latest_raw_frame_{slot}': source,
                       f'latest_frame_{slot}_at': 1000,
                       f'latest_frame_{slot}_ns': 1_000_000_000,
                       f'pose_inference_times_{slot}': [],
                       f'camera_health_{slot}': {},
                       f'pose_times_{slot}': [], f'pose_reliable_times_{slot}': []},
                )
                name = f'camera_loop_{slot}'
                function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
                exec(compile(ast.Module(body=[function], type_ignores=[]), 'main.py', 'exec'), state)
                state[name]()
                stages = monitor.snapshot(sample_resources=False)['stages']
                self.assertIn(f'camera.{slot}.pose_pipeline', stages)
                self.assertIn(f'camera.{slot}.pose_postprocess', stages)
                self.assertGreater(
                    stages[f'camera.{slot}.pose_pipeline']['durationMs']['median'],
                    stages[f'camera.{slot}.pose_inference']['durationMs']['median'],
                )
                self.assertFalse(detector.input_writeable)
                self.assertEqual([item['kind'] for item in drained], ['fallback'])
                self.assertTrue(detector.closed)
                np.testing.assert_array_equal(source, np.full((48, 64, 3), 37, dtype=np.uint8))
                self.assertIsNot(state[f'latest_frame_{slot}'], source)
                self.assertEqual(state[f'latest_processed_frame_{slot}_ns'], 1_000_000_000)


if __name__ == '__main__':
    unittest.main()
