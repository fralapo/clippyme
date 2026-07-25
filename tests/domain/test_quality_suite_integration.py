import json
import shutil
import subprocess

import pytest

from clippyme.pipeline.quality_suite import run_manifest


pytestmark = pytest.mark.integration


def test_synthetic_vertical_clip_passes_real_quality_suite(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe unavailable")

    clip = tmp_path / "synthetic-vertical.mp4"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
        "-t", "2", "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(clip),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=60)

    manifest = tmp_path / "quality.json"
    manifest.write_text(json.dumps({
        "cases": [{
            "name": "synthetic-vertical",
            "path": clip.name,
            "expected_duration": 2.0,
            "duration_tolerance": 0.25,
            "expected_aspect": "9:16",
            "min_size_bytes": 10_000,
            "max_black_ratio": 0.05,
            "max_freeze_ratio": 0.1,
            "allow_warnings": True,
        }],
    }), encoding="utf-8")

    result = run_manifest(str(manifest))
    assert result["summary"]["total"] == 1
    assert result["summary"]["failed"] == 0
    case = result["cases"][0]
    assert case["metrics"]["has_video"] is True
    assert case["metrics"]["has_audio"] is True
    assert case["metrics"]["width"] == 360
    assert case["metrics"]["height"] == 640
