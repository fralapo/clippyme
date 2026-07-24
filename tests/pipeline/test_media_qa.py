import json
import subprocess

from clippyme.pipeline import media_qa


def test_probe_media_normalizes_streams(monkeypatch, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * 20_000)
    payload = {
        "format": {"duration": "12.5"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
            },
        ],
    }
    monkeypatch.setattr(
        media_qa.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            json.dumps(payload),
            "",
        ),
    )
    report = media_qa.probe_media(str(path))
    assert report["duration"] == 12.5
    assert report["has_video"] and report["has_audio"]
    assert (report["width"], report["height"], report["fps"]) == (1080, 1920, 30.0)


def test_probe_failure_is_a_soft_report(monkeypatch, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * 20_000)
    monkeypatch.setattr(
        media_qa.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "bad media"),
    )
    report = media_qa.probe_media(str(path))
    assert report["has_video"] is False
    assert "bad media" in report["probe_error"]


def test_signal_parser_extracts_black_freeze_and_volume(monkeypatch):
    stderr = """
    black_start:0 black_end:2 black_duration:2
    black_start:5 black_end:6 black_duration:1
    lavfi.freezedetect.freeze_duration: 4.0
    mean_volume: -22.4 dB
    max_volume: -0.4 dB
    """
    monkeypatch.setattr(
        media_qa.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", stderr),
    )
    report = media_qa.inspect_signal("clip.mp4", 10.0)
    assert report["black_seconds"] == 3.0
    assert report["black_ratio"] == 0.3
    assert report["freeze_ratio"] == 0.4
    assert report["mean_volume_db"] == -22.4
    assert report["max_volume_db"] == -0.4
    assert report["signal_error"] is None


def test_failed_signal_pass_keeps_partial_metrics_and_error(monkeypatch):
    stderr = """
    black_start:0 black_end:2 black_duration:2
    Error initializing filter 'freezedetect'
    """
    monkeypatch.setattr(
        media_qa.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", stderr),
    )
    report = media_qa.inspect_signal("clip.mp4", 10.0)
    assert report["black_seconds"] == 2.0
    assert report["black_ratio"] == 0.2
    assert report["freeze_seconds"] is None
    assert report["freeze_ratio"] is None
    assert "freezedetect" in report["signal_error"]


def test_failed_signal_pass_does_not_fabricate_zeroes(monkeypatch):
    monkeypatch.setattr(
        media_qa.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            "",
            "filter unavailable",
        ),
    )
    report = media_qa.inspect_signal("clip.mp4", 10.0)
    assert report["black_seconds"] is None
    assert report["freeze_seconds"] is None
    assert "filter unavailable" in report["signal_error"]


def test_inspect_clip_marks_wrong_aspect_critical(monkeypatch):
    monkeypatch.setattr(
        media_qa,
        "probe_media",
        lambda path: {
            "duration": 10.0,
            "has_video": True,
            "has_audio": True,
            "size_bytes": 1_000_000,
            "width": 1920,
            "height": 1080,
        },
    )
    monkeypatch.setattr(media_qa, "inspect_signal", lambda path, duration: {})
    report = media_qa.inspect_clip(
        "clip.mp4",
        expected_duration=10.0,
        expected_aspect=9 / 16,
    )
    assert report["critical"] is True
    assert any("aspect" in issue for issue in report["issues"])
