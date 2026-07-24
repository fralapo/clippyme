"""Regression tests for overlay-param + platform bounding (M2).

ComposeRequest / PublishRequest leave hook_params/subtitle_params as free-form
dicts that flow into Pillow text rendering and ffmpeg numeric args. These tests
pin the DoS / payload-smuggling guards added in the security audit:
oversized text, absurd numbers, nested values, and arbitrary platform keys are
all rejected at the Pydantic boundary, while normal payloads pass.
"""
import pytest
from pydantic import ValidationError

from clippyme.api.schemas import ComposeRequest, PublishRequest


def test_compose_accepts_normal_overlay_params():
    req = ComposeRequest(
        hook_params={"text": "Wait for it", "size": "M", "offset_y": 5},
        subtitle_params={"mode": "karaoke", "preset": "hormozi_bold", "offset_y": -10},
    )
    assert req.hook_params["text"] == "Wait for it"


def test_compose_rejects_oversized_text():
    with pytest.raises(ValidationError):
        ComposeRequest(hook_params={"text": "A" * 5000})


def test_compose_rejects_absurd_number():
    with pytest.raises(ValidationError):
        ComposeRequest(subtitle_params={"font_size": 10**9})


def test_compose_rejects_nested_value():
    with pytest.raises(ValidationError):
        ComposeRequest(subtitle_params={"x": {"nested": 1}})


def test_compose_rejects_too_many_keys():
    with pytest.raises(ValidationError):
        ComposeRequest(hook_params={f"k{i}": i for i in range(50)})


def test_publish_accepts_known_platform_shape():
    req = PublishRequest(platforms=[
        {"platform": "tiktok", "accountId": "acc1", "platformSpecificData": {}},
        {"platform": "youtube", "accountId": "acc2"},
    ])
    assert len(req.platforms) == 2


def test_publish_rejects_unknown_platform():
    with pytest.raises(ValidationError):
        PublishRequest(platforms=[{"platform": "myspace", "accountId": "a"}])


def test_publish_rejects_smuggled_control_key():
    with pytest.raises(ValidationError):
        PublishRequest(platforms=[
            {"platform": "youtube", "accountId": "a", "publishNow": True},
        ])


def test_publish_rejects_missing_account():
    with pytest.raises(ValidationError):
        PublishRequest(platforms=[{"platform": "tiktok"}])


def test_publish_bounds_overlay_params():
    with pytest.raises(ValidationError):
        PublishRequest(
            platforms=[{"platform": "tiktok", "accountId": "a"}],
            hook_params={"text": "A" * 5000},
        )


def test_publish_bounds_tiktok_settings():
    # Accepts a normal flat settings object...
    ok = PublishRequest(
        platforms=[{"platform": "tiktok", "accountId": "a"}],
        tiktok_settings={"privacy": "PUBLIC_TO_EVERYONE", "duet": False},
    )
    assert ok.tiktok_settings["duet"] is False
    # ...but rejects a nested / oversized payload.
    with pytest.raises(ValidationError):
        PublishRequest(
            platforms=[{"platform": "tiktok", "accountId": "a"}],
            tiktok_settings={"x": {"nested": 1}},
        )


def test_publish_bounds_platform_specific_data():
    # Frontend's real shape passes...
    ok = PublishRequest(platforms=[
        {"platform": "instagram", "accountId": "a", "platformSpecificData": {"shareToFeed": True}},
    ])
    assert ok.platforms[0]["platformSpecificData"]["shareToFeed"] is True
    # ...nested junk smuggled inside platformSpecificData is rejected.
    with pytest.raises(ValidationError):
        PublishRequest(platforms=[
            {"platform": "youtube", "accountId": "a",
             "platformSpecificData": {"evil": {"deep": 1}}},
        ])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_overlay_rejects_non_finite_numbers(value):
    with pytest.raises(ValidationError):
        ComposeRequest(hook_params={"offset_y": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_drop_ranges_reject_non_finite_numbers(value):
    with pytest.raises(ValidationError):
        ComposeRequest(drop_ranges=[[0.0, value]])


def test_compose_rejects_unknown_or_non_boolean_toggles():
    with pytest.raises(ValidationError):
        ComposeRequest(toggles={"shell": True})
    with pytest.raises(ValidationError):
        ComposeRequest(toggles={"hook": "false"})


def test_publish_accepts_only_known_boolean_toggles():
    ok = PublishRequest(
        platforms=[{"platform": "youtube", "accountId": "a"}],
        toggles={"hook": True, "subtitles": False},
    )
    assert ok.toggles == {"hook": True, "subtitles": False}
    with pytest.raises(ValidationError):
        PublishRequest(
            platforms=[{"platform": "youtube", "accountId": "a"}],
            toggles={"hook": 1},
        )
