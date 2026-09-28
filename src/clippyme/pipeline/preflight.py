"""Pure preflight estimates and resource-policy enforcement.

The estimates are intentionally conservative: they are used to fail early when a
job clearly cannot fit on disk or violates an operator-configured quota, not to
promise an exact completion time or bill.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any

from clippyme.pipeline.analysis.gemini_request import compute_gemini_cost

_GIB = 1024 ** 3
_MIB = 1024 ** 2


class PreflightRejected(RuntimeError):
    """Raised before expensive transcription/AI/render work starts."""


@dataclass(frozen=True)
class PreflightInputs:
    duration_seconds: float
    input_bytes: int
    width: int | None = None
    height: int | None = None
    model: str = "gemini-3.5-flash"
    aspect: str = "9:16"
    has_gpu: bool = False
    max_clips: int | None = None
    analysis_enabled: bool = True
    # Every other model the Gemini calls may land on (the fallback chain after
    # ``model``, and the reformat-retry chain) — the budget covers the priciest.
    fallback_models: tuple[str, ...] = ()
    retry_models: tuple[str, ...] = ()


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def expected_clip_count(duration_seconds: float, max_clips: int | None = None) -> int:
    """Estimate useful shorts from source duration without overproducing."""
    if duration_seconds <= 0:
        estimate = 1
    else:
        estimate = _clamp(int(round(duration_seconds / 100.0)), 1, 12)
    if max_clips and max_clips > 0:
        estimate = min(estimate, int(max_clips))
    return estimate


# Upper bounds for the analysis call (the transcript is not known yet at
# preflight, only the duration). Words per second: conversational speech —
# live streams measured ~1/s, dense podcasts reach ~2.8/s. Tokens per word:
# each word is a TOON row ``w,start,end`` plus its copy in the plain text, and
# Gemini tokenizes every timestamp digit separately — the offline Gemma
# tokenizer measured 17-21 tokens/word with 2-decimal timestamps and 23-25
# with Deepgram's float32 ones (``0.79999995``), plus ~4k for the template.
SPEECH_WORDS_PER_SECOND = 2.8
PROMPT_TOKENS_PER_WORD = 26
PROMPT_TEMPLATE_TOKENS = 5_500
# Visible answer: the prompt asks for 3-15 clips of JSON copy, ~250 tokens
# each (observed ~3k for 13 clips). Thinking is on by default and billed as
# output; Google publishes no size for the default level, so this is an
# assumption — recalibrate from the recorded ``thinking_tokens``. The
# reformat retry sends back at most the answer plus a short instruction.
OUTPUT_BASE_TOKENS = 700
OUTPUT_TOKENS_PER_CLIP = 250
THINKING_TOKENS = 8_192
REFORMAT_OVERHEAD_TOKENS = 500


def estimate_gemini_tokens(duration_seconds: float) -> tuple[int, int]:
    """Upper-bound prompt / visible-output tokens of the analysis call."""
    words = max(0.0, float(duration_seconds)) * SPEECH_WORDS_PER_SECOND
    clips = _clamp(int(round(float(duration_seconds) / 100.0)), 3, 15)
    return (
        int(PROMPT_TEMPLATE_TOKENS + words * PROMPT_TOKENS_PER_WORD),
        OUTPUT_BASE_TOKENS + clips * OUTPUT_TOKENS_PER_CLIP,
    )


def _worst_call_cost(models, input_tokens, output_tokens, pricing):
    """Highest cost of one call over every model it may land on, or None if
    any of them is unpriced (the fallback can't be proven within budget)."""
    costs = []
    for model in models:
        cost = compute_gemini_cost(input_tokens, output_tokens, model, THINKING_TOKENS,
                                   pricing=pricing)["total_cost"]
        if cost is None:
            return None
        costs.append(cost)
    return max(costs, default=0.0)


def estimate_gemini_cost(
    duration_seconds: float,
    model: str,
    pricing: dict[str, dict[str, float]] | None,
    *,
    enabled: bool = True,
    fallback_models: tuple[str, ...] = (),
    retry_models: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Worst-case Gemini spend: the analysis call on the priciest model of its
    fallback chain plus one reformat retry on the priciest retry model.
    ``estimated_cost_usd`` is unrounded (the budget gate compares it) and
    None when any reachable model has no known price."""
    if not enabled:
        return {
            "model": model,
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "estimated_cost_usd": 0.0,
            "pricing_known": True,
        }
    input_tokens, output_tokens = estimate_gemini_tokens(duration_seconds)
    pricing = pricing or {}
    analysis = _worst_call_cost((model, *fallback_models), input_tokens, output_tokens, pricing)
    reformat = _worst_call_cost(
        retry_models, output_tokens + REFORMAT_OVERHEAD_TOKENS, output_tokens, pricing)
    cost = None if analysis is None or reformat is None else analysis + reformat
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": THINKING_TOKENS,
        "estimated_cost_usd": cost,
        "pricing_known": cost is not None,
    }


def estimate_disk_bytes(inputs: PreflightInputs, clip_count: int) -> int:
    """Conservative peak disk requirement including source slices and temp files."""
    duration = max(1.0, float(inputs.duration_seconds))
    input_bytes = max(0, int(inputs.input_bytes))
    selected_seconds = min(duration, clip_count * 45.0) if inputs.analysis_enabled else duration
    generated = selected_seconds * 18_000_000 / 8
    transcript_and_metadata = (
        max(64 * _MIB, duration * 30_000)
        if inputs.analysis_enabled
        else 8 * _MIB
    )
    return int(input_bytes + generated * 1.35 + transcript_and_metadata)


def estimate_runtime_seconds(inputs: PreflightInputs, clip_count: int) -> int:
    """Wall-clock estimate based on source minutes and output volume."""
    duration = max(1.0, float(inputs.duration_seconds))
    source_minutes = duration / 60.0
    if inputs.analysis_enabled:
        analysis_factor = 0.65 if inputs.has_gpu else 1.15
    else:
        analysis_factor = 0.05
    render_factor = 0.55 if inputs.has_gpu else 1.25
    seconds = 45 + source_minutes * 60 * analysis_factor + clip_count * 45 * render_factor
    return max(30, int(math.ceil(seconds)))


def build_preflight(
    inputs: PreflightInputs,
    *,
    pricing: dict[str, dict[str, float]] | None = None,
    free_disk_bytes: int | None = None,
) -> dict[str, Any]:
    clip_count = (
        expected_clip_count(inputs.duration_seconds, inputs.max_clips)
        if inputs.analysis_enabled
        else 1
    )
    disk_required = estimate_disk_bytes(inputs, clip_count)
    runtime_seconds = estimate_runtime_seconds(inputs, clip_count)
    cost = estimate_gemini_cost(
        inputs.duration_seconds,
        inputs.model,
        pricing,
        enabled=inputs.analysis_enabled,
        fallback_models=tuple(inputs.fallback_models),
        retry_models=tuple(inputs.retry_models),
    )
    report = {
        "duration_seconds": round(max(0.0, float(inputs.duration_seconds)), 3),
        "input_bytes": max(0, int(inputs.input_bytes)),
        "input_mb": round(max(0, int(inputs.input_bytes)) / _MIB, 2),
        "source_width": inputs.width,
        "source_height": inputs.height,
        "aspect": inputs.aspect,
        "gpu": bool(inputs.has_gpu),
        "analysis_enabled": bool(inputs.analysis_enabled),
        "expected_clips": clip_count,
        "estimated_runtime_seconds": runtime_seconds,
        "estimated_runtime_minutes": round(runtime_seconds / 60.0, 1),
        "required_disk_bytes": disk_required,
        "required_disk_gb": round(disk_required / _GIB, 2),
        **cost,
    }
    if free_disk_bytes is not None:
        report["free_disk_bytes"] = max(0, int(free_disk_bytes))
        report["free_disk_gb"] = round(max(0, int(free_disk_bytes)) / _GIB, 2)
        report["disk_headroom_gb"] = round((int(free_disk_bytes) - disk_required) / _GIB, 2)
    return report


def enforce_preflight(report: dict[str, Any], env: dict[str, str] | None = None) -> None:
    """Apply operator quotas. Unset/zero knobs are disabled."""
    env = os.environ if env is None else env

    def _float(name: str, default: float = 0.0) -> float:
        try:
            return float(env.get(name, default) or default)
        except (TypeError, ValueError):
            return default

    max_duration = _float("CLIPPYME_MAX_DURATION_SECONDS")
    if max_duration > 0 and float(report.get("duration_seconds") or 0) > max_duration:
        raise PreflightRejected(
            f"source duration exceeds CLIPPYME_MAX_DURATION_SECONDS ({max_duration:g}s)"
        )

    max_input_gb = _float("CLIPPYME_MAX_INPUT_GB")
    if max_input_gb > 0 and float(report.get("input_bytes") or 0) > max_input_gb * _GIB:
        raise PreflightRejected(f"input exceeds CLIPPYME_MAX_INPUT_GB ({max_input_gb:g} GiB)")

    max_cost = _float("CLIPPYME_MAX_ESTIMATED_COST_USD")
    if max_cost > 0:
        # A cost limit must be provable: an unpriced model reachable by the
        # job fails closed. Compared unrounded — the log/UI round, the gate not.
        estimated_cost = report.get("estimated_cost_usd")
        if estimated_cost is None:
            raise PreflightRejected(
                f"Gemini pricing unknown for model {report.get('model')} or one of its "
                "fallbacks, so CLIPPYME_MAX_ESTIMATED_COST_USD cannot be enforced"
            )
        if float(estimated_cost) > max_cost:
            raise PreflightRejected(
                f"estimated Gemini cost ${float(estimated_cost):.4f} exceeds configured "
                f"limit ${max_cost:.4f}"
            )

    required = int(report.get("required_disk_bytes") or 0)
    free = report.get("free_disk_bytes")
    reserve_gb = _float("CLIPPYME_MIN_FREE_DISK_GB", 1.0)
    if free is not None and int(free) - required < reserve_gb * _GIB:
        raise PreflightRejected(
            "insufficient disk headroom: "
            f"need {report.get('required_disk_gb', 0)} GiB plus {reserve_gb:g} GiB reserve, "
            f"have {report.get('free_disk_gb', 0)} GiB free"
        )


def format_preflight_log(report: dict[str, Any]) -> str:
    cost = report.get("estimated_cost_usd", 0)
    return (
        "[preflight] "
        f"duration_s={report.get('duration_seconds', 0)} "
        f"input_mb={report.get('input_mb', 0)} "
        f"clips={report.get('expected_clips', 0)} "
        f"runtime_min={report.get('estimated_runtime_minutes', 0)} "
        f"disk_gb={report.get('required_disk_gb', 0)} "
        f"cost_usd={'unknown' if cost is None else round(cost, 6)}"
    )
