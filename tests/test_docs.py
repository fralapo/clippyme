"""Documentation stays navigable and in step with the code.

* every relative Markdown link (and ``#anchor``) in a tracked doc resolves;
* every environment variable the backend reads is in the configuration
  reference, and so is every variable ``.env.example`` offers.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CONFIG_REF = REPO / "docs" / "reference" / "configuration.md"

# Passed from the backend to the pipeline subprocess, not operator settings.
INTERNAL_ENV = {"CLIPPYME_JOB_ID", "CLIPPYME_ATTEMPT", "CLIPPYME_LANGUAGE"}

_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"")
_ENV_READ = re.compile(
    r"(?:getenv|environ\.get|environ\[|_float|_enabled|_nonnegative_int|_env_int)"
    r"\(?\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']")


def _markdown_files():
    try:
        # safe.directory: a bind-mounted checkout owned by another user (Docker).
        out = subprocess.run(["git", "-c", f"safe.directory={REPO.as_posix()}", "ls-files",
                              "-co", "--exclude-standard", "*.md"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout
        return [REPO / p for p in out.splitlines() if (REPO / p).exists()]
    except (OSError, subprocess.CalledProcessError):
        # No git: the project's own documentation only, never tool caches.
        return sorted({*REPO.glob("*.md"), *REPO.glob("docs/**/*.md"),
                       *REPO.glob("dashboard/*.md"), *REPO.glob(".github/*.md")})


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces → '-'."""
    text = re.sub(r"[`*_]|<[^>]+>", "", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _anchors(path: Path) -> set:
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    return {_slug(m) for m in re.findall(r"^#{1,6}\s+(.+)$", text, flags=re.M)}


def _links(path: Path):
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    for match in _LINK.finditer(text):
        target = match.group(1) or match.group(2)
        if not re.match(r"^[a-z][a-z0-9+.-]*:", target, flags=re.I):
            yield target


@pytest.mark.parametrize("doc", _markdown_files(), ids=lambda p: p.relative_to(REPO).as_posix())
def test_relative_links_resolve(doc):
    broken = []
    for target in _links(doc):
        file_part, _, anchor = target.partition("#")
        dest = (doc.parent / file_part).resolve() if file_part else doc
        if not dest.exists():
            broken.append(target)
        elif anchor and dest.suffix == ".md" and anchor not in _anchors(dest):
            broken.append(target)
    assert broken == []


def _documented() -> str:
    return CONFIG_REF.read_text(encoding="utf-8")


def test_every_env_var_read_by_the_code_is_documented():
    read = set()
    for src in (REPO / "src" / "clippyme").rglob("*.py"):
        read |= set(_ENV_READ.findall(src.read_text(encoding="utf-8")))
    reference = _documented()
    missing = sorted(n for n in read - INTERNAL_ENV if f"`{n}`" not in reference)
    assert missing == []


def test_every_env_example_variable_is_documented():
    names = re.findall(r"^#?\s*([A-Z][A-Z0-9_]{2,})=", (REPO / ".env.example").read_text(encoding="utf-8"),
                       flags=re.M)
    reference = _documented()
    assert sorted(n for n in set(names) if f"`{n}`" not in reference) == []
