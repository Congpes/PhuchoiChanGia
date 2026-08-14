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
from fsr_step_pipeline import FsrStepPipeline, VALID_WINDOWS
from gait_cycle_pipeline import (
    analyze_gait_cycles,
    build_camera_gait_cycles,
)


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
    fsr_steps = FsrStepPipeline(window_size=5)
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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gait_cycle_analyses (
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
            "heel": rows_total(9, 11),
            "midfoot": rows_total(4, 8),
            "forefoot": rows_total(0, 3),
            "total": sum(sum(row) for row in matrix),
        }

    def build_region_analysis(samples, start_t, end_t, window_size=7):
        pipeline = FsrStepPipeline(window_size=window_size)
        selected = sorted(
            (
                sample for sample in samples
                if start_t <= sample["time"] <= end_t
            ),
            key=lambda sample: sample["time"],
        )
        for sample in selected:
            pipeline.add_sample(sample["side"], sample["time"], sample["regions"])
        result = pipeline.analysis(
            healthy_leg=getattr(state, "healthy_leg", "LEFT"),
            prosthetic_leg=getattr(state, "prosthetic_leg", "RIGHT"),
        )
        result["cycleAnchors"] = pipeline.all_pairs()
        return result
    def build_live_gait(window_size=5, recorded_range=None):
        """Build gait cycles from sagittal-camera motion, independently of FSR."""
        if recorded_range is None:
            gait_lock = getattr(state, "live_gait_lock", None)
            if gait_lock is None:
                samples = list(getattr(state, "live_gait_samples", []))
            else:
                with gait_lock:
                    samples = list(getattr(state, "live_gait_samples", []))
            cutoff = time.time() - 30.0
            samples = [sample for sample in samples if sample.get("time", 0.0) >= cutoff]
            timestamps = [sample["time"] for sample in samples]
            signals = {
                "left_knee": [sample["left_knee"] for sample in samples],
                "right_knee": [sample["right_knee"] for sample in samples],
                "left_hip": [sample["left_hip"] for sample in samples],
                "right_hip": [sample["right_hip"] for sample in samples],
                "trunk": [sample["trunk_tilt"] for sample in samples],
            }
        else:
            start_t, end_t = recorded_range
            timestamps_all = list(getattr(state, "recorded_timestamps", []))
            indices = [
                index for index, timestamp in enumerate(timestamps_all)
                if start_t <= timestamp <= end_t
            ]
            timestamps = [timestamps_all[index] for index in indices]
            recorded_signals = {
                "left_knee": list(getattr(state, "recorded_left_knee", [])),
                "right_knee": list(getattr(state, "recorded_right_knee", [])),
                "left_hip": list(getattr(state, "recorded_left_hip", [])),
                "right_hip": list(getattr(state, "recorded_right_hip", [])),
                "trunk": list(getattr(state, "recorded_trunk_tilt", [])),
            }
            signals = {
                name: [values[index] for index in indices if index < len(values)]
                for name, values in recorded_signals.items()
            }
        cycles = build_camera_gait_cycles(
            timestamps,
            signals,
            window_size=window_size,
        )
        result = analyze_gait_cycles(
            cycles,
            window_size=window_size,
            healthy_leg=getattr(state, "healthy_leg", "LEFT"),
            prosthetic_leg=getattr(state, "prosthetic_leg", "RIGHT"),
        )
        pose_age = time.time() - float(getattr(state, "latest_sagittal_pose_at", 0.0) or 0.0)
        result.update({
            "source": "camera",
            "event": "peak_knee_flexion",
            "sampleCount": len(timestamps),
            "poseDetected": pose_age < 1.5,
            "message": (
                "Move through at least two full strides in the sagittal camera."
                if len(cycles) == 0 else ""
            ),
        })
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
                    sample_regions = region_totals(load_matrix)
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
            with state.camera_roles_lock:
                swapped = state.camera_roles_swapped
            if swapped:
                frames["frontal"], frames["sagittal"] = (
                    frames.get("sagittal"), frames.get("frontal")
                )
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
        return {
            "backendOnline": True,
            "swapped": swapped,
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
                "poseDetected": now - float(
                    getattr(state, "latest_sagittal_pose_at", 0.0) or 0.0
                ) < 1.5,
                "index": sagittal_index,
            },
        }

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
        state.latest_sagittal_pose_at = 0.0
        return {"status": "swapped", "swapped": swapped}

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
            "recorded_trunk_tilt", "recorded_left_hip", "recorded_right_hip",
            "session_markers",
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
            fsr_steps.reset()
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
        try:
            cursor.execute(
                "INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (segment_id, session_id, start_t, end_t, "manual", note,
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
            gait_analysis = build_live_gait(
                window_size=7,
                recorded_range=(start_t, end_t),
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
            return {"unit": "relative_load", "regions": {}}
        try:
            data = json.loads(row["data_json"])
            pairs = data.get("pairs") if isinstance(data, dict) else None
            if isinstance(pairs, list):
                pipeline = FsrStepPipeline(window_size=window)
                return pipeline.analysis(
                    healthy_leg=data.get("healthySide", "left"),
                    prosthetic_leg=data.get("prostheticSide", "right"),
                    pairs=pairs,
                )
            return data
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"unit": "relative_load", "regions": {}}
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
                return analyze_gait_cycles(
                    cycles,
                    window_size=window,
                    healthy_leg=data.get("healthySide", "left"),
                    prosthetic_leg=data.get("prostheticSide", "right"),
                )
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
