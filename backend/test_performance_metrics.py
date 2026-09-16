import unittest

from performance_metrics import PerformanceMonitor


class PerformanceMonitorTests(unittest.TestCase):
    def test_stage_summary_reports_rate_duration_latency_and_gaps(self):
        monitor = PerformanceMonitor(expected_fsr_hz=20.0)

        monitor.record_stage(
            "camera.0.read", duration_seconds=0.010,
            event_at=0.00, latency_seconds=0.020,
        )
        monitor.record_stage(
            "camera.0.read", duration_seconds=0.020,
            event_at=0.05, latency_seconds=0.040,
        )
        monitor.record_stage(
            "camera.0.read", duration_seconds=0.030,
            event_at=0.10, latency_seconds=0.060,
        )

        summary = monitor.snapshot(sample_resources=False)["stages"]["camera.0.read"]
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["retainedSampleCount"], 3)
        self.assertAlmostEqual(summary["rateHz"], 20.0)
        self.assertAlmostEqual(summary["durationMs"]["median"], 20.0)
        self.assertAlmostEqual(summary["durationMs"]["p95"], 29.0)
        self.assertAlmostEqual(summary["latencyMs"]["median"], 40.0)
        self.assertAlmostEqual(summary["intervalMs"]["p95"], 50.0)

    def test_fsr_summary_labels_time_based_loss_and_payload_repeats_as_estimates(self):
        monitor = PerformanceMonitor(expected_fsr_hz=20.0)
        matrix = [[1.0, 2.0], [3.0, 4.0]]

        monitor.record_fsr_chunk("COM8", 120, received_at=0.00)
        monitor.record_fsr_frame("left", matrix, "COM8", received_at=0.00)
        monitor.record_fsr_chunk("COM8", 100, received_at=0.05)
        monitor.record_fsr_frame("left", matrix, "COM8", received_at=0.05)
        monitor.record_fsr_chunk("COM8", 80, received_at=0.15)
        monitor.record_fsr_frame("left", matrix, "COM8", received_at=0.15)

        fsr = monitor.snapshot(sample_resources=False)["fsr"]
        left = fsr["bySide"]["left"]
        port = fsr["byPort"]["COM8"]
        self.assertEqual(left["frameCount"], 3)
        self.assertEqual(left["inferredMissingFrameCount"], 1)
        self.assertEqual(left["consecutivePayloadRepeatCount"], 2)
        self.assertEqual(port["bytesReceived"], 300)
        self.assertEqual(port["parsedFrameCount"], 3)
        self.assertAlmostEqual(port["averageWireBytesPerFrame"], 100.0)
        self.assertEqual(
            fsr["limitations"]["missingFrames"],
            "device_sequence_when_available_otherwise_receive_interval_estimate",
        )
        self.assertEqual(
            fsr["limitations"]["duplicateFrames"],
            "device_sequence_when_available_otherwise_consecutive_equal_payloads",
        )

    def test_single_sample_keeps_unavailable_measurements_null(self):
        monitor = PerformanceMonitor(expected_fsr_hz=20.0)
        monitor.record_stage("camera.0.read", 0.01, event_at=1.0)
        monitor.record_fsr_chunk("COM8", 100, received_at=1.0)
        monitor.record_fsr_frame(
            "left", [[1.0]], "COM8", received_at=1.0
        )

        snapshot = monitor.snapshot(sample_resources=False)
        self.assertIsNone(snapshot["stages"]["camera.0.read"]["rateHz"])
        self.assertIsNone(snapshot["fsr"]["bySide"]["left"]["rateHz"])
        self.assertIsNone(
            snapshot["fsr"]["bySide"]["left"]["inferredMissingFrameCount"]
        )
        self.assertIsNone(
            snapshot["fsr"]["bySource"]["serial:COM8"]["wireBytesPerSecond"]
        )

    def test_capture_totals_remain_correct_after_percentile_deques_roll_over(self):
        monitor = PerformanceMonitor(expected_fsr_hz=20.0, max_samples=10)
        for index in range(25):
            monitor.record_fsr_chunk("COM8", 10, received_at=index * 0.01)
        for index in range(5):
            monitor.record_fsr_frame(
                "left", [[float(index)]], "COM8", received_at=index * 0.05
            )

        source = monitor.snapshot(sample_resources=False)["fsr"]["bySource"][
            "serial:COM8"
        ]
        self.assertEqual(source["chunkCount"], 25)
        self.assertEqual(source["retainedChunkSampleCount"], 10)
        self.assertEqual(source["bytesReceived"], 250)
        self.assertEqual(source["parsedFrameCount"], 5)
        self.assertAlmostEqual(source["averageWireBytesPerFrame"], 50.0)

    def test_udp_sequence_is_exact_per_device_not_falsely_attributed_to_one_foot(self):
        udp = PerformanceMonitor(expected_fsr_hz=20.0)
        for index, sequence in enumerate((10, 12, 12)):
            at = index * 0.05
            udp.record_fsr_chunk(
                "device-1", 90, transport="udp", received_at=at
            )
            udp.record_fsr_frame(
                "right", [[float(sequence)]], "device-1",
                transport="udp", sequence=sequence, received_at=at,
            )
        fsr = udp.snapshot(sample_resources=False)["fsr"]
        udp_right = fsr["bySide"]["right"]
        udp_source = fsr["bySource"]["udp:device-1"]
        self.assertIsNone(udp_right["missingFrameCount"])
        self.assertEqual(
            udp_right["missingFrameReason"],
            "device_sequence_global_side_unknown",
        )
        self.assertEqual(udp_source["sequence"]["missing"], 1)
        self.assertEqual(udp_source["sequence"]["duplicate"], 1)
        self.assertEqual(udp_source["sequence"]["scope"], "device_all_sides")

    def test_interleaved_two_foot_udp_sequence_has_no_false_missing_packets(self):
        monitor = PerformanceMonitor(expected_fsr_hz=20.0)
        for index, (side, sequence) in enumerate((
            ("left", 0), ("right", 1), ("left", 2), ("right", 3),
        )):
            at = index * 0.025
            monitor.record_fsr_chunk(
                "device-1", 90, transport="udp", received_at=at
            )
            monitor.record_fsr_frame(
                side, [[float(sequence)]], "device-1",
                transport="udp", sequence=sequence, received_at=at,
            )

        fsr = monitor.snapshot(sample_resources=False)["fsr"]
        source = fsr["bySource"]["udp:device-1"]
        self.assertEqual(source["sequence"]["missing"], 0)
        self.assertEqual(source["sequence"]["duplicate"], 0)
        self.assertIsNone(fsr["bySide"]["left"]["missingFrameCount"])
        self.assertIsNone(fsr["bySide"]["right"]["missingFrameCount"])

    def test_serial_batching_makes_time_gap_loss_unavailable(self):
        serial = PerformanceMonitor(expected_fsr_hz=20.0)

        serial.record_fsr_chunk(
            "COM8", 200, parsed_frame_count=2, received_at=0.0
        )
        serial.record_fsr_frame(
            "left", [[1.0]], "COM8", batch_size=2, received_at=0.0
        )
        serial.record_fsr_frame(
            "left", [[2.0]], "COM8", batch_size=2, received_at=0.0
        )
        serial_left = serial.snapshot(sample_resources=False)["fsr"]["bySide"]["left"]
        self.assertIsNone(serial_left["inferredMissingFrameCount"])
        self.assertEqual(
            serial_left["missingFrameReason"],
            "unavailable_serial_batching_without_sequence",
        )

    def test_resource_samples_and_reset_are_reproducible(self):
        now = [10.0]
        process_cpu = [2.0]
        memory_bytes = [100 * 1024 * 1024]
        monitor = PerformanceMonitor(
            clock=lambda: now[0],
            process_time=lambda: process_cpu[0],
            memory_reader=lambda: memory_bytes[0],
            logical_cpu_count=4,
        )

        now[0] = 12.0
        process_cpu[0] = 3.0
        monitor.sample_resources()
        resources = monitor.snapshot(sample_resources=False)["resources"]
        self.assertAlmostEqual(
            resources["processCpuPercentOfOneCore"]["median"], 50.0
        )
        self.assertAlmostEqual(
            resources["processCpuPercentOfSystem"]["median"], 12.5
        )
        self.assertAlmostEqual(resources["workingSetMiB"]["median"], 100.0)

        monitor.record_stage("preview.camera0", 0.01, event_at=12.0)
        monitor.reset()
        snapshot = monitor.snapshot(sample_resources=False)
        self.assertEqual(snapshot["stages"], {})
        self.assertEqual(snapshot["fsr"]["bySide"], {})
        self.assertEqual(snapshot["resources"]["sampleCount"], 0)

    def test_failed_memory_probe_stays_null(self):
        now = [1.0]
        process_cpu = [1.0]
        monitor = PerformanceMonitor(
            clock=lambda: now[0],
            process_time=lambda: process_cpu[0],
            memory_reader=lambda: None,
        )
        now[0] = 2.0
        process_cpu[0] = 1.5
        monitor.sample_resources()
        resources = monitor.snapshot(sample_resources=False)["resources"]
        self.assertEqual(resources["sampleCount"], 1)
        self.assertEqual(resources["workingSetSampleCount"], 0)
        self.assertIsNone(resources["workingSetMiB"]["median"])


if __name__ == "__main__":
    unittest.main()
