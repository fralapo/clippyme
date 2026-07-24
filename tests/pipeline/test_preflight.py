import pytest

from clippyme.pipeline.preflight import (
    PreflightInputs,
    PreflightRejected,
    build_preflight,
    enforce_preflight,
    estimate_gemini_cost,
    expected_clip_count,
)


PRICING = {"gemini-test": {"input": 1.0, "output": 2.0}}


def test_expected_clip_count_is_bounded_and_honours_cap():
    assert expected_clip_count(0) == 1
    assert expected_clip_count(10_000) == 12
    assert expected_clip_count(10_000, max_clips=4) == 4


def test_build_preflight_exposes_capacity_cost_and_time():
    report = build_preflight(
        PreflightInputs(
            duration_seconds=600,
            input_bytes=500 * 1024 * 1024,
            width=1920,
            height=1080,
            model="gemini-test",
            has_gpu=True,
        ),
        pricing=PRICING,
        free_disk_bytes=20 * 1024 ** 3,
    )
    assert report["expected_clips"] == 6
    assert report["estimated_runtime_seconds"] > 0
    assert report["required_disk_bytes"] > report["input_bytes"]
    assert report["pricing_known"] is True
    assert report["estimated_cost_usd"] > 0
    assert report["disk_headroom_gb"] > 0


def test_unknown_model_cost_is_explicitly_zero_and_unknown():
    report = estimate_gemini_cost(60, "gemini-future", PRICING)
    assert report["estimated_cost_usd"] == 0
    assert report["pricing_known"] is False


def test_duration_quota_rejected():
    report = build_preflight(
        PreflightInputs(duration_seconds=601, input_bytes=10, model="gemini-test"),
        pricing=PRICING,
        free_disk_bytes=20 * 1024 ** 3,
    )
    with pytest.raises(PreflightRejected, match="duration"):
        enforce_preflight(report, {"CLIPPYME_MAX_DURATION_SECONDS": "600", "CLIPPYME_MIN_FREE_DISK_GB": "0"})


def test_cost_quota_rejected():
    report = build_preflight(
        PreflightInputs(duration_seconds=3600, input_bytes=10, model="gemini-test"),
        pricing=PRICING,
        free_disk_bytes=20 * 1024 ** 3,
    )
    with pytest.raises(PreflightRejected, match="cost"):
        enforce_preflight(report, {
            "CLIPPYME_MAX_ESTIMATED_COST_USD": "0.000001",
            "CLIPPYME_MIN_FREE_DISK_GB": "0",
        })


def test_disk_reserve_rejected():
    report = build_preflight(
        PreflightInputs(duration_seconds=600, input_bytes=1024 ** 3, model="gemini-test"),
        pricing=PRICING,
        free_disk_bytes=1024 ** 3,
    )
    with pytest.raises(PreflightRejected, match="disk"):
        enforce_preflight(report, {"CLIPPYME_MIN_FREE_DISK_GB": "0.5"})
