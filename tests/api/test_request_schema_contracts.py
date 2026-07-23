"""Regression tests for request-schema/domain contract mismatches."""
import pytest
from pydantic import ValidationError

from clippyme.api.schemas import (
    BatchRequest, LiveMonitorPublishingRequest, LiveMonitorStartRequest,
    LiveMonitorStopRequest, ProcessRequest,
)


_MONITOR_BASE = {
    "slug": "somechannel",
    "platforms": [{"platform": "tiktok", "accountId": "account-1"}],
}


def test_process_language_is_normalized_and_allowlisted():
    request = ProcessRequest(url="https://upload.invalid/local", language=" it ")
    assert request.language == "it"

    with pytest.raises(ValidationError):
        ProcessRequest(url="https://upload.invalid/local", language="../../bad")


def test_batch_rejects_all_blank_urls_after_cleaning():
    with pytest.raises(ValidationError):
        BatchRequest(urls=["", "   "])


def test_batch_language_is_rejected_at_api_boundary():
    with pytest.raises(ValidationError):
        BatchRequest(urls=["https://example.com/video"], language="not-a-language")


def test_live_monitor_start_preserves_runtime_domain_fields():
    request = LiveMonitorStartRequest(
        **_MONITOR_BASE,
        delete_after_publish=False,
        max_clips=9,
        timezone="Europe/Rome",
    )
    payload = request.model_dump()
    assert payload["delete_after_publish"] is False
    assert payload["max_clips"] == 9
    assert payload["timezone"] == "Europe/Rome"


@pytest.mark.parametrize("max_clips", [0, 51])
def test_live_monitor_start_bounds_max_clips(max_clips):
    with pytest.raises(ValidationError):
        LiveMonitorStartRequest(**_MONITOR_BASE, max_clips=max_clips)


def test_live_monitor_start_rejects_unknown_timezone():
    with pytest.raises(ValidationError):
        LiveMonitorStartRequest(**_MONITOR_BASE, timezone="Mars/Olympus_Mons")


def test_live_monitor_publishing_requires_a_strict_boolean():
    assert LiveMonitorPublishingRequest(enabled=False).enabled is False
    with pytest.raises(ValidationError):
        LiveMonitorPublishingRequest(enabled="false")



def test_live_monitor_stop_id_is_path_safe():
    assert LiveMonitorStopRequest(monitor_id="youtube:0123456789abcdefabcd").monitor_id
    with pytest.raises(ValidationError):
        LiveMonitorStopRequest(monitor_id="youtube:https://example.com/channel")
