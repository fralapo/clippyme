"""Transcript cache (URL-hash keyed, TTL-pruned).

Extracted from ``pipeline.main`` as a first, dependency-light step of breaking
up that 2216-line module: this unit is pure stdlib (no cv2/torch/yt-dlp), so it
imports and unit-tests on the host. The heavier pipeline stages stay in
``main`` until they can be split + verified against the Docker integration
suite.

Transcripts are keyed by ``SHA256(url)[:16]`` and stored as JSON under
``data/cache/``. Entries older than ``CACHE_TTL_DAYS`` are pruned on read.
"""
import hashlib
import json
import os
import time

# Resolve to an absolute path anchored at the repo root (../../../data/cache
# from this file), so transcripts are never written outside the data tree when
# the process is launched from an unexpected CWD. An explicit env override is
# honoured for non-standard install prefixes.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
CACHE_DIR = os.environ.get("CLIPPYME_CACHE_DIR") or os.path.join(_REPO_ROOT, "data", "cache")
CACHE_TTL_DAYS = 7


def get_cache_path(url: str) -> str:
    """Return cache file path for a URL, based on SHA256 hash."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{url_hash}_transcript.json")


def load_cached_transcript(url: str):
    """Load a cached transcript if it exists and is not expired (else None)."""
    cache_path = get_cache_path(url)
    if not os.path.exists(cache_path):
        return None
    try:
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime > CACHE_TTL_DAYS * 86400:
            os.remove(cache_path)
            return None
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"📦 Loaded cached transcript ({os.path.basename(cache_path)})")
        return data
    except Exception:
        return None


def save_transcript_cache(url: str, transcript) -> None:
    """Save transcript to cache atomically (tmp + replace)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = get_cache_path(url)
    tmp_path = cache_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(transcript, f)
        os.replace(tmp_path, cache_path)
        print(f"💾 Transcript cached ({os.path.basename(cache_path)})")
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        print(f"⚠️  Failed to cache transcript: {e}")
