import unittest

from realtime_services import gait_reanalysis_decision


def _analysis(
    cycle_count,
    *,
    quality_count=0,
    coverage=8,
    sample_count=157,
    version="raw-replay-v1",
):
    cycles = []
    for index in range(cycle_count):
        cycle = {"pairIndex": index + 1}
        if index < quality_count:
            cycle["cameraCycleQuality"] = {"steadyWalking": True}
        cycles.append(cycle)
    slots = [
        (metric, side)
        for metric in ("knee", "hip", "trunk", "lateral_trunk")
        for side in ("left", "right")
    ]
    metrics = {
        metric: {
            side: {"mean": [1.0] if (metric, side) in slots[:coverage] else []}
            for side in ("left", "right")
        }
        for metric in ("knee", "hip", "trunk", "lateral_trunk")
    }
    return {
        "algorithmVersion": version,
        "sampleCount": sample_count,
        "cycles": cycles,
        "metrics": metrics,
    }


class GaitReanalysisDecisionTests(unittest.TestCase):
    def test_newer_quality_run_beats_one_extra_legacy_cycle(self):
        candidate = _analysis(
            3,
            quality_count=3,
            version="raw-replay-v4-camera-trunk-qa",
        )
        existing = _analysis(4, version="raw-replay-v1")

        decision = gait_reanalysis_decision(
            candidate,
            existing,
            candidate_version="raw-replay-v4-camera-trunk-qa",
        )

        self.assertTrue(decision["replace"])
        self.assertEqual(decision["reason"], "newer_quality_qualified_analysis")
        self.assertEqual(decision["candidateScore"]["qualityQualifiedCycleCount"], 3)
        self.assertEqual(decision["existingScore"]["cycleCount"], 4)

    def test_newer_run_with_only_one_qualified_cycle_is_kept_out(self):
        decision = gait_reanalysis_decision(
            _analysis(5, quality_count=1, version="raw-replay-v4-camera-trunk-qa"),
            _analysis(4, version="raw-replay-v1"),
            candidate_version="raw-replay-v4-camera-trunk-qa",
        )
        self.assertFalse(decision["replace"])
        self.assertEqual(decision["reason"], "newer_analysis_failed_quality_guard")

    def test_newer_run_cannot_reduce_metric_coverage(self):
        decision = gait_reanalysis_decision(
            _analysis(
                3,
                quality_count=3,
                coverage=7,
                version="raw-replay-v4-camera-trunk-qa",
            ),
            _analysis(4, coverage=8, version="raw-replay-v1"),
            candidate_version="raw-replay-v4-camera-trunk-qa",
        )
        self.assertFalse(decision["replace"])

    def test_newer_run_cannot_replace_after_sample_coverage_collapse(self):
        decision = gait_reanalysis_decision(
            _analysis(
                3,
                quality_count=3,
                sample_count=40,
                version="raw-replay-v4-camera-trunk-qa",
            ),
            _analysis(4, sample_count=157, version="raw-replay-v1"),
            candidate_version="raw-replay-v4-camera-trunk-qa",
        )
        self.assertFalse(decision["replace"])

    def test_equal_version_still_keeps_higher_cycle_count(self):
        decision = gait_reanalysis_decision(
            _analysis(3, quality_count=3, version="raw-replay-v4-camera-trunk-qa"),
            _analysis(4, quality_count=4, version="raw-replay-v4-camera-trunk-qa"),
            candidate_version="raw-replay-v4-camera-trunk-qa",
        )
        self.assertFalse(decision["replace"])
        self.assertEqual(decision["reason"], "candidate_score_lower")


if __name__ == "__main__":
    unittest.main()
