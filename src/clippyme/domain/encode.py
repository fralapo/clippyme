"""Shared libx264 encode settings for every render / compose pass.

A single clip can pass through several sequential ffmpeg re-encodes before the
user downloads it — reframe → auto-zoom → (at download) grade → subtitles →
smart-cut → hook → logo. libx264 is lossy, so **each generation discards a
little detail**; at the old scattered defaults (CRF 23 / preset ``fast`` on the
reframe, zoom, subtitle and smart-cut passes) that compounded into visibly
softer, blockier output by the time a fully-composed clip was downloaded.

Centralising the settings here keeps every generation at a near-visually-
lossless CRF so the whole chain stays clean, and lets the entire pipeline be
tuned from one place (env overrides) instead of N drifting literals.

Pure / dependency-free (only ``os``) so it is host-importable and unit-testable.
"""
import os

# CRF 18 is x264's widely-cited "visually lossless" point: a single generation
# is essentially indistinguishable from the source, and several stacked
# generations still stay clean. Lower = higher quality + bigger files (0 = truly
# lossless, huge). Valid range 0–51.
_DEFAULT_CRF = 18
# 'medium' gives better psychovisual decisions and smaller files than 'fast' at
# the same CRF, for a modest amount of extra encode time — worth it because
# these encodes feed further encodes (generational robustness).
_DEFAULT_PRESET = "medium"

_VALID_PRESETS = {
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
}

# A single compose-layer ffmpeg pass on a ≤75s clip finishes in seconds; a pass
# that runs this long is hung, not slow. Every compose-layer subprocess.run
# passes this timeout because those calls execute on asyncio's shared default
# thread pool — a handful of hung ffmpeg processes would otherwise pin its
# workers forever and stall job polling for the whole API, not just the
# offending request.
_DEFAULT_FFMPEG_TIMEOUT = 600


def ffmpeg_timeout() -> int:
    """Per-pass ffmpeg timeout in seconds — ``CLIPPYME_FFMPEG_TIMEOUT`` (>0) or 600."""
    raw = (os.getenv("CLIPPYME_FFMPEG_TIMEOUT") or "").strip()
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return _DEFAULT_FFMPEG_TIMEOUT


def x264_crf() -> int:
    """Resolved CRF — ``CLIPPYME_X264_CRF`` (clamped to 0–51) or the default 18."""
    raw = (os.getenv("CLIPPYME_X264_CRF") or "").strip()
    if raw:
        try:
            v = int(raw)
            if 0 <= v <= 51:
                return v
        except ValueError:
            pass
    return _DEFAULT_CRF


def x264_preset() -> str:
    """Resolved preset — ``CLIPPYME_X264_PRESET`` (if a valid name) or 'medium'."""
    raw = (os.getenv("CLIPPYME_X264_PRESET") or "").strip().lower()
    return raw if raw in _VALID_PRESETS else _DEFAULT_PRESET


def x264_video_args(crf=None, preset=None, pix_fmt="yuv420p", faststart=True):
    """Return the shared ``-c:v libx264 …`` argument list for one encode pass.

    ``crf`` / ``preset`` override the env/default when given (e.g. a deliberately
    higher-quality master pass, or a faster preset for a cheap intermediate).
    ``pix_fmt`` defaults to ``yuv420p`` for universal player/mobile decode
    (pass ``None`` to omit). ``faststart`` writes the moov atom up front so the
    mp4 is progressively playable and uploads cleanly to social. Audio flags
    (``-c:a copy`` / ``aac`` / ``-an``) stay at the call site — this only owns
    the video codec settings.
    """
    args = [
        "-c:v", "libx264",
        "-preset", preset or x264_preset(),
        "-crf", str(crf if crf is not None else x264_crf()),
    ]
    if pix_fmt:
        args += ["-pix_fmt", pix_fmt]
    if faststart:
        args += ["-movflags", "+faststart"]
    return args
