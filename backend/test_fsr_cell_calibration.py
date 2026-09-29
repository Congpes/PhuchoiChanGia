import unittest
import sys
import io
import json
import threading
import socket
from unittest.mock import patch
from pathlib import Path

import fsr_force
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import FSR_Transmitter_2 as transmitter


class ShoeZeroTests(unittest.TestCase):
    def capture(self, zero, sides=('left', 'right'), base=5.0):
        for side in sides:
            zero.process(side, [[base]], 0)
        zero.start(sides, 0)
        for i in range(1, 61):
            for side in sides:
                zero.process(side, [[base + (0.01 if i % 2 else -0.01)]], i/20)
        zero.finish(3.0)

    def test_both_zero_filters_small_noise_keeps_increment_and_cancel_restores(self):
        zero = transmitter.ShoeZero()
        self.capture(zero)
        self.assertEqual(zero.state()[0], ('left', 'right'))
        for side in ('left', 'right'):
            result, meta = zero.process(side, [[5.01]], 3.1)
            self.assertEqual(result, [[0]])
            self.assertTrue(meta['zero_applied'])
            self.assertEqual(meta['zero_baseline_n'], [[5]])
            self.assertAlmostEqual(zero.process(side, [[8.3]], 3.2)[0][0][0], 3.3)
        zero.reset()
        self.assertEqual(zero.process('right', [[8.3]], 4)[0], [[8.3]])
        self.assertFalse(zero.process('right', [[8.3]], 4)[1]['zero_applied'])

    def test_single_side_does_not_change_other_and_never_rezeros_while_loaded(self):
        zero = transmitter.ShoeZero()
        self.capture(zero, ('right',))
        self.assertEqual(zero.process('left', [[9]], 4)[0], [[9]])
        for i in range(10):
            self.assertEqual(zero.process('right', [[15]], 4+i)[0], [[10]])

    def test_missing_stale_or_unstable_capture_does_not_partially_commit(self):
        zero = transmitter.ShoeZero()
        zero.process('right', [[5]], 0)
        with self.assertRaises(ValueError):
            zero.start(('left', 'right'), 0)
        with self.assertRaises(ValueError):
            zero.start(('right',), 2)
        zero.process('left', [[5]], 2)
        zero.process('right', [[5]], 2)
        zero.start(('left', 'right'), 2)
        for i in range(1, 61):
            zero.process('left', [[5]], 2+i/20)
            zero.process('right', [[5 if i<30 else 10]], 2+i/20)
        with self.assertRaises(ValueError):
            zero.finish(5)
        self.assertEqual(zero.state(), ((), False))

    def test_capture_timeout_sparse_samples_and_shape_change_are_rejected(self):
        for samples in ([(.1, 5), (3, 5)], [(i/20,5) for i in range(1,30)]):
            zero = transmitter.ShoeZero()
            zero.process('right', [[5]], 0)
            zero.start(('right',), 0)
            for stamp, val in samples:
                zero.process('right', [[val]], stamp)
            with self.assertRaises(ValueError):
                zero.finish(3)
            self.assertEqual(zero.state(), ((), False))
        zero = transmitter.ShoeZero()
        self.capture(zero, ('right',))
        with self.assertRaises(ValueError):
            zero.process('right', [[5, 5]], 4)

    def test_nonfinite_input_never_enters_zero_capture(self):
        zero = transmitter.ShoeZero()
        for value in (float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                zero.process('right', [[value]], 0)

    def test_live_conversion_uses_zero_only_for_newton(self):
        app = transmitter.FSRTransmitterApp.__new__(transmitter.FSRTransmitterApp)
        app.shoe_zero = transmitter.ShoeZero()
        raw = [[200.0]*4 for _ in range(12)]
        baseline = transmitter.matrix_for_unit(raw, 'newton', 'right')
        app._convert_live_matrix(raw, 'newton', 'right', 0)
        app.shoe_zero.start(('right',), 0)
        for i in range(1, 61):
            app._convert_live_matrix(raw, 'newton', 'right', i/20)
        app.shoe_zero.finish(3)
        output, metadata = app._convert_live_matrix(raw, 'newton', 'right', 3.1)
        self.assertEqual(output, [[0.0]*4 for _ in range(12)])
        self.assertEqual(metadata['zero_baseline_n'], baseline)
        output, metadata = app._convert_live_matrix(raw, 'raw_adc', 'right', 3.2)
        self.assertEqual(output, raw)
        self.assertFalse(metadata['zero_applied'])

    def test_live_raw_nonfinite_is_rejected_before_conversion(self):
        app = transmitter.FSRTransmitterApp.__new__(transmitter.FSRTransmitterApp)
        app.shoe_zero = transmitter.ShoeZero()
        raw = [[200.0]*4 for _ in range(12)]
        raw[0][0] = float('nan')
        with self.assertRaises(ValueError):
            app._convert_live_matrix(raw, 'newton', 'right', 0)

    def test_invalid_raw_does_not_poison_ema_history(self):
        app = transmitter.FSRTransmitterApp.__new__(transmitter.FSRTransmitterApp)
        app.smoothed_matrices = {}
        app.ema_alpha_value = .2
        with self.assertRaises(ValueError):
            app._apply_ema_filter(1, [[float('nan')]])
        self.assertEqual(app.smoothed_matrices, {})
        self.assertEqual(app._apply_ema_filter(1, [[200]]), [[200]])

    def test_queued_old_zero_frame_is_not_painted_after_cancel(self):
        app = transmitter.FSRTransmitterApp.__new__(transmitter.FSRTransmitterApp)
        app.shoe_zero = transmitter.ShoeZero()
        app.running = True
        app._selected_unit = 'newton'
        self.capture(app.shoe_zero, ('right',))
        _, metadata = app.shoe_zero.process('right', [[5]], 3.1)
        app.shoe_zero.reset()
        # Intentionally no canvases: outdated callback must return before drawing.
        app._update_after_frame(1, 'right', [[0]], 'newton', 'old', metadata)

    def test_udp_transmits_same_zero_values_and_metadata_as_log(self):
        app = transmitter.FSRTransmitterApp.__new__(transmitter.FSRTransmitterApp)
        app.send_lock = threading.Lock()
        app.sequence = 0
        app.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            receiver.bind(('127.0.0.1', 0))
            receiver.settimeout(1)
            meta = {'zero_applied': True, 'zero_revision': 2,
                    'zero_baseline_n': [[5]], 'zero_noise_n': [[.02]]}
            app._send_matrix_udp([[3]], '127.0.0.1', receiver.getsockname()[1],
                                 ('test-device', 'right', 'newton'), meta)
            record = json.loads(receiver.recv(60000))
            self.assertEqual(record['values'], [[3]])
            self.assertEqual(record['unit'], 'newton')
            for key, value in meta.items():
                self.assertEqual(record[key], value)
        finally:
            receiver.close()
            app.socket.close()

    def test_failed_retake_preserves_old_zero_until_explicit_cancel(self):
        zero = transmitter.ShoeZero()
        self.capture(zero, ('right',))
        zero.process('right', [[5]], 4)
        zero.start(('right',), 4)
        with self.assertRaises(ValueError):
            zero.finish(7)
        self.assertEqual(zero.process('right', [[8]], 7.1)[0], [[3]])
        zero.reset()
        self.assertEqual(zero.process('right', [[8]], 7.2)[0], [[8]])

    def test_log_keeps_original_adc_and_exact_zero_snapshot(self):
        app = transmitter.FSRTransmitterApp.__new__(transmitter.FSRTransmitterApp)
        app.log_lock = threading.Lock()
        app.log_handle = io.StringIO()
        app.log_started_at = 0
        app.log_sample_count = 0
        metadata = {'zero_applied': True, 'zero_baseline_n': [[5]],
                    'zero_noise_n': [[.02]], 'zero_revision': 1}
        app._write_log_sample('right', [[200]], [[201]], [[3]], 'newton', 4, metadata)
        record = json.loads(app.log_handle.getvalue())
        self.assertEqual(record['raw_values'], [[200]])
        self.assertEqual(record['filtered_raw_values'], [[201]])
        self.assertEqual(record['values'], [[3]])
        for key, value in metadata.items():
            self.assertEqual(record[key], value)

    def test_zero_ui_cancel_and_single_foot_action(self):
        # Real Tk controls and callbacks, no serial port opened.
        root = transmitter.tk.Tk()
        root.withdraw()
        app = transmitter.FSRTransmitterApp(root)
        try:
            self.assertEqual(app.zero_button_text.get(), 'Zero hết')
            app.running = True
            app.shoe_zero.process('right', [[5]], 0)
            with patch.object(transmitter.messagebox, 'askokcancel', return_value=True), \
                    patch.object(transmitter.time, 'monotonic', return_value=0):
                app.zero_right_button.invoke()
            self.assertTrue(app.shoe_zero.state()[1])
            self.assertEqual(app.zero_button_text.get(), 'Huỷ zero')
            self.assertIn('disabled', app.zero_left_button.state())
            app._toggle_zero()
            self.assertEqual(app.shoe_zero.state(), ((), False))
            self.assertEqual(app.zero_button_text.get(), 'Zero hết')
            self.assertNotIn('disabled', app.zero_left_button.state())
            self.capture(app.shoe_zero, ('right',))
            app._refresh_zero_controls()
            self.assertEqual(app.zero_button_text.get(), 'Huỷ zero')
            app._toggle_zero()
            self.assertEqual(app.shoe_zero.process('right', [[8]], 4)[0], [[8]])
        finally:
            app.close()


class CellCalibrationTests(unittest.TestCase):
    def test_right_first_cell_matches_both_loading_holds_from_check_log(self):
        raw = [[250.0]*4 for _ in range(12)]
        # check.jsonl: 10-13s large weight; 19-23s stacked weight.
        # Supersedes the earlier one-load refit, not independent validation.
        for adc, expected in ((241.66673991272825, 14.3961622),
                              (200.70540231173453, 17.664718645)):
            raw[0][0] = adc
            value = transmitter.matrix_for_unit(raw, 'newton', 'right')[0][0]
            self.assertAlmostEqual(value, expected, delta=0.005)

    def test_piecewise_calibration_interpolates_without_snapping_or_saturation(self):
        profile = {'side': 'right', 'cells': [[{
            'baseline_n': 1, 'gain': 2,
            'points_n': [[0, 0], [10, 14], [12, 17]],
        }]]}
        # Input is legacy N, anchors are after baseline subtraction.
        # Above measured range retain old gain, continuously from last anchor.
        for value, expected in ((0, 0), (1, 0), (6, 7), (11, 14),
                                (12, 15.5), (13, 17), (14, 19)):
            self.assertEqual(fsr_force.apply_cell_calibration(
                [[value]], 'right', profile), [[expected]])
        self.assertEqual(profile['cells'][0][0]['points_n'], [[0, 0], [10, 14], [12, 17]])

    def test_invalid_piecewise_anchors_are_rejected(self):
        for points in ([], [[0, 0]], [[0, 0], [10, 14], [10, 17]],
                       [[0, 0], [10, 14], [12, 13]],
                       [[1, 0], [10, 14], [12, 17]],
                       [[0, 1], [10, 14], [12, 17]],
                       [[0, 0], [10, 14], [float('nan'), 17]],
                       [[0, 0], [10, 14], [12, float('inf')]],
                       [[0, 0], [10], [12, 17]]):
            with self.subTest(points=points), self.assertRaises(ValueError):
                fsr_force.apply_cell_calibration([[8]], 'right', {'side': 'right',
                    'cells': [[{'baseline_n': 1, 'gain': 2, 'points_n': points}]]})

    def test_eighteen_cells_fit_two_loading_levels_and_check_return_hold(self):
        # Fixed filtered ADC medians from check.jsonl, not generated by mapper.
        # Return hold is same-cycle screening only, NOT independent validation.
        fixtures = [
            (1, 1, 241.66673991272825, 200.70540231173453, 238.8253752308106),
            (1, 2, 204.69115806886376, 164.0766075719103, 206.94033587519644),
            (1, 3, 251.66425196045424, 205.02463058274344, 236.62447019785657),
            (1, 4, 231.38700187754435, 170.45694438322425, 224.61126804223017),
            (2, 2, 141.9524440897684, 120.38228778954209, 148.05794873978147),
            (2, 4, 256.0426673398525, 197.0163174193509, 248.24564120064733),
            (3, 1, 192.07577080734808, 154.5605059695559, 186.95014760071),
            (3, 2, 180.7836816240453, 144.4944253850107, 173.27382308515274),
            (3, 3, 150.68810764639946, 127.36970548038326, 144.0655946803085),
            (3, 4, 177.07924065933742, 148.2641620819553, 170.5951947793681),
            (4, 1, 279.00716636584156, 204.3858055454707, 254.51058860986922),
            (4, 2, 219.0499820227559, 165.30747974329773, 213.64522966850998),
            (4, 3, 134.7766054589539, 121.9488112973371, 133.1015462496227),
            (4, 4, 192.40418785377602, 146.5007632288806, 182.49418015721307),
            (5, 1, 174.7503620196524, 138.53212560536284, 165.41456500366283),
            (5, 2, 272.4313928781674, 203.5635463682108, 257.6830392641124),
            (5, 3, 151.9493718566201, 125.94411893981406, 155.89055255398455),
            (6, 2, 165.62085328842016, 140.073247720324, 169.3645568134934),
        ]
        for row, col, large, stacked, returned in fixtures:
            with self.subTest(row=row, col=col):
                raw = [[5000.0]*4 for _ in range(12)]
                for adc, expected in ((large, 14.3961622), (stacked, 17.664718645)):
                    raw[row-1][col-1] = adc
                    result = transmitter.matrix_for_unit(raw, 'newton', 'right')
                    self.assertAlmostEqual(result[row-1][col-1], expected, delta=0.005)
                raw[row-1][col-1] = returned
                value = transmitter.matrix_for_unit(raw, 'newton', 'right')[row-1][col-1]
                self.assertAlmostEqual(value, 14.3961622, delta=1.0)
                self.assertEqual(transmitter.matrix_for_unit(raw, 'raw_adc', 'right'), raw)

    def test_retest_cells_and_left_retain_previous_conversion(self):
        raw = [[200.0]*4 for _ in range(12)]
        right = transmitter.matrix_for_unit(raw, 'newton', 'right')
        # Outputs recorded from v3 before adding three-point anchors.
        for row, col, expected in ((2, 1, 17.70030133484575),
                                   (2, 3, 14.665340870836921),
                                   (5, 4, 11.663736882609854),
                                   (6, 1, 13.927466247526295)):
            self.assertAlmostEqual(right[row-1][col-1], expected)
        self.assertAlmostEqual(transmitter.matrix_for_unit(raw, 'newton', 'left')[0][0],
                               24.313644546868854)

    def test_builtin_profiles_cover_both_feet_and_can_be_disabled(self):
        self.assertTrue(hasattr(transmitter, 'BUILTIN_CELL_CALIBRATIONS'))
        profiles = transmitter.BUILTIN_CELL_CALIBRATIONS
        for side in ('left', 'right'):
            self.assertEqual(len(profiles[side]['cells']), 12)
            self.assertTrue(all(len(row) == 4 and all(cell is not None for cell in row)
                                for row in profiles[side]['cells']))
        self.assertIs(transmitter.CELL_CALIBRATIONS, profiles)
        old = transmitter.CELL_CALIBRATIONS
        try:
            transmitter.CELL_CALIBRATIONS = {}
            raw = [[200.0]*4 for _ in range(12)]
            self.assertEqual(transmitter.matrix_for_unit(raw, 'newton', 'left'),
                             transmitter.matrix_for_unit(raw, 'newton'))
        finally:
            transmitter.CELL_CALIBRATIONS = old

    def test_active_profiles_are_selected_by_side_without_cross_application(self):
        self.assertTrue(hasattr(transmitter, 'CELL_CALIBRATIONS'))
        old = transmitter.CELL_CALIBRATIONS
        raw = [[200.0] * 4 for _ in range(12)]
        legacy = transmitter.matrix_for_unit(raw, 'newton')[0][0]
        try:
            transmitter.CELL_CALIBRATIONS = {
                'left': {'side': 'left', 'cells': [[{'baseline_n': 1, 'gain': 2}] * 4 for _ in range(12)]},
                'right': {'side': 'right', 'cells': [[{'baseline_n': 2, 'gain': 3}] * 4 for _ in range(12)]},
            }
            self.assertAlmostEqual(transmitter.matrix_for_unit(raw, 'newton', 'left')[0][0], (legacy-1)*2)
            self.assertAlmostEqual(transmitter.matrix_for_unit(raw, 'newton', 'right')[0][0], (legacy-2)*3)
            self.assertEqual(transmitter.matrix_for_unit(raw, 'raw_adc', 'left'), raw)
            self.assertEqual(transmitter.matrix_for_unit(raw, 'newton', None)[0][0], legacy)
        finally:
            transmitter.CELL_CALIBRATIONS = old

    def test_log_provenance_uses_matching_side_and_only_newton(self):
        self.assertTrue(hasattr(transmitter, 'calibration_metadata'))
        old = transmitter.CELL_CALIBRATIONS
        try:
            transmitter.CELL_CALIBRATIONS = {
                'left': {'id': 'left-test', 'status': 'trial'},
                'right': {'id': 'right-test', 'status': 'trial'},
            }
            self.assertEqual(transmitter.calibration_metadata('left', 'newton'),
                             {'calibration_id': 'left-test', 'calibration_status': 'trial'})
            self.assertEqual(transmitter.calibration_metadata('right', 'newton')['calibration_id'], 'right-test')
            self.assertIsNone(transmitter.calibration_metadata('left', 'raw_adc')['calibration_id'])
        finally:
            transmitter.CELL_CALIBRATIONS = old

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
