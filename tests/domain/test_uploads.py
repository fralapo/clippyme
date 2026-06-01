"""Unit tests for clippyme.domain.uploads.stream_upload_within_limit."""
import asyncio
import os

import pytest

from clippyme.domain.uploads import FileTooLarge, stream_upload_within_limit


class FakeUpload:
    """Minimal UploadFile stand-in: yields `data` in `chunk`-sized reads."""

    def __init__(self, data: bytes, chunk: int = 1024 * 1024):
        self._buf = data
        self._chunk = chunk
        self._pos = 0

    async def read(self, n: int) -> bytes:
        # Honour our own chunking rather than n, to keep the test simple.
        out = self._buf[self._pos:self._pos + self._chunk]
        self._pos += len(out)
        return out


def test_writes_full_file_under_limit(tmp_path):
    dest = tmp_path / "out.mp4"
    data = b"a" * 5000
    written = asyncio.run(stream_upload_within_limit(FakeUpload(data), str(dest), limit_bytes=10_000))
    assert written == 5000
    assert dest.read_bytes() == data


def test_raises_and_removes_partial_when_over_limit(tmp_path):
    dest = tmp_path / "out.mp4"
    data = b"a" * 5000
    with pytest.raises(FileTooLarge) as exc:
        asyncio.run(stream_upload_within_limit(
            FakeUpload(data, chunk=1000), str(dest), limit_bytes=2000
        ))
    assert exc.value.limit_mb == 2000 // (1024 * 1024)
    # Partial upload must not be left on disk.
    assert not os.path.exists(dest)
