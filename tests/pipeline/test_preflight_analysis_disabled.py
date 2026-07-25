from clippyme.pipeline.preflight import PreflightInputs, build_preflight


def test_analysis_disabled_estimates_one_clip_and_no_gemini_cost():
    report = build_preflight(
        PreflightInputs(
            duration_seconds=900,
            input_bytes=500 * 1024 * 1024,
            model="gemini-priced",
            analysis_enabled=False,
        ),
        pricing={"gemini-priced": {"input": 10.0, "output": 30.0}},
        free_disk_bytes=20 * 1024 ** 3,
    )
    assert report["analysis_enabled"] is False
    assert report["expected_clips"] == 1
    assert report["input_tokens"] == 0
    assert report["output_tokens"] == 0
    assert report["estimated_cost_usd"] == 0
    assert report["pricing_known"] is True
