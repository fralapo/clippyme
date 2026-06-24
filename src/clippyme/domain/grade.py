"""Color grade compose layer (video-use `grade.py` port, ASC-CDL flavoured).

ClippyMe normalised audio and zoomed but never touched colour. Viral shorts
live on punch, so this adds an optional grade layer to the compose pipeline.

`build_grade_filter(preset)` is pure (returns an ffmpeg filter string or "") so
it is host-unit-testable; `apply_grade` is the thin ffmpeg wrapper. Presets are
deliberately gentle (talking-head-safe — never crush skin tones). Mirrors the
warm_cinematic / neutral_punch / none set shipped with video-use's grade.py.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess

from clippyme.domain.encode import x264_video_args

logger = logging.getLogger(__name__)

# preset name -> raw ffmpeg video filter chain (no leading -vf).
# Values chosen conservatively: a subtle contrast/saturation lift plus a mild
# warm split for the cinematic look. `none` is an explicit no-op.
GRADE_PRESETS: dict[str, str] = {
    "none": "",
    # Minimal corrective: contrast bump + gentle saturation, no hue shift.
    "neutral_punch": "eq=contrast=1.08:saturation=1.08:gamma=0.98",
    # Warm/teal split, slightly desaturated highlights — retro/technical feel.
    "warm_cinematic": (
        "eq=contrast=1.06:saturation=0.96:gamma=0.99,"
        "colorbalance=rs=0.03:gh=-0.01:bs=-0.04:rm=0.02:bm=-0.02"
    ),
    # Cooler, crisp, higher-contrast — modern social look.
    "cool_crisp": (
        "eq=contrast=1.10:saturation=1.04:gamma=0.97,"
        "colorbalance=rs=-0.03:bs=0.04:rm=-0.01:bm=0.02"
    ),
    # Punchy warm pop — bright, vivid, high-energy.
    "vivid_pop": "eq=contrast=1.12:saturation=1.18:brightness=0.02",
}

DEFAULT_GRADE = "none"


def build_grade_filter(preset: str | None) -> str:
    """Return the ffmpeg filter chain for `preset`, or "" for none/unknown.

    Unknown presets fall back to "" (no grade) rather than raising — a bad
    value from the UI must never break a download.
    """
    if not preset:
        return ""
    return GRADE_PRESETS.get(str(preset).strip().lower(), "")


def apply_grade(input_path: str, output_path: str, preset: str) -> bool:
    """Apply a colour grade preset to `input_path` → `output_path` via ffmpeg.

    Returns True on success. A `none`/unknown preset is treated as a no-op and
    the function returns False so the caller keeps the ungraded input (no
    pointless re-encode).
    """
    vf = build_grade_filter(preset)
    if not vf:
        return False
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", vf,
        # Shared near-visually-lossless encode (CRF 18 / medium). +faststart so
        # any compose layer can be the last one before the final byte-for-byte
        # copy and still emit a web-progressive mp4. See domain/encode.py.
        *x264_video_args(),
        "-c:a", "copy",
        output_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not os.path.exists(output_path):
        logger.warning(
            "grade '%s' failed (rc=%s): %s",
            preset, proc.returncode,
            (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:],
        )
        return False
    return True


async def apply_grade_async(input_path: str, output_path: str, preset: str) -> bool:
    return await asyncio.to_thread(apply_grade, input_path, output_path, preset)
