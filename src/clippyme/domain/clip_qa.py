"""Post-render output QA (video-use step 7 + superpowers verification).

video-use verifies its OWN output before showing the user: re-inspect the
rendered file at every cut, check duration / audio / overlay sanity, fix and
re-render, cap at 3 passes. ClippyMe shipped composed clips with zero automated
check. This module is the cheap analogue: the pure scoring lives here
(host-unit-testable); compose.py probes the final file and feeds the numbers in.

`evaluate_clip_qa` returns {"ok": bool, "issues": [str, ...]} — a soft report.
Failures are logged as warnings, not raised: a QA miss must never block a
download, only surface the problem.
"""
from __future__ import annotations

# Composed clip may legitimately differ from the expected length (Smart Cut
# removes silences). We only flag GROSS mismatches that signal a broken render
# (truncated file, wrong stream), not the normal shortening from editing.
DURATION_SHORT_RATIO = 0.25   # output < 25% of expected → suspicious
DURATION_LONG_SLACK = 1.5     # output > expected * 1.5 → suspicious
MIN_BYTES = 10_000            # smaller than this is effectively empty


def evaluate_clip_qa(
    *,
    actual_duration: float | None,
    expected_duration: float | None,
    has_audio: bool,
    size_bytes: int | None,
    smartcut_applied: bool = False,
) -> dict:
    """Score a rendered clip against expectations. Pure — no I/O.

    `expected_duration` is the clip's (end - start). When Smart Cut ran the
    output is expected to be shorter, so the lower bound is relaxed.
    """
    issues: list[str] = []

    if size_bytes is not None and size_bytes < MIN_BYTES:
        issues.append(f"output is effectively empty ({size_bytes} bytes)")

    if not has_audio:
        issues.append("output has no audio stream")

    if actual_duration is not None and actual_duration <= 0:
        issues.append("output duration is zero")

    if (
        actual_duration is not None
        and expected_duration is not None
        and expected_duration > 0
        and actual_duration > 0
    ):
        ratio = actual_duration / expected_duration
        # Smart Cut only ever shortens; a too-LONG output is always wrong.
        if ratio > DURATION_LONG_SLACK:
            issues.append(
                f"output ({actual_duration:.1f}s) far longer than expected "
                f"({expected_duration:.1f}s)"
            )
        # A too-SHORT output is wrong unless Smart Cut intentionally trimmed.
        if ratio < DURATION_SHORT_RATIO and not smartcut_applied:
            issues.append(
                f"output ({actual_duration:.1f}s) far shorter than expected "
                f"({expected_duration:.1f}s)"
            )

    return {"ok": not issues, "issues": issues}
