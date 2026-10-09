import unittest

from fsi_phase_metrics import (
    FOREFOOT_CELL_IDS,
    HEEL_CELL_IDS,
    STANCE_CELL_IDS,
    force_symmetry_index,
    compare_phase_pair,
    detect_contact_intervals,
    FsiSessionAnalyzer,
    physical_cell_to_matrix,
    phase_fsi,
    phase_summary,
    phase_windows,
    roi_series,
    validate_roi,
)


class FsiMetricTests(unittest.TestCase):
    def test_transmitter_v3_imports_without_creating_a_window(self):
        import FSR_Transmitter_3 as transmitter
        self.assertEqual(transmitter.FOREFOOT_CELL_IDS, FOREFOOT_CELL_IDS)
        self.assertEqual(transmitter.HEEL_CELL_IDS, HEEL_CELL_IDS)
        self.assertTrue(hasattr(transmitter, "FSRTransmitterApp"))

    def test_force_symmetry_index(self):
        self.assertEqual(force_symmetry_index(420, 420), 100.0)
        self.assertEqual(force_symmetry_index(300, 400), 75.0)
        self.assertEqual(force_symmetry_index(0, 400), 0.0)
        self.assertIsNone(force_symmetry_index(0, 0))
        self.assertIsNone(force_symmetry_index(-1, 2))
        self.assertIsNone(force_symmetry_index(float("nan"), 2))

    def test_physical_roi_mapping(self):
        self.assertEqual(len(FOREFOOT_CELL_IDS), 9)
        self.assertEqual(len(HEEL_CELL_IDS), 4)
        self.assertEqual(len(STANCE_CELL_IDS), 13)
        self.assertEqual(physical_cell_to_matrix(1), (0, 3))
        self.assertEqual(physical_cell_to_matrix(48), (11, 0))
        roi = {
            "heel": [physical_cell_to_matrix(cell) for cell in HEEL_CELL_IDS],
            "forefoot": [physical_cell_to_matrix(cell) for cell in FOREFOOT_CELL_IDS],
            "stance_sampled": [physical_cell_to_matrix(cell) for cell in STANCE_CELL_IDS],
        }
        validate_roi(roi, exclusive=False)
        self.assertEqual(set(roi["stance_sampled"]), set(roi["heel"]) | set(roi["forefoot"]))

    def test_roi_series_sums_each_sample(self):
        cells = [physical_cell_to_matrix(1), physical_cell_to_matrix(2)]
        samples = [
            {"timestamp": 0.0, "matrix": [[0.0] * 4 for _ in range(12)]},
            {"timestamp": 0.1, "matrix": [[0.0] * 4 for _ in range(12)]},
        ]
        samples[0]["matrix"][0][3] = 10.0
        samples[0]["matrix"][0][2] = 5.0
        samples[1]["matrix"][0][3] = 20.0
        self.assertEqual(roi_series(samples, cells), [15.0, 20.0])

    def test_phase_summary_integrates_same_timestamp_group(self):
        cells = [physical_cell_to_matrix(cell) for cell in STANCE_CELL_IDS]
        samples = []
        for timestamp, value in ((0.0, 10.0), (0.5, 20.0), (1.0, 10.0)):
            matrix = [[0.0] * 4 for _ in range(12)]
            for row, col in cells:
                matrix[row][col] = value / len(cells)
            samples.append({"timestamp": timestamp, "matrix": matrix, "valid": True})
        summary = phase_summary(samples, 0.0, 1.0, cells)
        self.assertAlmostEqual(summary["mean"], 13.3333, places=3)
        self.assertAlmostEqual(summary["peak"], 20.0, places=3)
        self.assertAlmostEqual(summary["impulse"], 15.0, places=3)
        self.assertEqual(summary["valid_sample_count"], 3)

    def test_missing_sample_is_invalid(self):
        cells = [physical_cell_to_matrix(42)]
        samples = [
            {"timestamp": 0.0, "matrix": [[0.0] * 4 for _ in range(12)], "valid": False},
        ]
        summary = phase_summary(samples, 0.0, 1.0, cells)
        self.assertEqual(summary["quality"], "invalid/missing")
        self.assertIsNone(summary["mean"])

    def test_redistribution_keeps_regional_fsi(self):
        left_heel = {"mean": 100.0, "peak": 100.0, "impulse": 100.0}
        right_heel = {"mean": 300.0, "peak": 300.0, "impulse": 300.0}
        left_fore = {"mean": 300.0, "peak": 300.0, "impulse": 300.0}
        right_fore = {"mean": 100.0, "peak": 100.0, "impulse": 100.0}
        self.assertEqual(phase_fsi(left_heel, right_heel, region="heel")["fsi"], 33.33)
        self.assertEqual(phase_fsi(left_fore, right_fore, region="forefoot")["fsi"], 33.33)
        combined_left = {"mean": 400.0, "peak": 400.0, "impulse": 400.0}
        combined_right = {"mean": 400.0, "peak": 400.0, "impulse": 400.0}
        self.assertEqual(
            phase_fsi(combined_left, combined_right, region="stance_sampled")["fsi"],
            100.0,
        )

    def test_validate_roi_rejects_duplicates_and_out_of_bounds(self):
        with self.assertRaises(ValueError):
            validate_roi({"heel": [(0, 0), (0, 0)]})
        with self.assertRaises(ValueError):
            validate_roi({"heel": [(12, 0)]})
        with self.assertRaises(ValueError):
            validate_roi({"heel": []})

    def test_contact_detection_uses_all_48_cells_and_finds_heel_off(self):
        heel = [physical_cell_to_matrix(cell) for cell in HEEL_CELL_IDS]
        fore = [physical_cell_to_matrix(cell) for cell in FOREFOOT_CELL_IDS]
        samples = []
        for timestamp, heel_value in ((0.0, 8.0), (0.1, 8.0), (0.2, 1.0), (0.3, 1.0)):
            matrix = [[0.0] * 4 for _ in range(12)]
            for row, col in heel:
                matrix[row][col] = heel_value / len(heel)
            for row, col in fore:
                matrix[row][col] = 12.0 / len(fore)
            samples.append({"timestamp": timestamp, "matrix": matrix, "valid": True})
        intervals = detect_contact_intervals(samples, threshold=10.0, debounce=2, heel_cells=heel, forefoot_cells=fore)
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0]["ic"], 0.0)
        self.assertEqual(intervals[0]["ho"], 0.2)

    def test_missing_heel_off_is_explicit_fallback(self):
        windows = phase_windows({"ic": 0.0, "to": 1.0, "next_ic": 2.0}, {"ic": 1.0, "to": 1.5})
        self.assertEqual(windows["midstance"][2], "missing")
        self.assertEqual(windows["terminal_stance_window"][2], "fallback_no_ho")

    def test_phase_windows_use_relative_events_when_legs_are_offset(self):
        left = phase_windows(
            {"ic": 0.0, "to": 0.65, "ho": 0.4, "next_ic": 1.3},
            {"ic": 0.5, "to": 1.15, "ho": 0.85, "next_ic": 1.8},
        )
        right = phase_windows(
            {"ic": 0.5, "to": 1.15, "ho": 0.85, "next_ic": 1.8},
            {"ic": 0.0, "to": 0.65, "ho": 0.4, "next_ic": 1.3},
        )
        self.assertEqual(left["loading"][:2], (0.0, 1.15))
        self.assertEqual(right["loading"][:2], (0.5, 0.65))
        self.assertNotEqual(left["loading"][:2], right["loading"][:2])

    def test_stride_keeps_next_same_side_ic_for_swing(self):
        stride = __import__("fsi_phase_metrics").build_stride(
            [{"ic": 0.0, "to": 0.6, "detected": True}, {"ic": 1.2, "to": 1.8, "detected": True}],
            "left",
        )
        self.assertEqual(stride["next_ic"], 1.2)
        self.assertEqual(phase_windows(stride)["swing"][:2], (0.6, 1.2))

    def test_phase_pair_exposes_separate_mid_regions(self):
        cells = [physical_cell_to_matrix(cell) for cell in STANCE_CELL_IDS]
        def samples(value):
            matrix = [[0.0] * 4 for _ in range(12)]
            for row, col in cells:
                matrix[row][col] = value / len(cells)
            return [{"timestamp": 0.0, "matrix": matrix, "valid": True},
                    {"timestamp": 1.0, "matrix": matrix, "valid": True}]
        left = samples(100.0)
        right = samples(200.0)
        rows = compare_phase_pair(
            left, right,
            {"ic": 0.0, "to": 1.0, "ho": 0.5, "next_ic": 2.0},
            {"ic": 0.0, "to": 1.0, "ho": 0.5, "next_ic": 2.0},
            pair_id="BT1-BP1",
        )
        mid_regions = {(row["phase"], row["region"]) for row in rows if row["phase"] == "midstance"}
        self.assertEqual(mid_regions, {
            ("midstance", "heel"),
            ("midstance", "forefoot"),
            ("midstance", "stance_sampled"),
        })

    def test_session_analyzer_keeps_pair_and_session_layers(self):
        matrix = [[0.0] * 4 for _ in range(12)]
        for cell in STANCE_CELL_IDS:
            row, col = physical_cell_to_matrix(cell)
            matrix[row][col] = 1.0
        analyzer = FsiSessionAnalyzer(threshold=10.0, debounce=1)
        for timestamp in (0.0, 0.1, 0.2):
            analyzer.add_sample("left", timestamp, matrix)
            analyzer.add_sample("right", timestamp + 0.05, matrix)
        snapshot = analyzer.snapshot()
        self.assertIn("pairs", snapshot)
        self.assertIn("summary", snapshot)
        self.assertEqual(snapshot["sample_count"], {"left": 3, "right": 3})

    def test_session_pairing_uses_adjacent_event_time(self):
        left = [{"ic": 0.0}, {"ic": 1.4}]
        right = [{"ic": 0.6}, {"ic": 2.0}]
        pairs = FsiSessionAnalyzer._pair_events(left, right)
        self.assertEqual([(pair[0]["ic"], pair[1]["ic"]) for pair in pairs], [(0.0, 0.6), (1.4, 2.0)])


if __name__ == "__main__":
    unittest.main()
