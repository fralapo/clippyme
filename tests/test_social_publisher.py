"""Unit tests for social_publisher.py — pure-python paths only.

Avoids any real network call. Network code (ZernioClient) is tested by
mocking the requests.Session via monkeypatch.
"""
import os
import random
import sys
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import social_publisher as sp  # noqa: E402


# ---------------------------------------------------------------------------
# SmartScheduler — pure logic, no network
# ---------------------------------------------------------------------------


def _det_scheduler():
    """SmartScheduler with a deterministic RNG so tests don't flake."""
    s = sp.SmartScheduler()
    s.rng = random.Random(42)
    return s


def test_smartscheduler_picks_slot_in_free_window():
    s = _det_scheduler()
    day = date(2026, 4, 8)  # a Wednesday
    now = datetime(2026, 4, 8, 6, 0, 0)
    slot = s.find_slot(day, occupied=[], now=now)
    assert isinstance(slot, datetime)
    assert slot.date() == day
    # Wednesday windows are (7,11) and (14,22) — slot must be inside one
    in_window = (7 <= slot.hour < 11) or (14 <= slot.hour < 22)
    assert in_window, f"slot {slot} not in any wednesday window"


def test_smartscheduler_respects_min_gap():
    s = _det_scheduler()
    s.min_gap_seconds = 3600  # 1 hour
    day = date(2026, 4, 8)
    now = datetime(2026, 4, 8, 6, 0, 0)
    occupied = [datetime(2026, 4, 8, 9, 0), datetime(2026, 4, 8, 16, 0)]
    slot = s.find_slot(day, occupied=occupied, now=now)
    for o in occupied:
        assert abs((slot - o).total_seconds()) >= 3600


def test_smartscheduler_skips_past_times():
    s = _det_scheduler()
    day = date(2026, 4, 8)
    # It's already 7pm, so 'now' is past most of Wednesday's first window
    now = datetime(2026, 4, 8, 19, 0, 0)
    slot = s.find_slot(day, occupied=[], now=now)
    assert slot > now


def test_smartscheduler_fallback_when_overcrowded():
    s = _det_scheduler()
    s.min_gap_seconds = 60  # very tight
    day = date(2026, 4, 8)
    now = datetime(2026, 4, 8, 6, 0, 0)
    # Saturate every hour
    occupied = [datetime(2026, 4, 8, h, 0) for h in range(7, 23)]
    slot = s.find_slot(day, occupied=occupied, now=now)
    # The fallback returns *something* even when no clean slot is available
    assert isinstance(slot, datetime)
    assert slot.date() == day


# ---------------------------------------------------------------------------
# publish_clip — input validation
# ---------------------------------------------------------------------------


def test_publish_clip_rejects_missing_file():
    with pytest.raises(ValueError, match="clip not found"):
        sp.publish_clip(
            api_key="sk_test",
            clip_path="/nonexistent/clip.mp4",
            title="t", caption="c",
            platform_targets=[{"platform": "tiktok", "accountId": "x"}],
        )


def test_publish_clip_rejects_empty_platforms(tmp_path):
    fake_clip = tmp_path / "clip.mp4"
    fake_clip.write_bytes(b"\x00" * 100)
    with pytest.raises(ValueError, match="at least one platform"):
        sp.publish_clip(
            api_key="sk_test",
            clip_path=str(fake_clip),
            title="t", caption="c",
            platform_targets=[],
        )


def test_publish_clip_rejects_platform_target_without_account_id(tmp_path):
    fake_clip = tmp_path / "clip.mp4"
    fake_clip.write_bytes(b"\x00" * 100)
    with pytest.raises(ValueError, match="missing 'accountId'"):
        sp.publish_clip(
            api_key="sk_test",
            clip_path=str(fake_clip),
            title="t", caption="c",
            platform_targets=[{"platform": "tiktok"}],
        )


def test_publish_clip_rejects_unknown_schedule_mode(tmp_path):
    fake_clip = tmp_path / "clip.mp4"
    fake_clip.write_bytes(b"\x00" * 100)
    with pytest.raises(ValueError, match="unknown schedule_mode"):
        sp.publish_clip(
            api_key="sk_test",
            clip_path=str(fake_clip),
            title="t", caption="c",
            platform_targets=[{"platform": "tiktok", "accountId": "x"}],
            schedule_mode="lunch",
        )


def test_publish_clip_manual_mode_requires_scheduled_for(tmp_path):
    fake_clip = tmp_path / "clip.mp4"
    fake_clip.write_bytes(b"\x00" * 100)
    with pytest.raises(ValueError, match="manual.*requires scheduled_for"):
        sp.publish_clip(
            api_key="sk_test",
            clip_path=str(fake_clip),
            title="t", caption="c",
            platform_targets=[{"platform": "tiktok", "accountId": "x"}],
            schedule_mode="manual",
        )


# ---------------------------------------------------------------------------
# ZernioClient — network mocked end-to-end
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text

    def json(self):
        return self._json


def test_zernio_client_requires_api_key():
    with pytest.raises(ValueError):
        sp.ZernioClient(api_key="")


def test_zernio_client_request_calls_session(monkeypatch):
    client = sp.ZernioClient(api_key="sk_test")
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _FakeResponse(200, {"posts": [{"_id": "abc"}]})

    monkeypatch.setattr(client._session, "request", fake_request)
    posts = client.list_scheduled_posts("2026-04-08", "2026-04-08")
    assert posts == [{"_id": "abc"}]
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/posts")


def test_zernio_client_raises_on_http_error(monkeypatch):
    client = sp.ZernioClient(api_key="sk_test")

    def fake_request(method, url, **kwargs):
        return _FakeResponse(401, text="Unauthorized")

    monkeypatch.setattr(client._session, "request", fake_request)
    with pytest.raises(sp.ZernioError) as exc:
        client.list_accounts()
    assert exc.value.status_code == 401


def test_zernio_client_presign_payload(monkeypatch):
    client = sp.ZernioClient(api_key="sk_test")
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200, {
            "uploadUrl": "https://upload.example.com/x",
            "publicUrl": "https://media.example.com/x.mp4",
        })

    monkeypatch.setattr(client._session, "request", fake_request)
    res = client.presign_upload("clip.mp4", "video/mp4", size_bytes=12345)
    assert res["uploadUrl"]
    assert captured["json"] == {"filename": "clip.mp4", "contentType": "video/mp4", "size": 12345}
