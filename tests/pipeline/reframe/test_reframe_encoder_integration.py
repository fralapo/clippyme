"""The reframe master encode must not deadlock on ffmpeg's stderr.

``process_video_to_vertical`` streams raw frames into ffmpeg's stdin. If ffmpeg's
stderr is a pipe nobody reads until stdin is closed, an encoder that writes more
than the pipe capacity (64 KiB on Linux) before consuming its input blocks on
stderr while Python blocks on stdin: neither side ever returns. Single-threaded
ffmpeg (<= 6.x) reaches that state after ~2.5 min of stats output on a real
render; FFmpeg 7's threaded transcoder keeps consuming stdin, so the bug is
build dependent. The shim below makes it deterministic on any build by emitting
256 KiB of stderr before handing over to the real ffmpeg.

The render runs in a child process with a hard timeout so a regression fails
this test instead of hanging the suite.
"""
import os
import shutil
import stat
import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - host without the full CV runtime
    pytest.skip("heavy CV runtime unavailable", allow_module_level=True)

REAL_FFMPEG = shutil.which("ffmpeg")


def _clip(path, width=640, height=360, n_frames=60, fps=30):
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    for i in range(n_frames):
        frame = np.full((height, width, 3), (i * 4) % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.mark.skipif(os.name == "nt" or not REAL_FFMPEG, reason="POSIX shim over a real ffmpeg")
def test_render_survives_an_encoder_that_floods_stderr(tmp_path):
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "ffmpeg"
    shim.write_text(
        "#!/bin/sh\n"
        'case " $* " in *" -i - "*) head -c 262144 /dev/zero | tr "\\000" x >&2 ;; esac\n'
        f'exec {REAL_FFMPEG} "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    src, out = str(tmp_path / "src.mp4"), str(tmp_path / "out.mp4")
    _clip(src)
    env = {**os.environ, "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}"}
    code = (
        "import sys\n"
        "from clippyme.pipeline.reframe import reframe\n"
        f"ok = reframe.process_video_to_vertical({src!r}, {out!r}, reframe_mode='disabled')\n"
        "sys.exit(0 if ok else 3)\n"
    )

    try:
        child = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        pytest.fail("reframe deadlocked on an unread ffmpeg stderr pipe")

    assert child.returncode == 0, child.stdout.decode(errors="replace")[-2000:]
    cap = cv2.VideoCapture(out)
    try:
        assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) >= 55
        assert cap.get(cv2.CAP_PROP_FRAME_HEIGHT) > cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    finally:
        cap.release()
