"""Thread-safe runtime measurements for the G2-00 performance baseline.

The monitor keeps measurements separate from clinical data. Durations and
rates use a monotonic clock; Unix time is retained only as source/display
metadata. Direct serial FSR diagnostics are estimates because that protocol
has no sequence number, while UDP sequence metrics are exact when available.
"""

from __future__ import annotations

import ctypes
import math
import os
import sys
import threading
import time
from collections import deque


def _percentile(values, fraction):
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(fraction)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _rounded(value, digits=3):
    return None if value is None else round(float(value), digits)


def _distribution(values):
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return {
        "median": _rounded(_percentile(finite, 0.50)),
        "p95": _rounded(_percentile(finite, 0.95)),
        "max": _rounded(max(finite) if finite else None),
    }


def _intervals(values):
    ordered = list(values)
    return [
        max(0.0, float(current) - float(previous))
        for previous, current in zip(ordered, ordered[1:])
    ]


def _rate_from_totals(count, first_at, last_at):
    if int(count) < 2 or first_at is None or last_at is None:
        return None
    elapsed = float(last_at) - float(first_at)
    return None if elapsed <= 0.0 else (int(count) - 1) / elapsed


def _working_set_bytes():
    """Return current resident memory without adding a runtime dependency."""
    if sys.platform == "win32":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        success = ctypes.windll.psapi.GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb
        )
        return int(counters.WorkingSetSize) if success else None

    try:
        with open("/proc/self/statm", "r", encoding="ascii") as stream:
            resident_pages = int(stream.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (FileNotFoundError, IndexError, OSError, ValueError):
        try:
            import resource

            resident = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return resident if sys.platform == "darwin" else resident * 1024
        except (ImportError, OSError, ValueError):
            return None


class PerformanceMonitor:
    """Collect bounded distributions and exact totals since the last reset."""

    def __init__(
        self,
        *,
        expected_fsr_hz=20.0,
        max_samples=10000,
        clock=time.monotonic,
        wall_clock=time.time,
        process_time=time.process_time,
        memory_reader=_working_set_bytes,
        logical_cpu_count=None,
    ):
        self.expected_fsr_hz = max(0.1, float(expected_fsr_hz))
        self.max_samples = max(10, int(max_samples))
        self._clock = clock
        self._wall_clock = wall_clock
        self._process_time = process_time
        self._memory_reader = memory_reader
        self.logical_cpu_count = max(
            1, int(logical_cpu_count or os.cpu_count() or 1)
        )
        self._lock = threading.RLock()
        self.reset()

    def _new_deque(self):
        return deque(maxlen=self.max_samples)

    def reset(self):
        with self._lock:
            self._started_monotonic = float(self._clock())
            self._started_wall = float(self._wall_clock())
            self._last_resource_at = self._started_monotonic
            self._last_process_time = float(self._process_time())
            self._stages = {}
            self._resource_cpu_one_core = self._new_deque()
            self._resource_cpu_system = self._new_deque()
            self._resource_memory_mib = self._new_deque()
            self._resource_sample_count = 0
            self._fsr_sides = {}
            self._fsr_sources = {}

    def _maybe_sample_resources(self, now):
        if float(now) - self._last_resource_at >= 1.0:
            self.sample_resources(now=now)

    def sample_resources(self, *, now=None):
        with self._lock:
            now = float(self._clock() if now is None else now)
            process_now = float(self._process_time())
            elapsed = now - self._last_resource_at
            cpu_elapsed = process_now - self._last_process_time
            if elapsed <= 0.0:
                return
            self._last_resource_at = now
            self._last_process_time = process_now
            self._resource_sample_count += 1
            one_core_percent = max(0.0, cpu_elapsed / elapsed * 100.0)
            self._resource_cpu_one_core.append(one_core_percent)
            self._resource_cpu_system.append(
                one_core_percent / self.logical_cpu_count
            )
            memory_bytes = self._memory_reader()
            if memory_bytes is not None:
                self._resource_memory_mib.append(
                    max(0, int(memory_bytes)) / (1024.0 * 1024.0)
                )

    def record_stage(
        self,
        name,
        duration_seconds,
        *,
        event_at=None,
        latency_seconds=None,
    ):
        now = float(self._clock() if event_at is None else event_at)
        duration = max(0.0, float(duration_seconds))
        latency = None if latency_seconds is None else max(0.0, float(latency_seconds))
        with self._lock:
            stage = self._stages.setdefault(
                str(name),
                {
                    "events": self._new_deque(),
                    "durations": self._new_deque(),
                    "latencies": self._new_deque(),
                    "totalCount": 0,
                    "firstEventAt": None,
                    "lastEventAt": None,
                },
            )
            stage["events"].append(now)
            stage["durations"].append(duration)
            if latency is not None:
                stage["latencies"].append(latency)
            stage["totalCount"] += 1
            if stage["firstEventAt"] is None:
                stage["firstEventAt"] = now
            stage["lastEventAt"] = now
            self._maybe_sample_resources(now)

    def _source_status(self, source, transport):
        key = f"{str(transport).lower()}:{source}"
        status = self._fsr_sources.setdefault(
            key,
            {
                "source": str(source),
                "transport": str(transport).lower(),
                "chunkEvents": self._new_deque(),
                "chunkSizes": self._new_deque(),
                "chunkCount": 0,
                "bytesReceived": 0,
                "firstChunkAt": None,
                "lastChunkAt": None,
                "parsedFrameCount": 0,
                "firstFrameAt": None,
                "lastFrameAt": None,
                "multiFrameChunkCount": 0,
                "maxFramesPerChunk": 0,
                "sides": set(),
                "validSequenceCount": 0,
                "lastSequence": None,
                "sequenceMissingCount": 0,
                "sequenceDuplicateCount": 0,
                "sequenceOutOfOrderCount": 0,
            },
        )
        return key, status

    def record_fsr_chunk(
        self,
        source,
        size_bytes,
        *,
        transport="serial",
        parsed_frame_count=None,
        received_at=None,
    ):
        now = float(self._clock() if received_at is None else received_at)
        size = max(0, int(size_bytes))
        with self._lock:
            _, status = self._source_status(source, transport)
            status["chunkEvents"].append(now)
            status["chunkSizes"].append(size)
            status["chunkCount"] += 1
            status["bytesReceived"] += size
            if status["firstChunkAt"] is None:
                status["firstChunkAt"] = now
            status["lastChunkAt"] = now
            if parsed_frame_count is not None:
                parsed_count = max(0, int(parsed_frame_count))
                status["maxFramesPerChunk"] = max(
                    status["maxFramesPerChunk"], parsed_count
                )
                if parsed_count > 1:
                    status["multiFrameChunkCount"] += 1
            self._maybe_sample_resources(now)

    def _stream_status(self, side_status, source_key, transport):
        return side_status["streams"].setdefault(
            source_key,
            {
                "transport": str(transport).lower(),
                "events": self._new_deque(),
                "totalCount": 0,
                "firstEventAt": None,
                "lastEventAt": None,
                "lastPayload": None,
                "payloadRepeatCount": 0,
                "batchingObserved": False,
                "timeInferredMissingCount": 0,
                "deviceSequenceObserved": False,
                "lastReceivedAtUnix": None,
                "lastSampledAtUnix": None,
                "transportLatencies": self._new_deque(),
            },
        )

    def record_fsr_frame(
        self,
        side,
        matrix,
        source,
        *,
        transport="serial",
        sequence=None,
        batch_size=1,
        received_at=None,
        received_at_unix=None,
        sampled_at_unix=None,
        transport_latency_seconds=None,
    ):
        now = float(self._clock() if received_at is None else received_at)
        normalized_side = str(side).strip().lower()
        payload = tuple(
            float(value)
            for row in (matrix or [])
            for value in (row or [])
        )
        with self._lock:
            source_key, source_status = self._source_status(source, transport)
            source_status["parsedFrameCount"] += 1
            source_status["sides"].add(normalized_side)
            if source_status["firstFrameAt"] is None:
                source_status["firstFrameAt"] = now
            source_status["lastFrameAt"] = now

            side_status = self._fsr_sides.setdefault(
                normalized_side, {"streams": {}}
            )
            stream = self._stream_status(side_status, source_key, transport)
            previous_at = stream["lastEventAt"]
            stream["events"].append(now)
            stream["totalCount"] += 1
            if stream["firstEventAt"] is None:
                stream["firstEventAt"] = now
            stream["lastEventAt"] = now
            if previous_at is not None:
                expected_interval = 1.0 / self.expected_fsr_hz
                gap = max(0.0, now - previous_at)
                stream["timeInferredMissingCount"] += max(
                    0, int(math.floor(gap / expected_interval + 0.5)) - 1
                )
            if int(batch_size) > 1:
                stream["batchingObserved"] = True
            if stream["lastPayload"] == payload:
                stream["payloadRepeatCount"] += 1
            stream["lastPayload"] = payload

            try:
                parsed_sequence = int(sequence) if sequence is not None else None
            except (TypeError, ValueError):
                parsed_sequence = None
            if parsed_sequence is not None:
                # Both shipped UDP transmitters increment one shared sequence
                # across left and right channels. Evaluate it once per source;
                # a gap is exact for the device but cannot be assigned to a foot.
                previous_sequence = source_status["lastSequence"]
                source_status["validSequenceCount"] += 1
                stream["deviceSequenceObserved"] = True
                if previous_sequence is not None:
                    if parsed_sequence == previous_sequence:
                        source_status["sequenceDuplicateCount"] += 1
                    elif parsed_sequence > previous_sequence:
                        source_status["sequenceMissingCount"] += max(
                            0, parsed_sequence - previous_sequence - 1
                        )
                    else:
                        source_status["sequenceOutOfOrderCount"] += 1
                if previous_sequence is None or parsed_sequence > previous_sequence:
                    source_status["lastSequence"] = parsed_sequence

            if received_at_unix is not None:
                stream["lastReceivedAtUnix"] = float(received_at_unix)
            if sampled_at_unix is not None:
                stream["lastSampledAtUnix"] = float(sampled_at_unix)
            if transport_latency_seconds is not None:
                stream["transportLatencies"].append(
                    max(0.0, float(transport_latency_seconds))
                )
            self._maybe_sample_resources(now)

    def _stage_snapshot(self, stage):
        events = list(stage["events"])
        return {
            "count": int(stage["totalCount"]),
            "totalCountSinceReset": int(stage["totalCount"]),
            "retainedSampleCount": len(events),
            "rateHz": _rounded(_rate_from_totals(
                stage["totalCount"], stage["firstEventAt"], stage["lastEventAt"]
            )),
            "durationMs": _distribution(
                value * 1000.0 for value in stage["durations"]
            ),
            "latencyMs": _distribution(
                value * 1000.0 for value in stage["latencies"]
            ),
            "intervalMs": _distribution(
                value * 1000.0 for value in _intervals(events)
            ),
            "measurementQuality": {
                "sufficientForRate": stage["totalCount"] >= 2,
                "distributionTruncated": stage["totalCount"] > len(events),
            },
        }

    def _stream_snapshot(self, stream):
        events = list(stream["events"])
        total = int(stream["totalCount"])
        if stream["deviceSequenceObserved"]:
            missing = None
            duplicates = None
            missing_method = None
            missing_reason = "device_sequence_global_side_unknown"
        elif total < 2:
            missing = None
            duplicates = None
            missing_method = None
            missing_reason = "insufficient_samples"
        elif stream["batchingObserved"]:
            missing = None
            duplicates = None
            missing_method = None
            missing_reason = "unavailable_serial_batching_without_sequence"
        else:
            missing = int(stream["timeInferredMissingCount"])
            duplicates = int(stream["payloadRepeatCount"])
            missing_method = "receive_interval_estimate"
            missing_reason = None
        return {
            "transport": stream["transport"],
            "frameCount": total,
            "totalCountSinceReset": total,
            "retainedSampleCount": len(events),
            "rateHz": _rounded(_rate_from_totals(
                total, stream["firstEventAt"], stream["lastEventAt"]
            )),
            "intervalMs": _distribution(
                gap * 1000.0 for gap in _intervals(events)
            ),
            "missingFrameCount": missing,
            "inferredMissingFrameCount": (
                missing if missing_method == "receive_interval_estimate" else None
            ),
            "duplicateFrameCount": duplicates,
            "consecutivePayloadRepeatCount": (
                int(stream["payloadRepeatCount"]) if total >= 2 else None
            ),
            "missingFrameMethod": missing_method,
            "missingFrameReason": missing_reason,
            "sequenceScope": (
                "device_all_sides" if stream["deviceSequenceObserved"] else None
            ),
            "batchingObserved": bool(stream["batchingObserved"]),
            "lastReceivedAtUnix": stream["lastReceivedAtUnix"],
            "lastSampledAtUnix": stream["lastSampledAtUnix"],
            "transportLatencyMs": _distribution(
                value * 1000.0 for value in stream["transportLatencies"]
            ),
            "measurementQuality": {
                "sufficientForRate": total >= 2,
                "distributionTruncated": total > len(events),
                "exactLossDetection": False,
                "exactLossDetectionAtSource": bool(
                    stream["deviceSequenceObserved"]
                ),
            },
        }

    def _fsr_snapshot(self):
        sides = {}
        for side, status in self._fsr_sides.items():
            streams = {
                key: self._stream_snapshot(stream)
                for key, stream in sorted(status["streams"].items())
            }
            if len(streams) == 1:
                combined = dict(next(iter(streams.values())))
                combined["sourcePorts"] = list(streams)
                combined["streams"] = streams
            else:
                combined = {
                    "frameCount": sum(item["frameCount"] for item in streams.values()),
                    "totalCountSinceReset": sum(
                        item["totalCountSinceReset"] for item in streams.values()
                    ),
                    "retainedSampleCount": sum(
                        item["retainedSampleCount"] for item in streams.values()
                    ),
                    "rateHz": None,
                    "intervalMs": _distribution([]),
                    "missingFrameCount": None,
                    "inferredMissingFrameCount": None,
                    "duplicateFrameCount": None,
                    "consecutivePayloadRepeatCount": None,
                    "missingFrameMethod": None,
                    "missingFrameReason": "mixed_sources_reported_separately",
                    "sourcePorts": list(streams),
                    "streams": streams,
                    "measurementQuality": {
                        "sufficientForRate": False,
                        "mixedSources": True,
                    },
                }
            sides[side] = combined

        sources = {}
        serial_ports = {}
        for key, status in sorted(self._fsr_sources.items()):
            total_frames = int(status["parsedFrameCount"])
            has_sequence = status["validSequenceCount"] >= 2
            elapsed = (
                status["lastChunkAt"] - status["firstChunkAt"]
                if status["chunkCount"] >= 2 else None
            )
            summary = {
                "source": status["source"],
                "transport": status["transport"],
                "sides": sorted(status["sides"]),
                "chunkCount": int(status["chunkCount"]),
                "retainedChunkSampleCount": len(status["chunkSizes"]),
                "bytesReceived": int(status["bytesReceived"]),
                "chunkBytes": _distribution(status["chunkSizes"]),
                "parsedFrameCount": total_frames,
                "averageWireBytesPerFrame": _rounded(
                    status["bytesReceived"] / total_frames
                    if total_frames else None
                ),
                "wireBytesPerSecond": _rounded(
                    status["bytesReceived"] / elapsed
                    if elapsed is not None and elapsed > 0.0 else None
                ),
                "frameRateHz": _rounded(_rate_from_totals(
                    total_frames, status["firstFrameAt"], status["lastFrameAt"]
                )),
                "multiFrameChunkCount": int(status["multiFrameChunkCount"]),
                "maxFramesPerChunk": int(status["maxFramesPerChunk"]),
                "sequence": {
                    "scope": "device_all_sides",
                    "validSampleCount": int(status["validSequenceCount"]),
                    "last": status["lastSequence"],
                    "missing": (
                        int(status["sequenceMissingCount"])
                        if has_sequence else None
                    ),
                    "duplicate": (
                        int(status["sequenceDuplicateCount"])
                        if has_sequence else None
                    ),
                    "outOfOrder": (
                        int(status["sequenceOutOfOrderCount"])
                        if has_sequence else None
                    ),
                    "missingSideAttribution": "unknown",
                },
                "measurementQuality": {
                    "sufficientForRate": total_frames >= 2,
                    "batchingObserved": status["multiFrameChunkCount"] > 0,
                    "chunkDistributionTruncated": (
                        status["chunkCount"] > len(status["chunkSizes"])
                    ),
                    "exactSequenceLossDetection": has_sequence,
                },
            }
            sources[key] = summary
            if status["transport"] == "serial":
                serial_ports[status["source"]] = summary
        return {
            "expectedRateHz": self.expected_fsr_hz,
            "bySide": sides,
            "bySource": sources,
            "byPort": serial_ports,
            "limitations": {
                "missingFrames": "device_sequence_when_available_otherwise_receive_interval_estimate",
                "duplicateFrames": "device_sequence_when_available_otherwise_consecutive_equal_payloads",
                "wirePacketSize": "average_from_total_received_bytes_and_total_parsed_frames_since_reset",
                "serialBatching": "time_gap_loss_unavailable_when_multiple_frames_share_one_read",
            },
        }

    def snapshot(self, *, sample_resources=True):
        if sample_resources:
            self.sample_resources()
        with self._lock:
            sampled_at = float(self._wall_clock())
            return {
                "schemaVersion": 2,
                "measurement": {
                    "startedAtUnix": self._started_wall,
                    "sampledAtUnix": sampled_at,
                    "elapsedSeconds": _rounded(
                        max(0.0, float(self._clock()) - self._started_monotonic)
                    ),
                    "clock": "monotonic_for_intervals_wall_clock_for_display",
                    "maxSamplesPerSeries": self.max_samples,
                },
                "stages": {
                    name: self._stage_snapshot(stage)
                    for name, stage in sorted(self._stages.items())
                },
                "resources": {
                    "sampleCount": int(self._resource_sample_count),
                    "cpuSampleCount": len(self._resource_cpu_one_core),
                    "workingSetSampleCount": len(self._resource_memory_mib),
                    "logicalCpuCount": self.logical_cpu_count,
                    "processCpuPercentOfOneCore": _distribution(
                        self._resource_cpu_one_core
                    ),
                    "processCpuPercentOfSystem": _distribution(
                        self._resource_cpu_system
                    ),
                    "workingSetMiB": _distribution(self._resource_memory_mib),
                },
                "fsr": self._fsr_snapshot(),
            }
