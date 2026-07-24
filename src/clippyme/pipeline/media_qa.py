"""FFprobe/FFmpeg-backed output inspection for rendered clips.

The expensive signal pass is bounded by timeouts and degrades gracefully when a
particular ffmpeg filter is unavailable.  Structural probe failures are critical;
optional black/audio metrics become warnings through ``evaluate_clip_qa``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

from clippyme.domain.clip_qa import evaluate_clip_qa

_BLACK_RE = re.compile(r"black_duration:([0-9.]+)")
_MEAN_RE = re.compile(r"mean_volume:\s*(-?(?:inf|[0-9.]+))\s*dB", re.IGNORECASE)
_MAX_RE = re.compile(r"max_volume:\s*(-?(?:inf|[0-9.]+))\s*dB", re.IGNORECASE)
_FREEZE_RE = re.compile(r"freeze_duration:\s*([0-9.]+)")


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


def probe_media(path: str, timeout: float = 25.0) -> dict[str, Any]:
    """Return normalized structural media facts. Never raises."""
    report: dict[str, Any] = {
        "path": os.path.basename(path),
        "exists": os.path.isfile(path),
        "size_bytes": None,
        "duration": None,
        "has_video": False,
        "has_audio": False,
        "width": None,
        "height": None,
        "video_codec": None,
        "audio_codec": None,
        "fps": None,
        "probe_error": None,
    }
    try:
        report["size_bytes"] = os.path.getsize(path)
    except OSError as exc:
        report["probe_error"] = str(exc)
        return report

    command = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", path,
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        report["probe_error"] = str(exc)
        return report
    if proc.returncode != 0:
        report["probe_error"] = (proc.stderr or "ffprobe failed")[-1000:]
        return report
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        report["probe_error"] = f"invalid ffprobe JSON: {exc}"
        return report

    report["duration"] = _float((payload.get("format") or {}).get("duration"))
    for stream in payload.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video" and not report["has_video"]:
            report["has_video"] = True
            report["width"] = int(stream.get("width") or 0) or None
            report["height"] = int(stream.get("height") or 0) or None
            report["video_codec"] = stream.get("codec_name")
            rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "")
            if "/" in rate:
                try:
                    numerator, denominator = rate.split("/", 1)
                    if float(denominator):
                        report["fps"] = round(float(numerator) / float(denominator), 3)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
        elif kind == "audio" and not report["has_audio"]:
            report["has_audio"] = True
            report["audio_codec"] = stream.get("codec_name")
            report["sample_rate"] = int(stream.get("sample_rate") or 0) or None
            report["channels"] = int(stream.get("channels") or 0) or None
    return report


def inspect_signal(path: str, duration: float | None, timeout: float = 90.0) -> dict[str, Any]:
    """Measure full-frame black/freeze time and audio level in one bounded pass."""
    metrics: dict[str, Any] = {
        "black_seconds": None,
        "black_ratio": None,
        "freeze_seconds": None,
        "freeze_ratio": None,
        "mean_volume_db": None,
        "max_volume_db": None,
        "signal_error": None,
    }
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-i", path,
        "-vf", "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-60dB:d=2",
        "-af", "volumedetect", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        metrics["signal_error"] = str(exc)
        return metrics
    text = proc.stderr or ""
    black_seconds = sum(float(value) for value in _BLACK_RE.findall(text))
    freeze_seconds = sum(float(value) for value in _FREEZE_RE.findall(text))
    metrics["black_seconds"] = round(black_seconds, 3)
    metrics["freeze_seconds"] = round(freeze_seconds, 3)
    if duration and duration > 0:
        metrics["black_ratio"] = round(min(1.0, black_seconds / duration), 4)
        metrics["freeze_ratio"] = round(min(1.0, freeze_seconds / duration), 4)
    mean_match = _MEAN_RE.search(text)
    max_match = _MAX_RE.search(text)
    if mean_match and mean_match.group(1).lower() != "-inf":
        metrics["mean_volume_db"] = _float(mean_match.group(1))
    if max_match and max_match.group(1).lower() != "-inf":
        metrics["max_volume_db"] = _float(max_match.group(1))
    if proc.returncode != 0 and not any(value is not None for key, value in metrics.items()
                                        if key != "signal_error"):
        metrics["signal_error"] = text[-1000:] or f"ffmpeg exited {proc.returncode}"
    return metrics


def inspect_clip(
    path: str,
    *,
    expected_duration: float | None,
    expected_aspect: float | None,
    smartcut_applied: bool = False,
    run_signal_checks: bool = True,
) -> dict[str, Any]:
    probe = probe_media(path)
    signal = inspect_signal(path, probe.get("duration")) if run_signal_checks and probe.get("has_video") else {}
    metrics = {**probe, **signal}
    verdict = evaluate_clip_qa(
        actual_duration=probe.get("duration"),
        expected_duration=expected_duration,
        has_audio=bool(probe.get("has_audio")),
        has_video=bool(probe.get("has_video")),
        size_bytes=probe.get("size_bytes"),
        width=probe.get("width"),
        height=probe.get("height"),
        expected_aspect=expected_aspect,
        black_ratio=signal.get("black_ratio"),
        freeze_ratio=signal.get("freeze_ratio"),
        mean_volume_db=signal.get("mean_volume_db"),
        max_volume_db=signal.get("max_volume_db"),
        smartcut_applied=smartcut_applied,
    )
    return {**verdict, "metrics": metrics}
