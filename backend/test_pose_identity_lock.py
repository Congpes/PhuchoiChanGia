import unittest

from pose_identity_lock import PoseIdentityLock


class _Point:
    def __init__(self, x=0.5, y=0.5, z=0.0, visibility=1.0):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility


class _Landmarks:
    def __init__(self, left_x, right_x, visibility=1.0):
        self.landmark = [_Point() for _ in range(33)]
        for index in (23, 25, 27, 29, 31):
            self.landmark[index] = _Point(left_x, 0.5, visibility=visibility)
        for index in (24, 26, 28, 30, 32):
            self.landmark[index] = _Point(right_x, 0.5, visibility=visibility)


class PoseIdentityLockTests(unittest.TestCase):
    def test_corrects_transient_left_right_exchange(self):
        lock = PoseIdentityLock()
        lock.update(_Landmarks(0.20, 0.80), 10.00)
        lock.update(_Landmarks(0.23, 0.77), 10.03)
        swapped_raw = lock.update(_Landmarks(0.74, 0.26), 10.06)
        self.assertAlmostEqual(swapped_raw.landmark[23].x, 0.26)
        self.assertAlmostEqual(swapped_raw.landmark[24].x, 0.74)

    def test_low_confidence_jump_uses_predicted_track(self):
        lock = PoseIdentityLock()
        lock.update(_Landmarks(0.20, 0.80), 10.00)
        lock.update(_Landmarks(0.22, 0.78), 10.03)
        unreliable = lock.update(_Landmarks(0.90, 0.10, visibility=0.10), 10.06)
        self.assertLess(unreliable.landmark[23].x, 0.35)
        self.assertGreater(unreliable.landmark[24].x, 0.65)

    def test_resets_after_camera_gap(self):
        lock = PoseIdentityLock(max_gap_seconds=0.5)
        lock.update(_Landmarks(0.20, 0.80), 10.00)
        after_gap = lock.update(_Landmarks(0.70, 0.30), 11.00)
        self.assertAlmostEqual(after_gap.landmark[23].x, 0.70)


if __name__ == "__main__":
    unittest.main()
