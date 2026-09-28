"""End-to-end: kill the real orchestrator mid-cut, resume it, check the media.

source → prelive trim → source slice (killed here, the way an app shutdown
kills a job: ``terminate_tree``, SIGTERM first) → resume in a fresh process →
trim reused, partial slice discarded, slice re-cut → "reframe" → loudnorm →
QA → clip. Only ``pipeline.main`` is replaced (by ffmpeg-only stand-ins, no
cv2/Gemini); orchestrator, ffmpeg passes, QA and runtime state are the real
ones. The time marker in the frames (luma = 8*floor(T)+noise) checks that the
resumed clip starts at the right instant of the recording.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time

import psutil
import pytest

from clippyme.jobs.job_control import terminate_tree
from clippyme.jobs.runtime_state import load_runtime_state
from clippyme.pipeline.media_qa import probe_media

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="needs the real ffmpeg/ffprobe binaries",
)

OFFSET = 5.0

FAKE_MAIN = textwrap.dedent('''
    """ffmpeg-only stand-in for clippyme.pipeline.main (no cv2 / Gemini)."""
    import os, shutil, subprocess
    from clippyme.media.encode import x264_video_args
    from clippyme.pipeline.postprocess import normalize_audio  # the real one

    MODEL_PRICING = {}
    CUDA_AVAILABLE = False

    def download_youtube_video(url, output_dir, cookies):
        dest = os.path.join(output_dir, "vod.mp4")
        shutil.copyfile(os.environ["E2E_ORIGIN"], dest)
        with open(os.environ["E2E_DOWNLOADS"], "a") as log:
            log.write("download\\n")
        return dest, "vod"

    def process_video_to_vertical(src, out, **kwargs):
        vf = "scale=180:320:force_original_aspect_ratio=decrease,pad=180:320:(ow-iw)/2:(oh-ih)/2"
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf,
               *x264_video_args(faststart=False), "-c:a", "copy", out]
        return subprocess.run(cmd).returncode == 0

    def select_cover_frame(path):
        return None
''')

DRIVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import fake_main
    import clippyme.pipeline as pipeline
    sys.modules["clippyme.pipeline.main"] = fake_main
    pipeline.main = fake_main
    from clippyme.pipeline import orchestrator
    raise SystemExit(orchestrator.run(sys.argv[2:]))
''')


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _luma_at(path: str, seconds: float) -> float:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ss", f"{seconds:.3f}", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout
    return sum(raw) / len(raw)


def _survivors(marker: str) -> list[str]:
    found = []
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if marker in cmdline and proc.pid != os.getpid():
            found.append(cmdline)
    return found


def test_killed_cut_resumes_to_a_valid_clip_on_the_right_timeline(tmp_path):
    origin = str(tmp_path / "origin.mp4")
    _ff(
        "-f", "lavfi", "-i",
        "color=c=black:s=640x360:r=30:d=40,geq=lum='8*floor(T)+20*random(1)':cb=128:cr=128",
        "-f", "lavfi", "-i",
        "anoisesrc=color=pink:sample_rate=44100:duration=40:amplitude=0.9,"
        "volume='0.2+0.8*abs(sin(t*3))':eval=frame",
        "-c:v", "libx264", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", origin,
    )
    support = tmp_path / "support"
    support.mkdir()
    (support / "fake_main.py").write_text(FAKE_MAIN, encoding="utf-8")
    (support / "driver.py").write_text(DRIVER, encoding="utf-8")
    job = tmp_path / "job"
    job.mkdir()
    downloads = tmp_path / "downloads.log"
    env = {
        **os.environ,
        "E2E_ORIGIN": origin,
        "E2E_DOWNLOADS": str(downloads),
        "CLIPPYME_QA_SIGNAL": "0",
        "CLIPPYME_MIN_FREE_DISK_GB": "0",
        "PYTHONIOENCODING": "utf-8",
    }
    argv = [sys.executable, str(support / "driver.py"), str(support),
            "-u", "https://kick.com/example/videos/vod", "-o", str(job),
            "--skip-analysis", "--no-zoom", "--start-offset", str(OFFSET)]

    # Life 1: killed while ffmpeg is writing the source slice.
    life1 = subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Pre-fix code cut straight into the final name; either one means "cutting".
    cut_targets = (job / ".partial-source_vod_clip_1.mp4", job / "source_vod_clip_1.mp4")
    deadline = time.monotonic() + 60
    while not any(p.exists() and p.stat().st_size > 0 for p in cut_targets):
        assert life1.poll() is None, "orchestrator finished before the cut could be interrupted"
        assert time.monotonic() < deadline, "the cut never started"
        time.sleep(0.01)
    terminate_tree(life1.pid, timeout=5.0)
    life1.wait(timeout=10)
    assert not (job / "source_vod_clip_1.mp4").exists(), "an interrupted cut must not publish a slice"
    assert _survivors(str(job)) == []
    trimmed = job / "trimmed_vod.mp4"
    assert trimmed.exists()

    # Life 2: a fresh process resumes the same job.
    life2 = subprocess.run(argv, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert life2.returncode == 0, life2.stdout[-3000:] + life2.stderr[-3000:]
    assert "Resume: reusing acquired source" in life2.stdout
    assert "Skipped the first" not in life2.stdout, "life 2 must not trim again"
    assert _survivors(str(job)) == []

    state = load_runtime_state(str(job))
    assert state["stage"] == "completed"
    assert state["artifacts"]["head_trim_seconds"] == OFFSET
    assert downloads.read_text().count("download") == 1

    slice_path = str(job / "source_vod_clip_1.mp4")
    clip = str(job / "vod_clip_1.mp4")
    # Trimmed once: the clip's first frames are the recording at OFFSET, not 2*OFFSET.
    assert _luma_at(slice_path, 0.5) == pytest.approx(_luma_at(origin, OFFSET + 0.5), abs=6)
    report = probe_media(clip)
    assert report["probe_error"] is None
    assert report["duration"] == pytest.approx(40 - OFFSET, abs=0.3)
    assert report["sample_rate"] == 48000
    assert report["height"] > report["width"]
    metadata = json.loads((job / "vod_metadata.json").read_text(encoding="utf-8"))
    assert metadata["shorts"][0]["qa"]["critical"] is False
    # Completed URL job: both the trimmed source and the download it came from are gone.
    assert not trimmed.exists() and not (job / "vod.mp4").exists()
    assert not [name for name in os.listdir(job) if name.startswith(".partial-")]
