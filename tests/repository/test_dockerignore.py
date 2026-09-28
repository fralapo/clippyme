"""The backend image does ``COPY . .`` — whatever the build context holds
lands in an image layer. Observe the real context through BuildKit itself
(``FROM scratch`` + ``COPY . /`` exported to a local dir) on a fixture tree
filtered by the repo's .dockerignore: no reimplementation of the matcher.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_WIN_DOCKER = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"


def _docker():
    exe = shutil.which("docker") or (_WIN_DOCKER if os.path.exists(_WIN_DOCKER) else None)
    if exe is None:
        return None
    try:
        ok = subprocess.run([exe, "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return None
    return exe if ok else None


DOCKER = _docker()
pytestmark = pytest.mark.skipif(DOCKER is None, reason="needs a running Docker daemon")

# Must never reach the image: local secrets, scratch space, extra checkouts,
# agent/tool state and generated caches.
EXCLUDED = [
    ".env",
    ".env.local",
    ".env.production",
    "tmp/scratch.mp4.txt",
    ".worktrees/manual-publish/src/clippyme/x.py",
    ".claude/settings.local.json",
    ".codex/state",
    ".agents/state",
    ".superpowers/state",
    ".local/state",
    "graphify-out/graph.json",
    "tests/graphify-out/graph.json",
    ".ruff_cache/x",
    "data/config.json",
]
# Needed by the Dockerfile (pip install -e ., entrypoint, fonts at runtime).
REQUIRED = [
    "src/clippyme/__init__.py",
    "pyproject.toml",
    "requirements.lock",
    "requirements.txt",
    "requirements-runtime-tools.txt",
    "docker-entrypoint.sh",
    "fonts/Font.ttf",
    "LICENSE",
    ".env.example",
]


def test_build_context_keeps_required_files_and_drops_local_ones(tmp_path):
    ctx = tmp_path / "ctx"
    for rel in EXCLUDED + REQUIRED:
        path = ctx / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n")
    shutil.copy(REPO / ".dockerignore", ctx / ".dockerignore")
    out = tmp_path / "out"
    result = subprocess.run(
        [DOCKER, "build", "-q", "-f", "-", "--output", f"type=local,dest={out}", str(ctx)],
        input="FROM scratch\nCOPY . /\n", capture_output=True, text=True,
        env={**os.environ, "DOCKER_BUILDKIT": "1"}, timeout=300,
    )
    assert result.returncode == 0, result.stderr
    landed = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert sorted(set(EXCLUDED) & landed) == []
    assert sorted(set(REQUIRED) - landed) == []
