import json
import tempfile
import unittest
from pathlib import Path

from stereo_calibration import StereoCalibrationManager


class StereoCalibrationTests(unittest.TestCase):
    def test_generates_board_with_physical_dimensions_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = StereoCalibrationManager(Path(directory) / "calibration.json")
            png = manager.board_png(100)
            self.assertTrue(png.startswith(b"\x89PNG"))
            self.assertIn(b"pHYs", png)
            self.assertEqual(manager.board_info()["printWidthMm"], 210.0)
            self.assertEqual(manager.board_info()["printHeightMm"], 150.0)

    def test_uncalibrated_status_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = StereoCalibrationManager(Path(directory) / "missing.json")
            status = manager.status((0, 1))
            self.assertFalse(status["calibrated"])
            self.assertFalse(status["compatible"])
            self.assertEqual(status["minimumSamples"], 12)

    def test_resolution_mismatch_requires_recalibration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(
                json.dumps({
                    "valid": True,
                    "cameraIndices": [0, 1],
                    "imageSize": [640, 480],
                }),
                encoding="utf-8",
            )
            manager = StereoCalibrationManager(path)

            self.assertTrue(manager.compatible((0, 1)))
            self.assertFalse(
                manager.compatible(
                    (0, 1),
                    image_size_0=(1280, 720),
                    image_size_1=(1280, 720),
                )
            )
            status = manager.status(
                (0, 1),
                image_size_0=(1280, 720),
                image_size_1=(1280, 720),
            )
            self.assertTrue(status["cameraCompatible"])
            self.assertFalse(status["resolutionCompatible"])
            self.assertTrue(status["needsRecalibration"])


if __name__ == "__main__":
    unittest.main()
