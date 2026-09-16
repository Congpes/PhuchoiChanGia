import copy
import unittest

from fsr_step_pipeline import FsrStepPipeline, force_symmetry_index


def regions(total):
    return {
        "total": total,
        "heel": total * 0.35,
        "midfoot": total * 0.25,
        "forefoot": total * 0.40,
    }


class FsrStepPipelineTests(unittest.TestCase):
    def test_missing_foot_does_not_pair_old_stance_with_new_foot(self):
        for side, other in (('left', 'right'), ('right', 'left')):
            pipeline = FsrStepPipeline(contact_on=4000, contact_off=1800)
            self._feed_step(pipeline, side, 0.)
            self._feed_step(pipeline, side, 1.)
            self._feed_step(pipeline, other, 1.45)
            snapshot = pipeline.snapshot()
            self.assertEqual(len(snapshot['pairs']), 1)
            self.assertEqual(snapshot['pairs'][0][side]['sideIndex'], 2)
            self.assertEqual(snapshot['incompleteSteps'][0]['sideIndex'], 1)
            self.assertEqual(snapshot['incompleteSteps'][0]['unpairedReason'], 'missing_opposite_step')
            self.assertTrue(pipeline._incomplete_steps[0]['rawSamples'])

    def test_rejected_force_curve_reserves_its_contact_not_next_cycle(self):
        pipeline = FsrStepPipeline(contact_on=4000, contact_off=1800)
        self._feed_step(pipeline, 'left', 0.)
        # A genuine right landing with insufficient stance samples to analyse.
        for time, total in ((.3, 1000), (.45, 10000), (.50, 10000), (.55, 1000), (.60, 1000)):
            pipeline.add_sample('right', time, regions(total))
        self._feed_step(pipeline, 'left', 1.)
        self._feed_step(pipeline, 'right', 1.45)
        snapshot = pipeline.snapshot()
        self.assertEqual(len(snapshot['pairs']), 1)
        self.assertEqual(snapshot['pairs'][0]['left']['sideIndex'], 2)
        self.assertEqual(snapshot['incompleteSteps'][0]['unpairedReason'], 'opposite_force_measurement_missing')

    def test_pairing_uses_landings_even_when_stances_finish_in_reverse_order(self):
        pipeline = FsrStepPipeline()
        # L1 stays loaded while R1 finishes and R2 starts. L1 must still
        # pair with R1, never with the more recently finished right stance.
        for index in range(95):
            time = index * .02
            left = 130. if .2 <= time < 1.5 else 0.
            right = 130. if .5 <= time < .9 or 1.1 <= time < 1.4 else 0.
            pipeline.add_sample('left', time, regions(left))
            pipeline.add_sample('right', time, regions(right))
        pairs = pipeline.all_pairs()
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]['right']['sideIndex'], 1)
        self.assertAlmostEqual(pairs[0]['left']['contactAt'], .2)
        self.assertAlmostEqual(pairs[0]['right']['contactAt'], .5)

    def test_fsr_gap_does_not_reuse_partner_in_next_cycle(self):
        pipeline = FsrStepPipeline()
        for index in range(50):
            time = index * .02
            pipeline.add_sample('left', time, regions(130. if .2 <= time < .7 else 0.))
            if time <= .6 or time >= .98:
                pipeline.add_sample('right', time, regions(130. if .5 <= time < .8 else 0.))
        snapshot = pipeline.snapshot()
        self.assertEqual(snapshot['availablePairs'], 0)
        self.assertEqual(snapshot['incompleteSteps'][0]['unpairedReason'], 'opposite_force_measurement_missing')

    def test_packet_newton_metadata_is_preserved(self):
        pipeline = FsrStepPipeline(window_size=5)
        pipeline.set_force_metadata("N", "packet")
        self.assertEqual(pipeline.snapshot()["unit"], "N")
        self.assertEqual(pipeline.snapshot()["forceSource"], "packet")
        self.assertEqual(pipeline.analysis()["unit"], "N")

    def _feed_step(self, pipeline, side, start, amplitude=12000.0):
        pipeline.add_sample(side, start, regions(1000))
        pipeline.add_sample(side, start + 0.05, regions(1000))
        for index in range(12):
            phase = index / 11
            value = 1000 + amplitude * (1 - abs(2 * phase - 1))
            pipeline.add_sample(side, start + 0.10 + index * 0.05, regions(value))
        pipeline.add_sample(side, start + 0.72, regions(1000))
        pipeline.add_sample(side, start + 0.77, regions(1000))
        pipeline.add_sample(side, start + 0.82, regions(1000))

    def test_pairs_and_normalizes_steps(self):
        pipeline = FsrStepPipeline(contact_on=4000, contact_off=1800)
        self._feed_step(pipeline, "left", 0.0)
        self._feed_step(pipeline, "right", 0.45, amplitude=9000)
        snapshot = pipeline.snapshot()
        self.assertEqual(snapshot["availablePairs"], 1)
        pair = snapshot["pairs"][0]
        self.assertEqual(len(pair["left"]["curves"]["total"]), 101)
        self.assertEqual(len(pair["right"]["curves"]["heel"]), 101)
        self.assertEqual(pair["left"]["pairIndex"], 1)
        self.assertEqual(pair["right"]["pairIndex"], 1)
        self.assertGreater(pair["peakForeLeft"], 0.0)
        self.assertGreater(pair["peakForeRight"], 0.0)
        self.assertIsNotNone(pair["fsi"])

    def test_fifo_window_and_analysis(self):
        pipeline = FsrStepPipeline(window_size=5, contact_on=4000, contact_off=1800)
        for index in range(7):
            self._feed_step(pipeline, "left", index * 2.0)
            self._feed_step(pipeline, "right", index * 2.0 + 0.45, amplitude=9000)
        snapshot = pipeline.snapshot(healthy_leg="RIGHT", prosthetic_leg="LEFT")
        self.assertEqual(snapshot["availablePairs"], 5)
        self.assertEqual(snapshot["pairs"][0]["pairIndex"], 3)
        self.assertEqual(snapshot["healthySide"], "right")
        analysis = pipeline.analysis(healthy_leg="RIGHT", prosthetic_leg="LEFT")
        self.assertEqual(analysis["pairCount"], 5)
        self.assertEqual(analysis["regions"]["forefoot"]["left"]["steps"], 5)
        self.assertEqual(len(analysis["regions"]["total"]["right"]["sd"]), 101)
        self.assertEqual(len(analysis["peakForePairs"]), 5)
        self.assertEqual(analysis["peakForePairs"][-1]["pairIndex"], 7)
        summary_rows = {
            row["key"]: row for row in analysis["forceSummary"]["rows"]
        }
        self.assertEqual(
            [row["key"] for row in analysis["forceSummary"]["rows"][:4]],
            ["peakTotal", "peakHeel", "peakMidfoot", "peakFore"],
        )
        self.assertEqual(
            summary_rows["peakFore"]["label"],
            "Peak Fore (mũi / đẩy chân)",
        )
        self.assertEqual(analysis["forceSummary"]["pairCount"], 5)
        self.assertEqual(summary_rows["peakTotal"]["left"]["n"], 5)
        self.assertGreater(summary_rows["peakTotal"]["left"]["mean"], 0)
        self.assertGreater(summary_rows["peakFore"]["right"]["mean"], 0)
        self.assertIsNotNone(summary_rows["peakTotal"]["fsi"])
        self.assertEqual(len(analysis["forceSummary"]["pairRows"]), 5)

    def test_analysis_excludes_pair_marked_as_measurement_artifact(self):
        pipeline = FsrStepPipeline(window_size=5, contact_on=4000, contact_off=1800)
        self._feed_step(pipeline, "left", 0.0)
        self._feed_step(pipeline, "right", 0.45)
        valid = pipeline.all_pairs()[0]
        artifact = copy.deepcopy(valid)
        artifact["pairIndex"] = 2
        artifact["right"]["quality"] = {
            "accepted": False,
            "reasons": ["force_spike_noise"],
        }
        analysis = pipeline.analysis(pairs=[valid, artifact])
        self.assertEqual(analysis["pairCount"], 1)
        self.assertEqual(analysis["qualityExcludedPairCount"], 1)

    def test_analysis_uses_measured_curves_for_region_mean(self):
        pipeline = FsrStepPipeline(window_size=5)
        raw_curve = [80.0] * 101
        display_curve = [20.0] * 101
        step = {
            "sideIndex": 1,
            "curves": {
                "total": raw_curve,
                "heel": raw_curve,
                "midfoot": raw_curve,
                "forefoot": raw_curve,
            },
            "displayCurves": {
                "heel": display_curve,
                "midfoot": display_curve,
                "forefoot": display_curve,
            },
            "quality": {"accepted": True},
            "peakForePhasePercent": 80.0,
        }
        pair = {
            "pairIndex": 1,
            "left": copy.deepcopy(step),
            "right": copy.deepcopy(step),
            "peakForeLeft": 80.0,
            "peakForeRight": 80.0,
            "fsi": 100.0,
            "asymmetry": 0.0,
        }

        analysis = pipeline.analysis(pairs=[pair])

        self.assertEqual(analysis["regions"]["heel"]["left"]["mean"], raw_curve)
        self.assertEqual(analysis["regions"]["total"]["left"]["mean"], raw_curve)
        summary_rows = {
            row["key"]: row for row in analysis["forceSummary"]["rows"]
        }
        self.assertEqual(summary_rows["peakTotal"]["left"]["mean"], 80.0)
        self.assertEqual(summary_rows["peakHeel"]["left"]["mean"], 80.0)
        self.assertEqual(
            analysis["acquisitionQuality"]["acceptedPairCount"],
            1,
        )

    def test_analysis_keeps_start_stop_steps(self):
        pipeline = FsrStepPipeline(window_size=5)
        curve = [20.0] * 101
        pairs = []
        for index, duration in enumerate((0.72, 0.76, 0.74, 0.78, 1.95), 1):
            step = {
                "sideIndex": index,
                "duration": duration,
                "curves": {name: curve for name in ("total", "heel", "midfoot", "forefoot")},
                "quality": {"accepted": True},
                "peakForePhasePercent": 80.0,
            }
            pairs.append({
                "pairIndex": index,
                "left": copy.deepcopy(step),
                "right": copy.deepcopy(step),
                "peakForeLeft": 20.0,
                "peakForeRight": 20.0,
                "fsi": 100.0,
                "asymmetry": 0.0,
            })

        analysis = pipeline.analysis(pairs=pairs)

        self.assertEqual(analysis["pairCount"], 5)
        self.assertEqual(analysis["steadyStateExcludedPairCount"], 0)
        self.assertEqual(analysis["pairs"][-1]["pairIndex"], 5)

    def test_steady_state_filter_does_not_reject_consistently_slow_gait(self):
        pipeline = FsrStepPipeline(window_size=5)
        curve = [20.0] * 101
        pairs = []
        for index, duration in enumerate((1.70, 1.82, 1.76, 1.88, 1.79), 1):
            step = {
                "sideIndex": index,
                "duration": duration,
                "curves": {name: curve for name in ("total", "heel", "midfoot", "forefoot")},
                "quality": {"accepted": True},
                "peakForePhasePercent": 80.0,
            }
            pairs.append({
                "pairIndex": index,
                "left": copy.deepcopy(step),
                "right": copy.deepcopy(step),
                "peakForeLeft": 20.0,
                "peakForeRight": 20.0,
                "fsi": 100.0,
                "asymmetry": 0.0,
            })

        analysis = pipeline.analysis(pairs=pairs)

        self.assertEqual(analysis["pairCount"], 5)
        self.assertEqual(analysis["steadyStateExcludedPairCount"], 0)

    def test_analysis_keeps_real_low_effort_steps(self):
        pipeline = FsrStepPipeline(window_size=5)
        curve = [20.0] * 101
        pairs = []
        for index, effort in enumerate((155.0, 148.0, 160.0, 152.0, 55.0), 1):
            step = {
                "sideIndex": index,
                "duration": 0.75,
                "peakActivity": effort,
                "loadImpulse": effort * 0.55,
                "curves": {name: curve for name in ("total", "heel", "midfoot", "forefoot")},
                "quality": {"accepted": True},
                "peakForePhasePercent": 80.0,
            }
            pairs.append({
                "pairIndex": index,
                "left": copy.deepcopy(step),
                "right": copy.deepcopy(step),
                "peakForeLeft": 20.0,
                "peakForeRight": 20.0,
                "fsi": 100.0,
                "asymmetry": 0.0,
            })

        analysis = pipeline.analysis(pairs=pairs)

        self.assertEqual(analysis["pairCount"], 5)
        self.assertEqual(analysis["steadyStateExcludedPairCount"], 0)
        self.assertEqual(analysis["acquisitionQuality"]["steadyStateExclusions"], [])

    def test_low_peak_alone_does_not_hide_a_step_with_normal_impulse(self):
        pipeline = FsrStepPipeline(window_size=5)
        curve = [20.0] * 101
        pairs = []
        for index, peak in enumerate((155.0, 148.0, 160.0, 152.0, 55.0), 1):
            step = {
                "sideIndex": index,
                "duration": 0.75,
                "peakActivity": peak,
                "loadImpulse": 84.0,
                "curves": {name: curve for name in ("total", "heel", "midfoot", "forefoot")},
                "quality": {"accepted": True},
                "peakForePhasePercent": 80.0,
            }
            pairs.append({
                "pairIndex": index,
                "left": copy.deepcopy(step),
                "right": copy.deepcopy(step),
                "peakForeLeft": 20.0,
                "peakForeRight": 20.0,
                "fsi": 100.0,
                "asymmetry": 0.0,
            })

        analysis = pipeline.analysis(pairs=pairs)

        self.assertEqual(analysis["pairCount"], 5)
        self.assertEqual(analysis["steadyStateExcludedPairCount"], 0)

    def test_soft_selection_never_hides_more_than_two_of_seven_pairs(self):
        pipeline = FsrStepPipeline(window_size=7)
        curve = [20.0] * 101
        pairs = []
        durations = (0.72, 0.75, 0.78, 0.74, 1.90, 2.00, 2.10)
        for index, duration in enumerate(durations, 1):
            step = {
                "sideIndex": index,
                "duration": duration,
                "peakActivity": 150.0,
                "loadImpulse": 80.0,
                "curves": {name: curve for name in ("total", "heel", "midfoot", "forefoot")},
                "quality": {"accepted": True},
                "peakForePhasePercent": 80.0,
            }
            pairs.append({
                "pairIndex": index,
                "left": copy.deepcopy(step),
                "right": copy.deepcopy(step),
                "peakForeLeft": 20.0,
                "peakForeRight": 20.0,
                "fsi": 100.0,
                "asymmetry": 0.0,
            })

        analysis = pipeline.analysis(pairs=pairs)

        self.assertEqual(analysis["pairCount"], 7)
        self.assertEqual(analysis["steadyStateExcludedPairCount"], 0)

    def test_force_symmetry_index(self):
        self.assertEqual(force_symmetry_index(420.0, 420.0), 100.0)
        self.assertEqual(force_symmetry_index(420.0, 0.0), 0.0)
        self.assertIsNone(force_symmetry_index(0.0, 0.0))

    def test_rejects_too_short_step(self):
        pipeline = FsrStepPipeline(contact_on=4000, contact_off=1800)
        pipeline.add_sample("left", 0.0, regions(1000))
        pipeline.add_sample("left", 0.05, regions(9000))
        pipeline.add_sample("left", 0.10, regions(9000))
        pipeline.add_sample("left", 0.15, regions(1000))
        pipeline.add_sample("left", 0.20, regions(1000))
        snapshot = pipeline.snapshot()
        self.assertEqual(snapshot["status"]["completedSteps"]["left"], 0)

    def test_stale_unpaired_step_is_not_matched_to_a_later_foot(self):
        pipeline = FsrStepPipeline(contact_on=4000, contact_off=1800)
        self._feed_step(pipeline, "right", 0.0)
        self._feed_step(pipeline, "right", 2.0)
        self._feed_step(pipeline, "left", 2.45)
        snapshot = pipeline.snapshot()
        self.assertEqual(snapshot["availablePairs"], 1)
        self.assertEqual(snapshot["pairs"][0]["right"]["sideIndex"], 2)
        self.assertEqual(
            snapshot["status"]["discardedUnpairedSteps"]["right"],
            1,
        )

    def test_default_newton_threshold_detects_hardware_scale_step(self):
        pipeline = FsrStepPipeline()
        for index in range(4):
            pipeline.add_sample("left", index * 0.05, regions(30.0))
        for index, total in enumerate((100.0, 145.0, 205.0, 180.0, 130.0, 105.0)):
            pipeline.add_sample("left", 0.20 + index * 0.07, regions(total))
        pipeline.add_sample("left", 0.65, regions(76.0))
        pipeline.add_sample("left", 0.72, regions(72.0))
        snapshot = pipeline.snapshot()
        self.assertEqual(snapshot["status"]["completedSteps"]["left"], 1)

    def test_force_matrix_produces_robust_display_curves(self):
        pipeline = FsrStepPipeline()

        def matrix(total, phase):
            result = [[0.2 for _ in range(4)] for _ in range(12)]
            center = 10 if phase < 0.34 else 6 if phase < 0.67 else 2
            for row in range(max(0, center - 1), min(12, center + 2)):
                result[row][1] += total / 12.0
                result[row][2] += total / 12.0
            return result

        for index in range(4):
            pipeline.add_sample("left", index * 0.05, regions(30.0), matrix(0, 0))
        for index, total in enumerate((100, 145, 205, 180, 130, 105)):
            phase = index / 5
            pipeline.add_sample(
                "left",
                0.20 + index * 0.07,
                regions(total),
                matrix(total, phase),
            )
        pipeline.add_sample("left", 0.65, regions(76.0), matrix(5, 1))
        pipeline.add_sample("left", 0.72, regions(72.0), matrix(0, 1))
        step = pipeline._unpaired["left"][0]
        self.assertEqual(set(step["displayCurves"]), {"total", "heel", "midfoot", "forefoot"})
        self.assertTrue(all(len(curve) == 101 for curve in step["displayCurves"].values()))

    def test_idle_force_bump_below_peak_floor_is_rejected(self):
        pipeline = FsrStepPipeline()
        for index in range(4):
            pipeline.add_sample("right", index * 0.05, regions(25.0))
        for index, total in enumerate((90.0, 94.0, 98.0, 92.0, 88.0)):
            pipeline.add_sample("right", 0.20 + index * 0.07, regions(total))
        pipeline.add_sample("right", 0.60, regions(65.0))
        pipeline.add_sample("right", 0.67, regions(62.0))
        snapshot = pipeline.snapshot()
        self.assertEqual(snapshot["status"]["completedSteps"]["right"], 0)
        self.assertEqual(snapshot["status"]["rejectedSteps"]["right"], 1)

    def test_repeated_force_spikes_are_excluded_by_quality_control(self):
        pipeline = FsrStepPipeline()
        for index in range(4):
            pipeline.add_sample("left", index * 0.05, regions(30.0))
        noisy = (100.0, 205.0, 105.0, 210.0, 100.0, 200.0, 110.0, 205.0)
        for index, total in enumerate(noisy):
            pipeline.add_sample("left", 0.20 + index * 0.05, regions(total))
        pipeline.add_sample("left", 0.65, regions(70.0))
        pipeline.add_sample("left", 0.70, regions(68.0))
        snapshot = pipeline.snapshot()
        self.assertEqual(snapshot["status"]["completedSteps"]["left"], 0)
        self.assertEqual(snapshot["status"]["qualityRejectedSteps"]["left"], 1)
        self.assertEqual(
            snapshot["status"]["qualityRejectionReasons"]["left"]["force_spike_noise"],
            1,
        )

    def test_short_bluetooth_gap_is_smoothed_instead_of_rejecting_step(self):
        pipeline = FsrStepPipeline()
        for index in range(4):
            pipeline.add_sample("right", index * 0.05, regions(30.0))
        for timestamp, total in (
            (0.20, 100.0),
            (0.25, 145.0),
            (0.30, 190.0),
            (0.55, 170.0),
            (0.60, 130.0),
            (0.65, 100.0),
            (0.70, 70.0),
            (0.75, 65.0),
        ):
            pipeline.add_sample("right", timestamp, regions(total))

        snapshot = pipeline.snapshot()
        step = pipeline._unpaired["right"][0]
        self.assertEqual(snapshot["status"]["completedSteps"]["right"], 1)
        self.assertIn("short_packet_gap_interpolated", step["quality"]["warnings"])

    def test_recording_reset_keeps_unloaded_baseline_only(self):
        pipeline = FsrStepPipeline(contact_on=100, contact_off=50)
        pipeline.add_sample("left", 0.0, regions(12))
        pipeline.add_sample("right", 0.0, regions(18))
        pipeline.reset(keep_baseline=True)
        self.assertEqual(pipeline._sides["left"].baseline["total"], 12)
        self.assertEqual(pipeline._sides["right"].baseline["total"], 18)
        self.assertEqual(
            pipeline.snapshot()["status"]["completedSteps"],
            {"left": 0, "right": 0},
        )


if __name__ == "__main__":
    unittest.main()
