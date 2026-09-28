"""Goal 6 — Gemini cost estimate, budget gate and usage accounting.

Contract (ai.google.dev/gemini-api/docs/pricing + the SDK's UsageMetadata,
checked 2026-09-28): prices are USD per 1M tokens; thinking tokens are billed
at the output rate; ``candidates_token_count`` excludes thoughts and
``total_token_count`` = prompt + candidates + tool-use + thoughts, so cost is
priced from the categories, never from the total.
"""
import re
import struct
from types import SimpleNamespace

import pytest

from clippyme.domain import history_service
from clippyme.pipeline import gemini_request
from clippyme.pipeline.gemini_request import (
    MODEL_PRICING,
    add_call_cost,
    build_viral_prompt,
    compute_gemini_cost,
    usage_cost,
)
from clippyme.pipeline.preflight import (
    PreflightInputs,
    PreflightRejected,
    build_preflight,
    enforce_preflight,
    estimate_gemini_tokens,
)

NO_DISK = {"CLIPPYME_MIN_FREE_DISK_GB": "0"}


def _report(duration, model="gemini-3.5-flash", pricing=None, **kw):
    return build_preflight(
        PreflightInputs(duration_seconds=duration, input_bytes=10, model=model, **kw),
        pricing=MODEL_PRICING if pricing is None else pricing,
        free_disk_bytes=20 * 1024 ** 3,
    )


def _transcript(duration, words_per_second=2.8, float32=False):
    """Word list shaped like a real transcription: Deepgram (the default
    provider) sends float32 timestamps such as ``0.79999995``."""
    words, t = [], 0.3
    while t < duration - 1:
        s, e = round(t, 2), round(t + 0.3, 2)
        if float32:
            s, e = (float(f"{struct.unpack('f', struct.pack('f', v + 1e-5))[0]:.8g}")
                    for v in (s, e))
        words.append({"word": "davvero", "start": s, "end": e})
        t += 1.0 / words_per_second
    return {"text": " ".join(w["word"] for w in words), "segments": [{"words": words}]}


# --- G1: the preflight estimate must cover the payload actually sent ----------

@pytest.mark.parametrize("duration", [60, 600, 3600, 4 * 3600])
@pytest.mark.parametrize("float32", [False, True])
def test_input_estimate_covers_the_real_toon_payload(duration, float32):
    prompt, _words = build_viral_prompt(_transcript(duration, float32=float32), duration)
    # Gemini's tokenizer splits digits into single tokens, so every digit of
    # the TOON timestamps is at least one token — a hard floor, no tokenizer
    # needed. (Offline Gemma tokenizer measured 17-25 tokens per word.)
    floor = len(re.findall(r"\d", prompt)) + prompt.count("\n")
    estimate, _ = estimate_gemini_tokens(duration)
    assert estimate >= floor
    # ...and not a blanket multiplier: within 3x of the digit floor once the
    # words dominate the fixed template.
    if duration >= 600:
        assert estimate <= 3 * floor


def test_budget_rejects_a_job_the_old_estimate_let_through():
    # 1 h at 2.8 words/s is ~240k real prompt tokens (~$0.36 on 3.5-flash);
    # the old ~2 tokens/word estimate said ~$0.06.
    with pytest.raises(PreflightRejected, match="cost"):
        enforce_preflight(_report(3600), {"CLIPPYME_MAX_ESTIMATED_COST_USD": "0.10", **NO_DISK})


def test_budget_still_passes_a_job_clearly_under_it():
    enforce_preflight(_report(600), {"CLIPPYME_MAX_ESTIMATED_COST_USD": "1.00", **NO_DISK})


def test_estimate_prices_thinking_tokens_at_the_output_rate():
    report = _report(600, pricing={"gemini-3.5-flash": {"input": 0.0, "output": 1.0}})
    assert report["thinking_tokens"] > 0
    assert report["estimated_cost_usd"] == pytest.approx(
        (report["output_tokens"] + report["thinking_tokens"]) / 1_000_000)


def _exact_cost_report(cost):
    """A report whose estimate is exactly ``cost`` (only input priced)."""
    tokens, _ = estimate_gemini_tokens(600)
    rate = cost * 1_000_000 / tokens
    return _report(600, pricing={"gemini-3.5-flash": {"input": rate, "output": 0.0}},
                   retry_models=())


def test_budget_boundaries_use_the_unrounded_estimate():
    env = lambda limit: {"CLIPPYME_MAX_ESTIMATED_COST_USD": limit, **NO_DISK}  # noqa: E731
    enforce_preflight(_exact_cost_report(0.01), env("0.0100001"))       # just under
    enforce_preflight(_exact_cost_report(0.0099999), env("0.01"))       # just under
    with pytest.raises(PreflightRejected):                              # just over,
        enforce_preflight(_exact_cost_report(0.0100004), env("0.01"))   # rounds to 0.01


def test_budget_with_unknown_pricing_fails_closed():
    report = _report(60, model="gemini-99-ultra")
    assert report["pricing_known"] is False
    assert report["estimated_cost_usd"] is None
    with pytest.raises(PreflightRejected, match="pricing"):
        enforce_preflight(report, {"CLIPPYME_MAX_ESTIMATED_COST_USD": "100", **NO_DISK})


def test_unknown_pricing_without_a_budget_is_allowed():
    enforce_preflight(_report(60, model="gemini-99-ultra"), NO_DISK)


def test_budget_covers_the_priciest_fallback_model(monkeypatch):
    pricing = {"cheap": {"input": 0.01, "output": 0.01},
               "pricey": {"input": 10.0, "output": 10.0}}
    report = _report(600, model="cheap", pricing=pricing,
                     fallback_models=("pricey",), retry_models=())
    assert report["estimated_cost_usd"] == pytest.approx(
        (report["input_tokens"] + report["output_tokens"] + report["thinking_tokens"])
        * 10.0 / 1_000_000)
    with pytest.raises(PreflightRejected):
        enforce_preflight(report, {"CLIPPYME_MAX_ESTIMATED_COST_USD": "0.10", **NO_DISK})


def test_budget_fails_closed_when_a_fallback_model_is_unpriced():
    report = _report(60, fallback_models=("gemini-99-ultra",))
    assert report["pricing_known"] is False
    with pytest.raises(PreflightRejected, match="pricing"):
        enforce_preflight(report, {"CLIPPYME_MAX_ESTIMATED_COST_USD": "100", **NO_DISK})


def test_estimate_includes_the_reformat_retry_call():
    pricing = {"main": {"input": 0.0, "output": 0.0}, "retry": {"input": 1.0, "output": 1.0}}
    report = _report(600, model="main", pricing=pricing, retry_models=("retry",))
    assert report["estimated_cost_usd"] > 0


def test_default_chains_are_fully_priced():
    """Every model the pipeline reaches by default has an official price."""
    chain = gemini_request.build_model_chain("gemini-3.5-flash")
    retry = gemini_request.build_model_chain("gemini-2.5-flash")
    missing = [m for m in {*chain, *retry} if gemini_request.model_rates(m) is None]
    assert missing == []


# --- pricing table ---------------------------------------------------------------

def test_prices_are_per_million_tokens():
    cost = compute_gemini_cost(1, 0, "gemini-2.5-flash")
    assert cost["input_cost"] == pytest.approx(0.30 / 1_000_000)


def test_long_prompt_tier():
    assert gemini_request.model_rates("gemini-2.5-pro", 200_000) == {"input": 1.25, "output": 10.0}
    assert gemini_request.model_rates("gemini-2.5-pro", 200_001) == {"input": 2.50, "output": 15.0}


def test_dated_promo_rates():
    at = gemini_request.model_rates
    assert at("gemini-3.6-flash", today="2026-12-31") == {"input": 0.75, "output": 3.75}
    assert at("gemini-3.6-flash", today="2027-01-01") == {"input": 1.50, "output": 7.50}


# --- G2: thinking tokens and the actual cost -------------------------------------

def test_thinking_tokens_are_billed_at_the_output_rate_once():
    A, B, C = 1_000_000, 2_000_000, 4_000_000
    rates = MODEL_PRICING["gemini-2.5-flash"]
    cost = compute_gemini_cost(A, B, "gemini-2.5-flash", thinking_tokens=C)
    assert cost["thinking_tokens"] == C
    assert cost["total_cost"] == pytest.approx(rates["input"] * 1 + rates["output"] * (2 + 4))


def _usage(prompt=1_000_000, candidates=2_000_000, thoughts=4_000_000, **extra):
    total = prompt + candidates + (thoughts or 0)
    return SimpleNamespace(prompt_token_count=prompt, candidates_token_count=candidates,
                           thoughts_token_count=thoughts, total_token_count=total, **extra)


def test_usage_cost_reads_thoughts_and_never_the_total():
    cost = usage_cost(_usage(), "gemini-2.5-flash")
    assert (cost["input_tokens"], cost["output_tokens"], cost["thinking_tokens"]) == (
        1_000_000, 2_000_000, 4_000_000)
    assert cost["total_cost"] == pytest.approx(0.30 + 2.50 * 6)


@pytest.mark.parametrize("thoughts", [None, 0])
def test_usage_without_thoughts(thoughts):
    cost = usage_cost(_usage(thoughts=thoughts), "gemini-2.5-flash")
    assert cost["thinking_tokens"] == 0
    assert cost["total_cost"] == pytest.approx(0.30 + 2.50 * 2)


def test_usage_missing_is_not_a_failure():
    assert usage_cost(None, "gemini-2.5-flash") is None
    partial = SimpleNamespace(prompt_token_count=None, candidates_token_count=10)
    assert usage_cost(partial, "gemini-2.5-flash")["input_tokens"] == 0


def test_unknown_model_cost_is_unknown_not_zero():
    cost = usage_cost(_usage(), "gemini-99-ultra")
    assert cost["pricing_known"] is False
    assert cost["total_cost"] is None


def test_reformat_retry_cost_is_added_to_the_job_total():
    primary = compute_gemini_cost(1_000_000, 0, "gemini-2.5-flash")
    retry = compute_gemini_cost(0, 1_000_000, "gemini-2.5-flash-lite")
    total = add_call_cost(primary, retry)
    assert total["total_cost"] == pytest.approx(0.30 + 0.40)
    assert total["model"] == "gemini-2.5-flash"
    assert total["extra_calls"][0]["model"] == "gemini-2.5-flash-lite"
    unknown = add_call_cost(primary, compute_gemini_cost(1, 1, "gemini-99-ultra"))
    assert unknown["total_cost"] is None and unknown["pricing_known"] is False


# --- history ---------------------------------------------------------------------

@pytest.mark.parametrize("cost_analysis,expected", [
    ({"total_cost": 0.25, "model": "gemini-2.5-flash"}, 0.25),
    # pre-Goal-6 metadata of an unpriced model: 0 + note, not a real $0
    ({"total_cost": 0, "model": "gemini-3.6-flash", "note": "Pricing not available"}, None),
    ({"total_cost": None, "pricing_known": False}, None),
    ({}, None),
])
def test_history_cost(cost_analysis, expected):
    assert history_service.reported_cost(cost_analysis) == expected
