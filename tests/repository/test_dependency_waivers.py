"""Lockfile audit waivers must be visible, minimal and documented."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "CVE-2025-3000",
    "PYSEC-2026-1805",
    "PYSEC-2026-3447",
}


def test_ci_audit_only_waives_reviewed_advisories():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    actual = set(re.findall(r"--ignore-vuln\s+([A-Z]+-\d{4}-\d+)", workflow))
    assert actual == EXPECTED, "New or removed waiver requires a security review"


def test_runtime_waivers_are_documented_and_wheel_is_not_locked():
    policy = (ROOT / "docs/development/dependencies.md").read_text()
    lock = (ROOT / "requirements.lock").read_text()
    for advisory in EXPECTED | {"CVE-2026-24049"}:
        assert advisory in policy
    assert not re.search(r"^wheel==", lock, re.MULTILINE)
