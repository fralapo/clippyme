#!/usr/bin/env python3
"""Offline ClippyMe state backup/restore (stdlib only).

Backup and restore MUST run with the backend stopped and no active writers.
Never stops the running service or overwrites state automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT_ITEMS = (".env", "data", "output", "uploads")
MANIFEST = "clippyme-manifest.json"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_name(name: str) -> bool:
    pure = PurePosixPath(name)
    return (bool(name) and not name.startswith("/")
            and all(part not in ("", ".", "..") for part in name.split("/"))
            and pure.parts[0] in (*ROOT_ITEMS, MANIFEST))


def _gather(root: Path):
    items = []
    for stem in ROOT_ITEMS:
        top = root / stem
        if not top.exists() and not top.is_symlink():
            continue
        if top.is_symlink():
            raise ValueError(f"Refusing symlink: {top}")
        if top.is_file():
            items.append((top, stem))
            continue
        for folder, dirs, files in os.walk(top, followlinks=False):
            for name in (*dirs, *files):
                item = Path(folder) / name
                if item.is_symlink():
                    raise ValueError(f"Refusing symlink: {item}")
                if item.is_file():
                    items.append((item, item.relative_to(root).as_posix()))
    return items


def backup(root: Path, archive: Path) -> dict:
    root = root.resolve()
    archive = archive.resolve()
    if not root.is_dir():
        raise ValueError(f"Root is not a directory: {root}")
    if archive.exists():
        raise FileExistsError(f"Refusing overwrite of existing archive: {archive}")
    files = _gather(root)
    for stem in ("data", "output", "uploads"):
        if archive.is_relative_to(root / stem):
            raise ValueError("Backup archive cannot be inside an included folder")
    archive.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".clippyme-backup-", suffix=".tar.gz",
                                      dir=archive.parent)
    os.chmod(temp_name, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream, tarfile.open(fileobj=stream, mode="w:gz") as tar:
            manifest = {"version": 1, "files": {}}
            for path, name in files:
                manifest["files"][name] = {"size": path.stat().st_size, "sha256": _hash_file(path)}
                tar.add(path, arcname=name, recursive=False)
            raw = json.dumps(manifest, sort_keys=True).encode()
            info = tarfile.TarInfo(MANIFEST)
            info.mode = 0o600
            info.size = len(raw)
            from io import BytesIO
            tar.addfile(info, BytesIO(raw))
        os.replace(temp_name, archive)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)
    return manifest


def restore(root: Path, archive: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("Restore root must be an existing checkout directory")
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            if not _valid_name(member.name) or not member.isfile():
                raise ValueError(f"Unsafe archive member: {member.name}")
        indexed = {m.name: m for m in members}
        if len(indexed) != len(members) or MANIFEST not in indexed:
            raise ValueError("Missing manifest or duplicate members")
        raw = tar.extractfile(indexed[MANIFEST]).read()
        manifest = json.loads(raw)
        if manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict):
            raise ValueError("Unsupported manifest")
        saved = manifest["files"]
        if set(indexed) != set(saved) | {MANIFEST}:
            raise ValueError("Archive manifest does not match file list")
        for name, meta in saved.items():
            if not _valid_name(name) or name == MANIFEST:
                raise ValueError("Unsafe manifest path")
            if not isinstance(meta, dict) or not isinstance(meta.get("size"), int):
                raise ValueError("Invalid manifest size")
        # Never write on top of an existing configuration, job, or upload.
        for stem in ROOT_ITEMS:
            if (root / stem).exists() or (root / stem).is_symlink():
                raise FileExistsError(f"Restore requires empty destination: {root / stem}")
        staging = Path(tempfile.mkdtemp(prefix=".clippyme-restore-", dir=root))
        committed = []
        try:
            for name, meta in saved.items():
                destination = staging.joinpath(*PurePosixPath(name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source = tar.extractfile(indexed[name])
                if source is None:
                    raise ValueError("Missing archived file")
                with destination.open("xb") as target:
                    shutil.copyfileobj(source, target)
                os.chmod(destination, 0o600)
                if destination.stat().st_size != meta["size"] or _hash_file(destination) != meta["sha256"]:
                    raise ValueError(f"Checksum mismatch: {name}")
            for stem in ROOT_ITEMS:
                child = staging / stem
                if child.exists():
                    child.rename(root / stem)
                    committed.append(stem)
        except BaseException:
            for stem in reversed(committed):
                child = root / stem
                if child.is_dir():
                    shutil.rmtree(child)
                elif child.exists():
                    child.unlink()
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--confirm-stopped", action="store_true",
                        help="Confirm backend and live-monitor writers are stopped")
    options = parser.parse_args()
    if not options.confirm_stopped:
        parser.error("Refusing live backup/restore: stop the backend first and pass --confirm-stopped")
    outcome = backup(options.root, options.archive) if options.action == "backup" else restore(options.root, options.archive)
    print(f"{options.action} completed: {len(outcome['files'])} files verified")


if __name__ == "__main__":
    main()
