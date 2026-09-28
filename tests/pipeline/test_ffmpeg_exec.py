"""ffmpeg_exec invariants with deterministic stand-in child processes.

The children are tiny Python programs, so these run on every host (no ffmpeg,
no shell): a child that floods stderr before reading stdin, one that never
reads stdin, one that stops writing its output, one that fails.
"""
from __future__ import annotations

import os
import sys
import time

import pytest

from clippyme.pipeline import ffmpeg_exec
from clippyme.pipeline.ffmpeg_exec import (
    FfmpegError,
    FfmpegStalled,
    FrameEncoder,
    partial_path,
    run_ffmpeg,
    run_ffmpeg_atomic,
)


@pytest.fixture(autouse=True)
def _fast_watchdog(monkeypatch):
    monkeypatch.setattr(ffmpeg_exec, "STALL_TICK_SECONDS", 0.05)
    monkeypatch.setenv("CLIPPYME_FFMPEG_TIMEOUT", "1")


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


FRAME = b"\0" * (1024 * 1024)


def test_encoder_survives_a_child_that_floods_stderr_before_reading_stdin(tmp_path):
    out = tmp_path / "out.bin"
    encoder = FrameEncoder(_py(
        "import sys\n"
        "sys.stderr.write('x' * 1_000_000); sys.stderr.flush()\n"
        f"open({str(out)!r}, 'wb').write(sys.stdin.buffer.read())\n"
    ))
    try:
        for _ in range(8):
            encoder.write(FRAME)
        encoder.finish()
    finally:
        encoder.abort()
    assert out.stat().st_size == 8 * len(FRAME)


def test_encoder_kills_a_child_that_stops_consuming_frames():
    encoder = FrameEncoder(_py("import time; time.sleep(60)"))
    started = time.monotonic()
    try:
        with pytest.raises(FfmpegStalled):
            for _ in range(64):  # far more than any pipe buffer holds
                encoder.write(FRAME)
    finally:
        encoder.abort()
    assert time.monotonic() - started < 15
    assert encoder.proc.poll() is not None


def test_encoder_reports_the_stderr_tail_when_ffmpeg_dies():
    encoder = FrameEncoder(_py("import sys; sys.stderr.write('Unknown encoder libx265x'); sys.exit(1)"))
    try:
        with pytest.raises(FfmpegError, match="Unknown encoder"):
            for _ in range(64):
                encoder.write(FRAME)
            encoder.finish()
    finally:
        encoder.abort()


def test_encoder_is_not_stalled_while_python_is_busy_between_frames(tmp_path):
    """Slow producers (face detection, the global-smooth track pass) are not stalls."""
    encoder = FrameEncoder(_py("import sys; sys.stdin.buffer.read()"))
    try:
        encoder.write(FRAME)
        time.sleep(1.5)  # > the 1 s stall limit, but nobody is waiting on ffmpeg
        encoder.write(FRAME)
        encoder.finish()
    finally:
        encoder.abort()


def test_run_ffmpeg_kills_a_pass_whose_output_stops_growing(tmp_path):
    out = tmp_path / "out.mp4"
    started = time.monotonic()
    with pytest.raises(FfmpegStalled):
        run_ffmpeg(_py(f"open({str(out)!r}, 'wb').write(b'x' * 100); import time; time.sleep(60)"),
                   progress_path=str(out))
    assert time.monotonic() - started < 15


def test_run_ffmpeg_does_not_kill_a_slow_but_progressing_pass(tmp_path):
    out = tmp_path / "out.mp4"
    run_ffmpeg(_py(
        "import time\n"
        f"with open({str(out)!r}, 'wb') as f:\n"
        "    for _ in range(12):\n"
        "        f.write(b'x' * 10); f.flush(); time.sleep(0.25)\n"
    ), progress_path=str(out))  # 3 s total against a 1 s no-progress limit
    assert out.stat().st_size == 120


def test_atomic_pass_publishes_only_a_validated_file(tmp_path):
    dest = tmp_path / "source_clip.mp4"
    stale = tmp_path / ".partial-source_clip.mp4"
    stale.write_bytes(b"leftover from a crash")

    def build(target):
        return _py(f"open({target!r}, 'wb').write(b'complete')")

    run_ffmpeg_atomic(build, str(dest), validate=lambda p: open(p, "rb").read() == b"complete")
    assert dest.read_bytes() == b"complete"
    assert not stale.exists()


@pytest.mark.parametrize("child,validate", [
    ("import sys; open(sys.argv[1], 'wb').write(b'half'); sys.exit(1)", lambda p: True),
    ("import sys; open(sys.argv[1], 'wb').write(b'junk')", lambda p: False),
], ids=["ffmpeg-failed", "validation-failed"])
def test_failed_atomic_pass_leaves_neither_final_nor_partial(tmp_path, child, validate):
    dest = tmp_path / "source_clip.mp4"
    with pytest.raises(FfmpegError):
        run_ffmpeg_atomic(lambda target: [sys.executable, "-c", child, target], str(dest), validate=validate)
    assert not dest.exists()
    assert not os.path.exists(partial_path(str(dest)))
