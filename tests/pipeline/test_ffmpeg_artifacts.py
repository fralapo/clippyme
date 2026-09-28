"""Crash-safety of the orchestrator's ffmpeg artefacts, against the real ffmpeg.

Covers the resume path end to end on tiny synthetic media:

* the prelive head trim is applied to a logical source at most once, however
  many times the job resumes (a second trim shifts every clip in time);
* a source slice left behind by an interrupted cut (SIGKILL: no moov atom;
  SIGTERM: ffmpeg finalises a valid but short file; or plain garbage) is never
  fed to the reframe, and a crash's partial temp file never becomes a slice;
* loudnorm output always lands at 48 kHz (its dynamic mode upsamples to 192 kHz
  internally and would otherwise leave 96 kHz AAC behind);
* a wedged ffmpeg cannot hold a pass forever (POSIX: needs an ``ffmpeg`` shim).

The video carries a time marker — frame luma is ``8 * floor(T) + noise`` — so a
timeline shift is measured on the decoded pixels, not inferred from filenames.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import time

import pytest

from clippyme.domain.runtime_state import RuntimeState
from clippyme.pipeline import orchestrator
from clippyme.pipeline.media_qa import probe_media
from clippyme.pipeline.run_ops import build_cut_command

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="needs the real ffmpeg/ffprobe binaries",
)

URL = "https://kick.com/example/videos/vod"


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _marker_source(path, seconds: int, sample_rate: int = 48000) -> str:
    _ff(
        "-f", "lavfi", "-i",
        f"color=c=black:s=320x180:r=30:d={seconds},geq=lum='8*floor(T)+20*random(1)':cb=128:cr=128",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={sample_rate}:duration={seconds}",
        "-c:v", "libx264", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    )
    return str(path)


def _luma_at(path: str, seconds: float) -> float:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ss", f"{seconds:.3f}", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout
    assert raw, f"no frame decoded at {seconds}s of {path}"
    return sum(raw) / len(raw)


def _duration(path: str) -> float:
    report = probe_media(path)
    assert not report["probe_error"], report["probe_error"]
    return float(report["duration"])


@pytest.fixture(scope="module")
def vod(tmp_path_factory) -> str:
    return _marker_source(tmp_path_factory.mktemp("media") / "vod.mp4", 30)


@pytest.fixture(scope="module")
def short_source(tmp_path_factory) -> str:
    return _marker_source(tmp_path_factory.mktemp("media") / "short.mp4", 12)


class _DownloadingLegacy:
    """The one ``main`` function ``_prepare_input`` needs: a yt-dlp stand-in."""

    def __init__(self, origin: str):
        self.origin = origin
        self.downloads = 0

    def download_youtube_video(self, url, output_dir, cookies):
        self.downloads += 1
        dest = os.path.join(output_dir, "vod.mp4")
        shutil.copyfile(self.origin, dest)
        return dest, "vod"


def _url_args(offset: float) -> argparse.Namespace:
    return argparse.Namespace(input=None, url=URL, cookies=None, start_offset=offset)


def _acquire(job_dir, args, legacy) -> str:
    # A fresh RuntimeState per call = a fresh orchestrator process after restart.
    path, _title = orchestrator._prepare_input(args, str(job_dir), RuntimeState(str(job_dir)), legacy)
    return path


# --- F3: prelive trim idempotent across resume ------------------------------


def test_resume_does_not_trim_the_source_a_second_time(tmp_path, vod):
    legacy = _DownloadingLegacy(vod)
    first = _acquire(tmp_path, _url_args(5.0), legacy)
    # Frame 0.5 s into the trimmed source is frame 5.5 s of the recording.
    assert _luma_at(first, 0.5) == pytest.approx(_luma_at(vod, 5.5), abs=6)

    resumed = [_acquire(tmp_path, _url_args(5.0), legacy) for _ in range(3)]

    for path in resumed:
        assert _duration(path) == pytest.approx(_duration(first), abs=0.1)
        assert _luma_at(path, 0.5) == pytest.approx(_luma_at(first, 0.5), abs=6)
    assert legacy.downloads == 1, "a resume must reuse the acquired source"


def test_zero_prelive_skip_keeps_the_download_untouched(tmp_path, vod):
    legacy = _DownloadingLegacy(vod)
    first = _acquire(tmp_path, _url_args(0.0), legacy)
    again = _acquire(tmp_path, _url_args(0.0), legacy)
    assert os.path.basename(first) == os.path.basename(again) == "vod.mp4"
    assert _duration(again) == pytest.approx(_duration(vod), abs=0.1)
    assert not [name for name in os.listdir(tmp_path) if name.startswith("trimmed_")]


def test_damaged_trimmed_source_is_reacquired_and_trimmed_once(tmp_path, vod):
    legacy = _DownloadingLegacy(vod)
    first = _acquire(tmp_path, _url_args(5.0), legacy)
    expected_luma = _luma_at(first, 0.5)
    expected_duration = _duration(first)
    with open(first, "r+b") as handle:  # same size, different bytes: a torn write
        handle.seek(0)
        handle.write(os.urandom(64 * 1024))

    resumed = _acquire(tmp_path, _url_args(5.0), legacy)

    assert legacy.downloads == 2
    assert _duration(resumed) == pytest.approx(expected_duration, abs=0.1)
    assert _luma_at(resumed, 0.5) == pytest.approx(expected_luma, abs=6)


# --- F4: interrupted source slices are never reused -------------------------


class _RecordingLegacy:
    """Stands in for the cv2-bound render: records which slice it was fed."""

    def __init__(self):
        self.fed: list[dict] = []

    def process_video_to_vertical(self, src, out, **_kwargs):
        self.fed.append(probe_media(src))
        shutil.copyfile(src, out)
        return True

    def normalize_audio(self, path):
        return None

    def select_cover_frame(self, path):
        return None


def _render(job_dir, source: str, legacy) -> bool:
    clip = {"start": 2.0, "end": 8.0, "clip_filename": "clip.mp4"}
    metadata = {"shorts": [clip]}
    return orchestrator._render_one_clip(
        index=0,
        total=1,
        clip=clip,
        input_video=source,
        video_title="vod",
        output_dir=str(job_dir),
        metadata_file=str(job_dir / "vod_metadata.json"),
        clips_data=metadata,
        args=argparse.Namespace(reframe_mode="auto", no_zoom=True, letterbox_zoom=0.0),
        aspect_ratio=16 / 9,
        state=RuntimeState(str(job_dir)),
        legacy=legacy,
    )


def _sigkill_slice(src: str, dest: str, scratch) -> None:
    """What a killed cut leaves: the head of a non-faststart MP4, no moov atom."""
    full = str(scratch / "full.mp4")
    subprocess.run(build_cut_command(src, 2.0, 8.0, full), check=True, capture_output=True)
    with open(full, "rb") as handle:
        head = handle.read(os.path.getsize(full) // 2)
    assert len(head) > 10_000
    with open(dest, "wb") as handle:
        handle.write(head)


def _sigterm_slice(src: str, dest: str, scratch) -> None:
    """What a SIGTERM'd cut leaves: ffmpeg finalises a valid, too-short file."""
    subprocess.run(build_cut_command(src, 2.0, 3.5, dest), check=True, capture_output=True)


def _garbage_slice(src: str, dest: str, scratch) -> None:
    with open(dest, "wb") as handle:
        handle.write(os.urandom(64 * 1024))


@pytest.mark.parametrize("leftover", [_sigkill_slice, _sigterm_slice, _garbage_slice],
                         ids=["sigkill-no-moov", "sigterm-truncated", "garbage"])
def test_interrupted_slice_is_recut_not_reused(tmp_path, short_source, monkeypatch, leftover):
    monkeypatch.setenv("CLIPPYME_QA_SIGNAL", "0")
    job = tmp_path / "job"
    job.mkdir()
    leftover(short_source, str(job / "source_clip.mp4"), tmp_path)
    legacy = _RecordingLegacy()

    assert _render(job, short_source, legacy) is True

    fed = legacy.fed[0]
    assert fed["probe_error"] is None
    assert fed["duration"] == pytest.approx(6.0, abs=0.2)
    assert _duration(str(job / "source_clip.mp4")) == pytest.approx(6.0, abs=0.2)
    # Slice starts at 2.0 s of the source: the marker proves nothing shifted.
    assert _luma_at(str(job / "source_clip.mp4"), 0.5) == pytest.approx(
        _luma_at(short_source, 2.5), abs=6)


def test_partial_temp_from_a_crashed_cut_is_discarded(tmp_path, short_source, monkeypatch):
    monkeypatch.setenv("CLIPPYME_QA_SIGNAL", "0")
    job = tmp_path / "job"
    job.mkdir()
    partial = job / ".partial-source_clip.mp4"
    partial.write_bytes(os.urandom(64 * 1024))

    assert _render(job, short_source, _RecordingLegacy()) is True

    assert not partial.exists()
    assert _duration(str(job / "source_clip.mp4")) == pytest.approx(6.0, abs=0.2)


def test_complete_slice_is_reused_without_recutting(tmp_path, short_source, monkeypatch):
    monkeypatch.setenv("CLIPPYME_QA_SIGNAL", "0")
    job = tmp_path / "job"
    job.mkdir()
    slice_path = job / "source_clip.mp4"
    subprocess.run(build_cut_command(short_source, 2.0, 8.0, str(slice_path)),
                   check=True, capture_output=True)

    def _no_cut(*_args, **_kwargs):
        raise AssertionError("a complete slice must not be cut again")

    monkeypatch.setattr(orchestrator, "build_cut_command", _no_cut)
    legacy = _RecordingLegacy()

    assert _render(job, short_source, legacy) is True
    assert legacy.fed[0]["duration"] == pytest.approx(6.0, abs=0.2)


# --- F5: loudnorm sample rate ------------------------------------------------


@pytest.mark.parametrize("sample_rate", [44100, 48000])
def test_loudnorm_output_is_48khz_even_in_dynamic_mode(tmp_path, sample_rate):
    from clippyme.pipeline.postprocess import normalize_audio

    clip = str(tmp_path / "clip.mp4")
    # Peaky noise: +4 dB of gain to -14 LUFS would break TP=-1.5, so loudnorm
    # reverts to dynamic mode — the mode that upsamples to 192 kHz.
    _ff(
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=8",
        "-f", "lavfi", "-i",
        f"anoisesrc=color=pink:sample_rate={sample_rate}:duration=8:amplitude=0.9,"
        "volume='0.2+0.8*abs(sin(t*3))':eval=frame",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip,
    )
    before = _duration(clip)

    normalize_audio(clip)

    report = probe_media(clip)
    assert report["sample_rate"] == 48000
    assert report["has_video"] and report["has_audio"]
    assert report["duration"] == pytest.approx(before, abs=0.1)


# --- F2: a wedged ffmpeg is bounded (POSIX: PATH shim) -----------------------

posix_only = pytest.mark.skipif(os.name == "nt", reason="PATH shim needs a POSIX shell")


def _wedged_ffmpeg(tmp_path, monkeypatch) -> None:
    """An ``ffmpeg`` that writes some output, then hangs without progress."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "ffmpeg"
    shim.write_text(
        '#!/bin/sh\nfor a in "$@"; do last="$a"; done\n'
        'head -c 20000 /dev/urandom > "$last"\nexec sleep 30\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CLIPPYME_FFMPEG_TIMEOUT", "2")


@posix_only
def test_wedged_cut_is_bounded_and_leaves_no_slice(tmp_path, short_source, monkeypatch):
    job = tmp_path / "job"
    job.mkdir()
    _wedged_ffmpeg(tmp_path, monkeypatch)

    started = time.monotonic()
    with pytest.raises(Exception):
        _render(job, short_source, _RecordingLegacy())
    assert time.monotonic() - started < 10

    assert not (job / "source_clip.mp4").exists()
    assert not (job / ".partial-source_clip.mp4").exists()


@posix_only
def test_wedged_trim_falls_back_to_the_untrimmed_source(tmp_path, vod, monkeypatch):
    legacy = _DownloadingLegacy(vod)
    _wedged_ffmpeg(tmp_path, monkeypatch)

    started = time.monotonic()
    path = _acquire(tmp_path, _url_args(5.0), legacy)
    assert time.monotonic() - started < 10

    assert os.path.basename(path) == "vod.mp4"
    assert not [name for name in os.listdir(tmp_path) if "trimmed_" in name]
