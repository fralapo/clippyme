"""Host-unit tests for the colour-grade filter builder (pure)."""
from clippyme.domain.grade import GRADE_PRESETS, build_grade_filter


def test_none_and_unknown_are_empty():
    assert build_grade_filter("none") == ""
    assert build_grade_filter(None) == ""
    assert build_grade_filter("does_not_exist") == ""


def test_known_presets_return_filter_chains():
    for name in ("neutral_punch", "warm_cinematic", "cool_crisp", "vivid_pop"):
        f = build_grade_filter(name)
        assert f and "eq=" in f


def test_case_insensitive():
    assert build_grade_filter("Warm_Cinematic") == GRADE_PRESETS["warm_cinematic"]


def test_apply_grade_timeout_returns_false(monkeypatch):
    """A hung ffmpeg must degrade to 'keep the ungraded input', not raise.

    The compose layer treats a False return as a soft no-op, so a timeout
    behaves exactly like an unknown preset instead of failing the download.
    """
    import subprocess

    from clippyme.domain import grade as grade_module

    def hang(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)

    monkeypatch.setattr(grade_module.subprocess, "run", hang)
    assert grade_module.apply_grade("in.mp4", "out.mp4", "warm_cinematic") is False
