"""Offline state backups are lossless and refuse unsafe archives."""
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_clippyme.py"
spec = importlib.util.spec_from_file_location("clippyme_backup_script", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_backup_roundtrip_preserves_config_journal_and_video(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "data").mkdir()
    (root / "output").mkdir()
    (root / "uploads").mkdir()
    (root / ".env").write_text("SECRET=example")
    (root / "data" / "jobs_journal.json").write_text('{"jobs":[]}')
    (root / "data" / "config.json").write_text('{"zernio":{}}')
    (root / "output" / "clip.mp4").write_bytes(b"binary clips")
    (root / "uploads" / "source.mp4").write_bytes(b"upload")
    archive = tmp_path / "out.tar.gz"
    manifest = mod.backup(root, archive)
    assert archive.stat().st_mode & 0o777 == 0o600
    assert len(manifest["files"]) == 5
    fresh = tmp_path / "restore"
    fresh.mkdir()
    mod.restore(fresh, archive)
    assert (fresh / ".env").read_text() == "SECRET=example"
    assert (fresh / "output" / "clip.mp4").read_bytes() == b"binary clips"
    with pytest.raises(FileExistsError):
        mod.restore(fresh, archive)


def test_backup_refuses_symlinks_and_overwrite(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "data").mkdir()
    (root / "data" / "bad").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        mod.backup(root, tmp_path / "backup.tar.gz")
    (root / "data" / "bad").unlink()
    mod.backup(root, tmp_path / "backup.tar.gz")
    with pytest.raises(FileExistsError):
        mod.backup(root, tmp_path / "backup.tar.gz")


def test_restore_refuses_traversal_members_before_writing(tmp_path):
    archive = tmp_path / "attack.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        content = b"pwned"
        info = tarfile.TarInfo("data/../../attacker.txt")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    dest = tmp_path / "fresh"
    dest.mkdir()
    with pytest.raises(ValueError, match="Unsafe archive member"):
        mod.restore(dest, archive)
    assert not (tmp_path / "attacker.txt").exists()


def test_restore_rejects_checksum_mismatch_and_does_not_commit(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    manifest = {"version": 1, "files": {"data/config.json": {"size": 3, "sha256": "0" * 64}}}
    with tarfile.open(archive, "w:gz") as tar:
        file_content = b"abc"
        info = tarfile.TarInfo("data/config.json")
        info.size = len(file_content)
        tar.addfile(info, io.BytesIO(file_content))
        raw = json.dumps(manifest).encode()
        info = tarfile.TarInfo(mod.MANIFEST)
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
    dest = tmp_path / "fresh"
    dest.mkdir()
    with pytest.raises(ValueError, match="Checksum mismatch"):
        mod.restore(dest, archive)
    assert not (dest / "data").exists()
