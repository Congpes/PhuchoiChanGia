"""Bounded JPEG reuse for clients watching the same physical camera frame.

The four cache keys are ``(physical_slot, raw)``: slots 0/1, with a raw and
processed view each. A cache owns no images, encoder threads, or frame queue;
each entry retains only its latest successfully encoded immutable JPEG.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


PreviewKey = tuple[int, bool]
EncodedPreview = tuple[int, bytes]
PreviewEncoder = Callable[[], bytes | bytearray | memoryview | None]


@dataclass
class _StreamEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    latest: EncodedPreview | None = None
    encodes: int = 0
    cache_hits: int = 0


class PreviewJpegCache:
    """Encode each frame once per stream, without blocking other streams.

    ``get_or_encode(key, frame_ns, encoder)`` returns ``(actual_frame_ns, jpeg)``
    or ``None`` when the encoder fails by returning ``None``. If another client
    has already encoded this frame or a newer one, its result is returned
    without invoking ``encoder``. Callers must use the returned timestamp for
    stream deduplication and latency measurement, because a late request may
    receive a newer frame than the one it supplied.

    The encoder runs under that stream's lock. Exceptions propagate, release
    the lock, and leave the last successful result intact. Unknown keys raise
    ``KeyError`` instead of creating entries and growing the cache.
    """

    def __init__(self):
        self._streams = {
            (slot, raw): _StreamEntry()
            for slot in (0, 1)
            for raw in (False, True)
        }

    def get_or_encode(
        self,
        key: PreviewKey,
        frame_ns: int,
        encoder: PreviewEncoder,
    ) -> EncodedPreview | None:
        entry = self._streams[key]
        with entry.lock:
            if entry.latest is not None and frame_ns <= entry.latest[0]:
                entry.cache_hits += 1
                return entry.latest

            payload = encoder()
            if payload is None:
                return None

            result = (frame_ns, bytes(payload))
            entry.latest = result
            entry.encodes += 1
            return result

    def snapshot(self) -> dict:
        """Return JSON-safe counters; stream snapshots are read independently."""
        streams = {}
        for (slot, raw), entry in self._streams.items():
            with entry.lock:
                latest = entry.latest
                streams[f"camera{slot}.{'raw' if raw else 'processed'}"] = {
                    "frameNs": latest[0] if latest is not None else None,
                    "retainedBytes": len(latest[1]) if latest is not None else 0,
                    "encodes": entry.encodes,
                    "cacheHits": entry.cache_hits,
                }
        return {
            "cachedStreams": sum(
                stream["frameNs"] is not None for stream in streams.values()
            ),
            "retainedBytes": sum(stream["retainedBytes"] for stream in streams.values()),
            "encodes": sum(stream["encodes"] for stream in streams.values()),
            "cacheHits": sum(stream["cacheHits"] for stream in streams.values()),
            "streams": streams,
        }
