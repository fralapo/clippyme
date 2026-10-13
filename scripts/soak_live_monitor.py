#!/usr/bin/env python3
"""Read-only Live Monitor soak runner. Does not start, stop or publish streams."""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


def summarize(payload: dict) -> list[dict]:
    rows = []
    for mon in payload.get("monitors", []):
        if not isinstance(mon, dict) or not isinstance(mon.get("id"), str):
            continue
        rows.append({
            "id": mon["id"], "running": bool(mon.get("running")),
            "state": str(mon.get("state") or "unknown"),
            "pending": int(mon.get("pending_publish") or 0),
            "failed": int(mon.get("failed_publish") or 0),
            "published": int(mon.get("clips_published") or 0),
            "segments": int(mon.get("segments_captured") or 0),
        })
    return rows


def anomalies(previous: list[dict], current: list[dict], queue_limit: int) -> list[str]:
    before = {mon["id"]: mon for mon in previous}
    warnings = []
    for row in current:
        old = before.get(row["id"])
        if row["pending"] >= queue_limit:
            warnings.append(f"{row['id']}: pending queue at or above {queue_limit}")
        if old is None:
            continue
        if old["running"] and not row["running"]:
            warnings.append(f"{row['id']}: monitor stopped unexpectedly")
        if row["published"] < old["published"] or row["segments"] < old["segments"]:
            warnings.append(f"{row['id']}: counters reset (restart or state loss)")
        if row["failed"] > old["failed"]:
            warnings.append(f"{row['id']}: failed publication count increased")
    return warnings


def poll(base_url: str, token: str = "") -> dict:
    origin = urlsplit(base_url)
    if origin.scheme != "http" or origin.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Soak runner can only access a local ClippyMe instance")
    headers = {"X-API-Token": token} if token else {}
    req = Request(base_url.rstrip("/") + "/api/live-monitor/status", headers=headers)
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def run_probe(fetch, *, samples: int, interval: float = 0, pause=time.sleep,
              queue_limit: int = 50) -> list[dict]:
    history = []
    previous = []
    for index in range(samples):
        sample = summarize(fetch())
        history.append({"sample": index + 1, "monitors": sample,
                        "warnings": anomalies(previous, sample, queue_limit)})
        previous = sample
        if index + 1 < samples:
            pause(interval)
    return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--queue-limit", type=int, default=50)
    parser.add_argument("--output", help="JSONL report path (never includes credentials)")
    options = parser.parse_args()
    if not 0 < options.hours <= 168 or not 5 <= options.interval <= 3600:
        parser.error("Use 0<hours<=168 and 5<=interval<=3600 seconds")
    count = max(1, math.ceil(options.hours * 3600 / options.interval))
    history = run_probe(lambda: poll(options.base_url, os.getenv("CLIPPYME_API_TOKEN", "")),
                        samples=count, interval=options.interval,
                        queue_limit=options.queue_limit)
    if options.output:
        with open(options.output, "w", encoding="utf-8") as report:
            for row in history:
                report.write(json.dumps(row) + "\n")
    failures = sum(len(row["warnings"]) for row in history)
    print(f"Live Monitor soak: {len(history)} samples, {failures} warnings")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
