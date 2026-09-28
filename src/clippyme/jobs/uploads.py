"""Helpers for handling multipart file uploads."""
import asyncio
import contextlib
import os


async def _run_file_operation(function, *args):
    """Finish an in-flight file operation before propagating task cancellation."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await task
        raise


class FileTooLarge(Exception):
    """Raised when an upload exceeds the configured size limit."""

    def __init__(self, limit_mb: int):
        self.limit_mb = limit_mb
        super().__init__(f"File too large. Max size {limit_mb}MB")


async def stream_upload_within_limit(file, dest_path: str, limit_bytes: int) -> int:
    """Stream an UploadFile to ``dest_path`` while enforcing ``limit_bytes``.

    The destination is removed on every unsuccessful exit, including write
    errors and task cancellation, so aborted HTTP uploads never leave a partial
    file that later cleanup mistakes for a valid media input.
    """
    size = 0
    completed = False
    try:
        with open(dest_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                size += len(content)
                if size > limit_bytes:
                    raise FileTooLarge(limit_bytes // (1024 * 1024))
                await _run_file_operation(buffer.write, content)
            await _run_file_operation(buffer.flush)
            await _run_file_operation(os.fsync, buffer.fileno())
        completed = True
        return size
    finally:
        if not completed:
            with contextlib.suppress(OSError):
                os.remove(dest_path)
