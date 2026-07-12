"""Pure helpers for the pipeline entrypoint (host-testable).

Extracted from ``pipeline.main``'s ``__main__`` block, which imports
cv2/torch/mediapipe at module top and therefore can't run on the dev host.
Only stdlib + ``domain.encode`` here.
"""
import os

from clippyme.domain.encode import x264_video_args

_VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".avi"}


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
