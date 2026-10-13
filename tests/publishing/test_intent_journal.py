"""Durable publication receipts and a hard idempotency window guard."""
import json
import time

import pytest

from clippyme.core.errors import ConflictError
from clippyme.publishing import intent_journal as j

INTENT = "5f0c1d2e3a4b4c6d8e9f0a1b2c3d4e5f"


def test_pending_then_confirmed_replays_without_recreating(tmp_path):
    entry = j.begin_intent(str(tmp_path), 2, INTENT, now=100)
    assert entry["state"] == "pending"
    assert j.begin_intent(str(tmp_path), 2, INTENT, now=200) == entry
    receipt = {"post_id": "known", "status": "scheduled", "scheduled_for": "2030-01-01T00:00:00Z"}
    j.confirm_intent(str(tmp_path), 2, INTENT, receipt)
    accepted = j.read_intent(str(tmp_path), 2, INTENT)
    assert accepted["state"] == "confirmed"
    assert accepted["result"]["post_id"] == "known"
    assert (tmp_path / j.FILENAME).stat().st_mode & 0o777 == 0o600


def test_uncertain_intent_cannot_be_blindly_replayed_after_provider_key_window(tmp_path):
    j.begin_intent(str(tmp_path), 0, INTENT, now=100)
    with pytest.raises(ConflictError, match="Zernio"):
        j.begin_intent(str(tmp_path), 0, INTENT,
                       now=100 + j.REPLAY_WINDOW_GUARD_SECONDS)
    # No fresh key was generated and no accepted receipt fabricated.
    assert j.read_intent(str(tmp_path), 0, INTENT)["state"] == "pending"


def test_rejection_is_not_a_false_acceptance(tmp_path):
    j.begin_intent(str(tmp_path), 0, INTENT)
    j.reject_intent(str(tmp_path), 0, INTENT)
    assert j.read_intent(str(tmp_path), 0, INTENT) is None


def test_corrupted_ledger_fails_closed(tmp_path):
    (tmp_path / j.FILENAME).write_text("{broken")
    with pytest.raises(ConflictError):
        j.begin_intent(str(tmp_path), 0, INTENT)


def test_intent_ledger_never_stores_keys_or_caption(tmp_path):
    j.begin_intent(str(tmp_path), 0, INTENT)
    j.confirm_intent(str(tmp_path), 0, INTENT, {"post_id": "post1"})
    raw = (tmp_path / j.FILENAME).read_text()
    assert "api_key" not in raw and "caption" not in raw
