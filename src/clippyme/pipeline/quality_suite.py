"""Manifest-driven media quality regression suite.

This is deliberately a regular Python module rather than a CI-only script, so
operators can evaluate golden/synthetic clips locally, in Docker, or in GitHub
Actions with the exact same ffprobe/ffmpeg policy used by production renders.

Manifest example::

    {
      "cases": [
        {
          "name": "vertical-talking-head",
          "path": "fixtures/talking-head.mp4",
          "expected_duration": 24.0,
          "duration_tolerance": 1.0,
          "expected_aspect": "9:16",
          "allow_warnings": false
        }
      ]
    }

Paths are resolved relative to the manifest and must remain inside that
manifest's directory. Results can be written as JSON with ``--output``. The
process exits 1 when a critical defect, disallowed warning, or baseline mismatch
is found, making it suitable for CI quality gates.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from clippyme.pipeline.media_qa import inspect_clip

_ASPECTS = {"9:16": 9 / 16, "1:1": 1.0, "16:9": 16 / 9}


class QualityManifestError(ValueError):
    """The suite manifest is unsafe or malformed."""


def _atomic_json(path: str, payload: dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".quality-suite-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = ""
    finally:
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass


def _load_manifest(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise QualityManifestError(f"cannot read manifest: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("cases"), list):
        raise QualityManifestError("manifest must be an object containing a cases array")
    return value


def _finite_number(value: Any, *, field: str, minimum: float | None = None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise QualityManifestError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise QualityManifestError(f"{field} must be finite")
    if minimum is not None and parsed < minimum:
        raise QualityManifestError(f"{field} must be >= {minimum:g}")
    return parsed


def parse_aspect(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value in _ASPECTS:
        return _ASPECTS[value]
    aspect = _finite_number(value, field="expected_aspect", minimum=0.01)
    return aspect


def _safe_case_path(manifest_path: str, relative_path: Any) -> str:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise QualityManifestError("each case needs a non-empty path")
    root = Path(manifest_path).resolve().parent
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise QualityManifestError(f"case path escapes manifest directory: {relative_path}") from exc
    return str(candidate)


def _baseline_issues(case: dict[str, Any], report: dict[str, Any]) -> list[str]:
    """Compare measured metrics to optional explicit regression baselines."""
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    issues: list[str] = []

    expected_duration = _finite_number(
        case.get("expected_duration"),
        field="expected_duration",
        minimum=0,
    )
    tolerance = _finite_number(
        case.get("duration_tolerance", 1.5),
        field="duration_tolerance",
        minimum=0,
    )
    actual_duration = metrics.get("duration")
    if expected_duration is not None and actual_duration is not None:
        if abs(float(actual_duration) - expected_duration) > float(tolerance or 0):
            issues.append(
                f"duration baseline mismatch: measured {float(actual_duration):.3f}s, "
                f"expected {expected_duration:.3f}s ± {float(tolerance or 0):.3f}s"
            )

    for manifest_key, metric_key, relation in (
        ("min_size_bytes", "size_bytes", "minimum"),
        ("max_black_ratio", "black_ratio", "maximum"),
        ("max_freeze_ratio", "freeze_ratio", "maximum"),
        ("min_mean_volume_db", "mean_volume_db", "minimum"),
        ("max_peak_volume_db", "max_volume_db", "maximum"),
    ):
        threshold = _finite_number(case.get(manifest_key), field=manifest_key)
        measured = metrics.get(metric_key)
        if threshold is None or measured is None:
            continue
        measured = float(measured)
        violated = measured < threshold if relation == "minimum" else measured > threshold
        if violated:
            symbol = ">=" if relation == "minimum" else "<="
            issues.append(
                f"{metric_key} baseline mismatch: measured {measured:g}, expected {symbol} {threshold:g}"
            )
    return issues


def evaluate_case(
    case: dict[str, Any],
    *,
    manifest_path: str,
    signal_checks: bool = True,
) -> dict[str, Any]:
    if not isinstance(case, dict):
        raise QualityManifestError("each case must be an object")
    path = _safe_case_path(manifest_path, case.get("path"))
    name = str(case.get("name") or Path(path).stem)
    expected_duration = _finite_number(
        case.get("expected_duration"),
        field="expected_duration",
        minimum=0,
    )
    expected_aspect = parse_aspect(case.get("expected_aspect"))
    report = inspect_clip(
        path,
        expected_duration=expected_duration,
        expected_aspect=expected_aspect,
        smartcut_applied=bool(case.get("smartcut_applied", False)),
        run_signal_checks=bool(signal_checks and case.get("signal_checks", True)),
    )
    baseline_issues = _baseline_issues(case, report)
    warnings = list(report.get("warnings") or [])
    critical_issues = list(report.get("issues") or [])
    critical_issues.extend(baseline_issues)
    allow_warnings = bool(case.get("allow_warnings", True))
    passed = not critical_issues and (allow_warnings or not warnings)
    return {
        "name": name,
        "path": os.path.relpath(path, Path(manifest_path).resolve().parent),
        "passed": passed,
        "allow_warnings": allow_warnings,
        "critical": bool(critical_issues),
        "issues": critical_issues,
        "warnings": warnings,
        "metrics": deepcopy(report.get("metrics") or {}),
    }


def summarize_reports(reports: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(reports),
        "passed": sum(1 for report in reports if report.get("passed")),
        "failed": sum(1 for report in reports if not report.get("passed")),
        "critical": sum(1 for report in reports if report.get("critical")),
        "with_warnings": sum(1 for report in reports if report.get("warnings")),
    }


def run_manifest(
    manifest_path: str,
    *,
    signal_checks: bool = True,
) -> dict[str, Any]:
    manifest_path = str(Path(manifest_path).resolve())
    manifest = _load_manifest(manifest_path)
    reports = [
        evaluate_case(case, manifest_path=manifest_path, signal_checks=signal_checks)
        for case in manifest["cases"]
    ]
    return {
        "schema": 1,
        "manifest": os.path.basename(manifest_path),
        "summary": summarize_reports(reports),
        "cases": reports,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate rendered clips against a QA manifest")
    parser.add_argument("manifest", help="JSON quality-suite manifest")
    parser.add_argument("--output", help="write the full JSON report atomically")
    parser.add_argument(
        "--no-signal-checks",
        action="store_true",
        help="skip black/freeze/audio analysis and run structural checks only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_manifest(args.manifest, signal_checks=not args.no_signal_checks)
    except QualityManifestError as exc:
        print(f"quality manifest error: {exc}")
        return 2
    if args.output:
        _atomic_json(os.path.abspath(args.output), result)
    summary = result["summary"]
    print(
        "quality suite: "
        f"{summary['passed']}/{summary['total']} passed, "
        f"{summary['critical']} critical, {summary['with_warnings']} with warnings"
    )
    for report in result["cases"]:
        status = "PASS" if report["passed"] else "FAIL"
        details = report["issues"] or (
            report["warnings"] if not report["allow_warnings"] else []
        )
        suffix = f" — {'; '.join(details)}" if details else ""
        print(f"[{status}] {report['name']}{suffix}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
