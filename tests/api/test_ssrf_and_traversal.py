"""Regression tests for the audit-remediation security guards.

Covers (all host-runnable, no heavy deps):
- schemas.validate_public_url — SSRF scheme/host guard on /api/process URLs
- url_utils.filename_from_video_url — path-traversal guard
- social_publisher._reject_internal_upload_url — presigned-PUT SSRF guard
"""
import pytest

from clippyme.api.schemas import validate_public_url
from clippyme.domain.url_utils import filename_from_video_url
from clippyme.integrations.social_publisher import (
    ZernioError,
    _reject_internal_upload_url,
)


# --- SSRF: process/batch URL validation -----------------------------------

@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "http://127.0.0.1/x",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://10.0.0.5/internal",
    "http://[::1]/x",
    "javascript:alert(1)",
])
def test_validate_public_url_rejects_internal_and_bad_schemes(bad):
    with pytest.raises(ValueError):
        validate_public_url(bad)


@pytest.mark.parametrize("good", [
    "https://www.youtube.com/watch?v=abc",
    "http://8.8.8.8/video.mp4",  # public IP literal, no DNS needed
])
def test_validate_public_url_accepts_public(good):
    assert validate_public_url(good) == good


# --- Path traversal: filename extraction ----------------------------------

@pytest.mark.parametrize("url,expected", [
    ("/videos/abc/clip_1.mp4", "clip_1.mp4"),
    ("/videos/abc/clip_1.mp4?v=123", "clip_1.mp4"),
    ("/videos/abc/..", ""),            # bare parent ref → blocked
    ("/videos/abc/.", ""),             # current dir → blocked
    ("", ""),
    (None, ""),
])
def test_filename_from_video_url_blocks_traversal(url, expected):
    assert filename_from_video_url(url) == expected


# --- SSRF: presigned upload URL -------------------------------------------

@pytest.mark.parametrize("bad", [
    "http://s3.amazonaws.com/x",       # non-https
    "https://127.0.0.1/x",
    "https://169.254.169.254/x",
    "https://10.1.2.3/x",
])
def test_reject_internal_upload_url(bad):
    with pytest.raises(ZernioError):
        _reject_internal_upload_url(bad)


def test_accept_public_https_upload_url():
    # Public IP literal over https — must not raise.
    _reject_internal_upload_url("https://13.226.1.1/bucket/key")


# --- Security response headers ---------------------------------------------

def test_security_headers_present():
    from fastapi.testclient import TestClient

    from clippyme.api import app as app_module
    tc = TestClient(app_module.app)
    r = tc.get("/api/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "default-src 'none'" in r.headers.get("content-security-policy", "")
