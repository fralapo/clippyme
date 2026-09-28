"""Pure post-render output QA policy.

``media_qa`` owns ffprobe/ffmpeg I/O; this module turns normalized measurements
into a stable verdict that is cheap to unit-test.  Structural defects are marked
critical so the orchestrator can reject a broken temp render before atomically
publishing it.  Signal-quality findings remain warnings and never destroy a
usable clip.
"""
from __future__ import annotations

DURATION_SHORT_RATIO = 0.25
DURATION_LONG_SLACK = 1.5
MIN_BYTES = 10_000
ASPECT_TOLERANCE = 0.08
BLACK_WARNING_RATIO = 0.45
FREEZE_WARNING_RATIO = 0.70
QUIET_WARNING_DB = -38.0
CLIP_WARNING_DB = -0.1


def evaluate_clip_qa(
    *,
    actual_duration: float | None,
    expected_duration: float | None,
    has_audio: bool,
    size_bytes: int | None,
    smartcut_applied: bool = False,
    has_video: bool = True,
    width: int | None = None,
    height: int | None = None,
    expected_aspect: float | None = None,
    black_ratio: float | None = None,
    freeze_ratio: float | None = None,
    mean_volume_db: float | None = None,
    max_volume_db: float | None = None,
) -> dict:
    """Score a rendered clip against structural and signal expectations.

    Returns ``ok`` for a clean clip, ``critical`` when the file must not replace a
    known-good output, plus separate ``issues`` and ``warnings`` string arrays.
    The historical call shape remains valid because every new argument has a
    conservative default.
    """
    issues: list[str] = []
    warnings: list[str] = []

    if size_bytes is not None and size_bytes < MIN_BYTES:
        issues.append(f"output is effectively empty ({size_bytes} bytes)")
    if not has_video:
        issues.append("output has no video stream")
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
        if ratio > DURATION_LONG_SLACK:
            issues.append(
                f"output ({actual_duration:.1f}s) far longer than expected "
                f"({expected_duration:.1f}s)"
            )
        if ratio < DURATION_SHORT_RATIO and not smartcut_applied:
            issues.append(
                f"output ({actual_duration:.1f}s) far shorter than expected "
                f"({expected_duration:.1f}s)"
            )

    if width and height and expected_aspect and expected_aspect > 0:
        actual_aspect = float(width) / float(height)
        relative_error = abs(actual_aspect - expected_aspect) / expected_aspect
        if relative_error > ASPECT_TOLERANCE:
            issues.append(
                f"wrong aspect ratio ({width}x{height}, {actual_aspect:.3f}; "
                f"expected {expected_aspect:.3f})"
            )

    if black_ratio is not None and black_ratio > BLACK_WARNING_RATIO:
        warnings.append(f"large full-frame black share ({black_ratio * 100:.1f}%)")
    if freeze_ratio is not None and freeze_ratio > FREEZE_WARNING_RATIO:
        warnings.append(f"long frozen-frame share ({freeze_ratio * 100:.1f}%)")
    if mean_volume_db is not None and mean_volume_db < QUIET_WARNING_DB:
        warnings.append(f"audio is very quiet (mean {mean_volume_db:.1f} dB)")
    if max_volume_db is not None and max_volume_db > CLIP_WARNING_DB:
        warnings.append(f"audio peak may clip ({max_volume_db:.2f} dB)")

    return {
        "ok": not issues and not warnings,
        "critical": bool(issues),
        "issues": issues,
        "warnings": warnings,
    }
