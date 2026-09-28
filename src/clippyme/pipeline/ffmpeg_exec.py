"""Bounded, crash-safe ffmpeg subprocesses for the pipeline (no cv2 — host-tested).

Three invariants every pipeline ffmpeg pass needs:

* **stderr is never an unread pipe.** It goes to an anonymous temp file: no
  reader thread, no 64 KiB pipe to fill, and the tail is still available for the
  error message. (A pipe read only after stdin is closed deadlocks the reframe
  encode on single-threaded ffmpeg <= 6.x once ~64 KiB of stats accumulate.)
* **a pass that stops making progress is killed.** The watchdog counts fixed
  ticks instead of reading a wall clock, so a job the user paused (the whole
  process tree is SIGSTOPped, watchdog thread included) is not mistaken for a
  stall when it resumes: the suspended ticks never happen. The limit is
  ``CLIPPYME_FFMPEG_TIMEOUT`` (default 600 s) *without progress*, so a long but
  advancing pass is never cut short.
* **a produced file appears under its final name only when complete.** ffmpeg
  writes a hidden ``.partial-`` sibling in the same directory; it is renamed into
  place (atomic on one filesystem) only after ffmpeg exited 0 and the result
  passed validation. A killed process — SIGKILL leaves no moov atom, SIGTERM
  makes ffmpeg finalise a valid but short file — can only leave the partial,
  which the next attempt deletes. Durability across power loss (fsync) is out of
  scope: the threat here is a killed process, not a lost page cache.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from typing import Callable

from clippyme.domain.encode import ffmpeg_timeout

STALL_TICK_SECONDS = 1.0
_TAIL_BYTES = 4000


class FfmpegError(RuntimeError):
    """ffmpeg exited non-zero or produced an unusable file."""


class FfmpegStalled(FfmpegError):
    """ffmpeg made no progress for the stall limit and was killed."""


def partial_path(dest: str) -> str:
    """Hidden same-directory temp name (``glob('*.mp4')`` and /videos skip it)."""
    return os.path.join(os.path.dirname(dest), f".partial-{os.path.basename(dest)}")


def remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _tail(handle) -> str:
    end = handle.seek(0, os.SEEK_END)
    handle.seek(max(0, end - _TAIL_BYTES))
    return handle.read().decode("utf-8", errors="replace").strip()


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


class _Watchdog(threading.Thread):
    """Kill ``proc`` once ``progress()`` stays unchanged for ``limit`` seconds.

    ``progress()`` returning ``None`` means "not waiting on ffmpeg right now"
    and resets the count.
    """

    def __init__(self, proc: subprocess.Popen, progress: Callable[[], object], limit: float):
        super().__init__(daemon=True, name="ffmpeg-watchdog")
        self._proc = proc
        self._progress = progress
        self._limit = limit
        self._done = threading.Event()
        self.stalled = False

    def run(self) -> None:
        idle, last = 0.0, object()
        while not self._done.wait(STALL_TICK_SECONDS):
            if self._proc.poll() is not None:
                return
            token = self._progress()
            if token is None or token != last:
                idle, last = 0.0, token
                continue
            idle += STALL_TICK_SECONDS
            if idle >= self._limit:
                self.stalled = True
                self._proc.kill()
                return

    def stop(self) -> None:
        self._done.set()
        self.join()


def _reap(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def run_ffmpeg(command: list[str], *, progress_path: str) -> None:
    """Run a file-producing ffmpeg pass; progress = growth of ``progress_path``.

    Raises :class:`FfmpegStalled` / :class:`FfmpegError` carrying the stderr tail.
    """
    limit = float(ffmpeg_timeout())
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
        )
        watchdog = _Watchdog(proc, lambda: _size(progress_path), limit)
        watchdog.start()
        try:
            returncode = proc.wait()
        finally:
            _reap(proc)
            watchdog.stop()
        if watchdog.stalled:
            raise FfmpegStalled(f"ffmpeg made no progress for {limit:.0f}s and was killed: {_tail(err)}")
        if returncode != 0:
            raise FfmpegError(f"ffmpeg exited {returncode}: {_tail(err)}")


def run_ffmpeg_atomic(
    build_command: Callable[[str], list[str]],
    dest: str,
    *,
    validate: Callable[[str], bool],
) -> str:
    """``build_command(tmp)`` → ffmpeg → ``validate(tmp)`` → rename to ``dest``."""
    part = partial_path(dest)
    remove_quietly(part)  # a crashed attempt's leftover is never resumed from
    try:
        run_ffmpeg(build_command(part), progress_path=part)
        if not validate(part):
            raise FfmpegError(f"ffmpeg output failed validation: {os.path.basename(dest)}")
        os.replace(part, dest)
    finally:
        remove_quietly(part)
    return dest


class FrameEncoder:
    """ffmpeg reading raw frames on stdin (the reframe master encode).

    ``write`` raises :class:`FfmpegError` instead of ``BrokenPipeError`` when
    ffmpeg died, and :class:`FfmpegStalled` when ffmpeg stopped consuming frames
    for the stall limit. Always call :meth:`abort` in a ``finally``.
    """

    def __init__(self, command: list[str]):
        self._limit = float(ffmpeg_timeout())
        self._err = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._err,
        )
        self._written = 0
        self._busy = False
        self._watchdog = _Watchdog(self.proc, lambda: self._written if self._busy else None, self._limit)
        self._watchdog.start()

    def write(self, frame: bytes) -> None:
        self._busy = True
        try:
            self.proc.stdin.write(frame)
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise self._failure() from exc
        finally:
            self._busy = False
        self._written += 1

    def finish(self) -> None:
        """Close stdin and wait for the encoder to flush; raise on failure."""
        self._busy = True
        try:
            try:
                self.proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            returncode = self.proc.wait()
        finally:
            self._busy = False
        if returncode != 0 or self._watchdog.stalled:
            raise self._failure()

    def _failure(self) -> FfmpegError:
        _reap(self.proc)
        self._watchdog.stop()
        if self._watchdog.stalled:
            return FfmpegStalled(
                f"ffmpeg stopped consuming frames for {self._limit:.0f}s and was killed: {_tail(self._err)}"
            )
        return FfmpegError(f"ffmpeg exited {self.proc.returncode}: {_tail(self._err)}")

    def abort(self) -> None:
        """Kill (if still running), reap, stop the watchdog, drop the log. Idempotent."""
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        _reap(self.proc)
        self._watchdog.stop()
        self._err.close()
