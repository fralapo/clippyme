"""ffprobe-backed media inspection + pure A/V-sync helpers.

Robustness utilities ported from ``kamilstanuch/Autocrop-vertical`` (sixth
external study — see ``docs/autocrop-vertical-analysis.md``). They close two
real gaps in the clip / reframe render path:

* **Variable-frame-rate (VFR) detection** — phone uploads and some YouTube
  downloads carry a VFR video stream. The reframe loop decodes N frames with
  OpenCV and writes them back at a *fixed* ``-r fps``, so an undetected VFR
  source drifts against the stream-copied audio. ``is_vfr`` lets the caller
  re-mux to constant frame rate first.
* **Stream ``start_time`` compensation** — YouTube downloads frequently have a
  non-zero video-stream ``start_time`` (audio at 0.0s, video at e.g. 1.8s).
  When the video is re-encoded from frame 0 but the audio is stream-copied
  verbatim, that container offset becomes an audible A/V desync.
  ``audio_sync_seek_args`` trims the audio lead-in to match.

The pure parsing / decision helpers (``parse_frame_rate``, ``is_vfr``,
``parse_start_time``, ``audio_sync_seek_args``) perform no I/O and are
host-unit-tested in ``tests/pipeline/test_media_probe.py`` — no cv2 import, so
they run in the fast (non-integration) suite. The ``probe_*`` wrappers shell out
to ffprobe and **degrade gracefully (never raise)**: a missing ffprobe or an odd
file yields the "assume CFR / zero offset" default, so the pipeline keeps its
prior behaviour instead of breaking.
"""
from __future__ import annotations

import subprocess


def parse_frame_rate(rate: str) -> float:
    """Parse an ffprobe frame-rate string ("30000/1001", "25", "0/0") to fps.

    Returns ``0.0`` for empty / malformed / zero-denominator input rather than
    raising, so callers can treat "unknown" as "assume CFR / skip".
    """
    if not rate:
        return 0.0
    rate = rate.strip()
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return 0.0
            return float(num) / den_f
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return 0.0


def is_vfr(r_frame_rate: str, avg_frame_rate: str, threshold: float = 0.5) -> bool:
    """True when nominal (``r_frame_rate``) and average (``avg_frame_rate``) frame
    rates differ enough to indicate a variable frame rate.

    ffprobe reports both as "num/den". A gap above ``threshold`` fps means the
    container's real timing wanders from its nominal rate (classic for
    phone-recorded clips). Unknown / zero rates → ``False`` (assume CFR — the
    safer default, since a needless re-encode is worse than a no-op).
    """
    r = parse_frame_rate(r_frame_rate)
    avg = parse_frame_rate(avg_frame_rate)
    if r <= 0 or avg <= 0:
        return False
    return abs(r - avg) > threshold


def parse_start_time(value: str) -> float:
    """Parse an ffprobe stream ``start_time`` to seconds; "N/A"/""/garbage → 0.0."""
    if not value:
        return 0.0
    try:
        return float(value.strip())
    except ValueError:
        return 0.0


def audio_sync_seek_args(video_start_time: float, min_offset: float = 0.05) -> list[str]:
    """Return ffmpeg input-seek args dropping the audio lead-in equal to the video
    stream's ``start_time`` — or ``[]`` when the offset is negligible.

    Placed BEFORE ``-i`` (fast input seek) so the stream-copied audio is trimmed
    to begin where the (re-encoded-from-frame-0) video begins. Offsets under
    ``min_offset`` (≈1.5 frames @30fps) are ignored — not worth a re-seek, and it
    keeps the common zero-start case byte-identical to the old behaviour.
    """
    if video_start_time is None or video_start_time <= min_offset:
        return []
    return ["-ss", f"{video_start_time:.3f}"]


def reconcile_fps(reader_fps: float, scene_fps: float, tol: float = 0.1) -> float:
    """Choose the frame rate to encode at, given the OpenCV reader's rate and the
    scene-detector's rate for the same file.

    The reframe loop decodes frames with OpenCV and re-emits them at a fixed
    ``-r``; if the encoder rate doesn't match the *reader's* rate the output
    drifts against the stream-copied audio. PySceneDetect and OpenCV can disagree
    (e.g. 29.97 vs 30.0). Policy (Autocrop-vertical's "read fps from the same
    backend that reads the frames" learning, applied conservatively):

    * reader invalid (≤0) → fall back to ``scene_fps``;
    * scene invalid (≤0) → use ``reader_fps``;
    * the two **diverge** beyond ``tol`` → trust ``reader_fps`` (the frame source);
    * otherwise (within ``tol``) → keep ``scene_fps`` so the common case stays
      byte-identical to the prior behaviour.
    """
    if reader_fps is None or reader_fps <= 0:
        return scene_fps
    if scene_fps is None or scene_fps <= 0:
        return reader_fps
    if abs(reader_fps - scene_fps) > tol:
        return reader_fps
    return scene_fps


def probe_stream_start_time(video_path: str, stream: str = "v:0") -> float:
    """ffprobe a stream's ``start_time`` in seconds (0.0 if unavailable).

    Never raises — a missing ffprobe or unreadable file returns 0.0 so the caller
    simply skips the sync adjustment.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", stream,
             "-show_entries", "stream=start_time", "-of", "csv=p=0", video_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return parse_start_time(result.stdout)
    except (FileNotFoundError, OSError):
        pass
    return 0.0


def probe_is_variable_frame_rate(video_path: str, threshold: float = 0.5) -> bool:
    """ffprobe whether the first video stream is VFR.

    Never raises — a missing ffprobe / unreadable file / odd output returns
    ``False`` (assume CFR), so the pipeline only ever does *extra* work when it is
    confident the source is variable-rate.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate,avg_frame_rate",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False
        parts = result.stdout.strip().split(",")
        if len(parts) < 2:
            return False
        return is_vfr(parts[0], parts[1], threshold=threshold)
    except (FileNotFoundError, OSError):
        return False
