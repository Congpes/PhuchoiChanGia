import unittest

from fsr_step_pipeline import FsrStepPipeline


def regions(total):
    return {
        "total": total,
        "heel": total * 0.35,
        "midfoot": total * 0.25,
        "forefoot": total * 0.40,
    }


class FsrStepPipelineTests(unittest.TestCase):
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

    def test_rejects_too_short_step(self):
        pipeline = FsrStepPipeline(contact_on=4000, contact_off=1800)
        pipeline.add_sample("left", 0.0, regions(1000))
        pipeline.add_sample("left", 0.05, regions(9000))
        pipeline.add_sample("left", 0.10, regions(9000))
        pipeline.add_sample("left", 0.15, regions(1000))
        pipeline.add_sample("left", 0.20, regions(1000))
        snapshot = pipeline.snapshot()
        self.assertEqual(snapshot["status"]["completedSteps"]["left"], 0)


if __name__ == "__main__":
    unittest.main()
