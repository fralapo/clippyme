"""Tests for clippyme.integrations.social_publisher.

Covers the two pure, network-free pieces:
- _safe_zernio_base_url() — the SSRF-by-configuration guard on ZERNIO_BASE_URL.
- SmartScheduler.find_slot() — the deterministic (seeded) prime-time slot picker.
"""
import random
from datetime import date, datetime, time, timedelta

import pytest

from clippyme.integrations import social_publisher as sp
from clippyme.integrations.social_publisher import SmartScheduler


DEFAULT = "https://zernio.com/api/v1"


# --- _scrub_secrets (key-in-error-body redaction, M6) ----------------------

def test_scrub_secrets_redacts_own_api_key():
    client = sp.ZernioClient("sk_live_supersecret_abc123")
    body = '{"error":"invalid key sk_live_supersecret_abc123","platform":"youtube"}'
    scrubbed = client._scrub_secrets(body)
    assert "sk_live_supersecret_abc123" not in scrubbed
    assert "***REDACTED***" in scrubbed
    # Platform info preserved so the batch-publish 429 parser still works.
    assert '"platform":"youtube"' in scrubbed


def test_scrub_secrets_redacts_bearer_token():
    client = sp.ZernioClient("unrelated-key")
    body = "Authorization: Bearer abc.DEF-123_xyz failed"
    scrubbed = client._scrub_secrets(body)
    assert "abc.DEF-123_xyz" not in scrubbed
    assert "Bearer ***REDACTED***" in scrubbed


def test_scrub_secrets_handles_empty():
    client = sp.ZernioClient("k")
    assert client._scrub_secrets("") == ""


# --- _safe_zernio_base_url (SSRF guard) ------------------------------------

def test_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("ZERNIO_BASE_URL", raising=False)
    assert sp._safe_zernio_base_url() == DEFAULT


def test_honours_official_https_apex(monkeypatch):
    monkeypatch.setenv("ZERNIO_BASE_URL", "https://zernio.com/api/v2")
    assert sp._safe_zernio_base_url() == "https://zernio.com/api/v2"


def test_honours_official_subdomain(monkeypatch):
    monkeypatch.setenv("ZERNIO_BASE_URL", "https://eu.zernio.com/api/v1")
    assert sp._safe_zernio_base_url() == "https://eu.zernio.com/api/v1"


def test_rejects_non_https_scheme(monkeypatch):
    # http:// to the official host is still rejected — downgrade attack.
    monkeypatch.setenv("ZERNIO_BASE_URL", "http://zernio.com/api/v1")
    assert sp._safe_zernio_base_url() == DEFAULT


def test_rejects_foreign_host(monkeypatch):
    monkeypatch.setenv("ZERNIO_BASE_URL", "https://attacker.example.com/api/v1")
    assert sp._safe_zernio_base_url() == DEFAULT


def test_rejects_lookalike_suffix_host(monkeypatch):
    # 'notzernio.com' must NOT match the '.zernio.com' subdomain rule.
    monkeypatch.setenv("ZERNIO_BASE_URL", "https://evilzernio.com/api/v1")
    assert sp._safe_zernio_base_url() == DEFAULT


def test_empty_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ZERNIO_BASE_URL", "   ")
    assert sp._safe_zernio_base_url() == DEFAULT


# --- SmartScheduler --------------------------------------------------------

def _scheduler(seed=42):
    return SmartScheduler(rng=random.Random(seed))


def test_find_slot_lands_in_a_prime_time_window():
    day = date(2026, 6, 1)
    s = _scheduler()
    now = datetime.combine(day, time(0, 0))
    slot = s.find_slot(day, occupied=[], now=now)
    assert slot.date() == day
    windows = s._windows_for(day.weekday())
    assert any(w[0] <= slot.hour < w[1] for w in windows), \
        f"hour {slot.hour} not in any window {windows}"


def test_find_slot_is_deterministic_under_same_seed():
    day = date(2026, 6, 1)
    now = datetime.combine(day, time(0, 0))
    a = _scheduler(7).find_slot(day, occupied=[], now=now)
    b = _scheduler(7).find_slot(day, occupied=[], now=now)
    assert a == b


def test_find_slot_is_in_the_future():
    day = date(2026, 6, 1)
    now = datetime.combine(day, time(0, 0))
    slot = _scheduler().find_slot(day, occupied=[], now=now)
    assert slot > now


def test_is_window_free_detects_occupancy():
    day = date(2026, 6, 1)
    s = _scheduler()
    window = (12, 14)
    occupied = [datetime.combine(day, time(13, 0))]
    assert s._is_window_free(day, window, occupied) is False
    assert s._is_window_free(day, (18, 21), occupied) is True


def test_find_slot_last_resort_never_returns_past(monkeypatch):
    # Regression: step 3 (fully-occupied day fallback) picked a random time
    # inside a window with no `> now` guard — late in the day it could
    # schedule a publish at a time already gone.
    day = date(2026, 6, 1)  # Monday: windows (12,14) and (18,21)
    now = datetime.combine(day, time(20, 30))
    # Occupy every 15-minute step so steps 1 and 2 both fail.
    occupied = [datetime.combine(day, time(7, 0)) + timedelta(minutes=m)
                for m in range(0, 16 * 60, 15)]
    s = SmartScheduler(rng=random.Random(3), min_gap_seconds=0)
    # min_gap 0 would let step 2 succeed; occupy makes windows non-free but
    # gap_ok trivially true — so force step 3 by making _gap_ok fail instead.
    monkeypatch.setattr(s, "_gap_ok", lambda candidate, occ: False)
    for seed in range(20):
        s.rng = random.Random(seed)
        assert s.find_slot(day, occupied=occupied, now=now) > now


def test_find_slot_day_fully_past_falls_back_after_now():
    # The whole day (and all its windows) is already behind `now`: the
    # fallback must still be usable — now + min_gap, never yesterday.
    day = date(2026, 6, 1)
    now = datetime.combine(day, time(23, 30))
    s = SmartScheduler(rng=random.Random(5), min_gap_seconds=5400)
    occupied = [datetime.combine(day, time(h, 0)) for h in range(7, 23)]
    slot = s.find_slot(day, occupied=occupied, now=now)
    assert slot > now


def test_gap_ok_enforces_minimum_gap():
    s = SmartScheduler(rng=random.Random(1), min_gap_seconds=5400)  # 90 min
    base = datetime(2026, 6, 1, 12, 0)
    occupied = [base]
    assert s._gap_ok(base.replace(hour=14), occupied) is True       # 2h away
    assert s._gap_ok(base.replace(minute=30), occupied) is False    # 30 min away


# --- publish_clip manual-mode timestamp validation -------------------------

def _guard_network(monkeypatch):
    """Make any ZernioClient use blow up loudly, so a test that reaches the
    network instead of failing validation is unambiguous (and never hits the
    real API)."""
    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("validation should have rejected input before any network call")
    monkeypatch.setattr(sp, "ZernioClient", _Boom)


def test_manual_mode_rejects_non_iso_scheduled_for(monkeypatch, tmp_path):
    _guard_network(monkeypatch)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    with pytest.raises(ValueError, match="(?i)iso"):
        sp.publish_clip(
            api_key="sk_test",
            clip_path=str(clip),
            title="t",
            caption="c",
            platform_targets=[{"platform": "tiktok", "accountId": "acc1"}],
            schedule_mode="manual",
            scheduled_for="not-a-timestamp",
        )


def test_manual_mode_accepts_valid_iso_scheduled_for(monkeypatch, tmp_path):
    # A well-formed ISO 8601 timestamp must pass validation (it then proceeds
    # to the network layer, which our guard turns into a recognisable error —
    # proving validation itself did NOT reject it).
    _guard_network(monkeypatch)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    with pytest.raises(AssertionError, match="network"):
        sp.publish_clip(
            api_key="sk_test",
            clip_path=str(clip),
            title="t",
            caption="c",
            platform_targets=[{"platform": "tiktok", "accountId": "acc1"}],
            schedule_mode="manual",
            scheduled_for="2026-06-01T12:30:00",
        )
