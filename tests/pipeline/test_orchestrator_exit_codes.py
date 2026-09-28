"""The orchestrator's exit-code contract with the job runner.

``run()`` maps how an attempt ended to the exit code the runner retries on and
to the ``resumable`` flag restart recovery reads from the runtime state:

* deterministic rejections — preflight quota, bad input (ValueError), missing
  source (FileNotFoundError) → exit 2 (never retried), not resumable;
* anything else (network, crash, all clips failed) → exit 1 (retried from the
  checkpoints), resumable.

``clippyme.pipeline.main`` (cv2/torch) is replaced by an empty stand-in; the
first stage raises, so no ffmpeg, network or Gemini call is ever made.
"""
import sys
import types

import pytest

import clippyme.pipeline as pipeline
from clippyme.domain.runtime_state import load_runtime_state
from clippyme.pipeline import orchestrator
from clippyme.pipeline.preflight import PreflightRejected


@pytest.fixture
def fake_main(monkeypatch):
    legacy = types.ModuleType("clippyme.pipeline.main")
    monkeypatch.setitem(sys.modules, "clippyme.pipeline.main", legacy)
    monkeypatch.setattr(pipeline, "main", legacy, raising=False)
    return legacy


def _run(tmp_path, *extra):
    source = tmp_path / "in.mp4"
    source.write_bytes(b"video")
    out = tmp_path / "job"
    return orchestrator.run(["-i", str(source), "-o", str(out), *extra]), str(out)


@pytest.mark.parametrize("exc, code, resumable", [
    (PreflightRejected("estimated Gemini cost exceeds the limit"), 2, False),
    (ValueError("unsupported input"), 2, False),
    (FileNotFoundError("Input file not found or empty"), 2, False),
    (RuntimeError("all candidate clips failed rendering or QA"), 1, True),
    (OSError("connection reset"), 1, True),
])
def test_failure_maps_to_exit_code_and_resumable_flag(tmp_path, monkeypatch, fake_main,
                                                      exc, code, resumable):
    def fail(*args, **kwargs):
        raise exc

    monkeypatch.setattr(orchestrator, "_prepare_input", fail)
    rc, out = _run(tmp_path)
    state = load_runtime_state(out)
    assert rc == code
    assert state["stage"] == "failed"
    assert state["resumable"] is resumable
    assert str(exc) in state["last_error"]


def test_invalid_model_override_is_a_deterministic_rejection(tmp_path, monkeypatch, fake_main):
    """Real argv validation, before any stage: exit 2, not resumable."""
    reached = []
    monkeypatch.setattr(orchestrator, "_prepare_input", lambda *a, **k: reached.append(1))
    rc, out = _run(tmp_path, "--model", "not-a-gemini-model")
    assert rc == 2 and reached == []
    assert load_runtime_state(out)["resumable"] is False
