import copy
import unittest

from fsr_zero import merge_zero_round, summarize_zero_round


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

    def test_incremental_merge_keeps_history_and_uses_median(self):
        first = matrix(5.0)
        first[0][1] = 6.0
        second = matrix(6.0)
        second[0][1] = 3.0
        noise = matrix(0.2)

        result = merge_zero_round([], first, noise)
        result = merge_zero_round(result["history"], second, noise, adjacency=[((0, 0), (0, 1))])

        self.assertEqual(result["round_count"], 2)
        self.assertEqual(len(result["history"]), 2)
        self.assertAlmostEqual(result["baseline"][0][0], 5.5)
        self.assertAlmostEqual(result["baseline"][0][1], 4.5)
        self.assertNotEqual(result["baseline"][0][0] + result["baseline"][0][1], 12.0)
        self.assertTrue(result["redistribution_warnings"])

    def test_merge_does_not_mutate_existing_history(self):
        original = matrix(5.0)
        history = [{"matrix": copy.deepcopy(original), "noise": matrix(0.1)}]

        merge_zero_round(history, matrix(7.0), matrix(0.2))

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["matrix"], original)


if __name__ == "__main__":
    unittest.main()
