import os
import subprocess
import sys
import unittest
from pathlib import Path

from capture_performance_baseline import capture_baseline


class CapturePerformanceBaselineTests(unittest.TestCase):
    def test_help_does_not_crash_on_legacy_windows_console_encoding(self):
        script = Path(__file__).with_name("capture_performance_baseline.py")
        environment = dict(os.environ)
        environment["PYTHONIOENCODING"] = "cp1252"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("ascii", "replace"))

    def test_capture_resets_then_polls_until_requested_duration(self):
        calls = []
        sleeps = []
        now = [0.0]

        def request(url, method="GET"):
            calls.append((method, url))
            if method == "GET":
                now[0] += 0.4
            return {"sample": len(calls)}

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        report = capture_baseline(
            "http://127.0.0.1:8000",
            duration_seconds=2.5,
            sample_interval_seconds=1.0,
            requester=request,
            sleeper=sleep,
            clock=lambda: now[0],
        )

        self.assertEqual(calls[0], (
            "POST",
            "http://127.0.0.1:8000/diagnostics/performance/reset",
        ))
        self.assertEqual(
            calls[1:],
            [("GET", "http://127.0.0.1:8000/diagnostics/performance")] * 3,
        )
        self.assertEqual([round(value, 3) for value in sleeps], [1.0, 0.6, 0.1])
        self.assertEqual(report, {"sample": 4})

    def test_capture_rejects_non_positive_duration(self):
        with self.assertRaises(ValueError):
            capture_baseline(
                "http://127.0.0.1:8000",
                duration_seconds=0,
                requester=lambda *_args, **_kwargs: {},
                sleeper=lambda _seconds: None,
            )


if __name__ == "__main__":
    unittest.main()
