"""The .githooks/pre-commit secret scan, run for real in a throwaway repo.

Every fake secret below is assembled at runtime from a prefix + filler so
this file never carries a token-shaped literal (the hook scans it too).
On Windows the hook runs under Git for Windows' bash with the caller's PATH —
the environment where other MSYS tools shadowing Git's own (e.g. an msys64
``grep.exe``) re-expanded ``{n,}`` in regex arguments.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "pre-commit"


def _bash():
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            candidate = Path(git).resolve().parents[1] / "bin" / "bash.exe"
            if candidate.exists():
                return str(candidate)
        return None
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("git") is None, reason="needs git + bash")

SECRETS = {
    "google": "AIza" + "Ab_-9" * 7,                         # 35 chars
    "huggingface": "hf_" + "a1B2c3" * 6,
    "openai": "sk-" + "Z9y8X7" * 4,
    "elevenlabs": "sk_" + "0af3" * 6,
    "deepgram_kv": "DEEPGRAM_API_KEY=" + "q" * 40,
    "gemini_json": '"GEMINI_API_KEY": "' + "k" * 39 + '"',
    "cookie_file": "# Netscape " + "HTTP Cookie File",
    "token_header": "Token " + "ab12" * 10,
}


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / "README").write_text("base\n")
    _git(tmp_path, "add", "README")
    _git(tmp_path, "commit", "-q", "--no-verify", "-m", "base")
    return tmp_path


def _stage(repo, name, text, newline="\n"):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)
    _git(repo, "add", "--", name)


def _run_hook(repo, env=None):
    return subprocess.run([BASH, str(HOOK)], cwd=repo, capture_output=True,
                          text=True, env=env)


def test_clean_commit_passes_without_scanner_errors(repo):
    _stage(repo, "src/app.py", "print('hello')\nvalue = 'sk-short'\n")
    result = _run_hook(repo)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


@pytest.mark.parametrize("kind", sorted(SECRETS))
def test_each_secret_class_blocks_the_commit(repo, kind):
    _stage(repo, "config.txt", f"line one\nleak = {SECRETS[kind]}\n")
    result = _run_hook(repo)
    assert result.returncode == 1  # secret found (2 is reserved for scanner errors)
    assert "possible secret in config.txt" in result.stderr
    assert "No such file" not in result.stderr


def test_path_with_spaces_is_scanned(repo):
    _stage(repo, "my notes/key file.txt", f"x = {SECRETS['huggingface']}\n")
    result = _run_hook(repo)
    assert result.returncode != 0
    assert "possible secret in my notes/key file.txt" in result.stderr


def test_crlf_content_is_scanned(repo):
    _stage(repo, "win.txt", f"a\nk = {SECRETS['openai']}\n", newline="\r\n")
    assert _run_hook(repo).returncode != 0


def test_renamed_and_edited_file_is_scanned(repo):
    _stage(repo, "old.txt", "one\ntwo\nthree\nfour\nfive\n")
    _git(repo, "commit", "-q", "--no-verify", "-m", "old")
    _git(repo, "mv", "old.txt", "new.txt")
    _stage(repo, "new.txt", "one\ntwo\nthree\nfour\nfive\n" + SECRETS["elevenlabs"] + "\n")
    result = _run_hook(repo)
    assert result.returncode != 0
    assert "new.txt" in result.stderr


@pytest.mark.parametrize("path", [".env", "deploy/.env", "data/config.json",
                                  "data/cookies.txt", "deploy/cookies.txt"])
def test_secret_file_path_is_refused(repo, path):
    _stage(repo, path, "EMPTY=1\n")
    result = _run_hook(repo)
    assert result.returncode == 1
    assert f"secret file: {path}" in result.stderr


def test_gitignored_tmp_path_is_refused(repo):
    _stage(repo, "tmp/notes.txt", "scratch\n")
    result = _run_hook(repo)
    assert result.returncode == 1
    assert "refusing to commit from gitignored tmp/: tmp/notes.txt" in result.stderr


def test_scanner_failure_blocks_instead_of_passing(repo, tmp_path_factory):
    """A git that cannot produce the staged diff must not read as 'clean'."""
    _stage(repo, "a.txt", f"k = {SECRETS['google']}\n")
    # BASH_ENV runs before the hook: a `git` function beats any PATH entry
    # (Git for Windows' bash launcher prepends its own bin dirs to PATH).
    shim = tmp_path_factory.mktemp("shim") / "fail_diff.sh"
    shim.write_text(
        'git() { for a in "$@"; do [ "$a" = "-U0" ] && { echo boom >&2; return 3; }; done;'
        ' command git "$@"; }\n', newline="\n")
    env = dict(os.environ)
    env["BASH_ENV"] = str(shim).replace("\\", "/")
    result = _run_hook(repo, env=env)
    assert result.returncode == 2  # scan failed — never "clean", never "found"
    assert "scanner" in result.stderr
