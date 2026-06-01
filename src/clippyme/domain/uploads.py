"""Helpers for handling multipart file uploads.

Extracted from api.app.process_endpoint to keep the endpoint handler thin
(validate → call helper → return) per the repo's code-organization rule.
"""
import contextlib
import os


class FileTooLarge(Exception):
    """Raised when an upload exceeds the configured size limit.

    The partial file written so far is removed (best-effort) before this is
    raised; the caller is responsible for any *other* resources (e.g. the
    per-job output dir).
    """

    def __init__(self, limit_mb: int):
        self.limit_mb = limit_mb
        super().__init__(f"File too large. Max size {limit_mb}MB")


async def stream_upload_within_limit(file, dest_path: str, limit_bytes: int) -> int:
    """Stream an UploadFile to `dest_path`, enforcing `limit_bytes`.

    Reads in 1 MiB chunks. If the running total exceeds the limit we stop,
    close the file handle (required before deletion on Windows), remove the
    partial file best-effort, and raise FileTooLarge. Returns the number of
    bytes written on success.
    """
    size = 0
    oversize = False
    with open(dest_path, "wb") as buffer:
        while content := await file.read(1024 * 1024):
            size += len(content)
            if size > limit_bytes:
                oversize = True
                break
            buffer.write(content)
    if oversize:
        # Handle is closed (we left the `with`) before we delete the file.
        with contextlib.suppress(OSError):
            os.remove(dest_path)
        raise FileTooLarge(limit_bytes // (1024 * 1024))
    return size
