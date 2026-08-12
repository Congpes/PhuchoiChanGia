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


def install_realtime_services(app, state):
    """Install local camera archiving, FSR reception, and virtual clip APIs."""
    recordings_dir = Path(__file__).resolve().parent / "recordings"
    recordings_dir.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    archive_active = False
    writers = {"frontal": None, "sagittal": None}
    video_ids = {"frontal": None, "sagittal": None}
    fsr_lock = threading.Lock()
    latest_fsr = {"left": None, "right": None}
    recorded_fsr_samples = []
    fsr_filter = {
        "left": {"frames": deque(maxlen=5), "baseline": None},
        "right": {"frames": deque(maxlen=5), "baseline": None},
    }

    conn = get_db_connection()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS fsr_region_analyses (
            scan_id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()

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

    def adc_load_matrix(matrix):
        """Convert inverse ADC to a positive load value for force charts."""
        raw = np.asarray(matrix, dtype=float)
        return np.maximum(0.0, 4000.0 - raw).round(2).tolist()

    def region_totals(matrix):
        def rows_total(first_row, last_row):
            return sum(sum(row) for row in matrix[first_row:last_row + 1])

        return {
            "heel": rows_total(0, 2),
            "midfoot": rows_total(3, 7),
            "forefoot": rows_total(8, 11),
            "total": sum(sum(row) for row in matrix),
        }

    def build_region_analysis(samples, start_t, end_t):
        result = {"unit": "raw_adc", "regions": {}}
        selected = [
            sample for sample in samples
            if start_t <= sample["time"] <= end_t
        ]
        if selected:
            result["unit"] = selected[0].get("unit", "raw_adc")
        for region in ("heel", "midfoot", "forefoot"):
            result["regions"][region] = {}
            for side in ("left", "right"):
                side_samples = sorted(
                    (sample for sample in selected if sample["side"] == side),
                    key=lambda sample: sample["time"],
                )
                if len(side_samples) < 3:
                    result["regions"][region][side] = {
                        "mean": [], "sd": [], "steps": 0,
                    }
                    continue

                times = np.asarray([sample["time"] for sample in side_samples], dtype=float)
                totals = np.asarray([sample["total"] for sample in side_samples], dtype=float)
                span = float(np.max(totals) - np.min(totals))
                threshold = float(np.min(totals) + 0.15 * span)
                active = totals > threshold if span > 0 else np.ones_like(totals, dtype=bool)
                intervals = []
                interval_start = None
                for index, is_active in enumerate(active):
                    if is_active and interval_start is None:
                        interval_start = index
                    if interval_start is not None and (not is_active or index == len(active) - 1):
                        interval_end = index if is_active else index - 1
                        if interval_end - interval_start + 1 >= 3:
                            intervals.append((interval_start, interval_end))
                        interval_start = None
                if not intervals:
                    intervals = [(0, len(side_samples) - 1)]

                normalized_steps = []
                target = np.linspace(0.0, 1.0, 101)
                for first, last in intervals:
                    segment = side_samples[first:last + 1]
                    source = np.linspace(0.0, 1.0, len(segment))
                    values = np.asarray(
                        [sample["regions"][region] for sample in segment],
                        dtype=float,
                    )
                    normalized_steps.append(np.interp(target, source, values))
                stack = np.vstack(normalized_steps)
                result["regions"][region][side] = {
                    "mean": np.mean(stack, axis=0).round(4).tolist(),
                    "sd": (
                        np.std(stack, axis=0, ddof=1).round(4).tolist()
                        if len(normalized_steps) > 1
                        else np.zeros(101).tolist()
                    ),
                    "steps": len(normalized_steps),
                }
        return result
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
                load_matrix = adc_load_matrix(matrix)
                sample = {
                    "side": side,
                    "deviceId": packet.get("device_id", ""),
                    "unit": packet.get("unit", "raw_adc"),
                    "rows": len(matrix),
                    "columns": len(matrix[0]),
                    "values": matrix,
                    "total": sum(sum(row) for row in load_matrix),
                    "receivedAt": time.time(),
                    "source": address[0],
                }
                with fsr_lock:
                    latest_fsr[side] = sample
                    if getattr(state, "is_recording", False):
                        recorded_fsr_samples.append({
                            "time": max(0.0, time.time() - state.record_start_time),
                            "side": side,
                            "total": sample["total"],
                            "regions": region_totals(load_matrix),
                            "unit": sample["unit"],
                        })
            except (ValueError, UnicodeDecodeError, OSError):
                continue

    def archive_loop():
        nonlocal archive_active
        while getattr(state, "running", True):
            with lock:
                active = archive_active
                current = dict(writers)
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
            for view, writer in current.items():
                frame = frames.get(view)
                if writer is not None and frame is not None:
                    writer.write(cv2.resize(frame, (640, 480)))
            time.sleep(0.05)

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
        conn.close()
        return allowed

    threading.Thread(target=fsr_receiver, daemon=True, name="fsr-udp").start()
    threading.Thread(target=archive_loop, daemon=True, name="camera-archive").start()

    @app.get("/fsr/latest")
    def get_latest_fsr():
        now = time.time()
        with fsr_lock:
            result = {side: (dict(value) if value else None) for side, value in latest_fsr.items()}
        for value in result.values():
            if value is not None:
                value["connected"] = now - value["receivedAt"] < 2.0
        return result

    @app.get("/camera-status")
    def get_camera_status():
        with state.frame_lock_0:
            camera_0 = state.latest_frame_0 is not None
        with state.frame_lock_1:
            camera_1 = state.latest_frame_1 is not None
        if getattr(state, "SINGLE_CAMERA_MODE", False):
            camera_0 = camera_1
        return {
            "camera0": {"connected": camera_0},
            "camera1": {"connected": camera_1},
        }

    @app.post("/recording/start")
    def start_continuous_recording(
        session_id: str,
        healthy: str = Query("LEFT", pattern="^(LEFT|RIGHT)$"),
        prosthetic: str = Query("RIGHT", pattern="^(LEFT|RIGHT)$"),
    ):
        nonlocal archive_active, writers, video_ids
        if archive_active:
            raise HTTPException(status_code=409, detail="A recording is already active.")
        new_ids = {"frontal": uuid.uuid4().hex, "sagittal": uuid.uuid4().hex}
        codec = cv2.VideoWriter_fourcc(*"MJPG")
        new_writers = {
            view: cv2.VideoWriter(str(recordings_dir / f"{identifier}.avi"), codec, 20.0, (640, 480))
            for view, identifier in new_ids.items()
        }
        if not all(writer.isOpened() for writer in new_writers.values()):
            for writer in new_writers.values():
                writer.release()
            raise HTTPException(status_code=500, detail="Cannot create camera archive files.")

        for name in (
            "recorded_timestamps", "recorded_left_knee", "recorded_right_knee",
            "recorded_left_ankle", "recorded_right_ankle", "recorded_pelvic_tilt",
            "recorded_left_hip", "recorded_right_hip", "session_markers",
        ):
            setattr(state, name, [])
        state.active_session_id = session_id
        state.active_scan_type = "segment"
        state.healthy_leg = healthy
        state.prosthetic_leg = prosthetic
        state.record_duration = 24 * 60 * 60
        state.record_start_time = time.time()
        with fsr_lock:
            recorded_fsr_samples.clear()
        state.is_recording = True
        with lock:
            writers = new_writers
            video_ids = new_ids
            archive_active = True
        return {"status": "started"}

    @app.post("/recording/stop")
    def stop_continuous_recording():
        nonlocal archive_active, writers
        state.is_recording = False
        with lock:
            archive_active = False
            closing = list(writers.values())
            writers = {"frontal": None, "sagittal": None}
        for writer in closing:
            if writer is not None:
                writer.release()
        return {
            "status": "stopped",
            "durationSec": state.recorded_timestamps[-1] if state.recorded_timestamps else 0.0,
        }

    def _create_virtual_segment_impl(session_id: str, data: dict):
        start_t = max(0.0, float(data.get("startOffsetSec", 0.0)))
        end_t = float(data.get("endOffsetSec", 0.0))
        if end_t - start_t < 0.5:
            raise HTTPException(status_code=422, detail="Analysis clip must be at least 0.5 seconds.")
        if not state.recorded_timestamps or end_t > state.recorded_timestamps[-1] + 0.5:
            raise HTTPException(status_code=422, detail="End marker exceeds recorded data.")
        try:
            values = analyze_cropped_segment(
                start_t, end_t, state.recorded_timestamps,
                state.recorded_left_knee, state.recorded_right_knee,
                state.recorded_left_ankle, state.recorded_right_ankle,
                state.recorded_left_hip, state.recorded_right_hip,
                state.recorded_pelvic_tilt, state.healthy_leg, session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        (l_knee, r_knee, l_ankle, r_ankle, l_hip, r_hip, pelvic_t,
         load_sym, cop_traj, cadence, stride, fatigue_flag, fatigue_slope) = values
        segment_id = "seg-" + uuid.uuid4().hex[:8]
        scan_id = "clip-" + uuid.uuid4().hex[:8]
        scan_type = str(data.get("scanType", "segment"))
        note = str(data.get("note", "")).strip() or f"Clip {start_t:.1f}-{end_t:.1f} sec"
        recorded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (segment_id, session_id, start_t, end_t, "virtual_clip", note,
             json.dumps(video_ids), recorded_at),
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
        with fsr_lock:
            fsr_analysis = build_region_analysis(
                list(recorded_fsr_samples), start_t, end_t
            )
        cursor.execute(
            """INSERT OR REPLACE INTO fsr_region_analyses
            (scan_id, data_json, created_at) VALUES (?, ?, ?)""",
            (scan_id, json.dumps(fsr_analysis), recorded_at),
        )
        conn.commit()
        conn.close()
        return {"scanId": scan_id, "segmentId": segment_id, "label": note}
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
    def get_fsr_analysis(scan_id: str):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT data_json FROM fsr_region_analyses WHERE scan_id = ?",
            (scan_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return {"unit": "raw_adc", "regions": {}}
        try:
            return json.loads(row["data_json"])
        except (json.JSONDecodeError, TypeError):
            return {"unit": "raw_adc", "regions": {}}
    @app.get("/sessions/{session_id}/analysis-clips")
    def list_analysis_clips(session_id: str):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT sc.id AS scan_id, sc.label, sg.*
               FROM scans sc JOIN segments sg ON sg.id = sc.segment_id
               WHERE sc.session_id = ? AND sg.source_type = 'virtual_clip'
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

    @app.get("/session-video-frame/{session_id}/{video_id}")
    def get_session_video_frame(session_id: str, video_id: str, t: float = 0.0):
        if (
            len(video_id) != 32
            or not video_id.isalnum()
            or not video_belongs_to_session(session_id, video_id)
        ):
            raise HTTPException(status_code=404, detail="Video not found for this session.")
        path = recordings_dir / f"{video_id}.avi"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Video file is unavailable.")
        capture = cv2.VideoCapture(str(path))
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
        ok, frame = capture.read()
        capture.release()
        if not ok:
            raise HTTPException(status_code=404, detail="Frame is unavailable.")
        _, jpeg = cv2.imencode(".jpg", frame)
        return Response(content=jpeg.tobytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.get("/session-video/{session_id}/{video_id}")
    def stream_session_video(session_id: str, video_id: str, start: float = 0.0, end: float = 10.0):
        if len(video_id) != 32 or not video_id.isalnum() or not video_belongs_to_session(session_id, video_id):
            raise HTTPException(status_code=404, detail="Video not found for this session.")
        path = recordings_dir / f"{video_id}.avi"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Video file is unavailable.")

        def frames():
            capture = cv2.VideoCapture(str(path))
            fps = capture.get(cv2.CAP_PROP_FPS) or 20.0
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start) * 1000)
            while capture.isOpened():
                position = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if position > end:
                    break
                ok, frame = capture.read()
                if not ok:
                    break
                encoded, jpeg = cv2.imencode(".jpg", frame)
                if encoded:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" +
                           jpeg.tobytes() + b"\r\n")
                time.sleep(1.0 / fps)
            capture.release()
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")
