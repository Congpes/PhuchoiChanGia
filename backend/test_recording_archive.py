import json
import os
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from fastapi import FastAPI

import database
import realtime_services


class JsonSafetyTests(unittest.TestCase):
    def test_non_finite_pose_values_become_json_null(self):
        value = {
            "signal": [1.0, float("nan"), np.float64("inf")],
            "count": np.int64(3),
        }
        safe = realtime_services.finite_json(value)
        self.assertEqual(safe, {"signal": [1.0, None, None], "count": 3})

    def test_fsr_packet_timestamp_uses_source_clock(self):
        sampled, latency_ms, valid = realtime_services.packet_sample_time(
            {"timestamp_ms": 1000250},
            received_at=1000.300,
        )
        self.assertTrue(valid)
        self.assertAlmostEqual(sampled, 1000.250)
        self.assertAlmostEqual(latency_ms, 50.0)

    def test_invalid_fsr_packet_timestamp_falls_back_to_receive_time(self):
        sampled, latency_ms, valid = realtime_services.packet_sample_time(
            {"timestamp_ms": 123},
            received_at=1000.0,
        )
        self.assertFalse(valid)
        self.assertEqual(sampled, 1000.0)
        self.assertEqual(latency_ms, 0.0)

    def test_relative_recording_fsr_is_shifted_to_live_camera_clock(self):
        source = [{
            "pairIndex": 1,
            "left": {"start": 1.0, "end": 1.6},
            "right": {"start": 1.5, "end": 2.1},
        }]
        aligned = realtime_services.align_fsr_cycle_anchors(
            source,
            camera_timestamps_are_relative=False,
            fsr_timestamps_are_relative=True,
            record_start_time=1000.0,
        )
        self.assertEqual(aligned[0]["left"]["start"], 1001.0)
        self.assertEqual(aligned[0]["right"]["end"], 1002.1)
        self.assertEqual(source[0]["left"]["start"], 1.0)

    def test_recorded_camera_and_fsr_keep_same_relative_clock(self):
        source = [{
            "pairIndex": 1,
            "left": {"start": 1.0, "end": 1.6},
            "right": {"start": 1.5, "end": 2.1},
        }]
        aligned = realtime_services.align_fsr_cycle_anchors(
            source,
            camera_timestamps_are_relative=True,
            fsr_timestamps_are_relative=True,
            record_start_time=1000.0,
        )
        self.assertEqual(aligned, source)
        self.assertIsNot(aligned[0], source[0])

    def test_unrecorded_live_camera_and_fsr_keep_absolute_clock(self):
        source = [{
            "pairIndex": 1,
            "left": {"start": 1001.0},
            "right": {"start": 1001.5},
        }]
        aligned = realtime_services.align_fsr_cycle_anchors(
            source,
            camera_timestamps_are_relative=False,
            fsr_timestamps_are_relative=False,
            record_start_time=0.0,
        )
        self.assertEqual(aligned, source)

    def test_gait_quality_is_checked_per_leg(self):
        quality = {
            "targetSide": "right",
            "targetVisibilityThreshold": 0.70,
            "bodyInFrame": True,
            "legIdentityReliable": True,
            "outOfRangeAngles": [],
            "temporalJumpAngles": [],
            "landmarkVisibility": {
                "left_hip": 0.42,
                "left_knee": 0.44,
                "left_ankle": 0.41,
                "right_hip": 0.92,
                "right_knee": 0.90,
                "right_ankle": 0.88,
            },
        }
        self.assertTrue(realtime_services.gait_side_sample_reliable(quality, "left"))
        self.assertTrue(realtime_services.gait_side_sample_reliable(quality, "right"))
        quality["landmarkVisibility"]["right_knee"] = 0.69
        self.assertFalse(realtime_services.gait_side_sample_reliable(quality, "right"))


class _FakeWriter:
    paths = []
    calls = []

    def __init__(self, *_args, **_kwargs):
        self.released = False
        self.paths.append(_args[0])
        self.calls.append(_args)
        path = Path(_args[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-avi")

    def isOpened(self):
        return True

    def write(self, _frame):
        return None

    def release(self):
        self.released = True


class RecordingArchiveTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.original_db_file = database.DB_FILE
        database.DB_FILE = self.db_path
        self.recordings_dir = tempfile.TemporaryDirectory()
        _FakeWriter.paths.clear()
        _FakeWriter.calls.clear()
        database.init_db()
        conn = database.get_db_connection()
        conn.execute(
            """
            INSERT INTO patients
                (id, name, age, height_cm, weight_kg, healthy_leg, prosthetic_leg)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("p-record", "Record Patient", 30, 170, 60, "LEFT", "RIGHT"),
        )
        conn.execute(
            """INSERT INTO sessions
               (id, patient_id, created_at, is_practice_mode)
               VALUES (?, ?, ?, ?)""",
            ("s-record", "p-record", "2026-08-19T10:00:00Z", 0),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        database.DB_FILE = self.original_db_file
        self.recordings_dir.cleanup()
        try:
            os.unlink(self.db_path)
        except FileNotFoundError:
            pass

    @staticmethod
    def _state():
        now = time.time()
        state = SimpleNamespace(
            running=False,
            latest_frame_0=np.zeros((480, 640, 3), dtype=np.uint8),
            latest_frame_1=np.zeros((480, 640, 3), dtype=np.uint8),
            latest_frame_0_at=now,
            latest_frame_1_at=now,
            latest_pose_0_at=now,
            latest_pose_1_at=now,
            latest_sagittal_pose_at=now,
            frame_lock_0=threading.Lock(),
            frame_lock_1=threading.Lock(),
            camera_roles_lock=threading.Lock(),
            camera_roles_swapped=False,
            live_gait_lock=threading.Lock(),
            live_gait_samples=deque(),
            SINGLE_CAMERA_MODE=False,
            CAMERA_FRONTAL_INDEX=0,
            CAMERA_SAGITTAL_INDEX=1,
            is_recording=False,
            record_start_time=0.0,
            recorded_timestamps=[],
            recorded_left_knee=[],
            recorded_right_knee=[],
            recorded_left_ankle=[],
            recorded_right_ankle=[],
            recorded_left_hip=[],
            recorded_right_hip=[],
            recorded_pelvic_tilt=[],
            recorded_trunk_tilt=[],
        )
        return state

    @staticmethod
    def _endpoint(app, path, method):
        for route in app.routes:
            if getattr(route, "path", None) == path and method in route.methods:
                return route.endpoint
        raise AssertionError(f"Missing route {method} {path}")

    def _exercise_serial_worker(self, *, actual_failure=False, processing_failure=False):
        import serial
        from serial.tools import list_ports

        app, state = FastAPI(), self._state()
        clock = [100.0]
        reads = [0]
        workers = []
        observed = []
        payload = b'RR ' + b' '.join([b'100'] * 48) + b'\n'
        connection = mock.Mock(in_waiting=len(payload))
        original_add_sample = realtime_services.FsrStepPipeline.add_sample
        processing_calls = [0]

        def add_sample(pipeline, *args, **kwargs):
            processing_calls[0] += 1
            if processing_failure and processing_calls[0] == 1:
                raise ValueError('simulated step calculation failure')
            return original_add_sample(pipeline, *args, **kwargs)

        def read_chunk(_size):
            reads[0] += 1
            clock[0] += 1.0
            if actual_failure and reads[0] == 1:
                raise serial.SerialException('ReadFile failed: device disconnected')
            if reads[0] == 1:
                return payload
            if not actual_failure and reads[0] <= 22:
                # More than both former 3s and 8s disconnect thresholds.
                observed.append(latest()['serialStatus']['portStatus']['COM_TEST'])
                return b''
            state.running = False
            return payload

        def capture_thread(thread):
            if thread.name.startswith('fsr-serial-'):
                workers.append(thread)

        connection.read.side_effect = read_chunk
        with (
            mock.patch.object(realtime_services.threading.Thread, 'start', capture_thread),
            mock.patch.object(realtime_services.time, 'monotonic', side_effect=lambda: clock[0]),
            mock.patch.object(realtime_services.time, 'sleep'),
            mock.patch.object(serial, 'Serial', return_value=connection) as open_port,
            mock.patch.object(realtime_services.FsrStepPipeline, 'add_sample', add_sample),
            mock.patch.object(list_ports, 'comports', return_value=[SimpleNamespace(
                device='COM_TEST', description='Bluetooth serial', hwid='LOCALMFG&0002',
            )]),
            mock.patch.dict(os.environ, {
                'GAIT_RECORDINGS_DIR': self.recordings_dir.name,
                'FSR_SERIAL_AUTO': 'true', 'FSR_SERIAL_PORTS': 'COM_TEST',
            }),
        ):
            realtime_services.install_realtime_services(app, state)
            latest = self._endpoint(app, '/fsr/latest', 'GET')
            self._endpoint(app, '/fsr/connect', 'POST')()
            self.assertEqual(len(workers), 1)
            state.running = True
            workers[0].run()
            result = latest()
            return result, observed, open_port.call_count, connection.close.call_count

    def test_serial_silence_keeps_same_port_and_resumes_real_frames(self):
        result, observed, opens, closes = self._exercise_serial_worker()
        self.assertEqual(opens, 1)
        self.assertEqual(closes, 1)  # Only at explicit worker shutdown.
        status = result['serialStatus']['portStatus']['COM_TEST']
        self.assertEqual(status['frameCount'], 2)
        self.assertEqual(status['reconnectCount'], 0)
        stalled = [item for item in observed if item['state'] == 'stalled']
        self.assertTrue(stalled)
        self.assertTrue(all(item['connected'] and not item['dataFresh'] for item in stalled))
        self.assertTrue(all(item['frameCount'] == 1 for item in observed))

    def test_actual_serial_error_still_reopens_port(self):
        result, _, opens, closes = self._exercise_serial_worker(actual_failure=True)
        self.assertEqual(opens, 2)
        self.assertEqual(closes, 2)
        status = result['serialStatus']['portStatus']['COM_TEST']
        self.assertEqual(status['reconnectCount'], 1)
        self.assertEqual(status['frameCount'], 1)
        self.assertIn('ReadFile failed', status['lastDisconnectReason'])

    def test_step_processing_failure_does_not_close_serial_port(self):
        result, _, opens, closes = self._exercise_serial_worker(processing_failure=True)
        self.assertEqual((opens, closes), (1, 1))
        status = result['serialStatus']['portStatus']['COM_TEST']
        self.assertEqual(status['reconnectCount'], 0)
        self.assertEqual(status['processingErrorCount'], 1)
        self.assertEqual(status['rawFrameCount'], 2)
        self.assertEqual(status['frameCount'], 1)

    def test_video_only_clip_is_persisted_and_archive_is_completed(self):
        app = FastAPI()
        state = self._state()
        with (
            mock.patch.object(realtime_services.cv2, "VideoWriter", _FakeWriter),
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
            mock.patch.object(
                realtime_services,
                "analyze_cropped_segment",
                side_effect=ValueError("pose unavailable"),
            ),
        ):
            realtime_services.install_realtime_services(app, state)
            start = self._endpoint(app, "/recording/start", "POST")
            create_clip = self._endpoint(
                app, "/segments-v2/{session_id}", "POST"
            )
            stop = self._endpoint(app, "/recording/stop", "POST")
            delete_archive = self._endpoint(
                app,
                "/sessions/{session_id}/recordings/{stored_archive_id}",
                "DELETE",
            )

            started = start("s-record", "LEFT", "RIGHT")
            time.sleep(0.55)
            clip = create_clip(
                "s-record",
                {
                    "startOffsetSec": 0.0,
                    "endOffsetSec": 0.5,
                    "scanType": "segment",
                    "note": "Persistent clip",
                },
            )
            stopped = stop()

        self.assertEqual(clip["analysisStatus"], "video_only")
        self.assertTrue(clip["videoStored"])
        self.assertEqual(stopped["archiveId"], started["archiveId"])
        self.assertEqual(len(_FakeWriter.paths), 2)
        self.assertEqual(
            os.path.dirname(_FakeWriter.paths[0]),
            os.path.dirname(_FakeWriter.paths[1]),
        )
        self.assertEqual(
            {os.path.basename(path) for path in _FakeWriter.paths},
            {"frontal.avi", "sagittal.avi"},
        )

        conn = database.get_db_connection()
        try:
            archive = conn.execute(
                "SELECT status FROM recording_archives WHERE id = ?",
                (started["archiveId"],),
            ).fetchone()
            segment_count = conn.execute(
                "SELECT COUNT(*) FROM segments WHERE id = ?",
                (clip["segmentId"],),
            ).fetchone()[0]
            scan_count = conn.execute(
                "SELECT COUNT(*) FROM scans WHERE id = ?",
                (clip["scanId"],),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(archive["status"], "complete")
        self.assertEqual(segment_count, 1)
        self.assertEqual(scan_count, 1)

        deleted = delete_archive("s-record", started["archiveId"])
        self.assertEqual(deleted["deletedFiles"], 5)
        self.assertEqual(deleted["deletedSegments"], 1)
        self.assertEqual(deleted["deletedScans"], 1)
        self.assertTrue(all(not Path(path).exists() for path in _FakeWriter.paths))

        conn = database.get_db_connection()
        try:
            remaining_archive = conn.execute(
                "SELECT COUNT(*) FROM recording_archives WHERE id = ?",
                (started["archiveId"],),
            ).fetchone()[0]
            remaining_segment = conn.execute(
                "SELECT COUNT(*) FROM segments WHERE id = ?",
                (clip["segmentId"],),
            ).fetchone()[0]
            remaining_scan = conn.execute(
                "SELECT COUNT(*) FROM scans WHERE id = ?",
                (clip["scanId"],),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(remaining_archive, 0)
        self.assertEqual(remaining_segment, 0)
        self.assertEqual(remaining_scan, 0)

    def test_archive_preserves_native_hd_frame_size(self):
        app = FastAPI()
        state = self._state()
        state.CAMERA_REQUEST_WIDTH = 1280
        state.CAMERA_REQUEST_HEIGHT = 720
        state.latest_raw_frame_0 = np.zeros((720, 1280, 3), dtype=np.uint8)
        state.latest_raw_frame_1 = np.zeros((720, 1280, 3), dtype=np.uint8)
        with (
            mock.patch.object(realtime_services.cv2, "VideoWriter", _FakeWriter),
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, state)
            start = self._endpoint(app, "/recording/start", "POST")
            stop = self._endpoint(app, "/recording/stop", "POST")
            started = start("s-record", "LEFT", "RIGHT")
            stopped = stop()

        self.assertEqual(
            started["frameSizes"],
            {
                "frontal": {"width": 1280, "height": 720},
                "sagittal": {"width": 1280, "height": 720},
            },
        )
        self.assertEqual(stopped["frameSizes"], started["frameSizes"])
        self.assertTrue(all(call[3] == (1280, 720) for call in _FakeWriter.calls))

    def test_persisted_fsr_stream_rebuilds_newton_heatmap_after_recording(self):
        app = FastAPI()
        state = self._state()
        with (
            mock.patch.object(realtime_services.cv2, "VideoWriter", _FakeWriter),
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, state)
            start = self._endpoint(app, "/recording/start", "POST")
            stop = self._endpoint(app, "/recording/stop", "POST")
            get_fsr = self._endpoint(
                app,
                "/sessions/{session_id}/recordings/{stored_archive_id}/fsr-analysis",
                "GET",
            )
            started = start("s-record", "LEFT", "RIGHT")
            stop()
            matrix = [[float(row * 4 + column) for column in range(4)]
                      for row in range(12)]
            sample = {
                "time": 0.0,
                "side": "left",
                "total": 1128.0,
                "regions": {"heel": 100.0, "midfoot": 300.0, "forefoot": 728.0},
                "values": matrix,
                "forceValues": matrix,
                "unit": "N_estimated",
                "sourceUnit": "raw_adc",
                "timestampValid": True,
                "transportLatencyMs": 2.0,
            }
            fsr_path = (
                Path(self.recordings_dir.name)
                / "s-record"
                / started["archiveId"]
                / "fsr.jsonl"
            )
            fsr_path.write_text(
                json.dumps(sample) + "\n"
                + json.dumps({**sample, "side": "right"}) + "\n",
                encoding="utf-8",
            )
            analysis = get_fsr("s-record", started["archiveId"])

        self.assertTrue(analysis["persistent"])
        self.assertEqual(len(analysis["replayFrames"]), 2)
        self.assertEqual(analysis["replayFrames"][0]["values"], matrix)
        self.assertEqual(analysis["replayFrames"][0]["forceValues"], matrix)
        self.assertEqual(
            analysis["synchronization"]["sourceTimestampCoverage"], 1.0
        )

    def test_archive_fps_adapts_below_measured_capture_rate(self):
        app = FastAPI()
        state = self._state()
        now = time.time()
        state.capture_times_0 = deque(now - index / 12.5 for index in range(30, -1, -1))
        state.capture_times_1 = deque(now - index / 12.5 for index in range(30, -1, -1))
        state.pose_times_0 = deque(now - index / 10.0 for index in range(25, -1, -1))
        state.pose_times_1 = deque(now - index / 10.0 for index in range(25, -1, -1))
        state.pose_inference_times_0 = deque(state.pose_times_0)
        state.pose_inference_times_1 = deque(state.pose_times_1)
        state.pose_reliable_times_0 = deque(now - index / 8.0 for index in range(20, -1, -1))
        state.pose_reliable_times_1 = deque(now - index / 8.0 for index in range(20, -1, -1))
        state.camera_health_0 = {"qualityReady": True}
        state.camera_health_1 = {"qualityReady": True}
        with (
            mock.patch.object(realtime_services.cv2, "VideoWriter", _FakeWriter),
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(os.environ, {"GAIT_RECORDINGS_DIR": self.recordings_dir.name}),
        ):
            realtime_services.install_realtime_services(app, state)
            start = self._endpoint(app, "/recording/start", "POST")
            stop = self._endpoint(app, "/recording/stop", "POST")
            result = start("s-record", "LEFT", "RIGHT")
            stopped = stop()

        self.assertAlmostEqual(result["recordingFps"], 11.88, places=2)
        self.assertAlmostEqual(stopped["recordingFps"], 11.88, places=2)
        self.assertTrue(all(abs(call[2] - 11.88) < 0.01 for call in _FakeWriter.calls))

    def test_raw_recording_starts_with_pose_warning_instead_of_losing_video(self):
        app = FastAPI()
        state = self._state()
        now = time.time()
        state.capture_times_0 = deque(now - index / 20 for index in range(40, -1, -1))
        state.capture_times_1 = deque(now - index / 20 for index in range(40, -1, -1))
        state.pose_inference_times_0 = deque(now - index / 10 for index in range(20, -1, -1))
        state.pose_inference_times_1 = deque(now - index / 10 for index in range(20, -1, -1))
        state.pose_times_0 = deque()
        state.pose_times_1 = deque()
        state.pose_reliable_times_0 = deque()
        state.pose_reliable_times_1 = deque()
        state.camera_health_0 = {"qualityReady": True}
        state.camera_health_1 = {"qualityReady": True}
        with (
            mock.patch.object(realtime_services.cv2, "VideoWriter", _FakeWriter),
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(os.environ, {"GAIT_RECORDINGS_DIR": self.recordings_dir.name}),
        ):
            realtime_services.install_realtime_services(app, state)
            start = self._endpoint(app, "/recording/start", "POST")
            stop = self._endpoint(app, "/recording/stop", "POST")
            result = start("s-record", "LEFT", "RIGHT")
            stop()
        self.assertEqual(result["status"], "started")
        self.assertTrue(result["warnings"])

    def test_recording_seeds_recent_standing_pose_for_fast_first_cycle(self):
        app = FastAPI()
        state = self._state()
        state.live_gait_samples.append({
            "time": time.time(),
            "left_knee": 7.0,
            "right_knee": 8.0,
            "left_ankle": 90.0,
            "right_ankle": 90.0,
            "left_hip": 5.0,
            "right_hip": 6.0,
            "pelvic_tilt": 0.0,
            "trunk_tilt": 2.0,
            "frontal_trunk_lean": 0.5,
            "footTracking": {},
            "poseQuality": {
                "bilateralSagittalReliable": True,
                "frameReliable": True,
            },
        })
        with (
            mock.patch.object(realtime_services.cv2, "VideoWriter", _FakeWriter),
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, state)
            start = self._endpoint(app, "/recording/start", "POST")
            start("s-record", "LEFT", "RIGHT")

        self.assertEqual(list(state.recorded_timestamps), [0.0])
        self.assertEqual(list(state.recorded_left_knee), [7.0])
        self.assertEqual(len(state.live_gait_samples), 1)
        self.assertEqual(
            state.live_gait_samples[0]["time"],
            state.record_start_time,
        )

    def test_camera_probe_results_are_reused_when_configuration_is_applied(self):
        class _FakeCapture:
            def read(self):
                return True, np.zeros((240, 320, 3), dtype=np.uint8)

            def release(self):
                return None

        app = FastAPI()
        state = self._state()
        state.camera_workers_started = False
        state.camera_configured = False
        probed_indexes = []
        stop_calls = []

        def open_camera(index, _label, **_options):
            probed_indexes.append(index)
            return _FakeCapture() if index in (0, 1) else None

        def start_camera_workers():
            state.camera_workers_started = True
            return True

        def stop_camera_workers():
            stop_calls.append(True)
            state.camera_workers_started = False
            return True

        state.open_camera = open_camera
        state.start_camera_workers = start_camera_workers
        state.stop_camera_workers = stop_camera_workers

        with (
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {
                    "FSR_SERIAL_AUTO": "false",
                    "GAIT_RECORDINGS_DIR": self.recordings_dir.name,
                },
            ),
        ):
            realtime_services.install_realtime_services(app, state)

        devices = self._endpoint(app, "/camera/devices", "GET")
        configure = self._endpoint(app, "/camera/configure", "POST")
        first = devices()
        configured = configure(
            {
                "frontalIndex": 0,
                "sagittalIndex": 1,
                "singleCameraMode": False,
            }
        )
        second = devices()
        reconfigured = configure(
            {
                "frontalIndex": 1,
                "sagittalIndex": 0,
                "singleCameraMode": False,
            }
        )

        self.assertEqual([item["index"] for item in first["devices"]], [0, 1])
        self.assertEqual(probed_indexes, list(range(6)))
        self.assertEqual(configured["status"], "configured")
        self.assertFalse(configured["restarted"])
        self.assertTrue(second["configured"])
        self.assertEqual(second["devices"], first["devices"])
        self.assertEqual(reconfigured["status"], "configured")
        self.assertTrue(reconfigured["restarted"])
        self.assertEqual(stop_calls, [True])
        self.assertTrue(state.camera_workers_started)

    def test_camera_preview_uses_live_selected_frame_while_workers_run(self):
        app = FastAPI()
        state = self._state()
        state.camera_workers_started = True
        state.camera_configured = True
        state.latest_raw_frame_0 = np.full(
            (720, 1280, 3),
            (20, 100, 220),
            dtype=np.uint8,
        )
        state.STREAM_JPEG_QUALITY = 84
        state.open_camera = mock.Mock(
            side_effect=AssertionError("selected live camera must not be reopened")
        )

        with (
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {
                    "FSR_SERIAL_AUTO": "false",
                    "GAIT_RECORDINGS_DIR": self.recordings_dir.name,
                },
            ),
        ):
            realtime_services.install_realtime_services(app, state)

        preview = self._endpoint(app, "/camera/preview/{index}", "GET")
        response = preview(0)
        decoded = realtime_services.cv2.imdecode(
            np.frombuffer(response.body, dtype=np.uint8),
            realtime_services.cv2.IMREAD_COLOR,
        )

        self.assertEqual(response.media_type, "image/jpeg")
        self.assertEqual(decoded.shape[:2], (720, 1280))
        state.open_camera.assert_not_called()

    def test_replay_frame_maps_wall_clock_offset_to_shorter_avi_timeline(self):
        app = FastAPI()
        state = self._state()
        video_id = "a" * 32
        archive_id = "rec-timeline"
        video_dir = (
            Path(self.recordings_dir.name) / "s-record" / archive_id
        )
        video_dir.mkdir(parents=True)
        video_path = video_dir / "frontal.avi"
        writer = realtime_services.cv2.VideoWriter(
            str(video_path),
            realtime_services.cv2.VideoWriter_fourcc(*"MJPG"),
            10.0,
            (64, 48),
        )
        self.assertTrue(writer.isOpened())
        for index in range(20):
            writer.write(np.full((48, 64, 3), index * 10, dtype=np.uint8))
        writer.release()

        conn = database.get_db_connection()
        conn.execute(
            """INSERT INTO recording_archives
               (id, session_id, frontal_video_id, sagittal_video_id,
                started_at, stopped_at, duration_sec,
                frontal_frame_count, sagittal_frame_count, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                archive_id,
                "s-record",
                video_id,
                "b" * 32,
                "2026-08-24T00:00:00Z",
                "2026-08-24T00:00:04Z",
                4.0,
                20,
                0,
                "complete",
            ),
        )
        conn.commit()
        conn.close()

        with (
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, state)
        frame = self._endpoint(
            app,
            "/session-video-frame/{session_id}/{video_id}",
            "GET",
        )

        response = frame("s-record", video_id, 3.8)

        self.assertEqual(response.media_type, "image/jpeg")
        self.assertGreater(len(response.body), 100)

    def test_archived_mjpeg_replay_rejects_unsafe_playback_rate(self):
        app = FastAPI()
        state = self._state()
        with (
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, state)
        stream = self._endpoint(
            app,
            "/session-video/{session_id}/{video_id}",
            "GET",
        )

        for rate in (0.0, 0.24, 2.01, float("nan")):
            with self.subTest(rate=rate):
                with self.assertRaises(realtime_services.HTTPException) as ctx:
                    stream("s-record", "a" * 32, 0.0, 1.0, False, rate)
                self.assertEqual(ctx.exception.status_code, 422)

    def test_pose_replay_honors_requested_analysis_revision(self):
        conn = database.get_db_connection()
        conn.execute(
            """INSERT INTO scans
               (id, session_id, scan_type, label, recorded_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("clip-pose", "s-record", "manual", "Pose clip", "2026-08-19T10:01:00Z"),
        )
        for revision, current in ((1, 0), (2, 1)):
            pose = {
                "unit": "normalized_image",
                "views": {
                    "frontal": [
                        {
                            "time": float(revision),
                            "landmarks": {
                                "left_hip": {
                                    "x": 0.4,
                                    "y": 0.5,
                                    "visibility": 0.9,
                                }
                            },
                        }
                    ]
                },
            }
            conn.execute(
                """INSERT INTO analysis_runs
                   (id, scan_id, archive_id, algorithm_version, revision,
                    gait_json, fsr_json, pose_json, status, is_current, created_at)
                   VALUES (?, ?, NULL, ?, ?, ?, ?, ?, 'complete', ?, ?)""",
                (
                    f"run-pose-{revision}",
                    "clip-pose",
                    f"algorithm-v{revision}",
                    revision,
                    "{}",
                    "{}",
                    json.dumps(pose),
                    current,
                    f"2026-08-19T10:0{revision}:00Z",
                ),
            )
        conn.commit()
        conn.close()

        app = FastAPI()
        with (
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, self._state())
        replay = self._endpoint(
            app,
            "/scans/{scan_id}/pose-replay",
            "GET",
        )

        requested = replay("clip-pose", "frontal", 1)
        self.assertEqual(requested["analysisRevision"], 1)
        self.assertEqual(requested["algorithmVersion"], "algorithm-v1")
        self.assertEqual(requested["views"]["frontal"][0]["time"], 1.0)

        current = replay("clip-pose", "frontal")
        self.assertEqual(current["analysisRevision"], 2)
        self.assertEqual(current["algorithmVersion"], "algorithm-v2")
        self.assertEqual(current["views"]["frontal"][0]["time"], 2.0)

    def test_pose_replay_rejects_non_positive_revision(self):
        app = FastAPI()
        with (
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, self._state())
        replay = self._endpoint(
            app,
            "/scans/{scan_id}/pose-replay",
            "GET",
        )

        with self.assertRaises(realtime_services.HTTPException) as ctx:
            replay("clip-pose", "frontal", 0)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_patient_library_lists_recordings_from_previous_sessions(self):
        conn = database.get_db_connection()
        conn.execute(
            """INSERT INTO sessions
               (id, patient_id, created_at, is_practice_mode)
               VALUES (?, ?, ?, ?)""",
            ("s-previous", "p-record", "2026-08-18T10:00:00Z", 0),
        )
        for archive_id, session_id, video_prefix in (
            ("rec-current", "s-record", "c"),
            ("rec-previous", "s-previous", "d"),
        ):
            conn.execute(
                """INSERT INTO recording_archives
                   (id, session_id, frontal_video_id, sagittal_video_id,
                    started_at, duration_sec, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    archive_id,
                    session_id,
                    video_prefix * 32,
                    ("e" if video_prefix == "c" else "f") * 32,
                    "2026-08-24T00:00:00Z",
                    5.0,
                    "complete",
                ),
            )
        conn.commit()
        conn.close()

        app = FastAPI()
        with (
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, self._state())
        library = self._endpoint(
            app,
            "/patients/{patient_id}/recordings",
            "GET",
        )

        result = library("p-record")

        self.assertEqual(len(result), 2)
        self.assertEqual(
            {item["sessionId"] for item in result},
            {"s-record", "s-previous"},
        )
        self.assertTrue(all(item["sessionCreatedAt"] for item in result))

    def test_reference_recording_requires_review_and_can_be_approved(self):
        conn = database.get_db_connection()
        conn.execute(
            "UPDATE sessions SET is_reference = 1 WHERE id = ?",
            ("s-record",),
        )
        conn.execute(
            """INSERT INTO recording_archives
               (id, session_id, frontal_video_id, sagittal_video_id,
                started_at, stopped_at, duration_sec, status, reference_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "rec-reference",
                "s-record",
                "a" * 32,
                "b" * 32,
                "2026-08-26T10:00:00Z",
                "2026-08-26T10:00:05Z",
                5.0,
                "complete",
                "draft",
            ),
        )
        conn.commit()
        conn.close()

        app = FastAPI()
        with (
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, self._state())
        approve = self._endpoint(
            app,
            "/sessions/{session_id}/recordings/{stored_archive_id}/approve-reference",
            "POST",
        )
        library = self._endpoint(app, "/sessions/{session_id}/recordings", "GET")

        result = approve("s-record", "rec-reference")
        stored = next(
            item for item in library("s-record")
            if item["archiveId"] == "rec-reference"
        )

        self.assertEqual(result["status"], "approved")
        self.assertTrue(stored["isReference"])
        self.assertEqual(stored["referenceStatus"], "approved")

    def test_live_camera_pair_number_only_advances_for_new_complete_cycle(self):
        app = FastAPI()
        state = self._state()
        base = time.time() - 10.0

        def samples(start, end):
            timestamps = np.arange(start, end, 1.0 / 30.0)
            phase = 2 * np.pi * timestamps / 1.2
            result = []
            for index, relative_time in enumerate(timestamps):
                result.append({
                    "time": base + float(relative_time),
                    "left_knee": float(30 + 25 * np.cos(phase[index])),
                    "right_knee": float(28 + 23 * np.cos(phase[index] - np.pi)),
                    "left_hip": float(20 + 8 * np.sin(phase[index])),
                    "right_hip": float(19 + 7 * np.sin(phase[index] - np.pi)),
                    "trunk_tilt": 4.0,
                    "frontal_trunk_lean": float(2 * np.sin(phase[index])),
                    "poseQuality": {
                        "frameReliable": True,
                        "meanVisibility": 0.9,
                    },
                })
            return result

        initial_samples = samples(0.0, 8.0)
        for sample in initial_samples[:12]:
            sample["poseQuality"]["targetLegReliable"] = False
        state.live_gait_samples.extend(initial_samples)
        state.latest_sagittal_pose_at = time.time()
        with (
            mock.patch.object(realtime_services.threading.Thread, "start"),
            mock.patch.dict(
                os.environ,
                {"GAIT_RECORDINGS_DIR": self.recordings_dir.name},
            ),
        ):
            realtime_services.install_realtime_services(app, state)
        gait = self._endpoint(app, "/gait/steps", "GET")

        first = gait(5)
        repeated = gait(5)
        self.assertGreater(first["cycleCount"], 0)
        self.assertEqual(first["rejectedSampleCount"], 12)
        waveform = first["liveWaveform"]
        self.assertIn("central", waveform)
        self.assertEqual(waveform["windowSeconds"], 3.0)
        self.assertGreater(len(waveform["timestamps"]), 20)
        self.assertEqual(
            len(waveform["central"]["trunk"]),
            len(waveform["timestamps"]),
        )
        self.assertEqual(
            len(waveform["central"]["lateral_trunk"]),
            len(waveform["timestamps"]),
        )
        self.assertEqual(
            repeated["cycles"][-1]["pairIndex"],
            first["cycles"][-1]["pairIndex"],
        )

        state.live_gait_samples.extend(samples(8.0, 10.0))
        state.latest_sagittal_pose_at = time.time()
        advanced = gait(5)
        self.assertGreater(
            advanced["cycles"][-1]["pairIndex"],
            first["cycles"][-1]["pairIndex"],
        )

    def test_analysis_scan_updates_uses_qa_curves_and_summary_values(self):
        updates = realtime_services.analysis_scan_updates(
            {
                "metrics": {
                    "knee": {
                        "left": {"mean": [1, 2, 3]},
                        "right": {"mean": [4, 5, 6]},
                    },
                    "hip": {
                        "left": {"mean": [7, 8]},
                        "right": {"mean": [9, 10]},
                    },
                },
                "statistics": {"cadence": {"mean": 82.5}},
            },
            {
                "peakForePairs": [
                    {"fsi": 80.0},
                    {"fsi": 90.0},
                    {"fsi": None},
                ]
            },
        )

        self.assertEqual(updates["left_knee"], [1.0, 2.0, 3.0])
        self.assertEqual(updates["right_knee"], [4.0, 5.0, 6.0])
        self.assertEqual(updates["left_hip"], [7.0, 8.0])
        self.assertEqual(updates["right_hip"], [9.0, 10.0])
        self.assertEqual(updates["cadence"], 82.5)
        self.assertEqual(updates["plantar_load_symmetry"], 85.0)


if __name__ == "__main__":
    unittest.main()
