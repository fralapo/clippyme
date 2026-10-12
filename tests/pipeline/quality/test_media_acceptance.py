"""Real FFmpeg/libass acceptance checks; synthetic media, no external services.

The host suite excludes integration tests. In Docker CI these tests exercise
actual encoders, ASS subtitle burning, ffprobe and the manifest quality gate.
"""
import json
import subprocess

import pytest

from clippyme.editing.subtitles import burn_subtitles, generate_ass_karaoke
from clippyme.pipeline.quality.quality_suite import main as quality_main, run_manifest

pytestmark = pytest.mark.integration


def _ffmpeg(*arguments):
    completed = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-nostdin", "-loglevel", "error", *map(str, arguments)],
        capture_output=True,
        text=True,
        timeout=100,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-1500:]


def _manifest(folder, name, clip):
    manifest = folder / f"{name}.json"
    manifest.write_text(json.dumps({"cases": [{
        "name": name,
        "path": clip.name,
        "expected_duration": 3.0,
        "duration_tolerance": 0.35,
        "expected_aspect": "9:16",
        "min_size_bytes": 10_000,
        "max_black_ratio": 0.25,
        "max_freeze_ratio": 0.55,
        "min_mean_volume_db": -35,
        "max_peak_volume_db": -0.1,
        "allow_warnings": False,
    }]}), encoding="utf-8")
    return manifest


def test_real_karaoke_render_passes_media_acceptance_gate(tmp_path):
    source = tmp_path / "source.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=144x256:rate=12:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", source,
    )

    ass = tmp_path / "captions.ass"
    transcript = {"segments": [{"words": [
        {"word": "HELLO", "start": 0.3, "end": 1.0},
        {"word": "WORLD", "start": 1.0, "end": 1.8},
    ]}]}
    assert generate_ass_karaoke(transcript, 0, 3.0, str(ass), preset="hormozi_bold")
    assert "\\k" in ass.read_text(encoding="utf-8")

    rendered = tmp_path / "captioned.mp4"
    assert burn_subtitles(str(source), str(ass), str(rendered))
    manifest = _manifest(tmp_path, "karaoke-vertical", rendered)
    report = run_manifest(str(manifest))
    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1, report["cases"][0]
    assert report["cases"][0]["metrics"]["has_audio"]
    assert report["cases"][0]["metrics"]["has_video"]
    assert report["cases"][0]["metrics"]["width"] == 144
    assert report["cases"][0]["metrics"]["height"] == 256

    output = tmp_path / "acceptance-report.json"
    assert quality_main([str(manifest), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["failed"] == 0


def test_real_broken_export_is_rejected_by_quality_gate(tmp_path):
    broken = tmp_path / "broken.mp4"
    # Landscape, no audio: both defects must be detected from real ffprobe data.
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=256x144:rate=12:duration=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-an", broken,
    )
    manifest = _manifest(tmp_path, "broken-landscape-no-audio", broken)
    report = run_manifest(str(manifest))
    assert report["summary"]["failed"] == 1
    issues = report["cases"][0]["issues"]
    assert any("audio" in issue for issue in issues), issues
    assert any("aspect" in issue for issue in issues), issues
