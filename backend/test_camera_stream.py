"""Exercise the real stream generator without starting database/hardware services."""

import ast
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from camera_preview import PreviewJpegCache


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


if __name__ == '__main__':
    unittest.main()
