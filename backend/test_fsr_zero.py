import copy
import unittest

from fsr_zero import merge_zero_round, summarize_zero_round
from FSR_Transmitter_3 import ShoeZero


def matrix(value=0.0):
    return [[float(value) for _ in range(4)] for _ in range(12)]


class ZeroRoundStatisticsTests(unittest.TestCase):
    def test_nonzero_stable_round_uses_per_cell_median(self):
        samples = [matrix(5.0), matrix(5.4), matrix(4.8)]

        result = summarize_zero_round(samples)

        self.assertTrue(result["accepted"])
        self.assertAlmostEqual(result["matrix"][0][0], 5.0)

    def test_single_frame_spike_does_not_become_round_value(self):
        samples = [matrix(5.0), matrix(50.0), matrix(5.2), matrix(4.9), matrix(5.1)]

        result = summarize_zero_round(samples)

        self.assertTrue(result["accepted"])
        self.assertLess(result["matrix"][0][0], 6.0)

    def test_large_drift_rejects_round(self):
        samples = [matrix(2.0), matrix(2.1), matrix(7.0), matrix(7.1)]

        result = summarize_zero_round(samples)

        self.assertFalse(result["accepted"])
        self.assertIn("drift", result["reason"])

    def test_incremental_merge_keeps_history_and_uses_max_round_baseline(self):
        first = matrix(5.0)
        first[0][1] = 6.0
        second = matrix(6.0)
        second[0][1] = 3.0
        noise = matrix(0.2)

        result = merge_zero_round([], first, noise)
        result = merge_zero_round(result["history"], second, noise, adjacency=[((0, 0), (0, 1))])

        self.assertEqual(result["round_count"], 2)
        self.assertEqual(len(result["history"]), 2)
        self.assertAlmostEqual(result["baseline"][0][0], 6.0)
        self.assertAlmostEqual(result["baseline"][0][1], 6.0)
        self.assertEqual(result["median_baseline"][0][0], 5.5)
        self.assertEqual(result["median_baseline"][0][1], 4.5)
        self.assertTrue(result["redistribution_warnings"])

    def test_merge_does_not_mutate_existing_history(self):
        original = matrix(5.0)
        history = [{"matrix": copy.deepcopy(original), "noise": matrix(0.1)}]

        merge_zero_round(history, matrix(7.0), matrix(0.2))

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["matrix"], original)


class ShoeZeroStateTests(unittest.TestCase):
    @staticmethod
    def _matrix(value):
        return [[float(value) for _ in range(4)] for _ in range(12)]

    def _record(self, zero, value, start, side="left", unstable=False):
        zero.process(side, self._matrix(value), start)
        zero.start((side,), start)
        for index in range(12):
            timestamp = start + 0.1 * (index + 1)
            frame_value = value + (index * 2 if unstable else 0.0)
            zero.process(side, self._matrix(frame_value), timestamp)
        return zero.record_round(start + 1.3)

    def test_first_valid_click_creates_nonzero_profile(self):
        zero = ShoeZero()

        progress = self._record(zero, 5.0, 0.0)

        self.assertEqual(progress["left"], 1)
        self.assertAlmostEqual(zero.profiles["left"]["baseline"][0][0], 5.0)

    def test_second_click_recomputes_max_and_keeps_history(self):
        zero = ShoeZero()

        self._record(zero, 5.0, 0.0)
        self._record(zero, 6.0, 2.0)

        self.assertEqual(zero.progress()["left"], 2)
        self.assertAlmostEqual(zero.profiles["left"]["baseline"][0][0], 6.0)
        self.assertAlmostEqual(zero.profiles["left"]["median_baseline"][0][0], 5.5)

    def test_unstable_click_does_not_change_profile_or_count(self):
        zero = ShoeZero()

        self._record(zero, 5.0, 0.0)
        before = copy.deepcopy(zero.profiles["left"])
        result = self._record(zero, 6.0, 2.0, unstable=True)

        self.assertFalse(result["accepted"])
        self.assertEqual(result["left"], 1)
        self.assertEqual(zero.progress()["left"], 1)
        self.assertEqual(zero.profiles["left"], before)

    def test_clear_all_is_the_explicit_profile_reset(self):
        zero = ShoeZero()

        self._record(zero, 5.0, 0.0)
        zero.cancel_pending()
        self.assertIn("left", zero.profiles)
        zero.clear_all()

        self.assertEqual(zero.progress()["left"], 0)
        self.assertNotIn("left", zero.profiles)


if __name__ == "__main__":
    unittest.main()
