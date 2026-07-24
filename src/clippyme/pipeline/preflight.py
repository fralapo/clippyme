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


def estimate_gemini_tokens(duration_seconds: float) -> tuple[int, int]:
    """Approximate prompt/output token counts from conversational speech rate."""
    # ~2.4 spoken words/s; compact TOON rows average ~2.0 tokens/word including
    # timestamps. Add a fixed prompt/rubric allowance and a bounded JSON output.
    words = max(0.0, float(duration_seconds)) * 2.4
    input_tokens = int(5_500 + words * 2.0)
    output_tokens = int(700 + min(12, expected_clip_count(duration_seconds)) * 180)
    return input_tokens, output_tokens


def estimate_gemini_cost(
    duration_seconds: float,
    model: str,
    pricing: dict[str, dict[str, float]] | None,
) -> dict[str, Any]:
    input_tokens, output_tokens = estimate_gemini_tokens(duration_seconds)
    rates = (pricing or {}).get(model) or {}
    input_rate = float(rates.get("input") or 0.0)
    output_rate = float(rates.get("output") or 0.0)
    cost = input_tokens / 1_000_000 * input_rate + output_tokens / 1_000_000 * output_rate
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 6),
        "pricing_known": bool(rates),
    }


def estimate_disk_bytes(inputs: PreflightInputs, clip_count: int) -> int:
    """Conservative peak disk requirement including source slices and temp files."""
    duration = max(1.0, float(inputs.duration_seconds))
    input_bytes = max(0, int(inputs.input_bytes))
    # Assume 45 s/clip. Source slices + final encodes + one temp render can peak
    # near 18 Mbps combined. Preserve a copy-sized safety margin for atomic swaps.
    selected_seconds = min(duration, clip_count * 45.0)
    generated = selected_seconds * 18_000_000 / 8
    transcript_and_metadata = max(64 * _MIB, duration * 30_000)
    return int(input_bytes + generated * 1.35 + transcript_and_metadata)


def estimate_runtime_seconds(inputs: PreflightInputs, clip_count: int) -> int:
    """Wall-clock estimate based on source minutes and output volume."""
    duration = max(1.0, float(inputs.duration_seconds))
    source_minutes = duration / 60.0
    # GPU mainly improves detection/reframe; transcription/provider latency and
    # ffmpeg remain. These factors deliberately lean high.
    analysis_factor = 0.65 if inputs.has_gpu else 1.15
    render_factor = 0.55 if inputs.has_gpu else 1.25
    seconds = 45 + source_minutes * 60 * analysis_factor + clip_count * 45 * render_factor
    return max(30, int(math.ceil(seconds)))


def build_preflight(
    inputs: PreflightInputs,
    *,
    pricing: dict[str, dict[str, float]] | None = None,
    free_disk_bytes: int | None = None,
) -> dict[str, Any]:
    clip_count = expected_clip_count(inputs.duration_seconds, inputs.max_clips)
    disk_required = estimate_disk_bytes(inputs, clip_count)
    runtime_seconds = estimate_runtime_seconds(inputs, clip_count)
    cost = estimate_gemini_cost(inputs.duration_seconds, inputs.model, pricing)
    report = {
        "duration_seconds": round(max(0.0, float(inputs.duration_seconds)), 3),
        "input_bytes": max(0, int(inputs.input_bytes)),
        "input_mb": round(max(0, int(inputs.input_bytes)) / _MIB, 2),
        "source_width": inputs.width,
        "source_height": inputs.height,
        "aspect": inputs.aspect,
        "gpu": bool(inputs.has_gpu),
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
    env = env or os.environ

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
    estimated_cost = float(report.get("estimated_cost_usd") or 0)
    if max_cost > 0 and estimated_cost > max_cost:
        raise PreflightRejected(
            f"estimated Gemini cost ${estimated_cost:.4f} exceeds configured limit ${max_cost:.4f}"
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
    return (
        "[preflight] "
        f"duration_s={report.get('duration_seconds', 0)} "
        f"input_mb={report.get('input_mb', 0)} "
        f"clips={report.get('expected_clips', 0)} "
        f"runtime_min={report.get('estimated_runtime_minutes', 0)} "
        f"disk_gb={report.get('required_disk_gb', 0)} "
        f"cost_usd={report.get('estimated_cost_usd', 0)}"
    )
