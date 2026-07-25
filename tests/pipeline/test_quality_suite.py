import json

import pytest

from clippyme.pipeline import quality_suite


def _manifest(tmp_path, cases):
    path = tmp_path / "quality.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return path


def test_manifest_suite_passes_clean_case(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    manifest = _manifest(tmp_path, [{
        "name": "vertical",
        "path": "clip.mp4",
        "expected_duration": 10,
        "duration_tolerance": 0.5,
        "expected_aspect": "9:16",
        "allow_warnings": False,
    }])
    monkeypatch.setattr(quality_suite, "inspect_clip", lambda *args, **kwargs: {
        "critical": False,
        "issues": [],
        "warnings": [],
        "metrics": {
            "duration": 10.2,
            "size_bytes": 1_000_000,
            "black_ratio": 0.01,
            "freeze_ratio": 0.02,
            "mean_volume_db": -20,
            "max_volume_db": -1,
        },
    })
    result = quality_suite.run_manifest(str(manifest))
    assert result["summary"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "critical": 0,
        "with_warnings": 0,
    }
    assert result["cases"][0]["passed"] is True


def test_explicit_baseline_mismatch_fails(monkeypatch, tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"video")
    manifest = _manifest(tmp_path, [{
        "path": "clip.mp4",
        "expected_duration": 10,
        "duration_tolerance": 0.1,
        "max_black_ratio": 0.2,
    }])
    monkeypatch.setattr(quality_suite, "inspect_clip", lambda *args, **kwargs: {
        "critical": False,
        "issues": [],
        "warnings": [],
        "metrics": {"duration": 11, "black_ratio": 0.5},
    })
    case = quality_suite.run_manifest(str(manifest))["cases"][0]
    assert case["passed"] is False
    assert case["critical"] is True
    assert len(case["issues"]) == 2


def test_disallowed_warning_fails_without_becoming_critical(monkeypatch, tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"video")
    manifest = _manifest(tmp_path, [{
        "path": "clip.mp4",
        "allow_warnings": False,
    }])
    monkeypatch.setattr(quality_suite, "inspect_clip", lambda *args, **kwargs: {
        "critical": False,
        "issues": [],
        "warnings": ["audio is quiet"],
        "metrics": {},
    })
    case = quality_suite.run_manifest(str(manifest))["cases"][0]
    assert case["passed"] is False
    assert case["critical"] is False


def test_manifest_rejects_path_traversal(tmp_path):
    manifest = _manifest(tmp_path, [{"path": "../outside.mp4"}])
    with pytest.raises(quality_suite.QualityManifestError, match="escapes"):
        quality_suite.run_manifest(str(manifest))


def test_main_writes_report_and_returns_failure(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path, [{"path": "clip.mp4"}])
    output = tmp_path / "report.json"
    monkeypatch.setattr(quality_suite, "run_manifest", lambda *args, **kwargs: {
        "schema": 1,
        "manifest": "quality.json",
        "summary": {"total": 1, "passed": 0, "failed": 1, "critical": 1, "with_warnings": 0},
        "cases": [{
            "name": "broken", "passed": False, "critical": True,
            "issues": ["no video"], "warnings": [], "allow_warnings": True,
        }],
    })
    assert quality_suite.main([str(manifest), "--output", str(output)]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["failed"] == 1
