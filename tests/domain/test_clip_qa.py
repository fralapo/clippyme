"""Host-unit tests for the post-render QA evaluator (pure)."""
from clippyme.domain.clip_qa import evaluate_clip_qa


def _ev(**kw):
    base = dict(
        actual_duration=10.0, expected_duration=12.0,
        has_audio=True, size_bytes=1_000_000, smartcut_applied=False,
    )
    base.update(kw)
    return evaluate_clip_qa(**base)


def test_healthy_clip_passes():
    assert _ev()["ok"] is True


def test_empty_file_flagged():
    r = _ev(size_bytes=100)
    assert not r["ok"]
    assert any("empty" in i for i in r["issues"])


def test_missing_audio_flagged():
    r = _ev(has_audio=False)
    assert not r["ok"]
    assert any("audio" in i for i in r["issues"])


def test_zero_duration_flagged():
    r = _ev(actual_duration=0.0)
    assert not r["ok"]


def test_too_long_always_wrong():
    r = _ev(actual_duration=30.0, expected_duration=12.0)
    assert not r["ok"]
    assert any("longer" in i for i in r["issues"])


def test_too_short_wrong_without_smartcut():
    r = _ev(actual_duration=1.0, expected_duration=12.0, smartcut_applied=False)
    assert not r["ok"]
    assert any("shorter" in i for i in r["issues"])


def test_too_short_ok_with_smartcut():
    # Smart Cut legitimately removes silence → a short output is expected.
    r = _ev(actual_duration=1.0, expected_duration=12.0, smartcut_applied=True)
    assert r["ok"] is True


def test_missing_metrics_are_lenient():
    r = evaluate_clip_qa(
        actual_duration=None, expected_duration=None,
        has_audio=True, size_bytes=None,
    )
    assert r["ok"] is True
