import json
import os
import socket
import threading
import time
import traceback
import uuid
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from fastapi import HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from algorithms import analyze_cropped_segment
from database import get_db_connection
from fsr_force import matrix_to_newton, matrix_total, region_totals
from fsr_serial import FsrSerialFrameParser, configured_serial_ports
from fsr_step_pipeline import FsrStepPipeline, VALID_WINDOWS
from gait_cycle_pipeline import (
    analyze_gait_cycles,
    build_camera_gait_cycles,
)
from pose_quality import summarize_pose_quality
from stereo_calibration import StereoCalibrationError


def install_realtime_services(app, state):
    """Install local camera archiving, FSR reception, and virtual clip APIs."""
    recordings_dir = Path(
        os.getenv(
            "GAIT_RECORDINGS_DIR",
            str(Path(__file__).resolve().parent / "recordings"),
        )
    )
    recordings_dir.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    archive_active = False
    writers = {"frontal": None, "sagittal": None}
    video_ids = {"frontal": None, "sagittal": None}
    archive_id = None
    archive_session_id = None
    archive_started_at = 0.0
    archive_frame_counts = {"frontal": 0, "sagittal": 0}
    fsr_lock = threading.Lock()
    latest_fsr = {"left": None, "right": None}
    recorded_fsr_samples = []
    fsr_steps = FsrStepPipeline(window_size=5)
    fsr_serial_status = {
        'enabled': os.getenv('FSR_SERIAL_AUTO', 'true').lower() in ('1', 'true', 'yes'),
        'started': False,
        'ports': [],
        'connectedPorts': [],
        'lastError': '',
    }
    gait_cycle_lock = threading.Lock()
    live_camera_cycles = deque(maxlen=8)
    gait_pair_sequence = 0
    last_camera_cycle_end = None
    fsr_filter = {
        "left": {"frames": deque(maxlen=5), "baseline": None},
        "right": {"frames": deque(maxlen=5), "baseline": None},
    }
    camera_probe_lock = threading.Lock()
    camera_probe_cache = {"probedAt": 0.0, "devices": []}
    camera_probe_cache_seconds = max(
        30.0,
        float(os.getenv("CAMERA_PROBE_CACHE_SECONDS", "300")),
    )
    camera_max_probe_index = min(
        10,
        max(0, int(os.getenv("CAMERA_MAX_PROBE_INDEX", "5"))),
    )

    conn = get_db_connection()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS fsr_region_analyses (
            scan_id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gait_cycle_analyses (
            scan_id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    # A backend restart must never discard an existing file. Mark unfinished
    # rows as interrupted while keeping their video IDs available for recovery.
    conn.execute(
        """UPDATE recording_archives
           SET status = 'interrupted',
               stopped_at = COALESCE(stopped_at, ?)
           WHERE status = 'recording'""",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),),
    )
    conn.commit()
    conn.close()

    def probe_camera(index: int):
        """Open one candidate briefly; this is only used before capture workers start."""
        # On Windows, CAP_ANY may fall through to MSMF/other drivers and block
        # for tens of seconds for an index that does not exist. Device discovery
        # uses the configured primary backend only; capture workers retain the
        # normal fallback path after a real device has been selected.
        capture = state.open_camera(
            index,
            f"Camera setup probe {index}",
            allow_fallback=False,
        )
        if capture is None:
            return None
        try:
            success, frame = capture.read()
            if not success or frame is None:
                return None
            height, width = frame.shape[:2]
            return {"index": index, "label": f"Camera index {index}", "width": width, "height": height}
        finally:
            capture.release()

    def available_camera_devices(max_index: int | None = None, force: bool = False):
        scan_limit = camera_max_probe_index if max_index is None else min(
            camera_max_probe_index,
            max(0, int(max_index)),
        )
        with camera_probe_lock:
            if getattr(state, "camera_workers_started", False):
                if camera_probe_cache["devices"]:
                    return [dict(device) for device in camera_probe_cache["devices"]]
                configured_indexes = {
                    value
                    for value in (
                        getattr(state, "CAMERA_FRONTAL_INDEX", None),
                        getattr(state, "CAMERA_SAGITTAL_INDEX", None),
                    )
                    if value is not None
                }
                return [
                    {
                        "index": int(index),
                        "label": f"Camera index {index}",
                        "width": None,
                        "height": None,
                    }
                    for index in sorted(configured_indexes)
                ]
            now = time.monotonic()
            if (
                not force
                and camera_probe_cache["probedAt"] > 0.0
                and now - camera_probe_cache["probedAt"]
                <= camera_probe_cache_seconds
            ):
                return [dict(device) for device in camera_probe_cache["devices"]]

            devices = [
                device
                for index in range(scan_limit + 1)
                if (device := probe_camera(index))
            ]
            camera_probe_cache["probedAt"] = time.monotonic()
            camera_probe_cache["devices"] = devices
            return [dict(device) for device in devices]

    def normalize_matrix(values):
        if not isinstance(values, list) or not values:
            return []
        try:
            rows = [list(map(float, row)) for row in values]
        except (TypeError, ValueError):
            return []
        if not rows or len({len(row) for row in rows}) != 1:
            return []
        if len(rows) == 4 and len(rows[0]) == 12:
            return [list(column) for column in zip(*rows)]
        return rows

    def filter_fsr_matrix(side, matrix):
        """Keep raw inverse ADC while rejecting isolated serial spikes."""
        raw = np.asarray(matrix, dtype=float)
        channel = fsr_filter[side]
        channel["frames"].append(raw)
        filtered = np.median(np.stack(channel["frames"]), axis=0)
        return filtered.round(2).tolist()

    def build_region_analysis(samples, start_t, end_t, window_size=7):
        pipeline = FsrStepPipeline(window_size=window_size)
        selected = sorted(
            (
                sample for sample in samples
                if start_t <= sample["time"] <= end_t
            ),
            key=lambda sample: sample["time"],
        )
        replay_frames = []
        last_replay_time = {"left": None, "right": None}
        for sample in selected:
            pipeline.add_sample(sample["side"], sample["time"], sample["regions"])
            # Retain a 15 Hz stream for visual replay.  It is dense enough to
            # follow a video scrubber while keeping stored clip analyses compact.
            side = sample["side"]
            previous = last_replay_time.get(side)
            if previous is None or sample["time"] - previous >= 1.0 / 15.0:
                replay_frames.append({
                    "time": round(float(sample["time"]), 4),
                    "side": side,
                    "unit": sample.get("unit", "N_estimated"),
                    "regions": sample["regions"],
                    "forceValues": sample.get("forceValues", []),
                })
                last_replay_time[side] = sample["time"]
        result = pipeline.analysis(
            healthy_leg=getattr(state, "healthy_leg", "LEFT"),
            prosthetic_leg=getattr(state, "prosthetic_leg", "RIGHT"),
        )
        result["cycleAnchors"] = pipeline.all_pairs()
        result["replayFrames"] = replay_frames
        result["replaySampleRateHz"] = 15
        return result
    def reset_live_gait_cycles():
        nonlocal gait_pair_sequence, last_camera_cycle_end
        with gait_cycle_lock:
            live_camera_cycles.clear()
            gait_pair_sequence = 0
            last_camera_cycle_end = None

    def target_leg_sample_reliable(quality):
        if not isinstance(quality, dict):
            return True
        return bool(
            quality.get(
                "targetLegReliable",
                quality.get("frameReliable", True),
            )
        )

    def build_live_gait(window_size=5, recorded_range=None):
        """Build gait cycles from sagittal-camera motion, independently of FSR."""
        nonlocal gait_pair_sequence, last_camera_cycle_end
        if recorded_range is None:
            gait_lock = getattr(state, "live_gait_lock", None)
            if gait_lock is None:
                samples = list(getattr(state, "live_gait_samples", []))
            else:
                with gait_lock:
                    samples = list(getattr(state, "live_gait_samples", []))
            cutoff = time.time() - 30.0
            samples = [sample for sample in samples if sample.get("time", 0.0) >= cutoff]
            quality_samples = [sample.get("poseQuality", {}) for sample in samples]
            measurement_samples = [
                sample
                for sample in samples
                if target_leg_sample_reliable(sample.get("poseQuality", {}))
            ]
            rejected_sample_count = len(samples) - len(measurement_samples)
            timestamps = [sample["time"] for sample in measurement_samples]
            signals = {
                "left_knee": [sample["left_knee"] for sample in measurement_samples],
                "right_knee": [sample["right_knee"] for sample in measurement_samples],
                "left_hip": [sample["left_hip"] for sample in measurement_samples],
                "right_hip": [sample["right_hip"] for sample in measurement_samples],
                "trunk": [sample["trunk_tilt"] for sample in measurement_samples],
            }
        else:
            start_t, end_t = recorded_range
            timestamps_all = list(getattr(state, "recorded_timestamps", []))
            indices = [
                index for index, timestamp in enumerate(timestamps_all)
                if start_t <= timestamp <= end_t
            ]
            recorded_quality = list(getattr(state, "recorded_pose_quality", []))
            quality_samples = [
                recorded_quality[index] if index < len(recorded_quality) else {}
                for index in indices
            ]
            reliable_indices = [
                index
                for index in indices
                if target_leg_sample_reliable(
                    recorded_quality[index]
                    if index < len(recorded_quality)
                    else {}
                )
            ]
            rejected_sample_count = len(indices) - len(reliable_indices)
            timestamps = [timestamps_all[index] for index in reliable_indices]
            recorded_signals = {
                "left_knee": list(getattr(state, "recorded_left_knee", [])),
                "right_knee": list(getattr(state, "recorded_right_knee", [])),
                "left_hip": list(getattr(state, "recorded_left_hip", [])),
                "right_hip": list(getattr(state, "recorded_right_hip", [])),
                "trunk": list(getattr(state, "recorded_trunk_tilt", [])),
            }
            signals = {
                name: [
                    values[index]
                    for index in reliable_indices
                    if index < len(values)
                ]
                for name, values in recorded_signals.items()
            }
        detected_cycles = build_camera_gait_cycles(
            timestamps,
            signals,
            window_size=7,
        )
        if recorded_range is None:
            # The detector reprocesses a rolling signal window on every poll.
            # Promote only newly completed cycles into a persistent sequence so
            # the UI never renumbers old pairs when the 30-second window moves.
            with gait_cycle_lock:
                for cycle in sorted(
                    detected_cycles,
                    key=lambda item: max(
                        float(item["left"]["end"]),
                        float(item["right"]["end"]),
                    ),
                ):
                    cycle_end = max(
                        float(cycle["left"]["end"]),
                        float(cycle["right"]["end"]),
                    )
                    if (
                        last_camera_cycle_end is not None
                        and cycle_end <= last_camera_cycle_end + 0.15
                    ):
                        continue
                    gait_pair_sequence += 1
                    cycle["pairIndex"] = gait_pair_sequence
                    live_camera_cycles.append(cycle)
                    last_camera_cycle_end = cycle_end
                cycles = list(live_camera_cycles)[-int(window_size):]
        else:
            cycles = detected_cycles[-int(window_size):]
        result = analyze_gait_cycles(
            cycles,
            window_size=window_size,
            healthy_leg=getattr(state, "healthy_leg", "LEFT"),
            prosthetic_leg=getattr(state, "prosthetic_leg", "RIGHT"),
        )
        pose_age = time.time() - float(getattr(state, "latest_sagittal_pose_at", 0.0) or 0.0)
        pose_detected = bool(timestamps) if recorded_range is not None else pose_age < 1.5
        pose_quality = summarize_pose_quality(
            quality_samples,
            pose_detected=pose_detected,
            sample_count=len(timestamps),
            cycle_count=len(cycles),
        )
        synchronizer = getattr(state, "camera_synchronizer", None)
        camera_sync = synchronizer.status() if synchronizer is not None else None
        result.update({
            "source": "camera",
            "event": "peak_knee_flexion",
            "sampleCount": len(timestamps),
            "rejectedSampleCount": rejected_sample_count,
            "poseDetected": pose_detected,
            "poseQuality": pose_quality,
            "cameraSynchronization": camera_sync,
            "message": (
                "Move through at least two full strides in the sagittal camera."
                if len(cycles) == 0 else ""
            ),
        })
        return result
    def ingest_serial_fsr(side, matrix, port):
        side = str(side).lower()
        matrix = normalize_matrix(matrix)
        if side not in latest_fsr or not matrix:
            return
        matrix = filter_fsr_matrix(side, matrix)
        force_matrix, force_unit, force_source = matrix_to_newton(matrix, 'raw_adc')
        sample_regions = region_totals(force_matrix)
        sample = {
            'side': side,
            'deviceId': port,
            'unit': force_unit,
            'sourceUnit': 'raw_adc',
            'forceSource': force_source,
            'rows': len(matrix),
            'columns': len(matrix[0]),
            'values': matrix,
            'forceValues': force_matrix,
            'regions': sample_regions,
            'total': matrix_total(force_matrix),
            'receivedAt': time.time(),
            'source': f'serial:{port}',
        }
        with fsr_lock:
            latest_fsr[side] = sample
            step_time = (
                max(0.0, sample['receivedAt'] - state.record_start_time)
                if getattr(state, 'is_recording', False)
                else sample['receivedAt']
            )
            fsr_steps.add_sample(side, step_time, sample_regions)
            if getattr(state, 'is_recording', False):
                recorded_fsr_samples.append({
                    'time': max(0.0, time.time() - state.record_start_time),
                    'side': side,
                    'total': sample['total'],
                    'regions': sample_regions,
                    'forceValues': force_matrix,
                    'unit': force_unit,
                    'forceSource': force_source,
                })

    def fsr_receiver():
        port = int(os.getenv("FSR_UDP_PORT", "8765"))
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            print(f"[FSR] UDP receiver listening locally on port {port}.")
        except OSError as exc:
            print(f"[FSR] Cannot bind UDP port {port}: {exc}")
            return
        while getattr(state, "running", True):
            try:
                raw, address = sock.recvfrom(65535)
                packet = json.loads(raw.decode("utf-8"))
                side = str(packet.get("side", "")).lower()
                matrix = normalize_matrix(packet.get("values", []))
                if packet.get("type") != "fsr_matrix" or side not in latest_fsr or not matrix:
                    continue
                matrix = filter_fsr_matrix(side, matrix)
                force_matrix, force_unit, force_source = matrix_to_newton(
                    matrix,
                    packet.get("unit", "raw_adc"),
                )
                sample_regions = region_totals(force_matrix)
                sample = {
                    "side": side,
                    "deviceId": packet.get("device_id", ""),
                    "unit": force_unit,
                    "sourceUnit": str(packet.get("unit", "raw_adc")).lower(),
                    "forceSource": force_source,
                    "rows": len(matrix),
                    "columns": len(matrix[0]),
                    # Preserve the received matrix for legacy pressure-map clients.
                    "values": matrix,
                    "forceValues": force_matrix,
                    "regions": sample_regions,
                    "total": matrix_total(force_matrix),
                    "receivedAt": time.time(),
                    "source": address[0],
                }
                with fsr_lock:
                    latest_fsr[side] = sample
                    step_time = (
                        max(0.0, sample["receivedAt"] - state.record_start_time)
                        if getattr(state, "is_recording", False)
                        else sample["receivedAt"]
                    )
                    fsr_steps.add_sample(side, step_time, sample_regions)
                    if getattr(state, "is_recording", False):
                        recorded_fsr_samples.append({
                            "time": max(0.0, time.time() - state.record_start_time),
                            "side": side,
                            "total": sample["total"],
                            "regions": sample_regions,
                            "forceValues": sample["forceValues"],
                            "unit": sample["unit"],
                            "forceSource": sample["forceSource"],
                        })
            except (ValueError, UnicodeDecodeError, OSError):
                continue

    def fsr_serial_worker(port):
        try:
            import serial
        except ImportError:
            fsr_serial_status['lastError'] = 'pyserial is not installed'
            return
        baudrate = int(os.getenv('FSR_SERIAL_BAUDRATE', '9600'))
        parser = FsrSerialFrameParser()
        while getattr(state, 'running', True):
            connection = None
            try:
                connection = serial.Serial(port, baudrate, timeout=0.5)
                connection.reset_input_buffer()
                if port not in fsr_serial_status['connectedPorts']:
                    fsr_serial_status['connectedPorts'].append(port)
                fsr_serial_status['lastError'] = ''
                print(f'[FSR] Serial receiver connected to {port} at {baudrate} baud.')
                while getattr(state, 'running', True):
                    raw_line = connection.readline()
                    if not raw_line:
                        continue
                    line = raw_line.decode('utf-8', errors='ignore')
                    for side, matrix in parser.feed_line(line):
                        ingest_serial_fsr(side, matrix, port)
            except (OSError, ValueError, serial.SerialException) as exc:
                fsr_serial_status['lastError'] = f'{port}: {exc}'
            finally:
                if port in fsr_serial_status['connectedPorts']:
                    fsr_serial_status['connectedPorts'].remove(port)
                if connection is not None:
                    try:
                        connection.close()
                    except OSError:
                        pass
            time.sleep(2.0)

    def start_fsr_serial_workers():
        if fsr_serial_status['started']:
            return
        fsr_serial_status['started'] = True
        if not fsr_serial_status['enabled']:
            return
        try:
            from serial.tools import list_ports
        except ImportError:
            fsr_serial_status['lastError'] = 'pyserial is not installed'
            return
        ports = configured_serial_ports(list_ports.comports())
        fsr_serial_status['ports'] = ports
        if not ports:
            fsr_serial_status['lastError'] = 'No outgoing FSR serial port found'
            return
        for port in ports:
            threading.Thread(
                target=fsr_serial_worker,
                args=(port,),
                daemon=True,
                name=f'fsr-serial-{port}',
            ).start()

    def archive_loop():
        nonlocal archive_active, archive_frame_counts
        while getattr(state, "running", True):
            with lock:
                active = archive_active
            if not active:
                time.sleep(0.05)
                continue
            frames = {}
            with state.frame_lock_0:
                if state.latest_frame_0 is not None:
                    frames["frontal"] = state.latest_frame_0.copy()
            with state.frame_lock_1:
                if state.latest_frame_1 is not None:
                    frames["sagittal"] = state.latest_frame_1.copy()
            with state.camera_roles_lock:
                swapped = state.camera_roles_swapped
            if swapped:
                frames["frontal"], frames["sagittal"] = (
                    frames.get("sagittal"), frames.get("frontal")
                )
            with lock:
                if archive_active:
                    for view, writer in writers.items():
                        frame = frames.get(view)
                        if writer is None or frame is None:
                            continue
                        writer.write(cv2.resize(frame, (640, 480)))
                        archive_frame_counts[view] += 1
            time.sleep(0.05)

    def archive_video_path(session_id, stored_archive_id, view):
        safe_session = "".join(
            char for char in str(session_id) if char.isalnum() or char in "-_"
        )
        safe_archive = "".join(
            char
            for char in str(stored_archive_id)
            if char.isalnum() or char in "-_"
        )
        return recordings_dir / safe_session / safe_archive / f"{view}.avi"

    def video_file_path(session_id, video_id):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, frontal_video_id, sagittal_video_id
               FROM recording_archives
               WHERE session_id = ?
                 AND (frontal_video_id = ? OR sagittal_video_id = ?)
               ORDER BY started_at DESC
               LIMIT 1""",
            (session_id, video_id, video_id),
        )
        row = cursor.fetchone()
        conn.close()
        if row is not None:
            view = (
                "frontal"
                if row["frontal_video_id"] == video_id
                else "sagittal"
            )
            grouped = archive_video_path(session_id, row["id"], view)
            if grouped.is_file():
                return grouped
        # Compatibility with recordings created before grouped folders.
        return recordings_dir / f"{video_id}.avi"

    def video_timeline_duration(session_id, video_id):
        """Return the wall-clock duration used by segment offsets."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT duration_sec
               FROM recording_archives
               WHERE session_id = ?
                 AND (frontal_video_id = ? OR sagittal_video_id = ?)
               ORDER BY started_at DESC
               LIMIT 1""",
            (session_id, video_id, video_id),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return 0.0
        return max(0.0, float(row["duration_sec"] or 0.0))

    def video_media_position(capture, timeline_position, timeline_duration):
        """Map a wall-clock offset to the encoded AVI frame timeline.

        The archive loop can write fewer frames than its nominal FPS while pose
        processing is busy. Segment markers use wall-clock time, so seeking the
        AVI with those offsets directly can run past EOF. Scaling by the final
        frame count keeps recorded video, camera curves, and FSR markers aligned.
        """
        requested = max(0.0, float(timeline_position))
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if timeline_duration <= 0 or fps <= 0 or frame_count <= 1:
            return requested
        last_frame_position = (frame_count - 1) / fps
        ratio = min(requested, timeline_duration) / timeline_duration
        return ratio * last_frame_position

    def video_belongs_to_session(session_id, video_id):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT video_path FROM segments WHERE session_id = ?", (session_id,))
        allowed = False
        for row in cursor.fetchall():
            try:
                stored = json.loads(row["video_path"] or "{}")
                if video_id in stored.values():
                    allowed = True
                    break
            except (json.JSONDecodeError, AttributeError):
                continue
        if not allowed:
            cursor.execute(
                """SELECT 1 FROM recording_archives
                   WHERE session_id = ?
                     AND (frontal_video_id = ? OR sagittal_video_id = ?)
                   LIMIT 1""",
                (session_id, video_id, video_id),
            )
            allowed = cursor.fetchone() is not None
        conn.close()
        return allowed

    def latest_archive_for_session(session_id):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT * FROM recording_archives
               WHERE session_id = ?
               ORDER BY started_at DESC
               LIMIT 1""",
            (session_id,),
        )
        row = cursor.fetchone()
        result = dict(row) if row is not None else None
        conn.close()
        return result

    def finish_archive(status="complete"):
        nonlocal archive_active, writers
        with lock:
            was_active = archive_active
            archive_active = False
            closing = list(writers.values())
            writers = {"frontal": None, "sagittal": None}
            current_archive_id = archive_id
            current_session_id = archive_session_id
            current_started_at = archive_started_at
            counts = dict(archive_frame_counts)
            ids = dict(video_ids)
        for writer in closing:
            if writer is not None:
                writer.release()
        state.is_recording = False
        duration = (
            max(0.0, time.time() - current_started_at)
            if current_started_at > 0
            else 0.0
        )
        if current_archive_id is not None and was_active:
            conn = get_db_connection()
            conn.execute(
                """UPDATE recording_archives
                   SET stopped_at = ?, duration_sec = ?,
                       frontal_frame_count = ?, sagittal_frame_count = ?,
                       status = ?
                   WHERE id = ?""",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    duration,
                    counts["frontal"],
                    counts["sagittal"],
                    status,
                    current_archive_id,
                ),
            )
            conn.commit()
            conn.close()
        sizes = {}
        for view, identifier in ids.items():
            path = (
                archive_video_path(
                    current_session_id,
                    current_archive_id,
                    view,
                )
                if current_archive_id and current_session_id
                else recordings_dir / f"{identifier}.avi"
            )
            sizes[view] = path.stat().st_size if path.is_file() else 0
        return {
            "archiveId": current_archive_id,
            "durationSec": duration,
            "frameCounts": counts,
            "fileSizes": sizes,
            "videoIds": ids,
        }

    threading.Thread(target=fsr_receiver, daemon=True, name="fsr-udp").start()
    threading.Thread(target=archive_loop, daemon=True, name="camera-archive").start()

    @app.get("/fsr/latest")
    def get_latest_fsr():
        start_fsr_serial_workers()
        now = time.time()
        with fsr_lock:
            result = {
                side: (dict(value) if value else None)
                for side, value in latest_fsr.items()
            }
            step_snapshot = fsr_steps.snapshot(
                healthy_leg=getattr(state, "healthy_leg", "LEFT"),
                prosthetic_leg=getattr(state, "prosthetic_leg", "RIGHT"),
            )
        for value in result.values():
            if value is not None:
                value["connected"] = now - value["receivedAt"] < 2.0
        return {
            **result,
            'serialStatus': dict(fsr_serial_status),
            "peakFore": step_snapshot["peakFore"],
            "fsi": step_snapshot["fsi"],
            "forceSource": "formula_estimate",
        }

    @app.get("/fsr/steps")
    def get_fsr_steps(window: int = 5):
        if window not in VALID_WINDOWS:
            raise HTTPException(
                status_code=422,
                detail=f"Window must be one of {VALID_WINDOWS}.",
            )
        with fsr_lock:
            fsr_steps.set_window_size(window)
            return fsr_steps.snapshot(
                healthy_leg=getattr(state, "healthy_leg", "LEFT"),
                prosthetic_leg=getattr(state, "prosthetic_leg", "RIGHT"),
            )

    @app.get("/gait/steps")
    def get_gait_steps(window: int = 5):
        if window not in VALID_WINDOWS:
            raise HTTPException(
                status_code=422,
                detail=f"Window must be one of {VALID_WINDOWS}.",
            )
        return build_live_gait(window_size=window)
    @app.get("/camera/devices")
    def get_camera_devices():
        started_at = time.monotonic()
        devices = available_camera_devices()
        configured = bool(getattr(state, "camera_configured", False))
        return {
            "configured": configured,
            "devices": devices,
            "scanDurationMs": round((time.monotonic() - started_at) * 1000.0, 1),
            "configuration": {
                "singleCameraMode": bool(getattr(state, "SINGLE_CAMERA_MODE", False)),
                "frontalIndex": getattr(state, "CAMERA_FRONTAL_INDEX", None),
                "sagittalIndex": getattr(state, "CAMERA_SAGITTAL_INDEX", None),
            },
            "message": (
                "Camera roles can be changed without restarting the backend."
                if configured else ""
            ),
        }

    @app.get("/camera/preview/{index}")
    def camera_preview(index: int):
        if getattr(state, "camera_workers_started", False):
            raise HTTPException(status_code=409, detail="Camera preview is available only before capture starts.")
        if index < 0 or index > 5:
            raise HTTPException(status_code=422, detail="Camera index must be between 0 and 5.")
        capture = state.open_camera(index, f"Camera preview {index}")
        if capture is None:
            raise HTTPException(status_code=404, detail="Camera index is not available.")
        try:
            success, frame = capture.read()
            if not success or frame is None:
                raise HTTPException(status_code=404, detail="Camera returned no frame.")
            encoded, jpeg = cv2.imencode(".jpg", frame)
            if not encoded:
                raise HTTPException(status_code=500, detail="Cannot encode camera preview.")
            return Response(content=jpeg.tobytes(), media_type="image/jpeg")
        finally:
            capture.release()

    @app.post("/camera/configure")
    def configure_cameras(data: dict):
        if getattr(state, "is_recording", False):
            raise HTTPException(status_code=409, detail="Stop recording before configuring cameras.")
        try:
            frontal_index = int(data.get("frontalIndex"))
            single_camera_mode = bool(data.get("singleCameraMode", False))
            sagittal_index = frontal_index if single_camera_mode else int(data.get("sagittalIndex"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Choose valid camera indexes.") from exc
        if frontal_index < 0 or sagittal_index < 0 or frontal_index > 5 or sagittal_index > 5:
            raise HTTPException(status_code=422, detail="Camera indexes must be between 0 and 5.")
        if not single_camera_mode and frontal_index == sagittal_index:
            raise HTTPException(status_code=422, detail="Choose two different cameras, or enable single-camera mode.")

        requested = [frontal_index] if single_camera_mode else [frontal_index, sagittal_index]
        detected = {device["index"] for device in available_camera_devices()}
        missing = [index for index in requested if index not in detected]
        if missing:
            raise HTTPException(status_code=422, detail=f"Camera index not available: {missing}")

        restarted = bool(getattr(state, "camera_workers_started", False))
        if restarted:
            try:
                state.stop_camera_workers()
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        state.CAMERA_FRONTAL_INDEX = frontal_index
        state.CAMERA_SAGITTAL_INDEX = sagittal_index
        state.SINGLE_CAMERA_MODE = single_camera_mode
        state.camera_configured = True
        with state.camera_roles_lock:
            state.camera_roles_swapped = False
        with state.live_gait_lock:
            state.live_gait_samples.clear()
        synchronizer = getattr(state, "camera_synchronizer", None)
        if synchronizer is not None:
            synchronizer.reset()
        reset_live_gait_cycles()
        try:
            state.start_camera_workers()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "status": "configured",
            "restarted": restarted,
            "configuration": {
                "singleCameraMode": single_camera_mode,
                "frontalIndex": frontal_index,
                "sagittalIndex": sagittal_index,
            },
        }

    @app.get("/camera-status")
    def get_camera_status():
        now = time.time()
        camera_0 = now - float(getattr(state, "latest_frame_0_at", 0.0) or 0.0) < 2.0
        camera_1 = now - float(getattr(state, "latest_frame_1_at", 0.0) or 0.0) < 2.0
        pose_0 = now - float(getattr(state, "latest_pose_0_at", 0.0) or 0.0) < 1.5
        pose_1 = now - float(getattr(state, "latest_pose_1_at", 0.0) or 0.0) < 1.5
        with state.camera_roles_lock:
            swapped = state.camera_roles_swapped
        frontal_index = getattr(state, "CAMERA_FRONTAL_INDEX", 0)
        sagittal_index = getattr(state, "CAMERA_SAGITTAL_INDEX", 1)
        if swapped and not getattr(state, "SINGLE_CAMERA_MODE", False):
            camera_0, camera_1 = camera_1, camera_0
            pose_0, pose_1 = pose_1, pose_0
            frontal_index, sagittal_index = sagittal_index, frontal_index
        if getattr(state, "SINGLE_CAMERA_MODE", False):
            camera_0 = camera_1
            pose_0 = pose_1
        synchronizer = getattr(state, "camera_synchronizer", None)
        sync_status = synchronizer.status() if synchronizer is not None else {
            "enabled": False,
            "synchronized": False,
            "toleranceMs": None,
            "lastErrorMs": None,
            "meanErrorMs": None,
            "pairedSamples": 0,
            "fallbackSamples": 0,
        }
        if getattr(state, "SINGLE_CAMERA_MODE", False):
            sync_status = {
                **sync_status,
                "enabled": False,
                "synchronized": pose_1,
                "mode": "single_camera",
            }
        else:
            sync_status["mode"] = "dual_camera_2d"
        calibration_indices = None
        if (
            getattr(state, "CAMERA_FRONTAL_INDEX", None) is not None
            and getattr(state, "CAMERA_SAGITTAL_INDEX", None) is not None
        ):
            calibration_indices = (
                int(state.CAMERA_FRONTAL_INDEX),
                int(state.CAMERA_SAGITTAL_INDEX),
            )
        calibration_status = state.stereo_calibration.status(calibration_indices)
        return {
            "backendOnline": True,
            "swapped": swapped,
            "configuration": {
                "configured": bool(getattr(state, "camera_configured", False)),
                "singleCameraMode": bool(getattr(state, "SINGLE_CAMERA_MODE", False)),
                "frontalIndex": getattr(state, "CAMERA_FRONTAL_INDEX", None),
                "sagittalIndex": getattr(state, "CAMERA_SAGITTAL_INDEX", None),
                "workersStarted": bool(getattr(state, "camera_workers_started", False)),
            },
            "recording": {
                "active": bool(getattr(state, "is_recording", False)),
                "elapsed": (
                    max(0.0, now - float(getattr(state, "record_start_time", now)))
                    if getattr(state, "is_recording", False) else 0.0
                ),
                "sessionId": getattr(state, "active_session_id", ""),
            },
            "camera0": {
                "connected": camera_0,
                "poseDetected": pose_0,
                "index": frontal_index,
            },
            "camera1": {
                "connected": camera_1,
                "poseDetected": pose_1,
                "index": sagittal_index,
            },
            "synchronization": sync_status,
            "stereoCalibration": calibration_status,
        }

    @app.get("/camera/calibration/status")
    def get_camera_calibration_status():
        indices = None
        if (
            getattr(state, "CAMERA_FRONTAL_INDEX", None) is not None
            and getattr(state, "CAMERA_SAGITTAL_INDEX", None) is not None
        ):
            indices = (
                int(state.CAMERA_FRONTAL_INDEX),
                int(state.CAMERA_SAGITTAL_INDEX),
            )
        return state.stereo_calibration.status(indices)

    @app.get("/camera/calibration/board")
    def get_camera_calibration_board():
        return Response(
            content=state.stereo_calibration.board_png(),
            media_type="image/png",
            headers={
                "Content-Disposition": "attachment; filename=charuco_7x5_30mm.png",
                "X-Print-Size": "A4 landscape, actual size 100%; board 210mm x 150mm",
            },
        )

    @app.post("/camera/calibration/reset")
    def reset_camera_calibration_samples():
        if getattr(state, "is_recording", False):
            raise HTTPException(status_code=409, detail="Stop recording before camera calibration.")
        return state.stereo_calibration.reset_samples()

    @app.post("/camera/calibration/capture")
    def capture_camera_calibration_pair():
        if getattr(state, "SINGLE_CAMERA_MODE", False):
            raise HTTPException(status_code=409, detail="Stereo calibration requires two cameras.")
        if getattr(state, "is_recording", False):
            raise HTTPException(status_code=409, detail="Stop recording before camera calibration.")
        with state.frame_lock_0:
            frame_0 = (
                state.latest_raw_frame_0.copy()
                if getattr(state, "latest_raw_frame_0", None) is not None else None
            )
            captured_ns_0 = int(getattr(state, "latest_frame_0_ns", 0) or 0)
            captured_at_0 = float(getattr(state, "latest_frame_0_at", 0.0) or 0.0)
        with state.frame_lock_1:
            frame_1 = (
                state.latest_raw_frame_1.copy()
                if getattr(state, "latest_raw_frame_1", None) is not None else None
            )
            captured_ns_1 = int(getattr(state, "latest_frame_1_ns", 0) or 0)
            captured_at_1 = float(getattr(state, "latest_frame_1_at", 0.0) or 0.0)
        if (
            frame_0 is None or frame_1 is None
            or time.time() - captured_at_0 > 2.0
            or time.time() - captured_at_1 > 2.0
        ):
            raise HTTPException(status_code=409, detail="Both live camera frames are required.")
        try:
            return state.stereo_calibration.capture_pair(
                frame_0,
                frame_1,
                captured_ns_0,
                captured_ns_1,
                max_skew_ms=float(getattr(state, "CAMERA_SYNC_TOLERANCE_MS", 40.0)),
            )
        except StereoCalibrationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/camera/calibration/solve")
    def solve_camera_calibration():
        if getattr(state, "SINGLE_CAMERA_MODE", False):
            raise HTTPException(status_code=409, detail="Stereo calibration requires two cameras.")
        if getattr(state, "is_recording", False):
            raise HTTPException(status_code=409, detail="Stop recording before camera calibration.")
        try:
            return state.stereo_calibration.solve((
                int(state.CAMERA_FRONTAL_INDEX),
                int(state.CAMERA_SAGITTAL_INDEX),
            ))
        except (StereoCalibrationError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/camera/swap")
    def swap_camera_roles():
        if getattr(state, "SINGLE_CAMERA_MODE", False):
            raise HTTPException(status_code=409, detail="Only one camera is enabled.")
        if getattr(state, "is_recording", False):
            raise HTTPException(
                status_code=409,
                detail="Stop recording before swapping cameras.",
            )
        with state.camera_roles_lock:
            state.camera_roles_swapped = not state.camera_roles_swapped
            swapped = state.camera_roles_swapped
        with state.live_gait_lock:
            state.live_gait_samples.clear()
        synchronizer = getattr(state, "camera_synchronizer", None)
        if synchronizer is not None:
            synchronizer.reset()
        reset_live_gait_cycles()
        state.latest_sagittal_pose_at = 0.0
        return {"status": "swapped", "swapped": swapped}

    @app.post("/recording/start")
    def start_continuous_recording(
        session_id: str,
        healthy: str = Query("LEFT", pattern="^(LEFT|RIGHT)$"),
        prosthetic: str = Query("RIGHT", pattern="^(LEFT|RIGHT)$"),
    ):
        nonlocal archive_active, writers, video_ids
        nonlocal archive_id, archive_session_id, archive_started_at
        nonlocal archive_frame_counts
        if archive_active:
            raise HTTPException(status_code=409, detail="A recording is already active.")
        now = time.time()
        camera_0_ready = (
            now - float(getattr(state, "latest_frame_0_at", 0.0) or 0.0) < 2.0
        )
        camera_1_ready = (
            now - float(getattr(state, "latest_frame_1_at", 0.0) or 0.0) < 2.0
        )
        if not camera_0_ready or (
            not getattr(state, "SINGLE_CAMERA_MODE", False) and not camera_1_ready
        ):
            raise HTTPException(
                status_code=409,
                detail="Both camera streams must be active before recording.",
            )
        conn = get_db_connection()
        session_exists = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        conn.close()
        if session_exists is None:
            raise HTTPException(status_code=404, detail="Session not found.")

        new_ids = {"frontal": uuid.uuid4().hex, "sagittal": uuid.uuid4().hex}
        new_archive_id = "rec-" + uuid.uuid4().hex[:12]
        archive_dir = archive_video_path(
            session_id,
            new_archive_id,
            "frontal",
        ).parent
        archive_dir.mkdir(parents=True, exist_ok=True)
        codec = cv2.VideoWriter_fourcc(*"MJPG")
        new_writers = {
            view: cv2.VideoWriter(
                str(archive_video_path(session_id, new_archive_id, view)),
                codec,
                20.0,
                (640, 480),
            )
            for view in new_ids
        }
        if not all(writer.isOpened() for writer in new_writers.values()):
            for writer in new_writers.values():
                writer.release()
            raise HTTPException(status_code=500, detail="Cannot create camera archive files.")

        started_at = time.time()
        started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO recording_archives
                   (id, session_id, frontal_video_id, sagittal_video_id,
                    started_at, status)
                   VALUES (?, ?, ?, ?, ?, 'recording')""",
                (
                    new_archive_id,
                    session_id,
                    new_ids["frontal"],
                    new_ids["sagittal"],
                    started_iso,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            for writer in new_writers.values():
                writer.release()
            raise
        finally:
            conn.close()

        for name in (
            "recorded_timestamps", "recorded_left_knee", "recorded_right_knee",
            "recorded_left_ankle", "recorded_right_ankle", "recorded_pelvic_tilt",
            "recorded_trunk_tilt", "recorded_left_hip", "recorded_right_hip",
            "recorded_pose_quality", "session_markers",
        ):
            setattr(state, name, [])
        with state.live_gait_lock:
            state.live_gait_samples.clear()
        synchronizer = getattr(state, "camera_synchronizer", None)
        if synchronizer is not None:
            synchronizer.reset()
        reset_live_gait_cycles()
        state.active_session_id = session_id
        state.active_scan_type = "segment"
        state.healthy_leg = healthy
        state.prosthetic_leg = prosthetic
        state.record_duration = 24 * 60 * 60
        state.record_start_time = started_at
        with fsr_lock:
            recorded_fsr_samples.clear()
            fsr_steps.reset()
        state.is_recording = True
        with lock:
            writers = new_writers
            video_ids = new_ids
            archive_id = new_archive_id
            archive_session_id = session_id
            archive_started_at = started_at
            archive_frame_counts = {"frontal": 0, "sagittal": 0}
            archive_active = True
        return {
            "status": "started",
            "archiveId": new_archive_id,
            "videoIds": new_ids,
            "startedAt": started_iso,
        }

    @app.post("/recording/stop")
    def stop_continuous_recording():
        with lock:
            active = archive_active
        if not active:
            raise HTTPException(status_code=409, detail="No recording is active.")
        result = finish_archive("complete")
        if any(count <= 0 for count in result["frameCounts"].values()):
            result["warning"] = "One or more camera archives contain no frames."
        return {"status": "stopped", **result}

    def _create_virtual_segment_impl(session_id: str, data: dict):
        start_t = max(0.0, float(data.get("startOffsetSec", 0.0)))
        end_t = float(data.get("endOffsetSec", 0.0))
        if end_t - start_t < 0.5:
            raise HTTPException(status_code=422, detail="Analysis clip must be at least 0.5 seconds.")
        archive = latest_archive_for_session(session_id)
        if archive is None:
            raise HTTPException(
                status_code=409,
                detail="Start a camera recording before creating analysis clips.",
            )
        with lock:
            current_is_active = (
                archive_active
                and archive_session_id == session_id
                and archive_id == archive["id"]
            )
        available_duration = (
            max(0.0, time.time() - archive_started_at)
            if current_is_active
            else float(archive.get("duration_sec") or 0.0)
        )
        if end_t > available_duration + 0.75:
            raise HTTPException(status_code=422, detail="End marker exceeds recorded video.")
        source_video_ids = {
            "frontal": archive["frontal_video_id"],
            "sagittal": archive["sagittal_video_id"],
        }

        analysis_status = "ready"
        analysis_message = ""
        try:
            values = analyze_cropped_segment(
                start_t, end_t, state.recorded_timestamps,
                state.recorded_left_knee, state.recorded_right_knee,
                state.recorded_left_ankle, state.recorded_right_ankle,
                state.recorded_left_hip, state.recorded_right_hip,
                state.recorded_pelvic_tilt, state.healthy_leg, session_id,
                getattr(state, "recorded_pose_quality", []),
            )
            (l_knee, r_knee, l_ankle, r_ankle, l_hip, r_hip, pelvic_t,
             load_sym, cop_traj, cadence, stride,
             fatigue_flag, fatigue_slope) = values
        except (ValueError, TypeError, IndexError) as exc:
            # The video clip is primary evidence and must survive even when
            # MediaPipe temporarily loses the subject.
            analysis_status = "video_only"
            analysis_message = str(exc)
            l_knee = r_knee = l_ankle = r_ankle = []
            l_hip = r_hip = pelvic_t = []
            load_sym = cadence = stride = 0.0
            cop_traj = json.dumps([])
            fatigue_flag = 0
            fatigue_slope = 0.0
        segment_id = "seg-" + uuid.uuid4().hex[:8]
        scan_id = "clip-" + uuid.uuid4().hex[:8]
        scan_type = str(data.get("scanType", "segment"))
        note = str(data.get("note", "")).strip() or f"Clip {start_t:.1f}-{end_t:.1f} sec"
        recorded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            with fsr_lock:
                fsr_analysis = build_region_analysis(
                    list(recorded_fsr_samples), start_t, end_t
                )
        except Exception:
            fsr_analysis = {"unit": "N_estimated", "regions": {}, "pairs": [], "peakForePairs": []}
        try:
            gait_analysis = build_live_gait(
                window_size=7,
                recorded_range=(start_t, end_t),
            )
        except Exception:
            gait_analysis = {"unit": "degree", "metrics": {}, "cycles": []}
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (segment_id, session_id, start_t, end_t, "manual", note,
                 json.dumps(source_video_ids), recorded_at),
            )
            cursor.execute(
            """INSERT INTO scans
            (id, session_id, segment_id, scan_type, label, left_knee, right_knee,
             left_ankle, right_ankle, left_hip, right_hip, pelvic_tilt,
             plantar_load_symmetry, cop_trajectory, cadence, stride_length,
             fatigue_flag, fatigue_slope, actual_adjustment_degrees,
             actual_adjustment_notes, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (scan_id, session_id, segment_id, scan_type, note,
             json.dumps(l_knee), json.dumps(r_knee), json.dumps(l_ankle),
             json.dumps(r_ankle), json.dumps(l_hip), json.dumps(r_hip),
             json.dumps(pelvic_t), load_sym, cop_traj, cadence, stride,
             fatigue_flag, fatigue_slope, 0.0, "", recorded_at),
        )
            cursor.execute(
            """INSERT OR REPLACE INTO fsr_region_analyses
            (scan_id, data_json, created_at) VALUES (?, ?, ?)""",
            (scan_id, json.dumps(fsr_analysis), recorded_at),
        )
            cursor.execute(
            """INSERT OR REPLACE INTO gait_cycle_analyses
            (scan_id, data_json, created_at) VALUES (?, ?, ?)""",
            (scan_id, json.dumps(gait_analysis), recorded_at),
        )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {
            "scanId": scan_id,
            "segmentId": segment_id,
            "archiveId": archive["id"],
            "label": note,
            "analysisStatus": analysis_status,
            "analysisMessage": analysis_message,
            "videoStored": True,
        }
    @app.post("/segments-v2/{session_id}")
    def create_virtual_segment(session_id: str, data: dict):
        try:
            return _create_virtual_segment_impl(session_id, data)
        except HTTPException:
            raise
        except Exception as exc:
            error_id = uuid.uuid4().hex[:8]
            print(f"[Segment {error_id}] Unexpected error:")
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Cannot create analysis clip. Error code: {error_id}",
            ) from exc

    @app.get("/scans/{scan_id}/fsr-analysis")
    def get_fsr_analysis(scan_id: str, window: int = 7):
        if window not in VALID_WINDOWS:
            raise HTTPException(
                status_code=422,
                detail=f"Window must be one of {VALID_WINDOWS}.",
            )
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT data_json FROM fsr_region_analyses WHERE scan_id = ?",
            (scan_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return {"unit": "N_estimated", "regions": {}, "peakForePairs": []}
        try:
            data = json.loads(row["data_json"])
            pairs = data.get("pairs") if isinstance(data, dict) else None
            if isinstance(pairs, list):
                pipeline = FsrStepPipeline(window_size=window)
                result = pipeline.analysis(
                    healthy_leg=data.get("healthySide", "left"),
                    prosthetic_leg=data.get("prostheticSide", "right"),
                    pairs=pairs,
                )
                result["replayFrames"] = data.get("replayFrames", [])
                result["replaySampleRateHz"] = data.get("replaySampleRateHz", 15)
                return result
            return data
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"unit": "N_estimated", "regions": {}, "peakForePairs": []}
    @app.get("/scans/{scan_id}/gait-analysis")
    def get_gait_analysis(scan_id: str, window: int = 7):
        if window not in VALID_WINDOWS:
            raise HTTPException(
                status_code=422,
                detail=f"Window must be one of {VALID_WINDOWS}.",
            )
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT data_json FROM gait_cycle_analyses WHERE scan_id = ?",
            (scan_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return {"unit": "degree", "metrics": {}}
        try:
            data = json.loads(row["data_json"])
            cycles = data.get("cycles") if isinstance(data, dict) else None
            if isinstance(cycles, list):
                result = analyze_gait_cycles(
                    cycles,
                    window_size=window,
                    healthy_leg=data.get("healthySide", "left"),
                    prosthetic_leg=data.get("prostheticSide", "right"),
                )
                for name in (
                    "poseQuality",
                    "sampleCount",
                    "rejectedSampleCount",
                    "cameraSynchronization",
                ):
                    if name in data:
                        result[name] = data[name]
                return result
            return data
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"unit": "degree", "metrics": {}}
    @app.get("/sessions/{session_id}/analysis-clips")
    def list_analysis_clips(session_id: str):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT sc.id AS scan_id, sc.label, sg.*
               FROM scans sc JOIN segments sg ON sg.id = sc.segment_id
               WHERE sc.session_id = ?
                 AND sg.source_type IN ('manual', 'virtual_clip')
               ORDER BY sg.created_at ASC""",
            (session_id,),
        )
        result = []
        for row in cursor.fetchall():
            try:
                videos = json.loads(row["video_path"] or "{}")
            except json.JSONDecodeError:
                videos = {}
            start = float(row["start_offset_sec"])
            end = float(row["end_offset_sec"])
            result.append({
                "scanId": row["scan_id"],
                "segmentId": row["id"],
                "label": row["label"],
                "note": row["note"],
                "startOffsetSec": start,
                "endOffsetSec": end,
                "frontalVideoUrl": f"/session-video/{session_id}/{videos.get('frontal')}?start={start}&end={end}",
                "sagittalVideoUrl": f"/session-video/{session_id}/{videos.get('sagittal')}?start={start}&end={end}",
            })
        conn.close()
        return result

    def recording_archive_payload(row):
        session_id = row["session_id"]
        duration = float(row["duration_sec"] or 0.0)
        frontal_id = row["frontal_video_id"]
        sagittal_id = row["sagittal_video_id"]
        frontal_path = video_file_path(session_id, frontal_id)
        sagittal_path = video_file_path(session_id, sagittal_id)
        payload = {
            "archiveId": row["id"],
            "sessionId": session_id,
            "startedAt": row["started_at"],
            "stoppedAt": row["stopped_at"],
            "durationSec": duration,
            "status": row["status"],
            "frameCounts": {
                "frontal": row["frontal_frame_count"],
                "sagittal": row["sagittal_frame_count"],
            },
            "available": {
                "frontal": frontal_path.is_file() and frontal_path.stat().st_size > 0,
                "sagittal": sagittal_path.is_file() and sagittal_path.stat().st_size > 0,
            },
            "frontalVideoUrl": (
                f"/session-video/{session_id}/{frontal_id}"
                f"?start=0&end={duration}"
            ),
            "sagittalVideoUrl": (
                f"/session-video/{session_id}/{sagittal_id}"
                f"?start=0&end={duration}"
            ),
        }
        if "session_created_at" in row.keys():
            payload["sessionCreatedAt"] = row["session_created_at"]
        return payload

    @app.get("/sessions/{session_id}/recordings")
    def list_recording_archives(session_id: str):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT * FROM recording_archives
               WHERE session_id = ?
               ORDER BY started_at DESC""",
            (session_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [recording_archive_payload(row) for row in rows]

    @app.get("/patients/{patient_id}/recordings")
    def list_patient_recording_archives(patient_id: str):
        """List every preserved recording across one patient's sessions."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT ra.*, s.created_at AS session_created_at
               FROM recording_archives ra
               JOIN sessions s ON s.id = ra.session_id
               WHERE s.patient_id = ?
               ORDER BY ra.started_at DESC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [recording_archive_payload(row) for row in rows]

    @app.delete("/sessions/{session_id}/recordings/{stored_archive_id}")
    def delete_recording_archive(session_id: str, stored_archive_id: str):
        """Delete one synchronized recording pair and its derived clips."""
        with lock:
            deleting_active_archive = (
                archive_active
                and archive_id == stored_archive_id
                and archive_session_id == session_id
            )
        if deleting_active_archive:
            raise HTTPException(
                status_code=409,
                detail="Stop the active recording before deleting it.",
            )

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT * FROM recording_archives
               WHERE id = ? AND session_id = ?""",
            (stored_archive_id, session_id),
        )
        archive = cursor.fetchone()
        if archive is None:
            conn.close()
            raise HTTPException(status_code=404, detail="Recording not found.")
        if archive["status"] == "recording":
            conn.close()
            raise HTTPException(
                status_code=409,
                detail="Stop the active recording before deleting it.",
            )

        source_video_ids = {
            archive["frontal_video_id"],
            archive["sagittal_video_id"],
        }
        cursor.execute(
            "SELECT id, video_path FROM segments WHERE session_id = ?",
            (session_id,),
        )
        segment_ids = []
        for row in cursor.fetchall():
            try:
                stored_videos = json.loads(row["video_path"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if (
                isinstance(stored_videos, dict)
                and source_video_ids.intersection(stored_videos.values())
            ):
                segment_ids.append(row["id"])

        scan_ids = []
        if segment_ids:
            placeholders = ",".join("?" for _ in segment_ids)
            cursor.execute(
                f"SELECT id FROM scans WHERE segment_id IN ({placeholders})",
                segment_ids,
            )
            scan_ids = [row["id"] for row in cursor.fetchall()]
            if scan_ids:
                scan_placeholders = ",".join("?" for _ in scan_ids)
                cursor.execute(
                    f"DELETE FROM fsr_region_analyses "
                    f"WHERE scan_id IN ({scan_placeholders})",
                    scan_ids,
                )
                cursor.execute(
                    f"DELETE FROM gait_cycle_analyses "
                    f"WHERE scan_id IN ({scan_placeholders})",
                    scan_ids,
                )
                cursor.execute(
                    f"DELETE FROM scans WHERE id IN ({scan_placeholders})",
                    scan_ids,
                )
            cursor.execute(
                f"DELETE FROM segments WHERE id IN ({placeholders})",
                segment_ids,
            )
        cursor.execute(
            "DELETE FROM recording_archives WHERE id = ? AND session_id = ?",
            (stored_archive_id, session_id),
        )
        conn.commit()
        conn.close()

        grouped_dir = archive_video_path(
            session_id,
            stored_archive_id,
            "frontal",
        ).parent
        candidate_files = {
            archive_video_path(session_id, stored_archive_id, "frontal"),
            archive_video_path(session_id, stored_archive_id, "sagittal"),
            recordings_dir / f"{archive['frontal_video_id']}.avi",
            recordings_dir / f"{archive['sagittal_video_id']}.avi",
        }
        deleted_files = 0
        for path in candidate_files:
            try:
                if path.is_file():
                    path.unlink()
                    deleted_files += 1
            except OSError as exc:
                print(f"[Archive delete] Could not remove {path}: {exc}")
        for directory in (grouped_dir, grouped_dir.parent):
            try:
                directory.rmdir()
            except OSError:
                pass

        return {
            "archiveId": stored_archive_id,
            "deletedFiles": deleted_files,
            "deletedSegments": len(segment_ids),
            "deletedScans": len(scan_ids),
        }

    @app.get("/session-video-frame/{session_id}/{video_id}")
    def get_session_video_frame(session_id: str, video_id: str, t: float = 0.0):
        if (
            len(video_id) != 32
            or not video_id.isalnum()
            or not video_belongs_to_session(session_id, video_id)
        ):
            raise HTTPException(status_code=404, detail="Video not found for this session.")
        path = video_file_path(session_id, video_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Video file is unavailable.")
        capture = cv2.VideoCapture(str(path))
        media_position = video_media_position(
            capture,
            t,
            video_timeline_duration(session_id, video_id),
        )
        capture.set(cv2.CAP_PROP_POS_MSEC, media_position * 1000)
        ok, frame = capture.read()
        capture.release()
        if not ok:
            raise HTTPException(status_code=404, detail="Frame is unavailable.")
        _, jpeg = cv2.imencode(".jpg", frame)
        return Response(content=jpeg.tobytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.get("/session-video/{session_id}/{video_id}")
    def stream_session_video(
        session_id: str,
        video_id: str,
        start: float = 0.0,
        end: float = 10.0,
        loop: bool = False,
    ):
        if len(video_id) != 32 or not video_id.isalnum() or not video_belongs_to_session(session_id, video_id):
            raise HTTPException(status_code=404, detail="Video not found for this session.")
        path = video_file_path(session_id, video_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Video file is unavailable.")

        def frames():
            while True:
                capture = cv2.VideoCapture(str(path))
                fps = capture.get(cv2.CAP_PROP_FPS) or 20.0
                timeline_duration = video_timeline_duration(session_id, video_id)
                media_start = video_media_position(
                    capture, start, timeline_duration
                )
                media_end = video_media_position(capture, end, timeline_duration)
                capture.set(cv2.CAP_PROP_POS_MSEC, media_start * 1000)
                emitted = False
                while capture.isOpened():
                    position = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                    if position > media_end:
                        break
                    ok, frame = capture.read()
                    if not ok:
                        break
                    encoded, jpeg = cv2.imencode(".jpg", frame)
                    if encoded:
                        emitted = True
                        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" +
                               jpeg.tobytes() + b"\r\n")
                    time.sleep(1.0 / fps)
                capture.release()
                if not loop or not emitted:
                    break
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    def close_active_camera_archive():
        with lock:
            active = archive_active
        if active:
            finish_archive("interrupted")

    app.router.add_event_handler("shutdown", close_active_camera_archive)
