"""Pure helpers for the pipeline entrypoint (host-testable).

Extracted from ``pipeline.main``'s ``__main__`` block, which imports
cv2/torch/mediapipe at module top and therefore can't run on the dev host.
Only stdlib + ``domain.encode`` here.
"""
import os
import re

from clippyme.domain.encode import x264_video_args

_VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".avi"}

# Windows-forbidden filename characters + ASCII control chars.
_FORBIDDEN_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE_RE = re.compile(r"\s+")
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def sanitize_windows_basename(title: str | None, max_len: int = 80) -> str | None:
    """Windows-safe basename (no extension, no suffix) or None.

    Strips forbidden chars (<>:"/\\|?* + control), collapses whitespace,
    trims trailing dots/spaces, rejects reserved names (CON/PRN/AUX/NUL/
    COM1-9/LPT1-9). Truncates on a word boundary at ``max_len``. Returns
    None when nothing usable survives (caller supplies its own fallback).
    """
    if not title or not isinstance(title, str):
        return None
    cleaned = _FORBIDDEN_CHARS_RE.sub("", title)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    cleaned = cleaned.strip(". ")
    if not cleaned or cleaned.upper() in _RESERVED_NAMES:
        return None
    if len(cleaned) > max_len:
        cut = cleaned[:max_len]
        boundary, _, _ = cut.rpartition(" ")
        if boundary:
            cut = boundary
        cleaned = cut.strip(". ")
        if not cleaned:
            return None
    return cleaned


def clip_output_basename(
    title: str | None, index: int, fallback_base: str, max_len: int = 80
) -> str:
    """Windows-safe on-disk basename (no extension) for one clip.

    Prefers the clip's Gemini title, sanitized for Windows filesystems;
    falls back to the legacy ``{fallback_base}_clip_{index+1}`` convention
    for a missing/empty/reserved/all-forbidden title. Every result — title-
    or fallback-derived — carries the ``_clip_{index+1}`` suffix, so
    filenames stay unique across a job's clips.
    """
    fallback = f"{fallback_base}_clip_{index + 1}"
    cleaned = sanitize_windows_basename(title, max_len=max_len)
    if cleaned is None:
        return fallback
    return f"{cleaned}_clip_{index + 1}"


def resolve_output_dir(out: str | None, default: str) -> str:
    """Treat ``out`` as a directory unless it has a video suffix.

    Fixes the edge case where a user passes a new (non-existent) directory
    and the old logic called ``os.path.dirname`` on it, landing the output
    one level above the intended dir. Creates the directory when needed.
    """
    if not out:
        return default
    if os.path.splitext(out)[1].lower() in _VIDEO_SUFFIXES:
        return os.path.dirname(out) or default
    os.makedirs(out, exist_ok=True)
    return out


def build_cut_command(input_video: str, start: float, end: float, dest: str) -> list[str]:
    """ffmpeg argv for cutting the 16:9 source slice of one clip.

    ``-ss`` BEFORE ``-i`` uses fast input seek (jump to the keyframe before
    ``start``, decode forward to the exact time). ``-pix_fmt yuv420p`` +
    ``-vsync cfr`` guarantee the persisted slice is universally decodable and
    constant-frame-rate, so the downstream reframe render (raw frames at a
    fixed ``-r``) can't drift against audio even if the original download was
    VFR. Shared x264 settings (CRF 18 / medium): this slice feeds every later
    generation, so it must not be the weak link.
    """
    clip_duration = float(end) - float(start)
    return [
        'ffmpeg', '-y',
        '-ss', f'{float(start):.3f}',
        '-i', input_video,
        '-t', f'{clip_duration:.3f}',
        *x264_video_args(faststart=False),
        '-vsync', 'cfr',
        '-c:a', 'aac',
        dest,
    ]
