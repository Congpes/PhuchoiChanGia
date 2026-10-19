import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from camera_preview import PreviewJpegCache


class PreviewJpegCacheTests(unittest.TestCase):
    def test_concurrent_clients_encode_the_same_frame_once(self):
        cache = PreviewJpegCache()
        start = threading.Barrier(5)
        encoding = threading.Event()
        release = threading.Event()
        calls = []

        def encode():
            calls.append(1)
            encoding.set()
            if not release.wait(3):
                raise TimeoutError("Test did not release encoder")
            return b"shared-jpeg"

        def request():
            start.wait(timeout=3)
            return cache.get_or_encode((0, False), 100, encode)

        with ThreadPoolExecutor(max_workers=4) as executor:
            pending = [executor.submit(request) for _ in range(4)]
            try:
                start.wait(timeout=3)
                self.assertTrue(encoding.wait(3))
            finally:
                release.set()
            results = [future.result(timeout=3) for future in pending]

        self.assertEqual(results, [(100, b"shared-jpeg")] * 4)
        self.assertEqual(len(calls), 1)
        self.assertEqual(cache.snapshot()["encodes"], 1)
        self.assertEqual(cache.snapshot()["cacheHits"], 3)

    def test_new_frame_replaces_previous_frame(self):
        cache = PreviewJpegCache()
        self.assertEqual(
            cache.get_or_encode((0, True), 100, lambda: b"first"),
            (100, b"first"),
        )
        self.assertEqual(
            cache.get_or_encode((0, True), 200, lambda: b"second"),
            (200, b"second"),
        )
        self.assertEqual(cache.snapshot()["encodes"], 2)
        self.assertEqual(cache.snapshot()["retainedBytes"], 6)

    def test_old_request_returns_latest_timestamp_and_bytes(self):
        cache = PreviewJpegCache()
        cache.get_or_encode((1, False), 200, lambda: b"newer")

        def must_not_encode():
            self.fail("A stale request must use the newer cached JPEG")

        self.assertEqual(
            cache.get_or_encode((1, False), 100, must_not_encode),
            (200, b"newer"),
        )

    def test_waiting_old_client_cannot_displace_newer_frame(self):
        cache = PreviewJpegCache()
        encoding = threading.Event()
        release = threading.Event()

        def encode_new():
            encoding.set()
            if not release.wait(3):
                raise TimeoutError("Test did not release encoder")
            return b"newer"

        def must_not_encode():
            self.fail("The waiting stale request must use the newer JPEG")

        with ThreadPoolExecutor(max_workers=2) as executor:
            newer = executor.submit(cache.get_or_encode, (0, False), 200, encode_new)
            try:
                self.assertTrue(encoding.wait(3))
                older = executor.submit(
                    cache.get_or_encode, (0, False), 100, must_not_encode,
                )
            finally:
                release.set()
            self.assertEqual(newer.result(timeout=3), (200, b"newer"))
            self.assertEqual(older.result(timeout=3), (200, b"newer"))

    def test_failed_encode_is_retried_for_the_same_frame(self):
        cache = PreviewJpegCache()
        self.assertIsNone(cache.get_or_encode((0, True), 100, lambda: None))
        self.assertEqual(
            cache.get_or_encode((0, True), 100, lambda: b"retry"),
            (100, b"retry"),
        )
        self.assertEqual(cache.snapshot()["encodes"], 1)

    def test_failed_new_frame_preserves_last_successful_frame(self):
        cache = PreviewJpegCache()
        cache.get_or_encode((0, True), 100, lambda: b"valid")
        self.assertIsNone(cache.get_or_encode((0, True), 200, lambda: None))
        self.assertEqual(
            cache.get_or_encode((0, True), 100, lambda: b"wrong"),
            (100, b"valid"),
        )

    def test_encoder_exception_is_not_cached_and_lock_is_released(self):
        cache = PreviewJpegCache()

        def broken_encode():
            raise RuntimeError("Encoder failed")

        with self.assertRaisesRegex(RuntimeError, "Encoder failed"):
            cache.get_or_encode((1, False), 100, broken_encode)
        self.assertEqual(
            cache.get_or_encode((1, False), 100, lambda: b"recovered"),
            (100, b"recovered"),
        )

    def test_blocked_camera_does_not_block_another_camera_or_raw_stream(self):
        cache = PreviewJpegCache()
        encoding = threading.Event()
        release = threading.Event()

        def encode_slow():
            encoding.set()
            if not release.wait(3):
                raise TimeoutError("Test did not release encoder")
            return b"slow"

        with ThreadPoolExecutor(max_workers=3) as executor:
            slow = executor.submit(cache.get_or_encode, (0, False), 100, encode_slow)
            try:
                self.assertTrue(encoding.wait(3))
                other_camera = executor.submit(
                    cache.get_or_encode, (1, False), 100, lambda: b"other",
                )
                raw_stream = executor.submit(
                    cache.get_or_encode, (0, True), 100, lambda: b"raw",
                )
                self.assertEqual(other_camera.result(timeout=2), (100, b"other"))
                self.assertEqual(raw_stream.result(timeout=2), (100, b"raw"))
            finally:
                release.set()
            self.assertEqual(slow.result(timeout=3), (100, b"slow"))

    def test_cached_payload_is_immutable(self):
        cache = PreviewJpegCache()
        payload = bytearray(b"jpeg")
        encoded = cache.get_or_encode((1, True), 100, lambda: payload)
        payload[:] = b"oops"
        self.assertEqual(encoded, (100, b"jpeg"))
        self.assertIsInstance(encoded[1], bytes)
        self.assertEqual(
            cache.get_or_encode((1, True), 100, lambda: b"wrong"),
            (100, b"jpeg"),
        )

    def test_cache_retains_only_latest_result_for_each_of_four_streams(self):
        cache = PreviewJpegCache()
        for slot, raw in ((0, False), (0, True), (1, False), (1, True)):
            for timestamp in range(1, 21):
                cache.get_or_encode((slot, raw), timestamp, lambda: b"jpeg")
        snapshot = cache.snapshot()
        self.assertEqual(snapshot["cachedStreams"], 4)
        self.assertEqual(snapshot["retainedBytes"], 16)
        self.assertEqual(len(snapshot["streams"]), 4)
        self.assertEqual(snapshot["encodes"], 80)
        self.assertEqual(
            {stream["frameNs"] for stream in snapshot["streams"].values()},
            {20},
        )
        with self.assertRaises(KeyError):
            cache.get_or_encode((2, False), 100, lambda: b"out-of-scope")


if __name__ == "__main__":
    unittest.main()
