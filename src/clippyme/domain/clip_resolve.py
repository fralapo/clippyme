"""Shared job/clip resolution for the per-clip endpoints.

Every per-clip endpoint (smartcut, transcript, edit-ai, compose, publish) needs
the same chain: job dir → latest ``*_metadata.json`` → clip entry by index →
clip filename (from ``video_url``, falling back to the ``_clip_{i+1}.mp4``
naming convention) → absolute clip path. This module is the single owner of
that chain; the handlers call :func:`resolve_clip` and stay thin.

Pure sync filesystem code (handlers wrap it in ``asyncio.to_thread``); raises
``NotFoundError`` which the app-level ``ClippyMeError`` handler maps to 404.
"""
import json
import os
from dataclasses import dataclass

from clippyme.domain.errors import NotFoundError
from clippyme.domain.job_artifacts import find_job_metadata_path
from clippyme.domain.url_utils import filename_from_video_url


@dataclass(frozen=True)
class ResolvedClip:
    metadata_path: str
    metadata: dict
    clip_info: dict
    clip_filename: str
    clip_path: str

    @property
    def job_dir(self) -> str:
        return os.path.dirname(self.metadata_path)


def clip_filename_for(metadata_path: str, clip_info: dict, clip_index: int) -> str:
    """Clip filename, preferring (a) the ``clip_filename`` basename the
    pipeline persists into metadata (pipeline/main.py, task 4b) when it is a
    non-empty string with no path separators or ``..`` (defence against a
    tampered/legacy metadata file smuggling a path), then (b) the legacy
    metadata ``video_url``, then (c) the positional ``<base>_clip_{i+1}.mp4``
    convention when neither is present."""
    raw = clip_info.get("clip_filename")
    if isinstance(raw, str) and raw and "/" not in raw and "\\" not in raw and ".." not in raw:
        return raw
    filename = filename_from_video_url(clip_info.get("video_url"))
    if not filename:
        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")
        filename = f"{base_name}_clip_{clip_index + 1}.mp4"
    return filename


def composed_clip_basename(clip_info: dict, clip_index: int) -> str:
    """Filename for a clip's final composed (hook/subtitles/banner/…) output.

    Title-based and Windows-safe (no ``_clip_N`` suffix) so a downloaded /
    served composed clip is named meaningfully — ``<title>.mp4`` — instead of
    ``composed_clip_1.mp4``. Falls back to the legacy positional name when the
    title is missing/reserved/all-forbidden. Stable across re-composes of the
    same clip (same title → same file, overwritten in place). This is the
    SINGLE owner of the composed-file naming — the compose writer, the publish
    lookup and the delete-after-publish target all resolve through it.
    """
    from clippyme.pipeline.run_ops import sanitize_windows_basename

    title = (clip_info or {}).get("video_title_for_youtube_short") or (clip_info or {}).get("title")
    base = sanitize_windows_basename(title)
    return f"{base}.mp4" if base else f"composed_clip_{clip_index}.mp4"


def resolve_clip(job_id: str, clip_index: int, output_root: str,
                 *, require_file: bool = True) -> ResolvedClip:
    """Resolve a job's clip to its metadata + on-disk path.

    Raises ``NotFoundError`` (→ 404) when the job dir, metadata, clip index or
    — with ``require_file=True`` — the rendered mp4 is missing. Callers that
    can proceed without the base file (transcript/edit-ai read only metadata;
    publish may fall back to a composed file) pass ``require_file=False``.
    """
    job_dir = os.path.join(output_root, job_id)
    if not os.path.isdir(job_dir):
        raise NotFoundError("Job not found")

    try:
        metadata_path = find_job_metadata_path(job_id, output_root)
    except FileNotFoundError:
        raise NotFoundError("No metadata found")

    with open(metadata_path, encoding="utf-8") as f:
        metadata = json.load(f)

    clips = metadata.get("shorts", [])
    if clip_index < 0 or clip_index >= len(clips):
        raise NotFoundError("Clip not found")
    clip_info = clips[clip_index]

    clip_filename = clip_filename_for(metadata_path, clip_info, clip_index)
    clip_path = os.path.join(job_dir, clip_filename)
    if require_file and not os.path.exists(clip_path):
        raise NotFoundError(f"Clip file not found: {clip_filename}")

    return ResolvedClip(
        metadata_path=metadata_path,
        metadata=metadata,
        clip_info=clip_info,
        clip_filename=clip_filename,
        clip_path=clip_path,
    )
