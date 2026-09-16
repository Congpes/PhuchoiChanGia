from __future__ import annotations

import os
import math
from typing import Iterable

INDEX_MAP_RIGHT = [
    [36, 24, 12, 0],
    [47, 35, 23, 11],
    [37, 25, 13, 1],
    [46, 34, 22, 10],
    [38, 26, 14, 2],
    [45, 33, 21, 9],
    [39, 27, 15, 3],
    [44, 32, 20, 8],
    [40, 28, 16, 4],
    [43, 31, 19, 7],
    [41, 29, 17, 5],
    [42, 30, 18, 6],
]
# Verified hardware convention: RR is worn on the physical left foot, whose
# four sensor columns are mirrored. LL is worn on the physical right foot.
INDEX_MAP_LEFT = [row[::-1] for row in INDEX_MAP_RIGHT]


def hardware_values_to_matrix(
    values: Iterable[float],
    side: str,
) -> list[list[float]]:
    numbers = [float(value) for value in values]
    if len(numbers) != 48:
        raise ValueError("An FSR hardware frame must contain exactly 48 values")
    mapping = INDEX_MAP_LEFT if side == "left" else INDEX_MAP_RIGHT
    return [[numbers[index] for index in row] for row in mapping]


class FsrSerialFrameParser:
    def __init__(self) -> None:
        self.side: str | None = None
        self.values: list[float] = []
        self.pending_bytes = bytearray()
        self.discard_until_newline = False
        self.invalid_lines = 0

    def feed_bytes(self, data: bytes) -> list[tuple[str, list[list[float]]]]:
        """A serial timeout is not a line boundary; keep split numbers intact."""
        frames = []
        for chunk_index, chunk in enumerate(data.split(b'\n')):
            if chunk_index:
                if not self.discard_until_newline:
                    try:
                        line = self.pending_bytes.decode('ascii')
                    except UnicodeDecodeError:
                        self.invalid_lines += 1
                        self.side, self.values = None, []
                    else:
                        frames.extend(self.feed_line(line))
                self.pending_bytes.clear()
                self.discard_until_newline = False
            if not self.discard_until_newline:
                self.pending_bytes.extend(chunk)
                if len(self.pending_bytes) > 8192:
                    self.pending_bytes.clear()
                    self.discard_until_newline = True
                    self.side, self.values = None, []
                    self.invalid_lines += 1
        return frames

    def feed_line(self, line: str) -> list[tuple[str, list[list[float]]]]:
        tokens = str(line).strip().split()
        if not tokens:
            return []
        marker = tokens[0].upper()
        if marker in ("LL", "RR"):
            self.side = "left" if marker == "RR" else "right"
            self.values = []
            tokens = tokens[1:]
        elif self.side is None:
            return []
        try:
            numbers = [float(token) for token in tokens]
            if not all(math.isfinite(value) for value in numbers):
                raise ValueError('Non-finite FSR value')
            self.values.extend(numbers)
        except ValueError:
            self.invalid_lines += 1
            self.side = None
            self.values = []
            return []
        frames = []
        # A Bluetooth module does not necessarily repeat LL/RR before every
        # matrix. Keep the marker for this COM port and consume every complete
        # 48-value frame so a continuous hardware stream is not lost after the
        # first packet.
        while self.side is not None and len(self.values) >= 48:
            frame_values = self.values[:48]
            self.values = self.values[48:]
            frames.append((self.side, hardware_values_to_matrix(frame_values, self.side)))
        return frames


def read_fsr_serial_chunk(connection) -> bytes:
    """Drain queued bytes in batches; an empty timeout is NOT a port error.

    Keep a bounded read size without purging samples. Actual OS/serial errors
    propagate to the worker's reconnect handler.
    """
    return connection.read(max(1, min(4096, connection.in_waiting)))


def serial_retry_delay(failures: int, initial: float, maximum: float) -> float:
    return min(maximum, initial * (2.0 ** min(8, max(0, failures - 1))))


def configured_serial_ports(port_infos: Iterable[object]) -> list[str]:
    configured = [
        value.strip()
        for value in os.getenv("FSR_SERIAL_PORTS", "").split(",")
        if value.strip()
    ]
    if configured:
        return list(dict.fromkeys(configured))
    infos = list(port_infos)
    outgoing = [
        str(getattr(port, "device", ""))
        for port in infos
        if "LOCALMFG&0002" in str(getattr(port, "hwid", "")).upper()
    ]
    if outgoing:
        return list(dict.fromkeys(port for port in outgoing if port))
    candidates = []
    for port in infos:
        device = str(getattr(port, "device", ""))
        description = str(getattr(port, "description", "")).lower()
        hwid = str(getattr(port, "hwid", "")).upper()
        if not device or "LOCALMFG&0000" in hwid:
            continue
        labels = ("usb", "serial", "uart", "bluetooth")
        if any(label in description for label in labels):
            candidates.append(device)
    return list(dict.fromkeys(candidates))
