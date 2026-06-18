"""Host tests for clippyme.domain.job_artifacts (pure filesystem helpers)."""
import json
import os

import pytest

from clippyme.domain import job_artifacts as ja


def _write_meta(job_dir, base, data):
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, f"{base}_metadata.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def test_find_job_metadata_path_returns_match(tmp_path):
    out = str(tmp_path)
    _write_meta(os.path.join(out, "job1"), "vid", {"a": 1})
    assert ja.find_job_metadata_path("job1", out).endswith("vid_metadata.json")


def test_find_job_metadata_path_returns_newest_when_multiple(tmp_path):
    """With >1 metadata file, the newest-by-mtime wins (consistent with
    job_results._pick_latest_metadata) — not filesystem glob order."""
    out = str(tmp_path)
    job_dir = os.path.join(out, "job1")
    old = _write_meta(job_dir, "old", {"v": "old"})
    new = _write_meta(job_dir, "new", {"v": "new"})
    # Make `new` strictly newer regardless of write timing.
    os.utime(old, (1, 1))
    os.utime(new, (10_000_000, 10_000_000))
    assert ja.find_job_metadata_path("job1", out) == new


def test_find_job_metadata_path_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ja.find_job_metadata_path("nope", str(tmp_path))


def test_load_job_metadata_roundtrip(tmp_path):
    out = str(tmp_path)
    _write_meta(os.path.join(out, "job1"), "vid", {"clips": [1, 2, 3]})
    path, data = ja.load_job_metadata("job1", out)
    assert data["clips"] == [1, 2, 3]
    assert os.path.basename(path) == "vid_metadata.json"


def test_save_job_metadata_atomic_roundtrip(tmp_path):
    meta_path = str(tmp_path / "vid_metadata.json")
    ja.save_job_metadata(meta_path, {"x": "y"})
    with open(meta_path) as f:
        assert json.load(f) == {"x": "y"}
    # tmp sidecar must not linger
    assert not os.path.exists(meta_path + ".tmp")


def test_save_job_metadata_cleans_tmp_on_serialization_failure(tmp_path):
    meta_path = str(tmp_path / "vid_metadata.json")

    class _Unserializable:
        pass

    with pytest.raises(TypeError):
        ja.save_job_metadata(meta_path, {"bad": _Unserializable()})
    # Failed write leaves neither a tmp nor a corrupt target file
    assert not os.path.exists(meta_path + ".tmp")
    assert not os.path.exists(meta_path)


def test_save_job_metadata_overwrite_preserves_old_on_failure(tmp_path):
    meta_path = str(tmp_path / "vid_metadata.json")
    ja.save_job_metadata(meta_path, {"v": 1})

    class _Bad:
        pass

    with pytest.raises(TypeError):
        ja.save_job_metadata(meta_path, {"v": _Bad()})
    # Atomic replace means the original survives a failed rewrite
    with open(meta_path) as f:
        assert json.load(f) == {"v": 1}


def test_relocate_root_job_artifacts_moves_metadata_into_job_dir(tmp_path):
    out = str(tmp_path)
    # main.py wrote metadata into output/ root instead of output/<job_id>/
    stray = os.path.join(out, "job9_vid_metadata.json")
    with open(stray, "w") as f:
        json.dump({"ok": True}, f)
    job_dir = os.path.join(out, "job9")

    assert ja.relocate_root_job_artifacts("job9", job_dir, out) is True
    assert os.path.exists(os.path.join(job_dir, "job9_vid_metadata.json"))
    assert not os.path.exists(stray)


def test_relocate_root_job_artifacts_no_match_returns_false(tmp_path):
    out = str(tmp_path)
    assert ja.relocate_root_job_artifacts("ghost", os.path.join(out, "ghost"), out) is False
