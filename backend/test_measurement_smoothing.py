import unittest
from measurement_smoothing import smooth_camera_segments, FsrMedianFilter


class SmoothingTests(unittest.TestCase):
    def test_camera_preserves_missing_and_raw(self):
        raw = [2, 2, 90, 2, 2, None, 10, 11]
        self.assertEqual(smooth_camera_segments(raw), [2, 2, 2, 2, 2, None, 10, 11])
        self.assertEqual(raw[2], 90)

    def test_fsr_separate_feet_and_gap_reset(self):
        f = FsrMedianFilter()
        f.apply('left', [[10]], 1)
        f.apply('left', [[10]], 1.03)
        self.assertEqual(f.apply('left', [[90]], 1.06), [[10]])
        self.assertEqual(f.apply('right', [[80]], 1.07), [[80]])
        self.assertEqual(f.apply('left', [[30]], 2), [[30]])


if __name__ == '__main__':
    unittest.main()
