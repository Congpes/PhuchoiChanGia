import unittest

from fsr_force import adc_to_newton, gram_to_newton, matrix_to_newton, region_totals


class FsrForceTests(unittest.TestCase):
    def test_unloaded_adc_returns_zero_newton(self):
        self.assertEqual(adc_to_newton(4950.0), 0.0)

    def test_gram_to_newton_uses_standard_gravity(self):
        self.assertAlmostEqual(gram_to_newton(1000.0), 9.80665, places=5)

    def test_packet_units_are_interpreted_without_inverse_adc(self):
        raw_matrix, raw_unit, _ = matrix_to_newton([[4950.0]], "raw_adc")
        gram_matrix, gram_unit, _ = matrix_to_newton([[1000.0]], "gram")
        newton_matrix, newton_unit, _ = matrix_to_newton([[42.0]], "newton")

        self.assertEqual(raw_matrix, [[0.0]])
        self.assertEqual(raw_unit, "N_estimated")
        self.assertAlmostEqual(gram_matrix[0][0], 9.80665, places=5)
        self.assertEqual(gram_unit, "N_estimated")
        self.assertEqual(newton_matrix, [[42.0]])
        self.assertEqual(newton_unit, "N")

    def test_region_totals_follow_12_by_4_layout(self):
        matrix = [[1.0] * 4 for _ in range(12)]
        totals = region_totals(matrix)
        self.assertEqual(totals["forefoot"], 16.0)
        self.assertEqual(totals["midfoot"], 20.0)
        self.assertEqual(totals["heel"], 12.0)
        self.assertEqual(totals["total"], 48.0)


if __name__ == "__main__":
    unittest.main()
