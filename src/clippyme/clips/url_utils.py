"""URL helpers for resolving disk filenames from video_url references.

All backend consumers that need to turn a clip's ``video_url`` into a
filesystem path should go through :func:`filename_from_video_url` so
that cache-busting query strings (``?v=1234567``), fragments (``#t=3``)
and leading/trailing whitespace never leak into a filesystem lookup.

Historically we had half a dozen call sites each doing
``video_url.split("/")[-1]`` which broke after the reframe endpoint
started appending ``?v=...`` — see the bug fix in the commit that
introduced this module.
"""
from __future__ import annotations

from typing import Optional


def filename_from_video_url(video_url: Optional[str]) -> str:
    """Extract the bare filename from a stored ``video_url``.

    Safe against:
      - ``None`` or empty input (returns ``""``)
      - Query strings: ``/videos/abc/clip_1.mp4?v=1234`` → ``clip_1.mp4``
      - Fragments:     ``/videos/abc/clip_1.mp4#t=5``   → ``clip_1.mp4``
      - Leading/trailing whitespace
      - Trailing slashes
      - Backslashes on Windows-style paths
      - Path traversal: only the last path component is kept (everything
        up to the final forward- or back-slash separator is discarded), and
        a result of ``.`` / ``..`` — or anything that would still carry a
        separator or null byte — is rejected to ``""``. So a crafted
        ``/videos/<job>/../../etc/passwd`` collapses to ``passwd`` and a
        join with the job directory cannot escape it.

    The returned value is therefore always a single, separator-free
    filename safe to ``os.path.join`` with a job directory. Callers should
    still validate the ``job_id`` portion of the path with
    ``is_valid_job_id`` and confirm the file exists.
    """
    if not video_url or not isinstance(video_url, str):
        return ""
    # Strip whitespace first
    cleaned = video_url.strip()
    # Drop fragment
    if "#" in cleaned:
        cleaned = cleaned.split("#", 1)[0]
    # Drop query string
    if "?" in cleaned:
        cleaned = cleaned.split("?", 1)[0]
    # Normalize trailing slashes
    cleaned = cleaned.rstrip("/\\")
    if not cleaned:
        return ""
    # Take the last path component (handles both / and \)
    for sep in ("/", "\\"):
        if sep in cleaned:
            cleaned = cleaned.rsplit(sep, 1)[-1]
    # Path-traversal guard: the result is joined with a job directory by
    # callers, so a final component of "." / ".." (or anything that still
    # carries a separator / null byte) must never escape that directory.
    if cleaned in (".", "..") or "/" in cleaned or "\\" in cleaned or "\x00" in cleaned:
        return ""
    return cleaned


__all__ = ["filename_from_video_url"]
