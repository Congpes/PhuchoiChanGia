import unittest
import sys
from pathlib import Path

import fsr_force
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import FSR_Transmitter_2 as transmitter


class CellCalibrationTests(unittest.TestCase):
    def test_transmitter_corrects_only_right_newton_not_adc_or_left(self):
        raw = [[200.0] * 4 for _ in range(12)]
        profile = {'side': 'right', 'cells': [[{'baseline_n': 1, 'gain': 2}] * 4 for _ in range(12)]}
        legacy = transmitter.matrix_for_unit(raw, 'newton')
        corrected = transmitter.matrix_for_unit(raw, 'newton', side='right', profile=profile)
        self.assertAlmostEqual(corrected[0][0], (legacy[0][0] - 1) * 2)
        self.assertEqual(transmitter.matrix_for_unit(raw, 'raw_adc', side='right', profile=profile), raw)
        self.assertEqual(transmitter.matrix_for_unit(raw, 'newton', side='left', profile=profile), legacy)

    def test_baseline_is_subtracted_before_gain_and_negative_is_clamped(self):
        self.assertTrue(hasattr(fsr_force, 'apply_cell_calibration'))
        profile = {'side': 'right', 'cells': [[{'baseline_n': 1, 'gain': 2}, None]]}
        self.assertEqual(fsr_force.apply_cell_calibration([[8, 3]], 'right', profile), [[14, 3]])
        self.assertEqual(fsr_force.apply_cell_calibration([[0.5, 3]], 'right', profile), [[0, 3]])

    def test_left_and_disabled_profile_are_unchanged(self):
        self.assertTrue(hasattr(fsr_force, 'apply_cell_calibration'))
        profile = {'side': 'right', 'cells': [[{'baseline_n': 1, 'gain': 2}]]}
        self.assertEqual(fsr_force.apply_cell_calibration([[8]], 'left', profile), [[8]])
        self.assertEqual(fsr_force.apply_cell_calibration([[8]], 'right', None), [[8]])

    def test_invalid_profile_does_not_silently_produce_force(self):
        self.assertTrue(hasattr(fsr_force, 'apply_cell_calibration'))
        for cell in ({'baseline_n': 1, 'gain': float('nan')}, {'baseline_n': 1, 'gain': -2}):
            with self.assertRaises(ValueError):
                fsr_force.apply_cell_calibration([[8]], 'right', {'side': 'right', 'cells': [[cell]]})
        with self.assertRaises(ValueError):
            fsr_force.apply_cell_calibration([[8]], 'right', {'side': 'right', 'cells': []})


if __name__ == '__main__':
    unittest.main()
