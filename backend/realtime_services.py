import json
import os
import re
import shutil
import socket
import threading
import time
import traceback
import uuid
from bisect import bisect_left
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from fastapi import HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from algorithms import analyze_cropped_segment
from camera_fusion import frontal_metrics
from database import get_db_connection
from fsr_force import matrix_to_newton, matrix_total, region_totals
from fsr_serial import (
    FsrSerialFrameParser, configured_serial_ports,
    read_fsr_serial_chunk, serial_retry_delay,
)
from fsr_step_pipeline import FsrStepPipeline, VALID_WINDOWS
from gait_cycle_pipeline import (
    analyze_gait_cycles,
    build_synchronized_gait_cycles,
    estimate_foot_clearance_signals,
    estimate_step_motion_signals,
)
from pose_identity_lock import PoseIdentityLock
from phone_demo_library import install_phone_demo_library
from measurement_smoothing import FsrMedianFilter
from pose_angle_overlay import (
    draw_joint_angle_labels, draw_frontal_trunk_label,
    draw_sagittal_trunk_label, pose_frame_matches_source,
)
from pose_quality import assess_temporal_consistency, summarize_pose_quality
from stereo_calibration import StereoCalibrationError


ANALYSIS_ALGORITHM_VERSION = os.getenv(
    "GAIT_ANALYSIS_VERSION",
    "raw-replay-v6-adjacent-step-pairing",
)
TRUNK_REALTIME_WINDOW_SECONDS = 3.0
POSE_REPLAY_MAX_GAP_SECONDS = 0.35


def finite_json(value):
    """Convert NumPy values and non-finite floats into strict JSON values."""
    if isinstance(value, dict):
        return {str(key): finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [finite_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if np.isfinite(number) else None
    return value


def analysis_scan_updates(gait_analysis, fsr_analysis):
    """Return report-facing scan fields from the persisted QA analysis.

    ``scans`` is still consumed by the compact metrics dashboard.  The initial
    archive path used to leave that row populated with the unfiltered live
    arrays even after a better video analysis had been selected.  Keeping the
    derived row in sync prevents first-frame pose spikes from reappearing in a
    different analysis tab; the immutable raw/video evidence remains in the
    recording archive and ``analysis_runs``.
    """
    updates = {}
    metrics = gait_analysis.get("metrics", {}) if isinstance(gait_analysis, dict) else {}
    if isinstance(metrics, dict):
        for metric in ("knee", "hip"):
            metric_data = metrics.get(metric, {})
            if not isinstance(metric_data, dict):
                continue
            for side in ("left", "right"):
                side_data = metric_data.get(side, {})
                mean_curve = side_data.get("mean", []) if isinstance(side_data, dict) else []
                if not isinstance(mean_curve, list) or not mean_curve:
                    continue
                values = []
                for value in mean_curve:
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        continue
                    if np.isfinite(number):
                        values.append(number)
                if values:
                    updates[f"{side}_{metric}"] = values

        statistics = gait_analysis.get("statistics", {})
        cadence_data = statistics.get("cadence", {}) if isinstance(statistics, dict) else {}
        cadence_value = cadence_data.get("mean") if isinstance(cadence_data, dict) else None
        try:
            cadence_value = float(cadence_value)
        except (TypeError, ValueError):
            cadence_value = None
        if cadence_value is not None and np.isfinite(cadence_value) and cadence_value > 0:
            updates["cadence"] = cadence_value

    if isinstance(fsr_analysis, dict):
        pair_rows = fsr_analysis.get("peakForePairs")
        if not isinstance(pair_rows, list):
            pair_rows = fsr_analysis.get("pairs")
        fsi_values = []
        if isinstance(pair_rows, list):
            for pair in pair_rows:
                if not isinstance(pair, dict):
                    continue
                try:
                    value = float(pair.get("fsi"))
                except (TypeError, ValueError):
                    continue
                if np.isfinite(value) and 0 <= value <= 100:
                    fsi_values.append(value)
        if fsi_values:
            updates["plantar_load_symmetry"] = float(np.mean(fsi_values))
    return updates


def packet_sample_time(packet, received_at=None, max_clock_skew_seconds=5.0):
    """Resolve an FSR acquisition time on the camera backend system clock."""
    received = float(time.time() if received_at is None else received_at)
    try:
        sampled = float(packet.get("timestamp_ms")) / 1000.0
    except (AttributeError, TypeError, ValueError):
        return received, 0.0, False
    if not np.isfinite(sampled) or abs(received - sampled) > max_clock_skew_seconds:
        return received, 0.0, False
    return sampled, max(0.0, (received - sampled) * 1000.0), True


def align_fsr_cycle_anchors(
    anchors,
    *,
    camera_timestamps_are_relative,
    fsr_timestamps_are_relative,
    record_start_time,
):
    """Copy FSR contacts onto the camera clock without changing intervals."""
    camera_relative = bool(camera_timestamps_are_relative)
    fsr_relative = bool(fsr_timestamps_are_relative)
    if camera_relative == fsr_relative:
        offset = 0.0
    else:
        try:
            origin = float(record_start_time)
        except (TypeError, ValueError):
            return []
        if not np.isfinite(origin) or origin <= 0.0:
            return []
        offset = -origin if camera_relative else origin

    aligned = []
    for source in anchors or []:
        if not isinstance(source, dict):
            continue
        anchor = dict(source)
        valid = True
        for side in ("left", "right"):
            side_source = source.get(side)
            if not isinstance(side_source, dict):
                valid = False
                break
            side_anchor = dict(side_source)
            for field in ("start", "end"):
                if field not in side_anchor:
                    continue
                try:
                    value = float(side_anchor[field]) + offset
                except (TypeError, ValueError):
                    valid = False
                    break
                if not np.isfinite(value):
                    valid = False
                    break
                side_anchor[field] = value
            if not valid or "start" not in side_anchor:
                valid = False
                break
            anchor[side] = side_anchor
        if valid:
            aligned.append(anchor)
    return aligned


def gait_side_sample_reliable(quality, side, metric="knee"):
    """Return whether one sagittal leg can contribute to a gait curve.

    MediaPipe commonly lowers confidence for the far leg in a true side view.
    The old all-or-nothing frame gate therefore discarded the clearly visible
    near leg too. Keep 0.70 for the prosthetic target and use a conservative
    0.40 for the comparison leg, while retaining all geometry safeguards.
    """
    if not isinstance(quality, dict):
        return True
    normalized_side = str(side).strip().lower()
    if normalized_side not in ("left", "right"):
        return False
    if quality.get("bodyInFrame") is False or quality.get("legIdentityReliable") is False:
        return False
    if quality.get("cameraRolesPlausible") is False:
        return False
    relevant_angles = {f"{normalized_side}_{metric}"}
    if relevant_angles.intersection(quality.get("outOfRangeAngles", [])):
        return False
    temporal = set(quality.get("temporalJumpAngles", []))
    # A transient shoulder/hip-axis jump invalidates the trunk sample, but it
    # must not erase an otherwise reliable knee/hip frame. Each metric is gated
    # independently downstream.
    if relevant_angles.intersection(temporal):
        return False

    visibility = quality.get("landmarkVisibility")
    if isinstance(visibility, dict) and visibility:
        target_side = str(quality.get("targetSide") or "").lower()
        threshold = (
            float(quality.get("targetVisibilityThreshold", 0.70))
            if normalized_side == target_side
            else 0.40
        )
        return all(
            float(visibility.get(f"{normalized_side}_{joint}", 0.0)) >= threshold
            for joint in ("hip", "knee", "ankle")
        )

    # Compatibility with stored/test samples created before confidence values
    # were retained per landmark.
    target_side = str(quality.get("targetSide") or "").lower()
    if not target_side and quality.get("targetLegReliable") is False:
        return False
    if normalized_side == target_side:
        return bool(quality.get("targetLegReliable", quality.get("frameReliable", True)))
    return bool(
        quality.get(
            "bilateralSagittalReliable",
            quality.get("frameReliable", quality.get("targetLegReliable", True)),
        )
    )


def gait_trunk_sample_reliable(quality):
    if not isinstance(quality, dict):
        return True
    if quality.get("bodyInFrame") is False:
        return False
    return "trunk_tilt" not in set(quality.get("temporalJumpAngles", []))


def gait_analysis_score_details(data):
    """Summarize completeness and explicit camera-cycle quality."""
    if not isinstance(data, dict):
        return {
            "cycleCount": 0,
            "qualityQualifiedCycleCount": 0,
            "metricCoverage": 0,
            "sampleCount": 0,
        }
    cycles = data.get("cycles")
    cycle_count = (
        len(cycles)
        if isinstance(cycles, list)
        else int(data.get("cycleCount", 0) or 0)
    )
    coverage = 0
    metrics = data.get("metrics")
    if isinstance(metrics, dict):
        for metric in metrics.values():
            if not isinstance(metric, dict):
                continue
            for side in ("left", "right"):
                side_data = metric.get(side)
                if isinstance(side_data, dict) and side_data.get("mean"):
                    coverage += 1
    quality_qualified = 0
    if isinstance(cycles, list):
        quality_qualified = sum(
            1
            for cycle in cycles
            if isinstance(cycle, dict)
            and isinstance(cycle.get("cameraCycleQuality"), dict)
            and cycle["cameraCycleQuality"].get("steadyWalking") is True
        )
    return {
        "cycleCount": cycle_count,
        "qualityQualifiedCycleCount": quality_qualified,
        "metricCoverage": coverage,
        "sampleCount": int(data.get("sampleCount", 0) or 0),
    }


def gait_analysis_score(data):
    """Rank legacy/equal-version analyses by cycles, coverage, then samples."""
    details = gait_analysis_score_details(data)
    return (
        details["cycleCount"],
        details["metricCoverage"],
        details["sampleCount"],
    )


def _analysis_version_generation(value):
    match = re.search(r"(?:^|[-_])v(\d+)(?:[-_]|$)", str(value or "").lower())
    return int(match.group(1)) if match else 0


def gait_reanalysis_decision(
    candidate,
    existing,
    *,
    candidate_version,
    existing_version=None,
    minimum_quality_cycles=2,
    minimum_sample_ratio=0.50,
):
    """Choose a replay result without letting one noisy extra cycle win.

    A newer camera algorithm may intentionally return fewer cycles after
    rejecting turns or an invalid camera plane. It can replace the legacy run
    when at least two cycles explicitly passed camera quality checks, metric
    coverage does not regress, and pose-sample coverage has not collapsed.
    """
    candidate_score = gait_analysis_score_details(candidate)
    existing_score = gait_analysis_score_details(existing)
    if existing_version is not None:
        resolved_existing_version = existing_version
    elif isinstance(existing, dict):
        resolved_existing_version = existing.get("algorithmVersion")
    else:
        resolved_existing_version = None
    candidate_generation = _analysis_version_generation(candidate_version)
    existing_generation = _analysis_version_generation(resolved_existing_version)
    newer_algorithm = candidate_generation > existing_generation

    if existing_score["cycleCount"] <= 0:
        replace = candidate_score["cycleCount"] > 0
        reason = "no_existing_cycles" if replace else "candidate_has_no_cycles"
    elif newer_algorithm:
        existing_samples = existing_score["sampleCount"]
        sample_coverage_ok = (
            existing_samples <= 0
            or candidate_score["sampleCount"]
            >= float(minimum_sample_ratio) * existing_samples
        )
        quality_upgrade = (
            candidate_score["cycleCount"] >= int(minimum_quality_cycles)
            and candidate_score["qualityQualifiedCycleCount"]
            >= int(minimum_quality_cycles)
            and candidate_score["metricCoverage"]
            >= existing_score["metricCoverage"]
            and sample_coverage_ok
        )
        replace = quality_upgrade
        reason = (
            "newer_quality_qualified_analysis"
            if replace
            else "newer_analysis_failed_quality_guard"
        )
    else:
        replace = gait_analysis_score(candidate) >= gait_analysis_score(existing)
        reason = (
            "equal_or_legacy_score_not_worse"
            if replace
            else "candidate_score_lower"
        )
    return {
        "replace": bool(replace),
        "reason": reason,
        "candidateVersion": str(candidate_version or ""),
        "existingVersion": str(resolved_existing_version or ""),
        "newerAlgorithm": newer_algorithm,
        "candidateScore": candidate_score,
        "existingScore": existing_score,
    }


def lateral_trunk_feedback(
    samples,
    *,
    window_seconds=1.5,
    warning_degrees=5.0,
    critical_degrees=10.0,
    minimum_samples=8,
):
    """Describe sustained coronal trunk lean without reacting to normal sway."""
    reliable = []
    for sample in samples:
        quality = sample.get("poseQuality", {})
        value = sample.get("frontal_trunk_lean")
        try:
            value = float(value)
            timestamp = float(sample.get("time", 0.0))
        except (TypeError, ValueError):
            continue
        if (
            not np.isfinite(value)
            or not isinstance(quality, dict)
            or quality.get("balanceReliable") is not True
        ):
            continue
        reliable.append((timestamp, value))
    if reliable:
        end_time = reliable[-1][0]
        reliable = [
            item for item in reliable
            if item[0] >= end_time - float(window_seconds)
        ]
    if len(reliable) < int(minimum_samples):
        return {
            "available": False,
            "status": "insufficient",
            "reason": "Cần thấy rõ vai–hông trên camera chính diện và đồng bộ đủ khung hình.",
            "sampleCount": len(reliable),
            "method": "median_1.5s_sustained_dual_camera",
        }

    values = np.asarray([item[1] for item in reliable], dtype=float)
    median = float(np.median(values))
    same_direction = float(np.mean(values > 0.0)) if median >= 0 else float(np.mean(values < 0.0))
    sustained = abs(median) >= float(warning_degrees) and same_direction >= 0.70
    if not sustained:
        status = "aligned"
        direction = "center"
        message = "Thân trái–phải đang trong vùng cân bằng."
        recommendation = "Tiếp tục đi thẳng theo đường chuẩn và giữ vai thả lỏng."
    else:
        status = "critical" if abs(median) >= float(critical_degrees) else "warning"
        direction = "patient_right" if median > 0 else "patient_left"
        side_text = "phải" if median > 0 else "trái"
        message = f"Phát hiện thân nghiêng kéo dài sang bên {side_text} cơ thể ({abs(median):.1f}°)."
        recommendation = (
            "Nhắc người đo đưa vai và lồng ngực về giữa hai hông, "
            "giữ đầu thẳng và tiếp tục đi đúng đường chuẩn."
        )
    return {
        "available": True,
        "status": status,
        "angleDeg": round(median, 2),
        "absoluteAngleDeg": round(abs(median), 2),
        "direction": direction,
        "message": message,
        "recommendation": recommendation,
        "warningThresholdDeg": float(warning_degrees),
        "criticalThresholdDeg": float(critical_degrees),
        "sameDirectionRatio": round(same_direction, 3),
        "sampleCount": len(reliable),
        "windowSeconds": float(window_seconds),
        "method": "median_1.5s_sustained_dual_camera_anatomical_axis",
    }


def install_realtime_services(app, state):
    """Install local camera archiving, FSR reception, and virtual clip APIs."""
    install_phone_demo_library(app)
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
    archive_last_sequences = {"frontal": None, "sagittal": None}
    archive_timeline_stream = None
    archive_timeline_path_pending = None
    archive_timeline_last_flush = 0.0
    archive_fsr_lock = threading.Lock()
    archive_fsr_stream = None
    archive_fsr_pending_path = None
    archive_fsr_sample_count = 0
    archive_fsr_last_flush = 0.0
    archive_fps = min(
        30.0,
        max(5.0, float(os.getenv("CAMERA_ARCHIVE_FPS", "15"))),
    )
    archive_recording_fps = archive_fps
    default_archive_size = (
        int(getattr(state, "CAMERA_REQUEST_WIDTH", 640) or 640),
        int(getattr(state, "CAMERA_REQUEST_HEIGHT", 480) or 480),
    )
    archive_frame_sizes = {
        "frontal": default_archive_size,
        "sagittal": default_archive_size,
    }
    fsr_lock = threading.Lock()
    latest_fsr = {"left": None, "right": None}
    recorded_fsr_samples = []
    fsr_steps = FsrStepPipeline(window_size=5)
    fsr_median_filter = FsrMedianFilter()
    fsr_serial_status_lock = threading.Lock()
    # Windows Bluetooth SPP is prone to WinError 121 when two outgoing COM
    # ports are opened at exactly the same time.  Only serialize the short
    # open/reset section; each foot still has its own independent read loop.
    fsr_serial_open_lock = threading.Lock()
    fsr_serial_worker_ports = set()
    fsr_serial_status = {
        # The backend owns both outgoing Bluetooth COM ports. The old external
        # transmitter remains compatible through UDP but is no longer required.
        'enabled': os.getenv('FSR_SERIAL_AUTO', 'true').lower() in ('1', 'true', 'yes'),
        'started': False,
        'ports': [],
        'connectedPorts': [],
        'portStatus': {},
        'mode': 'serial_direct',
        'lastError': '',
    }
    gait_cycle_lock = threading.Lock()
    gait_response_cache_lock = threading.Lock()
    gait_response_cache = {"key": None, "at": 0.0, "value": None}
    live_camera_cycles = deque()
    consumed_step_ends = {}
    live_unmatched_steps = {}
    gait_pair_sequence = 0
    last_camera_cycle_end = None
    live_cycle_source = None
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
            frames = []
            captured_at = []
            for _ in range(6):
                success, frame = capture.read()
                if success and frame is not None:
                    frames.append(frame)
                    captured_at.append(time.perf_counter())
            if not frames:
                return None
            frame = frames[-1]
            height, width = frame.shape[:2]
            measured_fps = 0.0
            if len(captured_at) >= 2 and captured_at[-1] > captured_at[0]:
                measured_fps = (len(captured_at) - 1) / (captured_at[-1] - captured_at[0])
            quality_fn = getattr(state, "frame_quality_metrics", None)
            health = quality_fn(frame) if callable(quality_fn) else {}
            properties_fn = getattr(state, "capture_properties", None)
            if callable(properties_fn):
                properties = properties_fn(capture)
            else:
                capture_get = getattr(capture, "get", None)
                properties = {
                    "reportedFps": (
                        float(capture_get(cv2.CAP_PROP_FPS) or 0.0)
                        if callable(capture_get) else 0.0
                    ),
                    "fourcc": "",
                }
            return {
                "index": index,
                "label": f"Camera index {index}",
                "width": width,
                "height": height,
                "reportedFps": properties.get("reportedFps", 0.0),
                "probeFps": round(measured_fps, 2),
                "fourcc": properties.get("fourcc", ""),
                "imageQuality": health,
            }
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
        """Restore the old per-cell median; rawAdcValues stays immutable."""
        return fsr_median_filter.apply(side, matrix, time.monotonic())

    def reprocess_fsr_samples(samples):
        """Rebuild Newton/regions from immutable ADC values with fresh filters."""
        windows = {
            "left": deque(maxlen=5),
            "right": deque(maxlen=5),
        }
        rebuilt = []
        for source in sorted(samples, key=lambda item: float(item.get("time", 0.0))):
            side = str(source.get("side", "")).lower()
            if side not in windows:
                continue
            source_unit = str(source.get("sourceUnit", "")).lower()
            packet_force = normalize_matrix(source.get("forceValues", []))
            if source_unit == "newton" and packet_force:
                # Newton selected in the verified transmitter is the canonical
                # displayed force. Preserve it exactly during replay instead of
                # applying another ADC median filter and conversion.
                sample = dict(source)
                sample.update({
                    "forceValues": packet_force,
                    "regions": region_totals(packet_force),
                    "total": matrix_total(packet_force),
                    "unit": "N",
                    "sourceUnit": "newton",
                    "forceSource": "packet",
                })
                rebuilt.append(sample)
                continue
            raw_source = source.get("rawAdcValues")
            if raw_source is None:
                # Legacy sidecars only retained derived matrices. Preserve
                # those values instead of pretending they are raw ADC.
                rebuilt.append(dict(source))
                continue
            raw_matrix = normalize_matrix(raw_source)
            if not raw_matrix:
                continue
            filtered = raw_matrix
            force_matrix, force_unit, force_source = matrix_to_newton(
                filtered,
                "raw_adc",
            )
            sample = dict(source)
            sample.update({
                "rawAdcValues": raw_matrix,
                "values": filtered,
                "forceValues": force_matrix,
                "regions": region_totals(force_matrix),
                "total": matrix_total(force_matrix),
                "unit": force_unit,
                "sourceUnit": "raw_adc",
                "forceSource": force_source,
            })
            rebuilt.append(sample)
        return rebuilt

    def build_region_analysis(
        samples,
        start_t,
        end_t,
        window_size=0,
        *,
        session_id=None,
        reprocess_raw=False,
    ):
        pipeline = FsrStepPipeline(window_size=window_size)
        source_samples = reprocess_fsr_samples(samples) if reprocess_raw else samples
        selected = sorted(
            (
                sample for sample in source_samples
                if start_t <= sample["time"] <= end_t
            ),
            key=lambda sample: sample["time"],
        )
        replay_frames = []
        last_replay_time = {"left": None, "right": None}
        for sample in selected:
            pipeline.set_force_metadata(
                sample.get("unit", "N_estimated"),
                sample.get("forceSource", "formula_estimate"),
            )
            pipeline.add_sample(
                sample["side"],
                sample["time"],
                sample["regions"],
                sample.get("forceValues"),
            )
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
                    "values": sample.get("values", []),
                    "forceValues": sample.get("forceValues", []),
                    "sequence": sample.get("sequence"),
                    "sampledAt": sample.get("sampledAt"),
                    "transportLatencyMs": sample.get("transportLatencyMs"),
                })
                last_replay_time[side] = sample["time"]
        if session_id:
            context = patient_measurement_context(session_id)
            healthy_leg = context["healthySide"]
            prosthetic_leg = context["prostheticSide"]
        else:
            healthy_leg = getattr(state, "healthy_leg", "LEFT")
            prosthetic_leg = getattr(state, "prosthetic_leg", "RIGHT")
        result = pipeline.analysis(
            healthy_leg=healthy_leg,
            prosthetic_leg=prosthetic_leg,
        )
        result["cycleAnchors"] = pipeline.all_pairs()
        result["replayFrames"] = replay_frames
        result["replaySampleRateHz"] = 15
        result["reprocessedFromRawAdc"] = bool(
            reprocess_raw
            and any(
                sample.get("forceSource") == "formula_estimate"
                for sample in selected
            )
        )
        timestamped = [sample for sample in selected if sample.get("timestampValid")]
        latencies = [
            float(sample["transportLatencyMs"])
            for sample in timestamped
            if sample.get("transportLatencyMs") is not None
        ]
        result["synchronization"] = {
            "clock": "shared_system_clock",
            "sampleCount": len(selected),
            "sourceTimestampCount": len(timestamped),
            "sourceTimestampCoverage": (
                round(len(timestamped) / len(selected), 4) if selected else 0.0
            ),
            "medianTransportLatencyMs": (
                round(float(np.median(latencies)), 3) if latencies else None
            ),
            "p95TransportLatencyMs": (
                round(float(np.percentile(latencies, 95)), 3) if latencies else None
            ),
        }
        return finite_json(result)
    def reset_live_gait_cycles():
        nonlocal gait_pair_sequence, last_camera_cycle_end, live_cycle_source
        # Keep lock order consistent with get_gait_steps -> build_live_gait.
        with gait_response_cache_lock:
            gait_response_cache.update({"key": None, "at": 0.0, "value": None})
        with gait_cycle_lock:
            live_camera_cycles.clear()
            consumed_step_ends.clear()
            live_unmatched_steps.clear()
            gait_pair_sequence = 0
            last_camera_cycle_end = None
            live_cycle_source = None

    def target_leg_sample_reliable(quality):
        if not isinstance(quality, dict):
            return True
        return bool(
            quality.get(
                "bilateralSagittalReliable",
                quality.get(
                    "targetLegReliable",
                    quality.get("frameReliable", True),
                ),
            )
        )

    def patient_anthropometry(session_id):
        if not session_id:
            return {"heightCm": None, "leftLegLengthCm": None, "rightLegLengthCm": None}
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT p.height_cm, p.left_leg_length_cm, p.right_leg_length_cm
                   FROM sessions s JOIN patients p ON p.id = s.patient_id
                   WHERE s.id = ?""",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        return {
            "heightCm": row["height_cm"] if row else None,
            "leftLegLengthCm": row["left_leg_length_cm"] if row else None,
            "rightLegLengthCm": row["right_leg_length_cm"] if row else None,
        }

    def patient_measurement_context(session_id):
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT p.height_cm, p.left_leg_length_cm,
                          p.right_leg_length_cm, p.healthy_leg, p.prosthetic_leg
                   FROM sessions s JOIN patients p ON p.id = s.patient_id
                   WHERE s.id = ?""",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        return {
            "heightCm": row["height_cm"] if row else None,
            "leftLegLengthCm": row["left_leg_length_cm"] if row else None,
            "rightLegLengthCm": row["right_leg_length_cm"] if row else None,
            "healthySide": str(row["healthy_leg"] if row else "LEFT").lower(),
            "prostheticSide": str(row["prosthetic_leg"] if row else "RIGHT").lower(),
        }

    def stored_view_width_ratio(path, start_t, end_t, timeline_duration):
        """Estimate whether a stored view is frontal (wide hips) or sagittal."""
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            return None
        detector = state.mp_pose.Pose(
            static_image_mode=True,
            model_complexity=0,
            min_detection_confidence=0.50,
        )
        ratios = []
        try:
            for timeline_t in np.linspace(start_t, end_t, 12):
                media_t = video_media_position(
                    capture, float(timeline_t), timeline_duration
                )
                capture.set(cv2.CAP_PROP_POS_MSEC, media_t * 1000.0)
                ok, frame = capture.read()
                if not ok or frame is None:
                    continue
                result = detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                if not result.pose_landmarks:
                    continue
                points = state.pose_landmark_mapping(result.pose_landmarks)
                left_hip, right_hip = points["left_hip"], points["right_hip"]
                left_shoulder = points["left_shoulder"]
                right_shoulder = points["right_shoulder"]
                mid_hip = (
                    (left_hip["x"] + right_hip["x"]) / 2.0,
                    (left_hip["y"] + right_hip["y"]) / 2.0,
                )
                mid_shoulder = (
                    (left_shoulder["x"] + right_shoulder["x"]) / 2.0,
                    (left_shoulder["y"] + right_shoulder["y"]) / 2.0,
                )
                torso = max(1e-6, float(np.linalg.norm(
                    np.asarray(mid_hip) - np.asarray(mid_shoulder)
                )))
                ratios.append(abs(left_hip["x"] - right_hip["x"]) / torso)
        finally:
            detector.close()
            capture.release()
        return float(np.median(ratios)) if ratios else None

    def analyze_saved_video_clip(
        session_id,
        videos,
        start_t,
        end_t,
        *,
        fsr_anchors=None,
        fsr_contacts=None,
    ):
        """Re-run sagittal pose from persisted video when live RAM data is absent."""
        candidates = {}
        for view in ("frontal", "sagittal"):
            video_id = str(videos.get(view) or "")
            if not video_id:
                continue
            path = video_file_path(session_id, video_id)
            if not path.is_file():
                continue
            duration = video_timeline_duration(session_id, video_id)
            ratio = stored_view_width_ratio(path, start_t, end_t, duration)
            metadata_capture = cv2.VideoCapture(str(path))
            frame_width = int(metadata_capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            frame_height = int(metadata_capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            metadata_capture.release()
            candidates[view] = {
                "id": video_id,
                "path": path,
                "duration": duration,
                "widthRatio": ratio,
                "frameTimes": video_frame_times(session_id, video_id),
                "imageSize": (
                    [frame_width, frame_height]
                    if frame_width > 0 and frame_height > 0
                    else [640, 480]
                ),
            }
        if not candidates:
            return None
        measurable = [
            (view, item)
            for view, item in candidates.items()
            if item["widthRatio"] is not None
        ]
        if measurable:
            selected_view, selected = min(
                measurable, key=lambda pair: pair[1]["widthRatio"]
            )
        elif "sagittal" in candidates:
            selected_view, selected = "sagittal", candidates["sagittal"]
        else:
            selected_view, selected = next(iter(candidates.items()))

        context = patient_measurement_context(session_id)
        capture = cv2.VideoCapture(str(selected["path"]))
        nominal_fps = float(capture.get(cv2.CAP_PROP_FPS) or archive_fps)
        media_start = video_media_position(
            capture, start_t, selected["duration"]
        )
        media_end = video_media_position(capture, end_t, selected["duration"])
        capture.set(cv2.CAP_PROP_POS_MSEC, media_start * 1000.0)
        detector = state.create_pose_detector()
        identity = PoseIdentityLock()
        samples = []
        pose_replay = {"frontal": [], "sagittal": []}
        frame_index = 0
        previous = None
        try:
            while capture.isOpened():
                media_position = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                if media_position > media_end + 1.0 / max(1.0, nominal_fps):
                    break
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                source_frame_index = int(
                    capture.get(cv2.CAP_PROP_POS_FRAMES) or 1
                ) - 1
                frame_times = selected["frameTimes"]
                timeline_time = (
                    frame_times[source_frame_index]
                    if 0 <= source_frame_index < len(frame_times)
                    else None
                )
                if timeline_time is not None:
                    timestamp = float(timeline_time)
                    if timestamp < start_t:
                        continue
                    if timestamp > end_t:
                        break
                else:
                    fraction = (
                        (media_position - media_start) / (media_end - media_start)
                        if media_end > media_start
                        else 0.0
                    )
                    timestamp = start_t + max(0.0, min(1.0, fraction)) * (
                        end_t - start_t
                    )
                result = detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                if result.pose_landmarks:
                    locked = identity.update(result.pose_landmarks, timestamp)
                    pose_replay[selected_view].append({
                        "time": round(float(timestamp), 4),
                        "sourceFrameIndex": source_frame_index,
                        "landmarks": state.pose_landmark_mapping(locked),
                    })
                    height, width = frame.shape[:2]
                    sample = state.pose_sample_from_landmarks(
                        locked,
                        width,
                        height,
                        target_side=context["prostheticSide"],
                    )
                    if sample is not None:
                        temporal = assess_temporal_consistency(
                            sample,
                            previous,
                            1.0 / max(1.0, nominal_fps),
                        )
                        quality = sample.setdefault("poseQuality", {})
                        quality.update(temporal)
                        if not temporal["temporalReliable"]:
                            quality["frameReliable"] = False
                            quality["bilateralSagittalReliable"] = False
                            quality["targetLegReliable"] = False
                        sample["time"] = timestamp
                        samples.append(sample)
                        previous = sample
                frame_index += 1
        finally:
            detector.close()
            capture.release()

        # Keep the timestamps even when angles are unavailable. Foot cues can
        # complete a detected step, while invalid joint metrics remain NaN.
        measurement_samples = samples
        timestamps = [float(item["time"]) for item in measurement_samples]

        # Re-run the complementary frontal recording as well. Earlier saved-
        # video analysis used only the sagittal file, so every reanalysis erased
        # the lateral-trunk Mean ± SD even though the second camera was stored.
        frontal_view = "sagittal" if selected_view == "frontal" else "frontal"
        frontal_candidate = candidates.get(frontal_view)
        lateral_observations: list[tuple[float, float]] = []
        frontal_processed = 0
        frontal_detected = 0
        if frontal_candidate is not None:
            frontal_capture = cv2.VideoCapture(str(frontal_candidate["path"]))
            frontal_fps = float(
                frontal_capture.get(cv2.CAP_PROP_FPS) or archive_fps
            )
            frontal_start = video_media_position(
                frontal_capture, start_t, frontal_candidate["duration"]
            )
            frontal_end = video_media_position(
                frontal_capture, end_t, frontal_candidate["duration"]
            )
            frontal_capture.set(cv2.CAP_PROP_POS_MSEC, frontal_start * 1000.0)
            frontal_detector = state.create_pose_detector()
            frontal_identity = PoseIdentityLock()
            try:
                while frontal_capture.isOpened():
                    media_position = (
                        frontal_capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                    )
                    if media_position > frontal_end + 1.0 / max(1.0, frontal_fps):
                        break
                    ok, frame = frontal_capture.read()
                    if not ok or frame is None:
                        break
                    source_frame_index = int(
                        frontal_capture.get(cv2.CAP_PROP_POS_FRAMES) or 1
                    ) - 1
                    frontal_frame_times = frontal_candidate["frameTimes"]
                    timeline_time = (
                        frontal_frame_times[source_frame_index]
                        if 0 <= source_frame_index < len(frontal_frame_times)
                        else None
                    )
                    if timeline_time is not None:
                        timestamp = float(timeline_time)
                        if timestamp < start_t:
                            continue
                        if timestamp > end_t:
                            break
                    else:
                        fraction = (
                            (media_position - frontal_start)
                            / (frontal_end - frontal_start)
                            if frontal_end > frontal_start else 0.0
                        )
                        timestamp = start_t + max(0.0, min(1.0, fraction)) * (
                            end_t - start_t
                        )
                    result = frontal_detector.process(
                        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    )
                    frontal_processed += 1
                    if not result.pose_landmarks:
                        continue
                    locked = frontal_identity.update(result.pose_landmarks, timestamp)
                    pose_replay[frontal_view].append({
                        "time": round(float(timestamp), 4),
                        "landmarks": state.pose_landmark_mapping(locked),
                    })
                    mapping = state.pose_landmark_mapping(locked)
                    height, width = frame.shape[:2]
                    try:
                        metrics = frontal_metrics(mapping, (width, height))
                    except (KeyError, TypeError, ValueError):
                        continue
                    lateral = float(metrics.get("trunkLateralLean", float("nan")))
                    visibility = float(metrics.get("trunkMeanVisibility", 0.0))
                    if np.isfinite(lateral) and visibility >= 0.55:
                        lateral_observations.append((timestamp, lateral))
                        frontal_detected += 1
            finally:
                frontal_detector.close()
                frontal_capture.release()

        def matched_lateral(timestamp):
            if not lateral_observations:
                return float("nan")
            observation_times = [item[0] for item in lateral_observations]
            index = int(np.searchsorted(observation_times, timestamp))
            before = lateral_observations[index - 1] if index > 0 else None
            after = (
                lateral_observations[index]
                if index < len(lateral_observations)
                else None
            )
            # The two cameras run asynchronously. Linear time interpolation
            # between adjacent frontal observations removes the sample-and-hold
            # staircase without changing either measured endpoint. Never bridge
            # a real camera dropout.
            if before is not None and after is not None:
                before_gap = float(timestamp) - float(before[0])
                after_gap = float(after[0]) - float(timestamp)
                span = float(after[0]) - float(before[0])
                if (
                    before_gap >= 0.0
                    and after_gap >= 0.0
                    and span <= 0.25
                ):
                    if span <= 1e-9:
                        return float(after[1])
                    fraction = before_gap / span
                    return float(before[1]) + fraction * (
                        float(after[1]) - float(before[1])
                    )
            candidates_at_time = [
                item for item in (before, after) if item is not None
            ]
            closest = min(
                candidates_at_time,
                key=lambda item: abs(float(item[0]) - float(timestamp)),
            )
            return (
                float(closest[1])
                if abs(float(closest[0]) - float(timestamp)) <= 0.12
                else float("nan")
            )

        lateral_signal = [matched_lateral(timestamp) for timestamp in timestamps]
        signals = {
            **{
                f"{side}_{metric}": [
                    item[f"{side}_{metric}"]
                    if gait_side_sample_reliable(item.get("poseQuality", {}), side, metric)
                    else float("nan")
                    for item in measurement_samples
                ]
                for side in ("left", "right")
                for metric in ("knee", "hip")
            },
            "trunk": [
                item["trunk_tilt"]
                if gait_trunk_sample_reliable(item.get("poseQuality", {}))
                else float("nan")
                for item in measurement_samples
            ],
            "lateral_trunk": lateral_signal,
            "facing_sign": [
                float(item.get("sagittal_facing_sign", float("nan")))
                for item in measurement_samples
            ],
            "view_width_ratio": [
                float(item.get("sagittal_view_width_ratio", float("nan")))
                for item in measurement_samples
            ],
            "body_center_x": [
                float(item.get("sagittal_center_x", float("nan")))
                for item in measurement_samples
            ],
        }
        clearance = estimate_foot_clearance_signals(
            measurement_samples,
            left_leg_length_cm=context["leftLegLengthCm"],
            right_leg_length_cm=context["rightLegLengthCm"],
        )
        signals.update(clearance.get("signals", {}))
        signals.update(estimate_step_motion_signals(measurement_samples))
        cycle_detection = {}
        cycles = build_synchronized_gait_cycles(
            timestamps,
            signals,
            fsr_anchors,
            window_size=0,
            progress=cycle_detection,
            fsr_contacts=fsr_contacts,
        )
        analysis = analyze_gait_cycles(
            cycles,
            window_size=0,
            healthy_leg=context["healthySide"],
            prosthetic_leg=context["prostheticSide"],
        )
        pose_source_sizes = {
            view: list(item.get("imageSize") or [640, 480])
            for view, item in candidates.items()
        }
        if selected_view == "frontal":
            pose_replay = {
                "frontal": pose_replay["sagittal"],
                "sagittal": pose_replay["frontal"],
            }
            pose_source_sizes = {
                "frontal": pose_source_sizes.get("sagittal", [640, 480]),
                "sagittal": pose_source_sizes.get("frontal", [640, 480]),
            }
        analysis.update({
            "source": "saved_video_pose",
            "event": cycle_detection.get(
                "event", "completed_step_from_knee_and_foot_motion"
            ),
            "segmentationSource": cycle_detection.get(
                "segmentationSource", "camera"
            ),
            "sampleCount": len(measurement_samples),
            "rejectedSampleCount": sum(not any(
                gait_side_sample_reliable(item.get('poseQuality', {}), side)
                for side in ('left', 'right')
            ) for item in samples),
            "poseDetected": bool(samples),
            "poseQuality": summarize_pose_quality(
                [item.get("poseQuality", {}) for item in samples],
                pose_detected=bool(samples),
                sample_count=len(measurement_samples),
                cycle_count=len(cycles),
            ),
            "anthropometry": context,
            "footClearanceCalibration": clearance,
            "cycleDetection": cycle_detection,
            "videoPoseAnalysis": {
                "selectedStoredView": selected_view,
                "selectedWidthRatio": selected["widthRatio"],
                "storedRolesReversed": selected_view == "frontal",
                "processedFrames": frame_index,
                "detectedFrames": len(samples),
                "frontalProcessedFrames": frontal_processed,
                "frontalDetectedFrames": frontal_detected,
                "lateralTrunkSamples": int(np.sum(np.isfinite(lateral_signal))),
                "frameTimelineUsed": bool(selected["frameTimes"]),
                # Retain the continuous central-axis waveform for replay in
                # Scan. Cycle-normalized curves remain the source for Mean/SD
                # in Analysis; this stream follows the video clock directly.
                "continuousTrunk": {
                    "timestamps": [round(float(value), 4) for value in timestamps],
                    "trunk": [
                        (
                            round(float(item["trunk_tilt"]), 4)
                            if np.isfinite(float(item.get(
                                "trunk_tilt", float("nan")
                            )))
                            else None
                        )
                        for item in measurement_samples
                    ],
                    "lateral_trunk": [
                        round(float(value), 4) if np.isfinite(value) else None
                        for value in lateral_signal
                    ],
                },
            },
            "poseReplay": {
                "schemaVersion": 1,
                "unit": "normalized_image",
                "algorithmVersion": ANALYSIS_ALGORITHM_VERSION,
                "sourceSizes": pose_source_sizes,
                "views": pose_replay,
            },
            "lateralTrunkFeedback": {
                "available": bool(np.sum(np.isfinite(lateral_signal)) >= 6),
                "status": (
                    "recovered" if np.sum(np.isfinite(lateral_signal)) >= 6
                    else "insufficient"
                ),
                "reason": (
                    "Đã khôi phục góc thân trái–phải từ camera trước đã lưu."
                    if np.sum(np.isfinite(lateral_signal)) >= 6
                    else "Video camera trước chưa đủ landmark tin cậy."
                ),
                "sampleCount": int(np.sum(np.isfinite(lateral_signal))),
                "method": "saved_dual_camera_pose_linear_sync_250ms",
            },
        })
        return finite_json(analysis)

    def build_live_gait(
        window_size=5,
        recorded_range=None,
        *,
        height_cm=None,
        left_leg_length_cm=None,
        right_leg_length_cm=None,
        fsr_anchors=None,
        fsr_contacts=None,
    ):
        """Build camera curves, preferring synchronized FSR contact anchors."""
        nonlocal gait_pair_sequence, last_camera_cycle_end, live_cycle_source
        live_waveform = None
        source_fsr_contacts = list(fsr_contacts or [])
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
            measurement_samples = samples
            rejected_sample_count = sum(not any(
                gait_side_sample_reliable(sample.get('poseQuality', {}), side)
                for side in ('left', 'right')
            ) for sample in samples)
            timestamps = [sample["time"] for sample in measurement_samples]
            signals = {
                **{
                    f"{side}_{metric}": [
                        sample[f"{side}_{metric}"]
                        if gait_side_sample_reliable(sample.get("poseQuality", {}), side, metric)
                        else float("nan")
                        for sample in measurement_samples
                    ]
                    for side in ("left", "right")
                    for metric in ("knee", "hip")
                },
                "trunk": [
                    sample["trunk_tilt"]
                    if gait_trunk_sample_reliable(sample.get("poseQuality", {}))
                    else float("nan")
                    for sample in measurement_samples
                ],
                "lateral_trunk": [
                    float(sample.get("frontal_trunk_lean", float("nan")))
                    for sample in measurement_samples
                ],
                "facing_sign": [
                    float(sample.get("sagittal_facing_sign", float("nan")))
                    for sample in measurement_samples
                ],
                "view_width_ratio": [
                    float(sample.get("sagittal_view_width_ratio", float("nan")))
                    for sample in measurement_samples
                ],
                "body_center_x": [
                    float(sample.get("sagittal_center_x", float("nan")))
                    for sample in measurement_samples
                ],
            }
            geometry_samples = [
                sample if sample.get('poseQuality', {}).get('legIdentityReliable') is not False
                and sample.get('poseQuality', {}).get('bodyInFrame') is not False
                else {**sample, 'footTracking': {}}
                for sample in samples
            ]
            # Central trunk tilt is continuous, independent of left/right step
            # completion. Preserve its rolling signal alongside paired angles.
            # Expose a compact rolling signal alongside the normalized cycles;
            # the UI uses it only for the live waveform and keeps Mean comparison
            # based exclusively on completed, paired cycles.
            if measurement_samples:
                waveform_end = float(measurement_samples[-1]["time"])
                waveform_start = max(
                    float(measurement_samples[0]["time"]),
                    waveform_end - TRUNK_REALTIME_WINDOW_SECONDS,
                )
                waveform_samples = [
                    sample for sample in measurement_samples
                    if float(sample["time"]) >= waveform_start
                ]
                live_waveform = {
                    "windowSeconds": TRUNK_REALTIME_WINDOW_SECONDS,
                    "timestamps": [
                        round(float(sample["time"]) - waveform_start, 3)
                        for sample in waveform_samples
                    ],
                    # Trunk inclination is one central shoulder-hip axis, not
                    # a separate left/right measurement. Keep a dedicated
                    # stream for realtime; left/right remain for compatibility.
                    "central": {
                        "trunk": [
                            round(float(sample["trunk_tilt"]), 3)
                            for sample in waveform_samples
                        ],
                        "lateral_trunk": [
                            (
                                round(float(sample["frontal_trunk_lean"]), 3)
                                if np.isfinite(float(sample.get(
                                    "frontal_trunk_lean", float("nan")
                                )))
                                else None
                            )
                            for sample in waveform_samples
                        ],
                    },
                    "left": {
                        "knee": [round(float(sample["left_knee"]), 3) for sample in waveform_samples],
                        "hip": [round(float(sample["left_hip"]), 3) for sample in waveform_samples],
                        "trunk": [round(float(sample["trunk_tilt"]), 3) for sample in waveform_samples],
                        "lateral_trunk": [
                            (
                                round(float(sample["frontal_trunk_lean"]), 3)
                                if np.isfinite(float(sample.get("frontal_trunk_lean", float("nan"))))
                                else None
                            )
                            for sample in waveform_samples
                        ],
                    },
                    "right": {
                        "knee": [round(float(sample["right_knee"]), 3) for sample in waveform_samples],
                        "hip": [round(float(sample["right_hip"]), 3) for sample in waveform_samples],
                        "trunk": [round(float(sample["trunk_tilt"]), 3) for sample in waveform_samples],
                        "lateral_trunk": [
                            (
                                round(float(sample["frontal_trunk_lean"]), 3)
                                if np.isfinite(float(sample.get("frontal_trunk_lean", float("nan"))))
                                else None
                            )
                            for sample in waveform_samples
                        ],
                    },
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
                if any(
                    gait_side_sample_reliable(
                        recorded_quality[index]
                        if index < len(recorded_quality)
                        else {},
                        side,
                    )
                    for side in ("left", "right")
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
                "lateral_trunk": list(
                    getattr(state, "recorded_frontal_trunk_lean", [])
                ),
            }
            signals = {}
            for name, values in recorded_signals.items():
                side = name.split("_", 1)[0] if name.startswith(("left_", "right_")) else None
                metric = name.split("_", 1)[1] if side else name
                signal = []
                for index in reliable_indices:
                    quality = recorded_quality[index] if index < len(recorded_quality) else {}
                    valid = (
                        gait_side_sample_reliable(quality, side)
                        if side and metric in ("knee", "hip")
                        else gait_trunk_sample_reliable(quality)
                        if name == "trunk"
                        else True
                    )
                    signal.append(values[index] if valid and index < len(values) else float("nan"))
                signals[name] = signal
            recorded_tracking = list(getattr(state, "recorded_foot_tracking", []))
            geometry_samples = [
                {
                    "time": timestamps_all[index],
                    "footTracking": recorded_tracking[index]
                    if index < len(recorded_tracking) else {},
                }
                for index in reliable_indices
            ]
        if left_leg_length_cm is None or right_leg_length_cm is None:
            anthropometry = patient_anthropometry(getattr(state, "active_session_id", ""))
            height_cm = height_cm if height_cm is not None else anthropometry["heightCm"]
            left_leg_length_cm = (
                left_leg_length_cm if left_leg_length_cm is not None
                else anthropometry["leftLegLengthCm"]
            )
            right_leg_length_cm = (
                right_leg_length_cm if right_leg_length_cm is not None
                else anthropometry["rightLegLengthCm"]
            )
        clearance = estimate_foot_clearance_signals(
            geometry_samples,
            left_leg_length_cm=left_leg_length_cm,
            right_leg_length_cm=right_leg_length_cm,
        )
        signals.update(clearance.get("signals", {}))
        signals.update(estimate_step_motion_signals(geometry_samples))
        if fsr_anchors is None:
            if recorded_range is None:
                with fsr_lock:
                    source_fsr_anchors = fsr_steps.all_pairs()
                    source_fsr_contacts = fsr_steps.contact_events()
                fsr_timestamps_are_relative = bool(
                    getattr(state, "is_recording", False)
                )
            else:
                # Recorded arrays need anchors rebuilt from the same selected
                # FSR sidecar range.  Never reuse possibly stale live anchors.
                source_fsr_anchors = []
                fsr_timestamps_are_relative = True
        else:
            source_fsr_anchors = fsr_anchors
            # build_region_analysis preserves the recording/video timebase.
            fsr_timestamps_are_relative = recorded_range is not None
        aligned_fsr_anchors = align_fsr_cycle_anchors(
            source_fsr_anchors,
            camera_timestamps_are_relative=recorded_range is not None,
            fsr_timestamps_are_relative=fsr_timestamps_are_relative,
            record_start_time=getattr(state, "record_start_time", 0.0),
        )
        cycle_detection = {}
        contact_shift = (
            float(getattr(state, 'record_start_time', 0.0))
            if recorded_range is None and fsr_timestamps_are_relative else 0.0
        )
        aligned_contacts = [
            {**event, 'start': event['start'] + contact_shift if event['start'] is not None else None,
             'end': event['end'] + contact_shift}
            for event in source_fsr_contacts
        ]
        detected_cycles = build_synchronized_gait_cycles(
            timestamps,
            signals,
            aligned_fsr_anchors,
            window_size=0,
            progress=cycle_detection,
            fsr_contacts=aligned_contacts,
            consumed_until=dict(consumed_step_ends) if recorded_range is None else None,
        )
        if recorded_range is None:
            # The detector reprocesses a rolling signal window on every poll.
            # Promote only newly completed cycles into a persistent sequence so
            # the UI never renumbers old pairs when the 30-second window moves.
            with gait_cycle_lock:
                for item in cycle_detection.get('unmatchedSteps', []):
                    if item['reason'] != 'waiting_for_opposite_step':
                        live_unmatched_steps[(item['side'], round(item['end'], 4))] = item
                detected_source = cycle_detection.get(
                    "segmentationSource", "camera"
                )
                live_cycle_source = detected_source
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
                    for side in ('left', 'right'):
                        consumed_step_ends[side] = float(cycle[side]['end'])
                        live_unmatched_steps.pop((side, round(float(cycle[side]['end']), 4)), None)
                    last_camera_cycle_end = cycle_end
                # Keep completed pairs visible until the recording/session is
                # reset.  The raw pose samples still use the rolling cutoff for
                # detection, but aging a valid pair out here made a correct
                # chart disappear merely because the subject paused for 30 s.
                cycles = list(live_camera_cycles)[-int(window_size):]
                pending = [item for item in cycle_detection.get('unmatchedSteps', [])
                           if item['reason'] == 'waiting_for_opposite_step']
                cycle_detection['unmatchedSteps'] = list(live_unmatched_steps.values()) + pending
                cycle_detection['unmatchedStepCounts'] = {
                    side: sum(item['side'] == side for item in cycle_detection['unmatchedSteps'])
                    for side in ('left', 'right')
                }
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
            "totalPairs": gait_pair_sequence if recorded_range is None else len(cycles),
            "event": cycle_detection.get(
                "event", "completed_step_from_knee_and_foot_motion"
            ),
            "segmentationSource": cycle_detection.get(
                "segmentationSource", "camera"
            ),
            "sampleCount": len(timestamps),
            "rejectedSampleCount": rejected_sample_count,
            "poseDetected": pose_detected,
            "poseQuality": pose_quality,
            "cameraSynchronization": camera_sync,
            "anthropometry": {
                "heightCm": height_cm,
                "leftLegLengthCm": left_leg_length_cm,
                "rightLegLengthCm": right_leg_length_cm,
            },
            "footClearanceCalibration": clearance,
            "cycleDetection": cycle_detection,
            "message": (
                "Cần thấy trọn người và hoàn tất một bước trái cùng một bước phải "
                "để hiển thị cặp so sánh."
                if len(cycles) == 0 else ""
            ),
        })
        if live_waveform is not None:
            result["liveWaveform"] = live_waveform
        result["lateralTrunkFeedback"] = lateral_trunk_feedback(
            measurement_samples if recorded_range is None else []
        )
        return finite_json(result)
    def ingest_serial_fsr(side, matrix, port):
        side = str(side).lower()
        matrix = normalize_matrix(matrix)
        if side not in latest_fsr or not matrix:
            return
        raw_adc_matrix = [list(row) for row in matrix]
        matrix = filter_fsr_matrix(side, matrix)
        force_matrix, force_unit, force_source = matrix_to_newton(matrix, 'raw_adc')
        sample_regions = region_totals(force_matrix)
        received_at = time.time()
        sample = {
            'side': side,
            'deviceId': port,
            'unit': force_unit,
            'sourceUnit': 'raw_adc',
            'forceSource': force_source,
            'rows': len(matrix),
            'columns': len(matrix[0]),
            'values': matrix,
            'rawAdcValues': raw_adc_matrix,
            'forceValues': force_matrix,
            'regions': sample_regions,
            'total': matrix_total(force_matrix),
            'sampledAt': received_at,
            'receivedAt': received_at,
            'transportLatencyMs': 0.0,
            'timestampValid': False,
            'source': f'serial:{port}',
        }
        stored_sample = None
        with fsr_lock:
            latest_fsr[side] = sample
            step_time = (
                max(0.0, sample['receivedAt'] - state.record_start_time)
                if getattr(state, 'is_recording', False)
                else sample['receivedAt']
            )
            fsr_steps.set_force_metadata(force_unit, force_source)
            fsr_steps.add_sample(side, step_time, sample_regions, force_matrix)
            if getattr(state, 'is_recording', False):
                stored_sample = {
                    'time': max(0.0, sample['sampledAt'] - state.record_start_time),
                    'side': side,
                    'total': sample['total'],
                    'regions': sample_regions,
                    'values': matrix,
                    'rawAdcValues': raw_adc_matrix,
                    'forceValues': force_matrix,
                    'unit': force_unit,
                    'sourceUnit': 'raw_adc',
                    'forceSource': force_source,
                    'sampledAt': sample['sampledAt'],
                    'transportLatencyMs': 0.0,
                    'timestampValid': False,
                }
                recorded_fsr_samples.append(stored_sample)
        if stored_sample is not None:
            append_archive_fsr_sample(stored_sample)

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
                received_at = time.time()
                packet = json.loads(raw.decode("utf-8"))
                side = str(packet.get("side", "")).lower()
                packet_matrix = normalize_matrix(packet.get("values", []))
                raw_matrix = normalize_matrix(packet.get("raw_values", []))
                packet_unit = str(packet.get("unit", "raw_adc")).strip().lower()
                if (
                    packet.get("type") != "fsr_matrix"
                    or side not in latest_fsr
                    or not packet_matrix
                ):
                    continue
                if packet_unit == "newton":
                    # FSR_Transmitter_2.py already displays/sends the verified
                    # Newton matrix. Use the same values without a second filter.
                    matrix = packet_matrix
                    raw_adc_matrix = raw_matrix
                    force_matrix, force_unit, force_source = matrix_to_newton(
                        packet_matrix, "newton"
                    )
                elif raw_matrix:
                    raw_adc_matrix = raw_matrix
                    matrix = filter_fsr_matrix(side, raw_matrix)
                    force_matrix, force_unit, force_source = matrix_to_newton(
                        matrix, "raw_adc"
                    )
                else:
                    raw_adc_matrix = packet_matrix if packet_unit == "raw_adc" else []
                    matrix = filter_fsr_matrix(side, packet_matrix)
                    force_matrix, force_unit, force_source = matrix_to_newton(
                        matrix, packet_unit
                    )
                sample_regions = region_totals(force_matrix)
                sampled_at, transport_latency_ms, timestamp_valid = packet_sample_time(
                    packet, received_at
                )
                sample = {
                    "side": side,
                    "deviceId": packet.get("device_id", ""),
                    "unit": force_unit,
                    "sourceUnit": packet_unit,
                    "forceSource": force_source,
                    "rows": len(matrix),
                    "columns": len(matrix[0]),
                    # Matrix is in source units; forceValues is always Newton.
                    "values": matrix,
                    "rawAdcValues": raw_adc_matrix,
                    "forceValues": force_matrix,
                    "regions": sample_regions,
                    "total": matrix_total(force_matrix),
                    "sampledAt": sampled_at,
                    "receivedAt": received_at,
                    "transportLatencyMs": transport_latency_ms,
                    "timestampValid": timestamp_valid,
                    "sequence": packet.get("sequence"),
                    "hardwareMarker": packet.get("hardware_marker"),
                    "source": address[0],
                }
                stored_sample = None
                with fsr_lock:
                    latest_fsr[side] = sample
                    step_time = (
                        max(0.0, sample["sampledAt"] - state.record_start_time)
                        if getattr(state, "is_recording", False)
                        else sample["sampledAt"]
                    )
                    fsr_steps.set_force_metadata(force_unit, force_source)
                    fsr_steps.add_sample(
                        side,
                        step_time,
                        sample_regions,
                        force_matrix,
                    )
                    if getattr(state, "is_recording", False):
                        stored_sample = {
                            "time": max(0.0, sample["sampledAt"] - state.record_start_time),
                            "side": side,
                            "total": sample["total"],
                            "regions": sample_regions,
                            "values": sample["values"],
                            "rawAdcValues": sample["rawAdcValues"],
                            "forceValues": sample["forceValues"],
                            "unit": sample["unit"],
                            "sourceUnit": sample["sourceUnit"],
                            "forceSource": sample["forceSource"],
                            "sampledAt": sample["sampledAt"],
                            "receivedAt": sample["receivedAt"],
                            "transportLatencyMs": sample["transportLatencyMs"],
                            "timestampValid": sample["timestampValid"],
                            "sequence": sample["sequence"],
                            "hardwareMarker": sample["hardwareMarker"],
                        }
                        recorded_fsr_samples.append(stored_sample)
                if stored_sample is not None:
                    append_archive_fsr_sample(stored_sample)
            except (ValueError, UnicodeDecodeError, OSError):
                continue

    def serial_status_snapshot():
        with fsr_serial_status_lock:
            return {
                **fsr_serial_status,
                'ports': list(fsr_serial_status['ports']),
                'connectedPorts': list(fsr_serial_status['connectedPorts']),
                'portStatus': {
                    port: dict(value)
                    for port, value in fsr_serial_status['portStatus'].items()
                },
            }

    def refresh_serial_error_locked():
        errors = [
            f"{port}: {value.get('error')}"
            for port, value in fsr_serial_status['portStatus'].items()
            if value.get('error')
        ]
        fsr_serial_status['lastError'] = '; '.join(errors)

    def fsr_serial_worker(port):
        try:
            import serial
        except ImportError:
            with fsr_serial_status_lock:
                fsr_serial_status['lastError'] = 'pyserial is not installed'
                fsr_serial_worker_ports.discard(port)
            return
        baudrate = int(os.getenv('FSR_SERIAL_BAUDRATE', '9600'))
        retry_initial_seconds = max(
            0.25,
            float(os.getenv('FSR_SERIAL_RETRY_INITIAL_SECONDS', '0.5')),
        )
        retry_max_seconds = max(
            retry_initial_seconds,
            float(os.getenv('FSR_SERIAL_RETRY_MAX_SECONDS', '5')),
        )
        parser = FsrSerialFrameParser()
        while getattr(state, 'running', True):
            connection = None
            retry_delay = retry_initial_seconds
            try:
                with fsr_serial_status_lock:
                    port_status = fsr_serial_status['portStatus'].setdefault(port, {})
                    port_status.update({
                        'state': 'connecting',
                        'connected': False,
                        'error': '',
                    })
                    refresh_serial_error_locked()
                with fsr_serial_open_lock:
                    connection = serial.Serial(port, baudrate, timeout=0.5)
                    # Do not purge the initial LL/RR marker or the first frame.
                    # Give the Bluetooth bridge a short settling window before
                    # the other foot attempts to open its SPP channel.
                    time.sleep(0.12)
                # Never join a partial pre-disconnect frame to fresh bytes.
                # Preserve the last LL/RR identity because some modules send
                # their marker only once per Bluetooth session.
                known_side = parser.side
                parser = FsrSerialFrameParser()
                parser.side = known_side
                with fsr_serial_status_lock:
                    if port not in fsr_serial_status['connectedPorts']:
                        fsr_serial_status['connectedPorts'].append(port)
                    port_status = fsr_serial_status['portStatus'].setdefault(port, {})
                    port_status.update({
                        'state': 'waiting_data',
                        'connected': True,
                        'lastConnectedAt': time.time(),
                        'reconnectOnSilence': False,
                        'receiverVersion': 'persistent-stream-v4-diagnostics',
                        'dataFresh': False,
                        'dataGapSeconds': 0.0,
                        'nextRetrySeconds': 0.0,
                        'error': '',
                    })
                    refresh_serial_error_locked()
                print(f'[FSR] Serial receiver connected to {port} at {baudrate} baud.')
                last_frame_at = time.monotonic()
                stable_since = None
                while getattr(state, 'running', True):
                    read_started = time.monotonic()
                    with fsr_serial_status_lock:
                        port_status = fsr_serial_status['portStatus'][port]
                        port_status['stage'] = 'reading'
                        port_status['lastReadStartedAt'] = time.time()
                    raw_line = read_fsr_serial_chunk(connection)
                    read_ms = (time.monotonic() - read_started) * 1000.0
                    with fsr_serial_status_lock:
                        port_status = fsr_serial_status['portStatus'][port]
                        port_status['lastReadCompletedAt'] = time.time()
                        port_status['lastReadMs'] = round(read_ms, 2)
                        port_status['maxReadMs'] = max(port_status.get('maxReadMs', 0), round(read_ms, 2))
                    if not raw_line:
                        data_gap = time.monotonic() - last_frame_at
                        if data_gap >= 2.0:
                            stable_since = None
                        with fsr_serial_status_lock:
                            port_status = fsr_serial_status['portStatus'].setdefault(
                                port, {}
                            )
                            port_status.update({
                                'state': (
                                    'stalled'
                                    if data_gap >= 2.0
                                    else 'waiting_data'
                                ),
                                'dataGapSeconds': round(data_gap, 2),
                                'dataFresh': (
                                    (port_status.get('lastFrameAt') or 0) >= port_status['lastConnectedAt']
                                    and data_gap < 2.0
                                ),
                            })
                        # Match the standalone transmitter: no bytes means
                        # wait, not close/reopen an otherwise valid SPP handle.
                        continue
                    frames = parser.feed_bytes(raw_line)
                    with fsr_serial_status_lock:
                        port_status = fsr_serial_status['portStatus'].setdefault(port, {})
                        port_status['bytesReceived'] = int(port_status.get('bytesReceived', 0)) + len(raw_line)
                        port_status['lastByteAt'] = time.time()
                        port_status['invalidLinesThisConnection'] = parser.invalid_lines
                        port_status['rawFrameCount'] = int(port_status.get('rawFrameCount', 0)) + len(frames)
                        if frames:
                            port_status['lastParsedFrameAt'] = time.time()
                        if not frames:
                            gap = time.monotonic() - last_frame_at
                            port_status['dataGapSeconds'] = round(gap, 2)
                            if gap >= 2.0:
                                port_status['state'] = 'stalled'
                                port_status['dataFresh'] = False
                                stable_since = None
                    for side, matrix in frames:
                        now = time.monotonic()
                        if now - last_frame_at >= 2.0:
                            stable_since = None
                        last_frame_at = now
                        if stable_since is None:
                            stable_since = now
                        processing_started = time.monotonic()
                        with fsr_serial_status_lock:
                            port_status = fsr_serial_status['portStatus'][port]
                            port_status['stage'] = 'processing'
                            port_status['lastProcessingStartedAt'] = time.time()
                        try:
                            ingest_serial_fsr(side, matrix, port)
                        except Exception as exc:
                            # A force/step/archive failure is NOT a serial
                            # failure. Preserve the port and expose lost samples.
                            with fsr_serial_status_lock:
                                port_status = fsr_serial_status['portStatus'][port]
                                previous_error = port_status.get('processingError', '')
                                error_text = f'{type(exc).__name__}: {exc}'
                                port_status.update({
                                    'state': 'processing_error',
                                    'dataFresh': False,
                                    'processingError': error_text,
                                    'processingErrorAt': time.time(),
                                    'processingErrorCount': int(port_status.get('processingErrorCount', 0)) + 1,
                                })
                            if previous_error != error_text:
                                print(f'[FSR] {port} processing failed (port kept open): {error_text}')
                                traceback.print_exc()
                            continue
                        finally:
                            processing_ms = (time.monotonic() - processing_started) * 1000.0
                            with fsr_serial_status_lock:
                                port_status = fsr_serial_status['portStatus'][port]
                                port_status['lastProcessingCompletedAt'] = time.time()
                                port_status['lastProcessingMs'] = round(processing_ms, 2)
                                port_status['maxProcessingMs'] = max(port_status.get('maxProcessingMs', 0), round(processing_ms, 2))
                        with fsr_serial_status_lock:
                            port_status = fsr_serial_status['portStatus'].setdefault(
                                port, {}
                            )
                            port_status.update({
                                'state': 'receiving',
                                'connected': True,
                                'dataFresh': True,
                                'side': side,
                                'frameCount': int(port_status.get('frameCount', 0)) + 1,
                                'lastFrameAt': time.time(),
                                'dataGapSeconds': 0.0,
                                # One frame followed by another disconnect is
                                # not a recovered link. Reset after stable flow.
                                'consecutiveFailures': (
                                    0 if now - stable_since >= 10.0
                                    else int(port_status.get('consecutiveFailures', 0))
                                ),
                                'nextRetrySeconds': 0.0,
                                'error': '',
                                'processingError': '',
                            })
            except (OSError, ValueError, serial.SerialException) as exc:
                error_text = str(exc)
                with fsr_serial_status_lock:
                    port_status = fsr_serial_status['portStatus'].setdefault(port, {})
                    consecutive_failures = int(
                        port_status.get('consecutiveFailures', 0)
                    ) + 1
                    retry_delay = serial_retry_delay(
                        consecutive_failures, retry_initial_seconds, retry_max_seconds,
                    )
                    # Stagger the two SPP workers very slightly without tying a
                    # physical foot to a fixed COM number.
                    retry_delay = min(
                        retry_max_seconds,
                        retry_delay + (sum(ord(char) for char in port) % 4) * 0.05,
                    )
                    previous_reason = str(port_status.get('lastDisconnectReason', ''))
                    last_log_at = float(port_status.get('lastDisconnectLogAt', 0.0) or 0.0)
                    now_monotonic = time.monotonic()
                    should_log = (
                        error_text != previous_reason
                        or now_monotonic - last_log_at >= 5.0
                    )
                    port_status.update({
                        'state': 'retrying',
                        'stage': 'reconnecting',
                        'connected': False,
                        'dataFresh': False,
                        'reconnectCount': int(port_status.get('reconnectCount', 0)) + 1,
                        'consecutiveFailures': consecutive_failures,
                        'lastDisconnectReason': error_text,
                        'lastDisconnectAt': time.time(),
                        'nextRetrySeconds': round(retry_delay, 2),
                        'error': error_text,
                    })
                    port_status['recentPortErrors'] = (port_status.get('recentPortErrors', []) + [{
                        'at': time.time(), 'error': error_text,
                        'lastByteAt': port_status.get('lastByteAt'),
                        'lastParsedFrameAt': port_status.get('lastParsedFrameAt'),
                        'lastProcessingMs': port_status.get('lastProcessingMs'),
                    }])[-10:]
                    if should_log:
                        port_status['lastDisconnectLogAt'] = now_monotonic
                        print(
                            f'[FSR] {port} disconnected: {exc}; '
                            f'retrying in {retry_delay:.2f}s.'
                        )
                    refresh_serial_error_locked()
            finally:
                with fsr_serial_status_lock:
                    if port in fsr_serial_status['connectedPorts']:
                        fsr_serial_status['connectedPorts'].remove(port)
                if connection is not None:
                    try:
                        connection.close()
                    except OSError:
                        pass
            # Downstream processing errors never reach serial recovery.
            time.sleep(retry_delay)
        with fsr_serial_status_lock:
            fsr_serial_worker_ports.discard(port)
            fsr_serial_status['started'] = bool(fsr_serial_worker_ports)

    def start_fsr_serial_workers(force_rescan=False):
        if not fsr_serial_status['enabled']:
            return serial_status_snapshot()
        try:
            from serial.tools import list_ports
        except ImportError:
            with fsr_serial_status_lock:
                fsr_serial_status['lastError'] = 'pyserial is not installed'
            return serial_status_snapshot()
        ports = configured_serial_ports(list_ports.comports())
        with fsr_serial_status_lock:
            fsr_serial_status['ports'] = ports
            fsr_serial_status['lastScanAt'] = time.time()
        if not ports:
            with fsr_serial_status_lock:
                fsr_serial_status['lastError'] = 'Không tìm thấy cổng Bluetooth FSR chiều ra'
            return serial_status_snapshot()
        for port in ports:
            with fsr_serial_status_lock:
                if port in fsr_serial_worker_ports:
                    continue
                fsr_serial_worker_ports.add(port)
                fsr_serial_status['started'] = True
                fsr_serial_status['portStatus'].setdefault(
                    port,
                    {
                        'state': 'connecting',
                        'connected': False,
                        'side': None,
                        'frameCount': 0,
                        'lastFrameAt': None,
                        'dataGapSeconds': None,
                        'reconnectCount': 0,
                        'consecutiveFailures': 0,
                        'lastDisconnectReason': '',
                        'error': '',
                    },
                )
            threading.Thread(
                target=fsr_serial_worker,
                args=(port,),
                daemon=True,
                name=f'fsr-serial-{port}',
            ).start()
        return serial_status_snapshot()

    def current_archive_frame_sizes():
        """Resolve writer dimensions from the current raw logical camera views."""
        def physical_size(lock_object, raw_name, processed_name):
            with lock_object:
                frame = getattr(state, raw_name, None)
                if frame is None:
                    frame = getattr(state, processed_name, None)
                if isinstance(frame, np.ndarray) and frame.ndim >= 2:
                    return (int(frame.shape[1]), int(frame.shape[0]))
            return default_archive_size

        size_0 = physical_size(
            state.frame_lock_0, "latest_raw_frame_0", "latest_frame_0"
        )
        size_1 = physical_size(
            state.frame_lock_1, "latest_raw_frame_1", "latest_frame_1"
        )
        if getattr(state, "SINGLE_CAMERA_MODE", False):
            return {"frontal": size_1, "sagittal": size_1}
        sizes = {"frontal": size_0, "sagittal": size_1}
        with state.camera_roles_lock:
            swapped = bool(getattr(state, "camera_roles_swapped", False))
        if swapped:
            sizes["frontal"], sizes["sagittal"] = (
                sizes["sagittal"], sizes["frontal"]
            )
        return sizes

    def prepare_archive_frame(frame, target_size):
        """Fit a changed camera mode without stretching gait geometry."""
        target_width, target_height = map(int, target_size)
        source_height, source_width = frame.shape[:2]
        if (source_width, source_height) == (target_width, target_height):
            return frame
        scale = min(target_width / source_width, target_height / source_height)
        fitted_width = max(1, int(round(source_width * scale)))
        fitted_height = max(1, int(round(source_height * scale)))
        resized = cv2.resize(
            frame,
            (fitted_width, fitted_height),
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
        )
        canvas = np.zeros((target_height, target_width, frame.shape[2]), dtype=frame.dtype)
        offset_x = (target_width - fitted_width) // 2
        offset_y = (target_height - fitted_height) // 2
        canvas[
            offset_y:offset_y + fitted_height,
            offset_x:offset_x + fitted_width,
        ] = resized
        return canvas

    def archive_loop():
        nonlocal archive_active, archive_frame_counts, archive_recording_fps
        nonlocal archive_last_sequences
        nonlocal archive_timeline_last_flush
        nonlocal archive_timeline_stream
        while getattr(state, "running", True):
            with lock:
                active = archive_active
                started_at = archive_started_at
            if not active:
                time.sleep(0.05)
                continue
            # VideoWriter requires a fixed FPS. Pace writes from wall-clock
            # time, but never duplicate a stale capture frame. Duplicating the
            # latest frame hid a USB-camera collapse (for example, 1 FPS became
            # fifteen identical frames) and made replay look frozen.
            target_count = max(
                1,
                int(max(0.0, time.time() - started_at) * archive_recording_fps) + 1,
            )
            frames = {}
            sequences = {}
            captured_times = {}
            captured_ns = {}
            with state.frame_lock_0:
                # Source archives are immutable raw evidence. Skeletons,
                # angles and charts are derived again from these pixels.
                frontal = getattr(state, "latest_raw_frame_0", None)
                if frontal is None:
                    frontal = getattr(state, "latest_frame_0", None)
                if frontal is not None:
                    frames["frontal"] = frontal.copy()
                    sequences["frontal"] = int(
                        getattr(state, "latest_capture_sequence_0", 0)
                        or getattr(state, "latest_frame_0_ns", 0)
                        or 0
                    )
                    captured_times["frontal"] = float(
                        getattr(state, "latest_frame_0_at", 0.0) or 0.0
                    )
                    captured_ns["frontal"] = int(
                        getattr(state, "latest_frame_0_ns", 0) or 0
                    )
            with state.frame_lock_1:
                sagittal = getattr(state, "latest_raw_frame_1", None)
                if sagittal is None:
                    sagittal = getattr(state, "latest_frame_1", None)
                if sagittal is not None:
                    frames["sagittal"] = sagittal.copy()
                    sequences["sagittal"] = int(
                        getattr(state, "latest_capture_sequence_1", 0)
                        or getattr(state, "latest_frame_1_ns", 0)
                        or 0
                    )
                    captured_times["sagittal"] = float(
                        getattr(state, "latest_frame_1_at", 0.0) or 0.0
                    )
                    captured_ns["sagittal"] = int(
                        getattr(state, "latest_frame_1_ns", 0) or 0
                    )
                    if getattr(state, "SINGLE_CAMERA_MODE", False):
                        frames["frontal"] = sagittal.copy()
                        sequences["frontal"] = sequences["sagittal"]
                        captured_times["frontal"] = captured_times["sagittal"]
                        captured_ns["frontal"] = captured_ns["sagittal"]
            with state.camera_roles_lock:
                swapped = state.camera_roles_swapped
            if swapped:
                frames["frontal"], frames["sagittal"] = (
                    frames.get("sagittal"), frames.get("frontal")
                )
                sequences["frontal"], sequences["sagittal"] = (
                    sequences.get("sagittal"), sequences.get("frontal")
                )
                captured_times["frontal"], captured_times["sagittal"] = (
                    captured_times.get("sagittal"), captured_times.get("frontal")
                )
                captured_ns["frontal"], captured_ns["sagittal"] = (
                    captured_ns.get("sagittal"), captured_ns.get("frontal")
                )
            with lock:
                if archive_active:
                    for view, writer in writers.items():
                        frame = frames.get(view)
                        sequence = sequences.get(view)
                        if writer is None or frame is None or sequence is None:
                            continue
                        if archive_frame_counts[view] >= target_count:
                            continue
                        if archive_last_sequences[view] == sequence:
                            continue
                        encoded_frame = prepare_archive_frame(
                            frame,
                            archive_frame_sizes.get(view, default_archive_size),
                        )
                        frame_index = archive_frame_counts[view]
                        writer.write(encoded_frame)
                        archive_frame_counts[view] += 1
                        archive_last_sequences[view] = sequence
                        if (
                            archive_timeline_stream is None
                            and archive_timeline_path_pending is not None
                        ):
                            archive_timeline_stream = (
                                archive_timeline_path_pending.open(
                                    "a",
                                    encoding="utf-8",
                                    buffering=1,
                                )
                            )
                        if archive_timeline_stream is not None:
                            captured_at = float(
                                captured_times.get(view) or time.time()
                            )
                            timeline_item = {
                                "schemaVersion": 1,
                                "view": view,
                                "frameIndex": frame_index,
                                "sequence": sequence,
                                "time": round(
                                    max(0.0, captured_at - started_at),
                                    6,
                                ),
                                "capturedAt": captured_at,
                                "capturedNs": int(captured_ns.get(view) or 0),
                            }
                            archive_timeline_stream.write(
                                json.dumps(
                                    timeline_item,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                                + "\n"
                            )
                            now_monotonic = time.monotonic()
                            if now_monotonic - archive_timeline_last_flush >= 1.0:
                                archive_timeline_stream.flush()
                                archive_timeline_last_flush = now_monotonic
            time.sleep(0.01)

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

    def archive_fsr_path(session_id, stored_archive_id):
        return archive_video_path(
            session_id, stored_archive_id, "frontal"
        ).with_name("fsr.jsonl")

    def archive_timeline_path(session_id, stored_archive_id):
        return archive_video_path(
            session_id, stored_archive_id, "frontal"
        ).with_name("frame_timeline.jsonl")

    def archive_manifest_path(session_id, stored_archive_id):
        return archive_video_path(
            session_id, stored_archive_id, "frontal"
        ).with_name("capture_manifest.json")

    def load_archive_fsr_samples(session_id, stored_archive_id):
        path = archive_fsr_path(session_id, stored_archive_id)
        if not path.is_file():
            return []
        samples = []
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    sample = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if (
                    isinstance(sample, dict)
                    and sample.get("side") in ("left", "right")
                    and np.isfinite(float(sample.get("time", float("nan"))))
                ):
                    samples.append(sample)
        return sorted(samples, key=lambda sample: float(sample["time"]))

    def archive_for_video(session_id, video_id):
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT * FROM recording_archives
                   WHERE session_id = ?
                     AND (frontal_video_id = ? OR sagittal_video_id = ?)
                   ORDER BY started_at DESC LIMIT 1""",
                (session_id, video_id, video_id),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    def load_archive_frame_timeline(session_id, stored_archive_id):
        path = archive_timeline_path(session_id, stored_archive_id)
        result = {"frontal": [], "sagittal": []}
        if not path.is_file():
            return result
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                    view = str(item.get("view", ""))
                    frame_index = int(item.get("frameIndex"))
                    relative_time = float(item.get("time"))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if view not in result or frame_index < 0 or not np.isfinite(relative_time):
                    continue
                result[view].append((frame_index, max(0.0, relative_time)))
        for view in result:
            result[view].sort(key=lambda item: item[0])
        return result

    def video_frame_times(session_id, video_id):
        archive = archive_for_video(session_id, video_id)
        if archive is None:
            return []
        view = (
            "frontal"
            if archive["frontal_video_id"] == video_id
            else "sagittal"
        )
        entries = load_archive_frame_timeline(
            session_id,
            archive["id"],
        )[view]
        if not entries:
            return []
        maximum = max(index for index, _ in entries)
        times = [None] * (maximum + 1)
        for index, relative_time in entries:
            times[index] = relative_time
        return times

    def append_archive_fsr_sample(sample):
        nonlocal archive_fsr_stream
        nonlocal archive_fsr_sample_count, archive_fsr_last_flush
        now = time.monotonic()
        encoded = json.dumps(
            finite_json(sample), ensure_ascii=False, separators=(",", ":")
        )
        with archive_fsr_lock:
            if archive_fsr_stream is None and archive_fsr_pending_path is not None:
                archive_fsr_stream = archive_fsr_pending_path.open(
                    "a", encoding="utf-8", buffering=1
                )
            if archive_fsr_stream is None:
                return
            archive_fsr_stream.write(encoded + "\n")
            archive_fsr_sample_count += 1
            if now - archive_fsr_last_flush >= 1.0:
                archive_fsr_stream.flush()
                archive_fsr_last_flush = now

    def recovered_video_path(session_id, stored_archive_id, view):
        original = archive_video_path(session_id, stored_archive_id, view)
        return original.with_name(f"{view}.recovered.avi")

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
            recovered = recovered_video_path(session_id, row["id"], view)
            if recovered.is_file():
                return recovered
            if grouped.is_file():
                return grouped
        # Compatibility with recordings created before grouped folders.
        return recordings_dir / f"{video_id}.avi"

    def recover_one_interrupted_video(source, destination, duration_sec):
        """Re-index an unclosed MJPEG AVI without modifying the source file."""
        capture = cv2.VideoCapture(str(source))
        nominal_fps = float(capture.get(cv2.CAP_PROP_FPS) or archive_fps)
        frame_count = 0
        while True:
            ok, _ = capture.read()
            if not ok:
                break
            frame_count += 1
        capture.release()
        if frame_count <= 0:
            return 0
        recovered_fps = min(
            nominal_fps,
            max(5.0, (frame_count - 1) / max(0.5, duration_sec)),
        )
        temporary = destination.with_name(f"{destination.stem}.recovering.avi")
        capture = cv2.VideoCapture(str(source))
        first_ok, first_frame = capture.read()
        if not first_ok or first_frame is None:
            capture.release()
            return 0
        source_size = (int(first_frame.shape[1]), int(first_frame.shape[0]))
        writer = cv2.VideoWriter(
            str(temporary),
            cv2.VideoWriter_fourcc(*"MJPG"),
            recovered_fps,
            source_size,
        )
        if not writer.isOpened():
            capture.release()
            writer.release()
            temporary.unlink(missing_ok=True)
            return 0
        written = 0
        write_error = None
        try:
            writer.write(first_frame)
            written = 1
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                writer.write(prepare_archive_frame(frame, source_size))
                written += 1
        except Exception as exc:
            write_error = exc
        finally:
            capture.release()
            writer.release()
        if write_error is not None:
            temporary.unlink(missing_ok=True)
            raise write_error
        validation = cv2.VideoCapture(str(temporary))
        valid_count = int(validation.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        first_ok, _ = validation.read()
        validation.release()
        if not first_ok or valid_count <= 0 or written <= 0:
            temporary.unlink(missing_ok=True)
            return 0
        os.replace(temporary, destination)
        return written

    def recover_interrupted_archives():
        """Recover files left without an AVI index after a backend crash."""
        if os.getenv("CAMERA_AUTO_RECOVER", "true").lower() not in (
            "1", "true", "yes"
        ):
            return
        conn = get_db_connection()
        rows = conn.execute(
            """SELECT * FROM recording_archives
               WHERE status = 'interrupted'
               ORDER BY started_at ASC"""
        ).fetchall()
        conn.close()
        for row in rows:
            session_id = row["session_id"]
            stored_archive_id = row["id"]
            sources = {
                view: archive_video_path(session_id, stored_archive_id, view)
                for view in ("frontal", "sagittal")
            }
            if not all(path.is_file() for path in sources.values()):
                continue
            try:
                started_at = datetime.fromisoformat(
                    str(row["started_at"]).replace("Z", "+00:00")
                ).timestamp()
            except (TypeError, ValueError):
                started_at = min(path.stat().st_ctime for path in sources.values())
            last_write = max(path.stat().st_mtime for path in sources.values())
            duration = max(0.5, last_write - started_at)
            counts = {}
            try:
                for view, source in sources.items():
                    destination = recovered_video_path(
                        session_id,
                        stored_archive_id,
                        view,
                    )
                    if destination.is_file():
                        validation = cv2.VideoCapture(str(destination))
                        count = int(validation.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                        validation.release()
                    else:
                        count = recover_one_interrupted_video(
                            source,
                            destination,
                            duration,
                        )
                    counts[view] = count
                if any(count <= 0 for count in counts.values()):
                    continue
                stopped_at = datetime.fromtimestamp(
                    last_write,
                    tz=timezone.utc,
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                conn = get_db_connection()
                conn.execute(
                    """UPDATE recording_archives
                       SET stopped_at = ?, duration_sec = ?,
                           frontal_frame_count = ?, sagittal_frame_count = ?,
                           status = 'complete'
                       WHERE id = ? AND session_id = ?
                         AND status = 'interrupted'""",
                    (
                        stopped_at,
                        duration,
                        counts["frontal"],
                        counts["sagittal"],
                        stored_archive_id,
                        session_id,
                    ),
                )
                conn.commit()
                conn.close()
                print(
                    f"[Archive recovery] Recovered {stored_archive_id}: "
                    f"{counts['frontal']}/{counts['sagittal']} frames, "
                    f"{duration:.1f}s."
                )
            except Exception as exc:
                print(f"[Archive recovery] Could not recover {stored_archive_id}: {exc}")

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
        nonlocal archive_active, writers, archive_recording_fps
        nonlocal archive_fsr_stream, archive_fsr_pending_path
        nonlocal archive_timeline_stream, archive_timeline_path_pending
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
            recording_fps = archive_recording_fps
            frame_sizes = dict(archive_frame_sizes)
            closing_timeline_stream = archive_timeline_stream
            archive_timeline_stream = None
            archive_timeline_path_pending = None
        for writer in closing:
            if writer is not None:
                writer.release()
        state.is_recording = False
        with archive_fsr_lock:
            closing_fsr_stream = archive_fsr_stream
            archive_fsr_stream = None
            archive_fsr_pending_path = None
            fsr_sample_count = archive_fsr_sample_count
        if closing_fsr_stream is not None:
            closing_fsr_stream.flush()
            closing_fsr_stream.close()
        if closing_timeline_stream is not None:
            closing_timeline_stream.flush()
            closing_timeline_stream.close()
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
        fsr_path = (
            archive_fsr_path(current_session_id, current_archive_id)
            if current_archive_id and current_session_id
            else None
        )
        timeline_path = (
            archive_timeline_path(current_session_id, current_archive_id)
            if current_archive_id and current_session_id
            else None
        )
        manifest_path = (
            archive_manifest_path(current_session_id, current_archive_id)
            if current_archive_id and current_session_id
            else None
        )
        if manifest_path is not None and was_active:
            context = patient_measurement_context(current_session_id)
            manifest = {
                "schemaVersion": 1,
                "captureKind": "raw_v1",
                "archiveId": current_archive_id,
                "sessionId": current_session_id,
                "durationSec": duration,
                "recordingFps": recording_fps,
                "videoIds": ids,
                "frameCounts": counts,
                "frameSizes": {
                    view: {"width": size[0], "height": size[1]}
                    for view, size in frame_sizes.items()
                },
                "frameTimeline": "frame_timeline.jsonl",
                "fsrStream": "fsr.jsonl",
                "fsrRawAdcStored": True,
                "cameraRoles": {
                    "frontal": int(getattr(state, "CAMERA_FRONTAL_INDEX", 0)),
                    "sagittal": int(getattr(state, "CAMERA_SAGITTAL_INDEX", 1)),
                },
                "anthropometry": context,
                "algorithmVersionAtCapture": ANALYSIS_ALGORITHM_VERSION,
            }
            temporary_manifest = manifest_path.with_suffix(".json.tmp")
            temporary_manifest.write_text(
                json.dumps(
                    finite_json(manifest),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(temporary_manifest, manifest_path)
        return {
            "archiveId": current_archive_id,
            "durationSec": duration,
            "frameCounts": counts,
            "effectiveFps": {
                view: round(count / duration, 2) if duration > 0 else 0.0
                for view, count in counts.items()
            },
            "fileSizes": sizes,
            "fsrSampleCount": fsr_sample_count,
            "fsrFileSize": (
                fsr_path.stat().st_size
                if fsr_path is not None and fsr_path.is_file()
                else 0
            ),
            "timelineFileSize": (
                timeline_path.stat().st_size
                if timeline_path is not None and timeline_path.is_file()
                else 0
            ),
            "manifestStored": bool(
                manifest_path is not None and manifest_path.is_file()
            ),
            "captureKind": "raw_v1",
            "videoIds": ids,
            "recordingFps": recording_fps,
            "frameSizes": {
                view: {"width": size[0], "height": size[1]}
                for view, size in frame_sizes.items()
            },
        }

    threading.Thread(target=fsr_receiver, daemon=True, name="fsr-udp").start()
    threading.Thread(target=archive_loop, daemon=True, name="camera-archive").start()
    threading.Thread(
        target=recover_interrupted_archives,
        daemon=True,
        name="archive-recovery",
    ).start()

    @app.post("/fsr/connect")
    def connect_fsr_hardware():
        """Discover both outgoing Bluetooth ports and connect them in-process."""
        status = start_fsr_serial_workers(force_rescan=True)
        return {
            "status": "connecting" if status.get("ports") else "not_found",
            "serialStatus": status,
            "message": (
                "Đang kết nối FSR trực tiếp trong AI-ProGait."
                if status.get("ports")
                else status.get("lastError")
            ),
        }

    @app.get("/fsr/serial-status")
    def get_fsr_serial_status():
        """Diagnostics without port discovery or the force/step processing lock."""
        return {'sampledAt': time.time(), **serial_status_snapshot()}

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
            'serialStatus': serial_status_snapshot(),
            "peakFore": step_snapshot["peakFore"],
            "fsi": step_snapshot["fsi"],
            "forceSource": step_snapshot["forceSource"],
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
    def get_gait_steps(
        window: int = 5,
        height_cm: float | None = None,
        left_leg_length_cm: float | None = None,
        right_leg_length_cm: float | None = None,
    ):
        if window not in VALID_WINDOWS:
            raise HTTPException(
                status_code=422,
                detail=f"Window must be one of {VALID_WINDOWS}.",
            )
        # Several chart widgets (or an old browser tab) can poll this expensive
        # analysis endpoint at the same time.  Reuse one short-lived result so
        # MediaPipe/camera capture never loses CPU to duplicate cycle analysis.
        cache_key = (
            window,
            height_cm,
            left_leg_length_cm,
            right_leg_length_cm,
            getattr(state, "active_session_id", ""),
        )
        live_lock = getattr(state, "live_gait_lock", None)
        if live_lock is None:
            live_samples = getattr(state, "live_gait_samples", [])
            latest_sample_at = (
                float(live_samples[-1].get("time", 0.0)) if live_samples else 0.0
            )
        else:
            with live_lock:
                live_samples = getattr(state, "live_gait_samples", [])
                latest_sample_at = (
                    float(live_samples[-1].get("time", 0.0)) if live_samples else 0.0
                )
        # A quarter-second generation bucket lets the two UI pollers share one
        # analysis, while a newly completed step is still visible promptly.
        with fsr_lock:
            contact_count = len(fsr_steps.contact_events())
        cache_key += (int(latest_sample_at * 4.0), contact_count)
        now = time.monotonic()
        with gait_response_cache_lock:
            if (
                gait_response_cache["key"] == cache_key
                and now - gait_response_cache["at"] < 0.25
                and gait_response_cache["value"] is not None
            ):
                return gait_response_cache["value"]
            value = build_live_gait(
                window_size=window,
                height_cm=height_cm,
                left_leg_length_cm=left_leg_length_cm,
                right_leg_length_cm=right_leg_length_cm,
            )
            gait_response_cache.update({"key": cache_key, "at": now, "value": value})
            return value
    @app.get("/camera/devices")
    def get_camera_devices(refresh: bool = False):
        started_at = time.monotonic()
        temporarily_stopped = False
        if refresh and getattr(state, "camera_workers_started", False):
            if getattr(state, "is_recording", False):
                raise HTTPException(
                    status_code=409,
                    detail="Hãy dừng ghi hình trước khi dò lại camera.",
                )
            state.stop_camera_workers()
            temporarily_stopped = True
        try:
            devices = available_camera_devices(force=refresh)
        finally:
            if temporarily_stopped and getattr(state, "camera_configured", False):
                state.start_camera_workers()
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
                "Có thể đổi vai trò camera mà không cần khởi động lại backend."
                if configured else ""
            ),
        }

    @app.get("/camera/preview/{index}")
    def camera_preview(index: int):
        if index < 0 or index > camera_max_probe_index:
            raise HTTPException(
                status_code=422,
                detail=f"Camera index must be between 0 and {camera_max_probe_index}.",
            )
        workers_started = bool(getattr(state, "camera_workers_started", False))
        if workers_started:
            single_camera = bool(getattr(state, "SINGLE_CAMERA_MODE", False))
            frontal_index = getattr(state, "CAMERA_FRONTAL_INDEX", None)
            sagittal_index = getattr(state, "CAMERA_SAGITTAL_INDEX", None)
            selected_slot = None
            if index == sagittal_index:
                selected_slot = 1
            elif not single_camera and index == frontal_index:
                selected_slot = 0
            if selected_slot is not None:
                lock = getattr(state, f"frame_lock_{selected_slot}")
                with lock:
                    frame = getattr(
                        state,
                        f"latest_raw_frame_{selected_slot}",
                        None,
                    )
                    if frame is None:
                        frame = getattr(state, f"latest_frame_{selected_slot}", None)
                    frame = frame.copy() if frame is not None else None
                if frame is None:
                    raise HTTPException(
                        status_code=503,
                        detail="Camera is starting and has not returned a frame yet.",
                    )
                encoded, jpeg = cv2.imencode(
                    ".jpg",
                    frame,
                    [
                        cv2.IMWRITE_JPEG_QUALITY,
                        int(getattr(state, "STREAM_JPEG_QUALITY", 84)),
                    ],
                )
                if not encoded:
                    raise HTTPException(status_code=500, detail="Cannot encode camera preview.")
                return Response(
                    content=jpeg.tobytes(),
                    media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"},
                )
            if getattr(state, "is_recording", False):
                raise HTTPException(
                    status_code=409,
                    detail="Hãy dừng ghi hình trước khi xem thử camera khác.",
                )
        capture = state.open_camera(index, f"Camera preview {index}")
        if capture is None:
            raise HTTPException(status_code=404, detail="Camera index is not available.")
        try:
            success, frame = capture.read()
            if not success or frame is None:
                raise HTTPException(status_code=404, detail="Camera returned no frame.")
            encoded, jpeg = cv2.imencode(
                ".jpg",
                frame,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    int(getattr(state, "STREAM_JPEG_QUALITY", 84)),
                ],
            )
            if not encoded:
                raise HTTPException(status_code=500, detail="Cannot encode camera preview.")
            return Response(
                content=jpeg.tobytes(),
                media_type="image/jpeg",
                headers={"Cache-Control": "no-store"},
            )
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
        if (
            frontal_index < 0
            or sagittal_index < 0
            or frontal_index > camera_max_probe_index
            or sagittal_index > camera_max_probe_index
        ):
            raise HTTPException(
                status_code=422,
                detail=f"Camera indexes must be between 0 and {camera_max_probe_index}.",
            )
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

    def recent_fps(values, now=None):
        now = time.time() if now is None else float(now)
        try:
            snapshot = list(values or [])
        except RuntimeError:
            snapshot = list(values or [])
        samples = [
            float(value)
            for value in snapshot
            if now - float(value) <= 3.0
        ]
        if len(samples) < 2 or samples[-1] <= samples[0]:
            return 0.0
        return round((len(samples) - 1) / (samples[-1] - samples[0]), 2)

    def recent_count(values, now=None, window_seconds=3.0):
        now = time.time() if now is None else float(now)
        try:
            snapshot = list(values or [])
        except RuntimeError:
            snapshot = list(values or [])
        return sum(
            1
            for value in snapshot
            if now - float(value) <= float(window_seconds)
        )

    @app.get("/camera-status")
    def get_camera_status():
        now = time.time()
        capture_fps_0 = recent_fps(getattr(state, "capture_times_0", []))
        capture_fps_1 = recent_fps(getattr(state, "capture_times_1", []))
        pose_fps_0 = recent_fps(getattr(state, "pose_times_0", []))
        pose_fps_1 = recent_fps(getattr(state, "pose_times_1", []))
        inference_fps_0 = recent_fps(getattr(state, "pose_inference_times_0", []))
        inference_fps_1 = recent_fps(getattr(state, "pose_inference_times_1", []))
        reliable_fps_0 = recent_fps(getattr(state, "pose_reliable_times_0", []))
        reliable_fps_1 = recent_fps(getattr(state, "pose_reliable_times_1", []))
        inference_count_0 = recent_count(getattr(state, "pose_inference_times_0", []), now)
        inference_count_1 = recent_count(getattr(state, "pose_inference_times_1", []), now)
        detection_count_0 = recent_count(getattr(state, "pose_times_0", []), now)
        detection_count_1 = recent_count(getattr(state, "pose_times_1", []), now)
        reliable_count_0 = recent_count(getattr(state, "pose_reliable_times_0", []), now)
        reliable_count_1 = recent_count(getattr(state, "pose_reliable_times_1", []), now)
        health_0 = dict(getattr(state, "camera_health_0", {}) or {})
        health_1 = dict(getattr(state, "camera_health_1", {}) or {})
        def physical_image_size(health):
            width = int(
                health.get("actualFrameWidth")
                or health.get("reportedWidth")
                or 0
            )
            height = int(
                health.get("actualFrameHeight")
                or health.get("reportedHeight")
                or 0
            )
            return (width, height) if width > 0 and height > 0 else None

        calibration_image_size_0 = physical_image_size(health_0)
        calibration_image_size_1 = physical_image_size(health_1)
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
            capture_fps_0, capture_fps_1 = capture_fps_1, capture_fps_0
            pose_fps_0, pose_fps_1 = pose_fps_1, pose_fps_0
            inference_fps_0, inference_fps_1 = inference_fps_1, inference_fps_0
            reliable_fps_0, reliable_fps_1 = reliable_fps_1, reliable_fps_0
            health_0, health_1 = health_1, health_0
            inference_count_0, inference_count_1 = inference_count_1, inference_count_0
            detection_count_0, detection_count_1 = detection_count_1, detection_count_0
            reliable_count_0, reliable_count_1 = reliable_count_1, reliable_count_0
            frontal_index, sagittal_index = sagittal_index, frontal_index
        if getattr(state, "SINGLE_CAMERA_MODE", False):
            camera_0 = camera_1
            pose_0 = pose_1
            capture_fps_0 = capture_fps_1
            pose_fps_0 = pose_fps_1
            inference_fps_0 = inference_fps_1
            reliable_fps_0 = reliable_fps_1
            health_0 = dict(health_1)
            inference_count_0 = inference_count_1
            detection_count_0 = detection_count_1
            reliable_count_0 = reliable_count_1
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
        calibration_status = state.stereo_calibration.status(
            calibration_indices,
            image_size_0=calibration_image_size_0,
            image_size_1=calibration_image_size_1,
        )
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
            "posePipeline": {
                "inputWidth": getattr(state, "POSE_INPUT_WIDTH", None),
                "reacquireInputWidth": getattr(
                    state, "POSE_REACQUIRE_INPUT_WIDTH", None
                ),
                "reacquireInterval": getattr(
                    state, "POSE_REACQUIRE_INTERVAL", None
                ),
                "targetFps": getattr(state, "POSE_TARGET_FPS", None),
                "modelComplexity": getattr(state, "POSE_MODEL_COMPLEXITY", None),
                "minDetectionConfidence": getattr(
                    state, "POSE_DETECTION_CONFIDENCE", None
                ),
                "minTrackingConfidence": getattr(
                    state, "POSE_TRACKING_CONFIDENCE", None
                ),
                "archiveMaxFps": archive_fps,
            },
            "captureProfile": {
                "requestedWidth": getattr(state, "CAMERA_REQUEST_WIDTH", None),
                "requestedHeight": getattr(state, "CAMERA_REQUEST_HEIGHT", None),
                "requestedFps": getattr(state, "CAMERA_REQUEST_FPS", None),
            },
            "previewProfile": {
                "maxWidth": getattr(state, "STREAM_MAX_WIDTH", None),
                "targetFps": getattr(state, "STREAM_TARGET_FPS", None),
                "jpegQuality": getattr(state, "STREAM_JPEG_QUALITY", None),
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
                "captureFps": capture_fps_0,
                "poseFps": pose_fps_0,
                "inferenceFps": inference_fps_0,
                "reliablePoseFps": reliable_fps_0,
                "poseDetectionRate": round(
                    detection_count_0 / max(1, inference_count_0), 3
                ),
                "reliablePoseRate": round(
                    reliable_count_0 / max(1, inference_count_0), 3
                ),
                "imageQuality": health_0,
            },
            "camera1": {
                "connected": camera_1,
                "poseDetected": pose_1,
                "index": sagittal_index,
                "captureFps": capture_fps_1,
                "poseFps": pose_fps_1,
                "inferenceFps": inference_fps_1,
                "reliablePoseFps": reliable_fps_1,
                "poseDetectionRate": round(
                    detection_count_1 / max(1, inference_count_1), 3
                ),
                "reliablePoseRate": round(
                    reliable_count_1 / max(1, inference_count_1), 3
                ),
                "imageQuality": health_1,
            },
            "synchronization": sync_status,
            "stereoCalibration": calibration_status,
        }

    @app.get("/system/health")
    def get_system_health():
        """Read-only preflight for field recording and reproducible QA logs."""
        conn = get_db_connection()
        try:
            integrity_rows = conn.execute("PRAGMA quick_check").fetchall()
            integrity = [str(row[0]) for row in integrity_rows]
            foreign_key_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
            archives = conn.execute(
                """SELECT id, session_id FROM recording_archives
                   WHERE status = 'complete' ORDER BY started_at DESC"""
            ).fetchall()
        finally:
            conn.close()
        missing_files = []
        for row in archives:
            for view in ("frontal", "sagittal"):
                original = archive_video_path(row["session_id"], row["id"], view)
                recovered = recovered_video_path(row["session_id"], row["id"], view)
                if not original.is_file() and not recovered.is_file():
                    missing_files.append(f"{row['id']}:{view}")
        usage = shutil.disk_usage(recordings_dir)
        camera = get_camera_status()
        configured = camera["configuration"]["configured"]
        camera_connected = (
            camera["camera1"]["connected"]
            and (
                camera["configuration"]["singleCameraMode"]
                or camera["camera0"]["connected"]
            )
        )
        camera_image_ready = (
            camera["camera1"].get("imageQuality", {}).get("qualityReady") is True
            and (
                camera["configuration"]["singleCameraMode"]
                or camera["camera0"].get("imageQuality", {}).get("qualityReady") is True
            )
        )
        camera_hardware_ready = camera_connected and camera_image_ready
        database_ok = integrity == ["ok"] and foreign_key_errors == 0
        return {
            "status": (
                "ok"
                if database_ok
                and not missing_files
                and (not configured or camera_hardware_ready)
                else "degraded"
            ),
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "database": {
                "integrity": integrity,
                "foreignKeyErrors": foreign_key_errors,
            },
            "archiveStorage": {
                "path": str(recordings_dir),
                "freeBytes": usage.free,
                "missingFiles": missing_files[:20],
                "missingFileCount": len(missing_files),
            },
            "camera": {
                "configured": configured,
                "connected": camera_connected,
                "hardwareReady": camera_hardware_ready,
                "recording": camera["recording"],
                "camera0": camera["camera0"],
                "camera1": camera["camera1"],
                "synchronization": camera["synchronization"],
                "posePipeline": camera["posePipeline"],
            },
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
        require_fsr: bool = False,
    ):
        nonlocal archive_active, writers, video_ids
        nonlocal archive_id, archive_session_id, archive_started_at
        nonlocal archive_frame_counts, archive_recording_fps, archive_frame_sizes
        nonlocal archive_last_sequences
        nonlocal archive_fsr_stream, archive_fsr_pending_path
        nonlocal archive_fsr_sample_count
        nonlocal archive_fsr_last_flush
        nonlocal archive_timeline_stream, archive_timeline_path_pending
        nonlocal archive_timeline_last_flush
        if archive_active:
            raise HTTPException(status_code=409, detail="A recording is already active.")
        if healthy == prosthetic:
            raise HTTPException(
                status_code=422,
                detail="Chân lành và chân giả phải ở hai bên khác nhau.",
            )
        conn = get_db_connection()
        try:
            if conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone() is None:
                raise HTTPException(status_code=404, detail="Không tìm thấy phiên đo.")
        finally:
            conn.close()
        now = time.time()
        with fsr_lock:
            fsr_preflight = {
                side: (dict(value) if value else None)
                for side, value in latest_fsr.items()
            }
        fsr_connected = {
            side: bool(
                sample
                and now - float(sample.get("receivedAt", 0.0) or 0.0) < 2.0
            )
            for side, sample in fsr_preflight.items()
        }
        fsr_ready = all(fsr_connected.get(side, False) for side in ("left", "right"))
        # FSR is optional for camera-only recordings. Keep require_fsr in the
        # public API for compatibility with older clients, but never let a
        # missing or stale insole prevent the raw camera archive from starting.
        invalid_fsr_timestamps = [
            side for side in ("left", "right")
            if fsr_connected.get(side, False)
            and not fsr_preflight[side].get("timestampValid", False)
        ]
        camera_0_ready = (
            now - float(getattr(state, "latest_frame_0_at", 0.0) or 0.0) < 2.0
        )
        camera_1_ready = (
            now - float(getattr(state, "latest_frame_1_at", 0.0) or 0.0) < 2.0
        )
        if getattr(state, "SINGLE_CAMERA_MODE", False):
            camera_0_ready = camera_1_ready
        if not camera_0_ready or (
            not getattr(state, "SINGLE_CAMERA_MODE", False) and not camera_1_ready
        ):
            raise HTTPException(
                status_code=409,
                detail="Cả hai luồng camera phải có hình trước khi bắt đầu ghi.",
            )
        single_camera = bool(getattr(state, "SINGLE_CAMERA_MODE", False))
        capture_rates = [
            recent_fps(getattr(state, "capture_times_1", [])),
        ] if single_camera else [
            recent_fps(getattr(state, "capture_times_0", [])),
            recent_fps(getattr(state, "capture_times_1", [])),
        ]
        pose_rates = [
            recent_fps(getattr(state, "pose_times_1", [])),
        ] if single_camera else [
            recent_fps(getattr(state, "pose_times_0", [])),
            recent_fps(getattr(state, "pose_times_1", [])),
        ]
        reliable_pose_rates = [
            recent_fps(getattr(state, "pose_reliable_times_1", [])),
        ] if single_camera else [
            recent_fps(getattr(state, "pose_reliable_times_0", [])),
            recent_fps(getattr(state, "pose_reliable_times_1", [])),
        ]
        inference_counts = [
            recent_count(getattr(state, "pose_inference_times_1", []), now),
        ] if single_camera else [
            recent_count(getattr(state, "pose_inference_times_0", []), now),
            recent_count(getattr(state, "pose_inference_times_1", []), now),
        ]
        detection_counts = [
            recent_count(getattr(state, "pose_times_1", []), now),
        ] if single_camera else [
            recent_count(getattr(state, "pose_times_0", []), now),
            recent_count(getattr(state, "pose_times_1", []), now),
        ]
        reliable_counts = [
            recent_count(getattr(state, "pose_reliable_times_1", []), now),
        ] if single_camera else [
            recent_count(getattr(state, "pose_reliable_times_0", []), now),
            recent_count(getattr(state, "pose_reliable_times_1", []), now),
        ]
        detection_ratios = [
            detected / max(1, inferred)
            for detected, inferred in zip(detection_counts, inference_counts)
        ]
        reliable_ratios = [
            reliable / max(1, inferred)
            for reliable, inferred in zip(reliable_counts, inference_counts)
        ]
        image_health = [
            dict(getattr(state, "camera_health_1", {}) or {}),
        ] if single_camera else [
            dict(getattr(state, "camera_health_0", {}) or {}),
            dict(getattr(state, "camera_health_1", {}) or {}),
        ]
        has_capture_telemetry = hasattr(state, "capture_times_1") and (
            single_camera or hasattr(state, "capture_times_0")
        )
        has_pose_telemetry = hasattr(state, "pose_times_1") and (
            single_camera or hasattr(state, "pose_times_0")
        )
        has_reliable_pose_telemetry = hasattr(state, "pose_reliable_times_1") and (
            single_camera or hasattr(state, "pose_reliable_times_0")
        )
        has_inference_telemetry = hasattr(state, "pose_inference_times_1") and (
            single_camera or hasattr(state, "pose_inference_times_0")
        )
        bad_image_reasons = sorted({
            reason
            for health in image_health
            if health and health.get("qualityReady") is False
            for reason in health.get("qualityReasons", [])
        })
        if bad_image_reasons:
            reason_text = {
                "too_dark": "hình quá tối hoặc nắp camera đang đóng",
                "overexposed": "hình bị cháy sáng",
                "too_blurry": "hình quá mờ/mất nét",
            }
            readable = [reason_text.get(item, item) for item in bad_image_reasons]
            raise HTTPException(
                status_code=409,
                detail=(
                    "Chất lượng hình camera chưa đạt: "
                    f"{', '.join(readable)}. Hãy kiểm tra nắp camera, ánh sáng và lấy nét."
                ),
            )
        if has_capture_telemetry and min(capture_rates, default=0.0) < 12.0:
            raise HTTPException(
                status_code=409,
                detail=(
                    "FPS camera chưa ổn định "
                    f"({', '.join(f'{value:.1f}' for value in capture_rates)}). "
                    "Hãy tăng ánh sáng, chờ vài giây và đóng Camera/Zoom/Meet rồi thử lại."
                ),
            )
        recording_warnings = []
        if not fsr_ready:
            missing_fsr = [
                "trái" if side == "left" else "phải"
                for side in ("left", "right")
                if not fsr_connected.get(side, False)
            ]
            recording_warnings.append(
                "Vẫn đang ghi video camera nhưng chưa nhận FSR chân "
                f"{', '.join(missing_fsr)}. Phiên này sẽ không có đủ dữ liệu "
                "lực, chạm đất, PeakFore hoặc FSI."
            )
        if invalid_fsr_timestamps:
            invalid_labels = [
                "trái" if side == "left" else "phải"
                for side in invalid_fsr_timestamps
            ]
            recording_warnings.append(
                "FSR chân "
                f"{', '.join(invalid_labels)} có timestamp không hợp lệ. "
                "Video vẫn được ghi nhưng không nên dùng dữ liệu lực của chân này."
            )
        if has_inference_telemetry and min(detection_ratios, default=0.0) < 0.70:
            recording_warnings.append(
                "Tỷ lệ nhận diện toàn thân chưa ổn định "
                f"({', '.join(f'{value * 100:.0f}%' for value in detection_ratios)}, cần ≥ 70%). "
                "Hãy giữ người trong khung hình liên tục."
            )
        if has_pose_telemetry and min(pose_rates, default=0.0) < 8.0:
            recording_warnings.append(
                "Nhận dạng toàn thân chưa đủ ổn định để ghi dữ liệu dáng đi "
                f"({', '.join(f'{value:.1f}' for value in pose_rates)} FPS). "
                "Hãy để toàn thân hiện rõ trong cả hai góc camera rồi thử lại."
            )
        if (
            has_reliable_pose_telemetry
            and (
                min(reliable_pose_rates, default=0.0) < 6.0
                or (
                    has_inference_telemetry
                    and min(reliable_ratios, default=0.0) < 0.50
                )
            )
        ):
            recording_warnings.append(
                "Pose đạt chất lượng chưa đủ ổn định "
                f"({', '.join(f'{value:.1f}' for value in reliable_pose_rates)} FPS; "
                f"{', '.join(f'{value * 100:.0f}%' for value in reliable_ratios)} frame đạt, "
                "cần ≥ 6 FPS và ≥ 50%). "
                "Hãy thấy trọn toàn thân, tăng ánh sáng và tránh che hông–gối–cổ chân."
            )
        synchronizer = getattr(state, "camera_synchronizer", None)
        if not single_camera and synchronizer is not None:
            sync_status = synchronizer.status()
            paired = int(
                sync_status.get(
                    "recentPairedSamples",
                    sync_status.get("pairedSamples", 0),
                ) or 0
            )
            fallback = int(
                sync_status.get(
                    "recentFallbackSamples",
                    sync_status.get("fallbackSamples", 0),
                ) or 0
            )
            pair_ratio = paired / max(1, paired + fallback)
            if (
                not sync_status.get("synchronized", False)
                or paired < 5
                or pair_ratio < 0.70
            ):
                recording_warnings.append(
                    "Hai camera chưa đồng bộ ổn định "
                    f"({paired} frame ghép, tỷ lệ {pair_ratio * 100:.0f}%). "
                    "Hãy chờ vài giây, đóng ứng dụng camera khác rồi thử lại."
                )
            gait_lock = getattr(state, "live_gait_lock", None)
            if gait_lock is not None:
                with gait_lock:
                    recent_samples = [
                        item
                        for item in getattr(state, "live_gait_samples", [])
                        if now - float(item.get("time", 0.0)) <= 3.0
                    ]
                role_checks = [
                    item.get("poseQuality", {}).get("cameraRolesPlausible")
                    for item in recent_samples
                    if item.get("poseQuality", {}).get("cameraRolesPlausible")
                    is not None
                ]
                role_ratio = sum(map(bool, role_checks)) / max(1, len(role_checks))
                if len(role_checks) >= 8 and role_ratio < 0.25:
                    recording_warnings.append(
                        "Hai vai trò camera có dấu hiệu đang chọn ngược. Hệ thống đã "
                        "khóa nguyên lựa chọn hiện tại; hãy dừng ghi và bấm Đảo cam "
                        "nếu hai ô xem trước không đúng."
                    )
                elif len(role_checks) >= 5 and role_ratio < 0.60:
                    recording_warnings.append(
                        "Chưa xác định chắc vai trò hai camera. Camera ngang phải thấy "
                        "người từ bên hông; hãy dùng nút Đảo cam nếu hai ô đang ngược."
                    )
        conn = get_db_connection()
        session_row = conn.execute(
            "SELECT is_reference FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        conn.close()
        if session_row is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        is_reference = bool(session_row["is_reference"])
        new_recording_fps = (
            round(
                min(
                    archive_fps,
                    max(8.0, min(capture_rates) * 0.95),
                ),
                2,
            )
            if has_capture_telemetry
            else archive_fps
        )

        new_ids = {"frontal": uuid.uuid4().hex, "sagittal": uuid.uuid4().hex}
        new_archive_id = "rec-" + uuid.uuid4().hex[:12]
        archive_dir = archive_video_path(
            session_id,
            new_archive_id,
            "frontal",
        ).parent
        archive_dir.mkdir(parents=True, exist_ok=True)
        fsr_path = archive_fsr_path(session_id, new_archive_id)
        timeline_path = archive_timeline_path(session_id, new_archive_id)
        try:
            fsr_path.touch(exist_ok=False)
            timeline_path.touch(exist_ok=False)
        except OSError as exc:
            fsr_path.unlink(missing_ok=True)
            timeline_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500,
                detail=f"Cannot create synchronized archive sidecars: {exc}",
            ) from exc
        codec = cv2.VideoWriter_fourcc(*"MJPG")
        new_frame_sizes = current_archive_frame_sizes()
        new_writers = {
            view: cv2.VideoWriter(
                str(archive_video_path(session_id, new_archive_id, view)),
                codec,
                new_recording_fps,
                new_frame_sizes[view],
            )
            for view in new_ids
        }
        if not all(writer.isOpened() for writer in new_writers.values()):
            for writer in new_writers.values():
                writer.release()
            fsr_path.unlink(missing_ok=True)
            timeline_path.unlink(missing_ok=True)
            for view in new_ids:
                archive_video_path(session_id, new_archive_id, view).unlink(
                    missing_ok=True
                )
            try:
                archive_dir.rmdir()
            except OSError:
                pass
            raise HTTPException(status_code=500, detail="Cannot create camera archive files.")

        started_at = time.time()
        started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO recording_archives
                   (id, session_id, frontal_video_id, sagittal_video_id,
                     started_at, status, reference_status, capture_kind)
                   VALUES (?, ?, ?, ?, ?, 'recording', ?, 'raw_v1')""",
                (
                    new_archive_id,
                    session_id,
                    new_ids["frontal"],
                    new_ids["sagittal"],
                    started_iso,
                    "draft" if is_reference else "none",
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            for writer in new_writers.values():
                writer.release()
            fsr_path.unlink(missing_ok=True)
            timeline_path.unlink(missing_ok=True)
            for view in new_ids:
                archive_video_path(session_id, new_archive_id, view).unlink(
                    missing_ok=True
                )
            try:
                archive_dir.rmdir()
            except OSError:
                pass
            raise
        finally:
            conn.close()

        for name in (
            "recorded_timestamps", "recorded_left_knee", "recorded_right_knee",
            "recorded_left_ankle", "recorded_right_ankle", "recorded_pelvic_tilt",
            "recorded_trunk_tilt", "recorded_left_hip", "recorded_right_hip",
            "recorded_frontal_trunk_lean",
            "recorded_pose_quality", "recorded_foot_tracking", "session_markers",
        ):
            setattr(state, name, [])
        warm_start_sample = None
        with state.live_gait_lock:
            if state.live_gait_samples:
                candidate = dict(state.live_gait_samples[-1])
                candidate_age = started_at - float(candidate.get("time", 0.0))
                required_values = (
                    "left_knee", "right_knee", "left_ankle", "right_ankle",
                    "pelvic_tilt", "trunk_tilt", "left_hip", "right_hip",
                )
                values_are_finite = all(
                    key in candidate and np.isfinite(float(candidate[key]))
                    for key in required_values
                )
                if (
                    abs(candidate_age) <= 0.75
                    and values_are_finite
                    and target_leg_sample_reliable(candidate.get("poseQuality", {}))
                ):
                    # Quiet standing at the instant recording starts is a
                    # legitimate first knee-extension event. Seeding it removes
                    # one whole warm-up stride from the realtime detector.
                    candidate["time"] = started_at
                    warm_start_sample = candidate
            state.live_gait_samples.clear()
            if warm_start_sample is not None:
                state.live_gait_samples.append(warm_start_sample)
        if warm_start_sample is not None:
            state.recorded_timestamps.append(0.0)
            state.recorded_left_knee.append(float(warm_start_sample["left_knee"]))
            state.recorded_right_knee.append(float(warm_start_sample["right_knee"]))
            state.recorded_left_ankle.append(float(warm_start_sample["left_ankle"]))
            state.recorded_right_ankle.append(float(warm_start_sample["right_ankle"]))
            state.recorded_pelvic_tilt.append(float(warm_start_sample["pelvic_tilt"]))
            state.recorded_trunk_tilt.append(float(warm_start_sample["trunk_tilt"]))
            state.recorded_left_hip.append(float(warm_start_sample["left_hip"]))
            state.recorded_right_hip.append(float(warm_start_sample["right_hip"]))
            state.recorded_frontal_trunk_lean.append(
                float(warm_start_sample.get("frontal_trunk_lean", float("nan")))
            )
            state.recorded_pose_quality.append(
                dict(warm_start_sample.get("poseQuality", {}))
            )
            state.recorded_foot_tracking.append(
                dict(warm_start_sample.get("footTracking", {}))
            )
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
            fsr_steps.reset(keep_baseline=True)
        with archive_fsr_lock:
            archive_fsr_stream = None
            archive_fsr_pending_path = fsr_path
            archive_fsr_sample_count = 0
            archive_fsr_last_flush = time.monotonic()
        with lock:
            writers = new_writers
            video_ids = new_ids
            archive_id = new_archive_id
            archive_session_id = session_id
            archive_started_at = started_at
            archive_frame_counts = {"frontal": 0, "sagittal": 0}
            archive_last_sequences = {"frontal": None, "sagittal": None}
            archive_recording_fps = new_recording_fps
            archive_frame_sizes = dict(new_frame_sizes)
            archive_timeline_stream = None
            archive_timeline_path_pending = timeline_path
            archive_timeline_last_flush = time.monotonic()
            archive_active = True
        state.is_recording = True
        return {
            "status": "started",
            "archiveId": new_archive_id,
            "videoIds": new_ids,
            "startedAt": started_iso,
            "recordingFps": new_recording_fps,
            "frameSizes": {
                view: {"width": size[0], "height": size[1]}
                for view, size in new_frame_sizes.items()
            },
            "fsrReady": fsr_ready,
            "fsrConnected": fsr_connected,
            "warnings": recording_warnings,
        }

    @app.post("/recording/stop")
    def stop_continuous_recording():
        with lock:
            active = archive_active
        if not active:
            raise HTTPException(status_code=409, detail="No recording is active.")
        result = finish_archive("complete")
        warnings = []
        fsr_samples = load_archive_fsr_samples(
            archive_session_id, result["archiveId"]
        )
        fsr_side_counts = {
            side: sum(1 for sample in fsr_samples if sample.get("side") == side)
            for side in ("left", "right")
        }
        result["fsrFrameCounts"] = fsr_side_counts
        minimum_fsr_samples = max(5, int(float(result["durationSec"]) * 5.0))
        weak_fsr_sides = [
            "trái" if side == "left" else "phải"
            for side, count in fsr_side_counts.items()
            if count < minimum_fsr_samples
        ]
        if weak_fsr_sides:
            warnings.append(
                "Dữ liệu FSR không đủ ổn định ở chân "
                f"{', '.join(weak_fsr_sides)} ({fsr_side_counts}). "
                "Không nên dùng phiên này để tính chạm đất, PeakFore hoặc FSI."
            )
        if any(count <= 0 for count in result["frameCounts"].values()):
            warnings.append("Một hoặc nhiều camera không lưu được khung hình nào.")
        slow_views = [
            view
            for view, fps in result.get("effectiveFps", {}).items()
            if float(fps) < 8.0
        ]
        if slow_views:
            warnings.append(
                "Video có FPS thực quá thấp ở camera: "
                f"{', '.join(slow_views)}. Không nên dùng phiên này để phân tích."
            )
        full_analysis = None
        if (
            float(result.get("durationSec", 0.0) or 0.0) >= 0.5
            and all(count > 0 for count in result["frameCounts"].values())
        ):
            try:
                full_analysis = _create_virtual_segment_impl(
                    archive_session_id,
                    {
                        "archiveId": result["archiveId"],
                        "startOffsetSec": 0.0,
                        "endOffsetSec": float(result["durationSec"]),
                        "scanType": "full_recording",
                        "note": "Bản ghi đầy đủ",
                    },
                )
            except Exception as exc:
                warnings.append(
                    "Đã lưu bộ video đầy đủ nhưng chưa tạo được bản phân tích tự động: "
                    f"{exc}. Có thể mở bộ video và tạo lại phân tích sau."
                )
        else:
            warnings.append(
                "Bộ video quá ngắn hoặc thiếu frame nên chưa tạo bản phân tích đầy đủ."
            )
        result["fullAnalysis"] = full_analysis
        if warnings:
            result["warnings"] = warnings
            result["warning"] = warnings[0]
        return {"status": "stopped", **result}

    def _create_virtual_segment_impl(session_id: str, data: dict):
        start_t = max(0.0, float(data.get("startOffsetSec", 0.0)))
        end_t = float(data.get("endOffsetSec", 0.0))
        if end_t - start_t < 0.5:
            raise HTTPException(status_code=422, detail="Analysis clip must be at least 0.5 seconds.")
        requested_archive_id = str(data.get("archiveId", "")).strip()
        if requested_archive_id:
            conn = get_db_connection()
            try:
                row = conn.execute(
                    """SELECT * FROM recording_archives
                       WHERE id = ? AND session_id = ?""",
                    (requested_archive_id, session_id),
                ).fetchone()
                archive = dict(row) if row is not None else None
            finally:
                conn.close()
        else:
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
            if current_is_active:
                with fsr_lock:
                    source_fsr_samples = list(recorded_fsr_samples)
            else:
                source_fsr_samples = load_archive_fsr_samples(
                    session_id, archive["id"]
                )
            fsr_analysis = build_region_analysis(
                source_fsr_samples,
                start_t,
                end_t,
                session_id=session_id,
                reprocess_raw=True,
            )
        except Exception:
            fsr_analysis = {"unit": "N_estimated", "regions": {}, "pairs": [], "peakForePairs": []}
        try:
            gait_analysis = build_live_gait(
                window_size=0,
                recorded_range=(start_t, end_t),
                fsr_anchors=fsr_analysis.get("cycleAnchors", []),
                fsr_contacts=fsr_analysis.get("contactEvents", []),
            )
        except Exception:
            gait_analysis = {"unit": "degree", "metrics": {}, "cycles": []}
        if (
            not current_is_active
            and (
                int(gait_analysis.get("sampleCount", 0) or 0) < 18
                or len(gait_analysis.get("cycles") or []) < 2
            )
        ):
            try:
                video_analysis = analyze_saved_video_clip(
                    session_id,
                    source_video_ids,
                    start_t,
                    end_t,
                    fsr_anchors=fsr_analysis.get("cycleAnchors", []),
                    fsr_contacts=fsr_analysis.get("contactEvents", []),
                )
                if video_analysis and gait_analysis_score(video_analysis) > gait_analysis_score(
                    gait_analysis
                ):
                    gait_analysis = video_analysis
                    if video_analysis.get("videoPoseAnalysis", {}).get(
                        "storedRolesReversed"
                    ):
                        source_video_ids = {
                            "frontal": source_video_ids["sagittal"],
                            "sagittal": source_video_ids["frontal"],
                        }
                    analysis_status = (
                        "ready" if video_analysis.get("cycles") else "pose_only"
                    )
                    analysis_message = (
                        "Đã phân tích lại pose trực tiếp từ video đã lưu."
                    )
            except Exception as exc:
                print(f"[Video pose analysis] {exc}")
        pose_replay = gait_analysis.pop(
            "poseReplay",
            {
                "schemaVersion": 1,
                "unit": "normalized_image",
                "algorithmVersion": ANALYSIS_ALGORITHM_VERSION,
                "views": {"frontal": [], "sagittal": []},
            },
        )
        gait_analysis["algorithmVersion"] = ANALYSIS_ALGORITHM_VERSION
        gait_analysis["analysisRevision"] = 1
        gait_analysis["analyzedAt"] = recorded_at
        fsr_analysis["algorithmVersion"] = ANALYSIS_ALGORITHM_VERSION
        fsr_analysis["analysisRevision"] = 1
        fsr_analysis["analyzedAt"] = recorded_at
        pose_replay["analysisRevision"] = 1
        pose_replay["analyzedAt"] = recorded_at
        scan_updates = analysis_scan_updates(gait_analysis, fsr_analysis)
        l_knee = scan_updates.get("left_knee", l_knee)
        r_knee = scan_updates.get("right_knee", r_knee)
        l_hip = scan_updates.get("left_hip", l_hip)
        r_hip = scan_updates.get("right_hip", r_hip)
        cadence = scan_updates.get("cadence", cadence)
        load_sym = scan_updates.get("plantar_load_symmetry", load_sym)
        run_id = "run-" + uuid.uuid4().hex[:12]
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
            cursor.execute(
            """INSERT INTO analysis_runs
               (id, scan_id, archive_id, algorithm_version, revision,
                gait_json, fsr_json, pose_json, status, is_current, created_at)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, 'complete', 1, ?)""",
            (
                run_id,
                scan_id,
                archive["id"],
                ANALYSIS_ALGORITHM_VERSION,
                json.dumps(finite_json(gait_analysis)),
                json.dumps(finite_json(fsr_analysis)),
                json.dumps(finite_json(pose_replay)),
                recorded_at,
            ),
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
            "analysisRevision": 1,
            "algorithmVersion": ANALYSIS_ALGORITHM_VERSION,
            "poseReplayAvailable": any(
                pose_replay.get("views", {}).get(view)
                for view in ("frontal", "sagittal")
            ),
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

    @app.post("/scans/{scan_id}/reanalyze-video")
    def reanalyze_scan_video(scan_id: str, force: bool = False):
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT sc.session_id, sg.id AS segment_id,
                          sg.start_offset_sec, sg.end_offset_sec, sg.video_path,
                          ga.data_json AS existing_analysis_json
                   FROM scans sc JOIN segments sg ON sg.id = sc.segment_id
                   LEFT JOIN gait_cycle_analyses ga ON ga.scan_id = sc.id
                   WHERE sc.id = ?""",
                (scan_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy đoạn phân tích.")
        try:
            videos = json.loads(row["video_path"] or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Đường dẫn video không hợp lệ.") from exc
        archive = None
        for video_id in videos.values():
            if video_id:
                archive = archive_for_video(row["session_id"], video_id)
                if archive is not None:
                    break
        if archive is not None:
            fsr_samples = load_archive_fsr_samples(
                row["session_id"],
                archive["id"],
            )
            fsr_analysis = build_region_analysis(
                fsr_samples,
                float(row["start_offset_sec"]),
                float(row["end_offset_sec"]),
                session_id=row["session_id"],
                reprocess_raw=True,
            )
        else:
            conn = get_db_connection()
            try:
                existing_fsr_row = conn.execute(
                    "SELECT data_json FROM fsr_region_analyses WHERE scan_id = ?",
                    (scan_id,),
                ).fetchone()
            finally:
                conn.close()
            try:
                fsr_analysis = json.loads(
                    existing_fsr_row["data_json"] if existing_fsr_row else "{}"
                )
            except (json.JSONDecodeError, TypeError):
                fsr_analysis = {}
        analysis = analyze_saved_video_clip(
            row["session_id"],
            videos,
            float(row["start_offset_sec"]),
            float(row["end_offset_sec"]),
            fsr_anchors=fsr_analysis.get("cycleAnchors", []),
            fsr_contacts=fsr_analysis.get("contactEvents", []),
        )
        if analysis is None or not analysis.get("poseDetected"):
            raise HTTPException(
                status_code=422,
                detail="Video không có đủ hình toàn thân để chạy lại pose.",
            )
        try:
            existing_analysis = json.loads(row["existing_analysis_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            existing_analysis = {}
        decision = gait_reanalysis_decision(
            analysis,
            existing_analysis,
            candidate_version=ANALYSIS_ALGORITHM_VERSION,
        )
        if (
            not force
            and not decision["replace"]
        ):
            return {
                "status": "kept_existing",
                "scanId": scan_id,
                "sampleCount": existing_analysis.get("sampleCount", 0),
                "cycleCount": len(existing_analysis.get("cycles") or []),
                "candidateCycleCount": decision["candidateScore"]["cycleCount"],
                "candidateVersion": decision["candidateVersion"],
                "candidateScore": decision["candidateScore"],
                "existingScore": decision["existingScore"],
                "decisionReason": decision["reason"],
                "videoPoseAnalysis": analysis.get("videoPoseAnalysis", {}),
                "message": "Bản phân tích lại kém hơn dữ liệu đã lưu nên không ghi đè.",
            }
        pose_replay = analysis.pop(
            "poseReplay",
            {
                "schemaVersion": 1,
                "unit": "normalized_image",
                "algorithmVersion": ANALYSIS_ALGORITHM_VERSION,
                "views": {"frontal": [], "sagittal": []},
            },
        )
        recorded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn = get_db_connection()
        try:
            revision = int(
                conn.execute(
                    """SELECT COALESCE(MAX(revision), 0) + 1
                       FROM analysis_runs WHERE scan_id = ?""",
                    (scan_id,),
                ).fetchone()[0]
            )
            analysis["algorithmVersion"] = ANALYSIS_ALGORITHM_VERSION
            analysis["analysisRevision"] = revision
            analysis["analyzedAt"] = recorded_at
            fsr_analysis["algorithmVersion"] = ANALYSIS_ALGORITHM_VERSION
            fsr_analysis["analysisRevision"] = revision
            fsr_analysis["analyzedAt"] = recorded_at
            pose_replay["algorithmVersion"] = ANALYSIS_ALGORITHM_VERSION
            pose_replay["analysisRevision"] = revision
            pose_replay["analyzedAt"] = recorded_at
            if analysis.get("videoPoseAnalysis", {}).get("storedRolesReversed"):
                corrected_videos = {
                    "frontal": videos.get("sagittal"),
                    "sagittal": videos.get("frontal"),
                }
                conn.execute(
                    "UPDATE segments SET video_path = ? WHERE id = ?",
                    (json.dumps(corrected_videos), row["segment_id"]),
                )
            conn.execute(
                "UPDATE analysis_runs SET is_current = 0 WHERE scan_id = ?",
                (scan_id,),
            )
            run_id = "run-" + uuid.uuid4().hex[:12]
            conn.execute(
                """INSERT INTO analysis_runs
                   (id, scan_id, archive_id, algorithm_version, revision,
                    gait_json, fsr_json, pose_json, status, is_current, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'complete', 1, ?)""",
                (
                    run_id,
                    scan_id,
                    archive["id"] if archive is not None else None,
                    ANALYSIS_ALGORITHM_VERSION,
                    revision,
                    json.dumps(finite_json(analysis)),
                    json.dumps(finite_json(fsr_analysis)),
                    json.dumps(finite_json(pose_replay)),
                    recorded_at,
                ),
            )
            conn.execute(
                """INSERT OR REPLACE INTO gait_cycle_analyses
                   (scan_id, data_json, created_at) VALUES (?, ?, ?)""",
                (scan_id, json.dumps(finite_json(analysis)), recorded_at),
            )
            conn.execute(
                """INSERT OR REPLACE INTO fsr_region_analyses
                   (scan_id, data_json, created_at) VALUES (?, ?, ?)""",
                (scan_id, json.dumps(finite_json(fsr_analysis)), recorded_at),
            )
            scan_updates = analysis_scan_updates(analysis, fsr_analysis)
            serialized_scan_updates = {
                name: (
                    json.dumps(finite_json(value))
                    if isinstance(value, list)
                    else value
                )
                for name, value in scan_updates.items()
            }
            if serialized_scan_updates:
                assignments = ", ".join(
                    f"{name} = ?" for name in serialized_scan_updates
                )
                conn.execute(
                    f"UPDATE scans SET {assignments} WHERE id = ?",
                    [*serialized_scan_updates.values(), scan_id],
                )
            if archive is not None:
                conn.execute(
                    """UPDATE recording_archives
                       SET analysis_revision = ?, last_analyzed_at = ?
                       WHERE id = ?""",
                    (revision, recorded_at, archive["id"]),
                )
            conn.commit()
        finally:
            conn.close()
        return {
            "status": "reanalyzed",
            "scanId": scan_id,
            "runId": run_id,
            "analysisRevision": revision,
            "algorithmVersion": ANALYSIS_ALGORITHM_VERSION,
            "sampleCount": analysis.get("sampleCount", 0),
            "cycleCount": analysis.get("cycleCount", 0),
            "fsrSampleCount": fsr_analysis.get("synchronization", {}).get(
                "sampleCount",
                0,
            ),
            "poseFrameCounts": {
                view: len(pose_replay.get("views", {}).get(view, []))
                for view in ("frontal", "sagittal")
            },
            "videoPoseAnalysis": analysis.get("videoPoseAnalysis", {}),
        }

    @app.get("/scans/{scan_id}/pose-replay")
    def get_pose_replay(
        scan_id: str,
        view: str | None = None,
        revision: int | None = None,
    ):
        if view is not None and view not in ("frontal", "sagittal"):
            raise HTTPException(status_code=422, detail="Unknown camera view.")
        if revision is not None and revision < 1:
            raise HTTPException(
                status_code=422,
                detail="Analysis revision must be a positive integer.",
            )
        conn = get_db_connection()
        try:
            if revision is None:
                pose_row = conn.execute(
                    """SELECT pose_json, algorithm_version, revision, created_at
                       FROM analysis_runs
                       WHERE scan_id = ? AND is_current = 1
                       ORDER BY revision DESC LIMIT 1""",
                    (scan_id,),
                ).fetchone()
            else:
                pose_row = conn.execute(
                    """SELECT pose_json, algorithm_version, revision, created_at
                       FROM analysis_runs
                       WHERE scan_id = ? AND revision = ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (scan_id, revision),
                ).fetchone()
        finally:
            conn.close()
        if pose_row is None:
            return {"available": False, "scanId": scan_id, "views": {}}
        try:
            pose = json.loads(pose_row["pose_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            pose = {}
        views = pose.get("views", {}) if isinstance(pose, dict) else {}
        if view is not None:
            views = {view: views.get(view, [])}
        return finite_json({
            "available": any(views.values()),
            "scanId": scan_id,
            "algorithmVersion": pose_row["algorithm_version"],
            "analysisRevision": pose_row["revision"],
            "analyzedAt": pose_row["created_at"],
            "unit": pose.get("unit", "normalized_image"),
            "sourceSizes": pose.get("sourceSizes", {}),
            "views": views,
        })

    @app.get("/scans/{scan_id}/fsr-analysis")
    def get_fsr_analysis(scan_id: str, window: int = 7, demo60: bool = False):
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
            if demo60:
                from demo_force_profile import demo_force_analysis
                return finite_json(demo_force_analysis(data, window))
            pairs = data.get("pairs") if isinstance(data, dict) else None
            if isinstance(pairs, list):
                pipeline = FsrStepPipeline(window_size=window)
                pipeline.set_force_metadata(
                    data.get("unit", "N_estimated"),
                    data.get("forceSource", "formula_estimate"),
                )
                result = pipeline.analysis(
                    healthy_leg=data.get("healthySide", "left"),
                    prosthetic_leg=data.get("prostheticSide", "right"),
                    pairs=pairs,
                )
                result["replayFrames"] = data.get("replayFrames", [])
                result['needsReanalysis'] = (
                    data.get('curveProcessing', {}).get('smoothing') != 'none'
                    or data.get('pairingMethod') != 'adjacent_opposite_contacts_no_skipped_side'
                )
                if result['needsReanalysis']:
                    result['curveProcessing'] = data.get('curveProcessing', {'smoothing': 'legacy_unknown'})
                result["replaySampleRateHz"] = data.get("replaySampleRateHz", 15)
                for name in (
                    "synchronization",
                    "incompleteSteps",
                    "contactEvents",
                    "reprocessedFromRawAdc",
                    "acquisitionQuality",
                    "steadyStateExcludedPairCount",
                    "selectionPolicy",
                    "algorithmVersion",
                    "analysisRevision",
                    "analyzedAt",
                ):
                    if name in data:
                        result[name] = data[name]
                return finite_json(result)
            return finite_json(data)
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
                result['needsReanalysis'] = (
                    data.get('curveProcessing', {}).get('smoothing') != 'none'
                    or data.get('pairingMethod') != 'adjacent_opposite_events_no_skipped_side'
                )
                if result['needsReanalysis']:
                    result['curveProcessing'] = data.get('curveProcessing', {'smoothing': 'legacy_unknown'})
                for name in (
                    "source",
                    "poseQuality",
                    "sampleCount",
                    "rejectedSampleCount",
                    "cameraSynchronization",
                    "cycleDetection",
                    "videoPoseAnalysis",
                    "footClearanceCalibration",
                    "algorithmVersion",
                    "analysisRevision",
                    "analyzedAt",
                ):
                    if name in data:
                        result[name] = data[name]
                return finite_json(result)
            return finite_json(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"unit": "degree", "metrics": {}}
    @app.get("/sessions/{session_id}/analysis-clips")
    def list_analysis_clips(session_id: str):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT sc.id AS scan_id, sc.label, sc.scan_type, sg.*,
                      s.is_reference AS is_reference,
                      ar.revision AS analysis_revision,
                      ar.algorithm_version AS algorithm_version,
                      CASE WHEN INSTR(COALESCE(ar.pose_json, ''), '"time"') > 0
                           THEN 1 ELSE 0 END AS pose_available,
                      ra.capture_kind AS capture_kind
               FROM scans sc JOIN segments sg ON sg.id = sc.segment_id
               JOIN sessions s ON s.id = sc.session_id
               LEFT JOIN analysis_runs ar
                 ON ar.scan_id = sc.id AND ar.is_current = 1
               LEFT JOIN recording_archives ra ON ra.id = ar.archive_id
               WHERE sc.session_id = ?
                 AND sg.source_type IN ('manual', 'virtual_clip')
               ORDER BY CASE WHEN sc.scan_type = 'full_recording' THEN 0 ELSE 1 END,
                        sg.created_at ASC""",
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
                "scanType": row["scan_type"],
                "analysisRevision": int(row["analysis_revision"] or 0),
                "algorithmVersion": row["algorithm_version"],
                "captureKind": row["capture_kind"] or "legacy_annotated",
                "poseReplayAvailable": bool(row["pose_available"]),
                "note": row["note"],
                "startOffsetSec": start,
                "endOffsetSec": end,
                "frontalVideoUrl": f"/session-video/{session_id}/{videos.get('frontal')}?start={start}&end={end}",
                "sagittalVideoUrl": f"/session-video/{session_id}/{videos.get('sagittal')}?start={start}&end={end}",
                "createdAt": row["created_at"],
                "isReference": bool(row["is_reference"]),
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
        fsr_path = archive_fsr_path(session_id, row["id"])
        timeline_path = archive_timeline_path(session_id, row["id"])
        manifest_path = archive_manifest_path(session_id, row["id"])
        payload = {
            "archiveId": row["id"],
            "sessionId": session_id,
            "startedAt": row["started_at"],
            "stoppedAt": row["stopped_at"],
            "durationSec": duration,
            "status": row["status"],
            "referenceStatus": row["reference_status"],
            "captureKind": row["capture_kind"],
            "analysisRevision": int(row["analysis_revision"] or 0),
            "lastAnalyzedAt": row["last_analyzed_at"],
            "frameCounts": {
                "frontal": row["frontal_frame_count"],
                "sagittal": row["sagittal_frame_count"],
            },
            "available": {
                "frontal": frontal_path.is_file() and frontal_path.stat().st_size > 0,
                "sagittal": sagittal_path.is_file() and sagittal_path.stat().st_size > 0,
                "fsr": fsr_path.is_file() and fsr_path.stat().st_size > 0,
                "timeline": (
                    timeline_path.is_file() and timeline_path.stat().st_size > 0
                ),
                "manifest": (
                    manifest_path.is_file() and manifest_path.stat().st_size > 0
                ),
            },
            "fsrAnalysisUrl": (
                f"/sessions/{session_id}/recordings/{row['id']}/fsr-analysis"
            ),
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
        if "is_reference" in row.keys():
            payload["isReference"] = bool(row["is_reference"])
        return payload

    @app.get("/sessions/{session_id}/recordings/{stored_archive_id}/fsr-analysis")
    def get_recording_fsr_analysis(session_id: str, stored_archive_id: str):
        conn = get_db_connection()
        try:
            archive = conn.execute(
                """SELECT duration_sec FROM recording_archives
                   WHERE id = ? AND session_id = ?""",
                (stored_archive_id, session_id),
            ).fetchone()
        finally:
            conn.close()
        if archive is None:
            raise HTTPException(status_code=404, detail="Recording not found.")
        samples = load_archive_fsr_samples(session_id, stored_archive_id)
        result = build_region_analysis(
            samples,
            0.0,
            max(0.0, float(archive["duration_sec"] or 0.0)),
            session_id=session_id,
            reprocess_raw=True,
        )
        result["archiveId"] = stored_archive_id
        result["persistent"] = True
        return result

    @app.get("/sessions/{session_id}/recordings")
    def list_recording_archives(session_id: str):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT ra.*, s.created_at AS session_created_at,
                      s.is_reference AS is_reference
               FROM recording_archives ra
               JOIN sessions s ON s.id = ra.session_id
               WHERE ra.session_id = ?
               ORDER BY ra.started_at DESC""",
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
            """SELECT ra.*, s.created_at AS session_created_at,
                      s.is_reference AS is_reference
               FROM recording_archives ra
               JOIN sessions s ON s.id = ra.session_id
               WHERE s.patient_id = ?
               ORDER BY ra.started_at DESC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [recording_archive_payload(row) for row in rows]

    @app.post(
        "/sessions/{session_id}/recordings/{stored_archive_id}/approve-reference"
    )
    def approve_reference_recording(session_id: str, stored_archive_id: str):
        """Approve one stopped recording as a reusable reference sample."""
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT ra.status, ra.reference_status, s.is_reference
                   FROM recording_archives ra
                   JOIN sessions s ON s.id = ra.session_id
                   WHERE ra.id = ? AND ra.session_id = ?""",
                (stored_archive_id, session_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Recording not found.")
            if not bool(row["is_reference"]):
                raise HTTPException(
                    status_code=409,
                    detail="Only a reference-capture session can approve a sample.",
                )
            if row["status"] == "recording":
                raise HTTPException(
                    status_code=409,
                    detail="Stop the recording before approving it.",
                )
            conn.execute(
                """UPDATE recording_archives SET reference_status = 'approved'
                   WHERE id = ? AND session_id = ?""",
                (stored_archive_id, session_id),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "status": "approved",
            "archiveId": stored_archive_id,
            "isReference": True,
        }

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
            recovered_video_path(session_id, stored_archive_id, "frontal"),
            recovered_video_path(session_id, stored_archive_id, "sagittal"),
            archive_fsr_path(session_id, stored_archive_id),
            archive_timeline_path(session_id, stored_archive_id),
            archive_manifest_path(session_id, stored_archive_id),
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
        if not np.isfinite(t) or t < 0:
            raise HTTPException(status_code=422, detail="Video time must be finite and non-negative.")
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
        encoded, jpeg = cv2.imencode(".jpg", frame)
        if not encoded:
            raise HTTPException(status_code=500, detail="Cannot encode video frame.")
        return Response(content=jpeg.tobytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.get("/session-video/{session_id}/{video_id}")
    def stream_session_video(
        session_id: str,
        video_id: str,
        start: float = 0.0,
        end: float = 10.0,
        loop: bool = False,
        rate: float = 1.0,
        pose_scan_id: str | None = None,
        pose_view: str | None = None,
        pose_revision: int | None = None,
        joint_angles: bool = False,
        trunk_angle: bool = False,
    ):
        if (
            not np.isfinite(start)
            or not np.isfinite(end)
            or start < 0
            or end <= start
        ):
            raise HTTPException(
                status_code=422,
                detail="Video range must be finite with 0 ≤ start < end.",
            )
        if not np.isfinite(rate) or rate < 0.25 or rate > 2.0:
            raise HTTPException(
                status_code=422,
                detail="Playback rate must be finite and between 0.25 and 2.0.",
            )
        if len(video_id) != 32 or not video_id.isalnum() or not video_belongs_to_session(session_id, video_id):
            raise HTTPException(status_code=404, detail="Video not found for this session.")
        path = video_file_path(session_id, video_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Video file is unavailable.")

        pose_frames = []
        pose_times = []
        pose_requested = any(
            value is not None
            for value in (pose_scan_id, pose_view, pose_revision)
        )
        if pose_requested:
            if not pose_scan_id or pose_view not in ("frontal", "sagittal"):
                raise HTTPException(
                    status_code=422,
                    detail="Pose overlay requires a scan id and valid camera view.",
                )
            if pose_revision is not None and pose_revision < 1:
                raise HTTPException(
                    status_code=422,
                    detail="Pose revision must be a positive integer.",
                )
            conn = get_db_connection()
            try:
                if pose_revision is None:
                    pose_row = conn.execute(
                        """SELECT ar.pose_json
                           FROM analysis_runs ar
                           JOIN scans s ON s.id = ar.scan_id
                           WHERE ar.scan_id = ? AND s.session_id = ?
                             AND ar.is_current = 1
                           ORDER BY ar.revision DESC LIMIT 1""",
                        (pose_scan_id, session_id),
                    ).fetchone()
                else:
                    pose_row = conn.execute(
                        """SELECT ar.pose_json
                           FROM analysis_runs ar
                           JOIN scans s ON s.id = ar.scan_id
                           WHERE ar.scan_id = ? AND s.session_id = ?
                             AND ar.revision = ?
                           ORDER BY ar.created_at DESC LIMIT 1""",
                        (pose_scan_id, session_id, pose_revision),
                    ).fetchone()
            finally:
                conn.close()
            if pose_row is None:
                raise HTTPException(
                    status_code=404,
                    detail="Pose overlay is unavailable for this video session.",
                )
            try:
                stored_pose = json.loads(pose_row["pose_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                stored_pose = {}
            source_frames = stored_pose.get("views", {}).get(pose_view, [])
            if isinstance(source_frames, list):
                pose_frames = sorted(
                    (
                        item for item in source_frames
                        if isinstance(item, dict)
                        and isinstance(item.get("landmarks"), dict)
                        and isinstance(item.get("time"), (int, float))
                    ),
                    key=lambda item: float(item["time"]),
                )
                pose_times = [float(item["time"]) for item in pose_frames]

        frame_times = video_frame_times(session_id, video_id)

        def overlay_pose(frame, source_frame_index, fallback_time):
            if not pose_times:
                return
            timeline_time = (
                frame_times[source_frame_index]
                if 0 <= source_frame_index < len(frame_times)
                else None
            )
            timestamp = (
                float(timeline_time)
                if timeline_time is not None
                else float(fallback_time)
            )
            index = bisect_left(pose_times, timestamp)
            candidates = []
            if index < len(pose_frames):
                candidates.append(pose_frames[index])
            if index > 0:
                candidates.append(pose_frames[index - 1])
            if not candidates:
                return
            nearest = min(
                candidates,
                key=lambda item: abs(float(item["time"]) - timestamp),
            )
            if (
                abs(float(nearest["time"]) - timestamp)
                <= POSE_REPLAY_MAX_GAP_SECONDS
            ):
                state.draw_gait_skeleton_mapping(
                    frame,
                    nearest["landmarks"],
                    sagittal=pose_view == "sagittal",
                )
                # Skeletons may be held briefly over a missing pose. Numbers
                # must instead belong to this frame, not a neighbouring step.
                matched_frame = pose_frame_matches_source(
                    nearest, source_frame_index, timestamp
                )
                if joint_angles and pose_view == "sagittal" and matched_frame:
                    draw_joint_angle_labels(frame, nearest["landmarks"])
                if trunk_angle and pose_view == "frontal" and matched_frame:
                    draw_frontal_trunk_label(frame, nearest["landmarks"])
                if trunk_angle and pose_view == "sagittal" and matched_frame:
                    draw_sagittal_trunk_label(frame, nearest["landmarks"])

        def frames():
            while True:
                capture = cv2.VideoCapture(str(path))
                nominal_fps = capture.get(cv2.CAP_PROP_FPS) or archive_fps
                timeline_duration = video_timeline_duration(session_id, video_id)
                frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                playback_fps = nominal_fps
                if timeline_duration > 0 and frame_count > 1:
                    # Older archives may contain fewer frames than their
                    # declared 20 FPS because pose processing delayed the
                    # archive loop. Replaying at the effective captured FPS
                    # keeps video duration aligned with scan/FSR timestamps.
                    playback_fps = min(
                        nominal_fps,
                        max(1.0, (frame_count - 1) / timeline_duration),
                    )
                media_start = video_media_position(
                    capture, start, timeline_duration
                )
                media_end = video_media_position(capture, end, timeline_duration)
                capture.set(cv2.CAP_PROP_POS_MSEC, media_start * 1000)
                emitted = False
                emitted_count = 0
                playback_started = time.monotonic()
                frame_interval = 1.0 / (playback_fps * rate)
                while capture.isOpened():
                    # Anchor every frame to one monotonic playback clock. A
                    # fixed sleep after JPEG encoding accumulated that work on
                    # every frame, so the MJPEG video drifted seconds behind
                    # the pose overlay near the end of a sample.
                    target_time = playback_started + emitted_count * frame_interval
                    remaining = target_time - time.monotonic()
                    if remaining > 0:
                        time.sleep(remaining)
                    position = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                    if position > media_end:
                        break
                    ok, frame = capture.read()
                    if not ok:
                        break
                    source_frame_index = int(
                        capture.get(cv2.CAP_PROP_POS_FRAMES) or 1
                    ) - 1
                    fallback_time = start + emitted_count / playback_fps
                    overlay_pose(frame, source_frame_index, fallback_time)
                    encoded, jpeg = cv2.imencode(".jpg", frame)
                    if encoded:
                        emitted = True
                        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" +
                               jpeg.tobytes() + b"\r\n")
                    emitted_count += 1
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
