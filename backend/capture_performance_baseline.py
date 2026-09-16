"""Capture one reproducible G2-00 runtime performance report."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


def request_json(url, method="GET"):
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=10.0) as response:
        return json.loads(response.read().decode("utf-8"))


def capture_baseline(
    base_url,
    *,
    duration_seconds=90.0,
    sample_interval_seconds=1.0,
    requester=request_json,
    sleeper=time.sleep,
    clock=time.monotonic,
):
    duration = float(duration_seconds)
    interval = float(sample_interval_seconds)
    if duration <= 0.0:
        raise ValueError("duration_seconds must be greater than zero")
    if interval <= 0.0:
        raise ValueError("sample_interval_seconds must be greater than zero")

    base = str(base_url).rstrip("/")
    reset_url = f"{base}/diagnostics/performance/reset"
    report_url = f"{base}/diagnostics/performance"
    requester(reset_url, method="POST")

    report = None
    started_at = float(clock())
    deadline = started_at + duration
    next_sample_at = min(started_at + interval, deadline)
    while True:
        wait_seconds = max(0.0, next_sample_at - float(clock()))
        if wait_seconds > 0.0:
            sleeper(wait_seconds)
        report = requester(report_url, method="GET")
        if next_sample_at >= deadline or float(clock()) >= deadline:
            break
        next_sample_at = min(next_sample_at + interval, deadline)
    return report


def default_output_path():
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return Path(__file__).resolve().parent.parent / "output" / (
        f"g2-00-baseline-{timestamp}.json"
    )


def main():
    # Windows PowerShell may still expose a legacy code page. Keep Vietnamese
    # help/status text from crashing the command when a glyph is unavailable.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    parser = argparse.ArgumentParser(
        description="Do hieu nang camera/pose/preview/ghi hinh/FSR cho G2-00."
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration", type=float, default=90.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    output_path = (args.output or default_output_path()).resolve()
    try:
        report = capture_baseline(
            args.url,
            duration_seconds=args.duration,
            sample_interval_seconds=args.interval,
        )
    except (OSError, urllib.error.URLError, ValueError) as exc:
        parser.error(f"Khong the lay bao cao tu backend: {exc}")

    report["captureRequest"] = {
        "durationSeconds": args.duration,
        "sampleIntervalSeconds": args.interval,
        "backendUrl": args.url.rstrip("/"),
        "savedAt": datetime.now().astimezone().isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Da luu bao cao G2-00: {output_path}")


if __name__ == "__main__":
    main()
