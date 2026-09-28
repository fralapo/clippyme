"""``_run_preflight`` wiring: the budget gate sees every model a job can bill.

The estimator's math is covered in test_gemini_cost.py; this pins what the
orchestrator feeds it — the same primary / fallback / reformat-retry chains
``pipeline.main`` builds at run time (``build_model_chain`` over
``GEMINI_FALLBACK_MODELS``; ``GEMINI_RETRY_MODEL`` or the default), the
pipeline's own price table, the clip cap — and that the gate is enforced.
"""
import types

import pytest

from clippyme.jobs.runtime_state import RuntimeState
from clippyme.pipeline import orchestrator
from clippyme.pipeline.gemini_request import DEFAULT_RETRY_MODEL
from clippyme.pipeline.preflight import PreflightRejected

PRICES = {  # USD / 1M tokens — test table, not the real one
    "gemini-cheap": {"input": 0.1, "output": 0.4},
    "gemini-pricey": {"input": 10.0, "output": 40.0},
    "gemini-retry": {"input": 0.1, "output": 0.4},
    DEFAULT_RETRY_MODEL: {"input": 0.1, "output": 0.4},
}


@pytest.fixture
def preflight(monkeypatch, tmp_path):
    """Run the real _run_preflight on a 10-minute source; returns the
    PreflightInputs it built and the report it enforced."""
    for name in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODELS", "GEMINI_RETRY_MODEL",
                 "CLIPPYME_MAX_CLIPS", "CLIPPYME_MAX_ESTIMATED_COST_USD",
                 "CLIPPYME_MAX_DURATION_SECONDS", "CLIPPYME_MAX_INPUT_GB"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLIPPYME_MIN_FREE_DISK_GB", "0")
    monkeypatch.setattr(orchestrator.shutil, "disk_usage",
                        lambda path: types.SimpleNamespace(free=10**12))
    monkeypatch.setattr(orchestrator, "probe_media",
                        lambda path: {"duration": 600.0, "size_bytes": 1000,
                                      "width": 1920, "height": 1080})
    seen = {}
    real_build = orchestrator.build_preflight

    def build(inputs, **kwargs):
        seen["inputs"], seen["pricing"] = inputs, kwargs.get("pricing")
        seen["report"] = real_build(inputs, **kwargs)
        return seen["report"]

    monkeypatch.setattr(orchestrator, "build_preflight", build)
    legacy = types.SimpleNamespace(MODEL_PRICING=PRICES, CUDA_AVAILABLE=False)
    source = tmp_path / "in.mp4"
    source.write_bytes(b"video")

    def run(model=None):
        args = types.SimpleNamespace(model=model, aspect="9:16", skip_analysis=False)
        state = RuntimeState(str(tmp_path / "job"))
        orchestrator._run_preflight(args, str(source), str(tmp_path), state, legacy)
        return seen

    return run


def test_chains_prices_and_clip_cap_reach_the_estimate(preflight, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-cheap")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-pricey, gemini-cheap")
    monkeypatch.setenv("GEMINI_RETRY_MODEL", "gemini-retry")
    monkeypatch.setenv("CLIPPYME_MAX_CLIPS", "4")
    seen = preflight()
    inputs = seen["inputs"]
    assert inputs.model == "gemini-cheap"
    assert inputs.fallback_models == ("gemini-pricey",)       # primary de-duplicated
    assert inputs.retry_models == ("gemini-retry", "gemini-pricey", "gemini-cheap")
    assert inputs.max_clips == 4 and inputs.analysis_enabled
    assert seen["pricing"] is PRICES                           # the pipeline's own table


def test_model_override_wins_and_default_retry_model_is_used(preflight, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-pricey")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    inputs = preflight(model="gemini-cheap")["inputs"]
    assert inputs.model == "gemini-cheap"
    assert inputs.fallback_models == ()
    assert inputs.retry_models == (DEFAULT_RETRY_MODEL,)


def test_budget_gate_covers_a_pricier_fallback(preflight, monkeypatch):
    """Within budget on the primary alone, over it once the fallback that may
    serve the call is priced in → rejected before any spend."""
    monkeypatch.setenv("GEMINI_MODEL", "gemini-cheap")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    monkeypatch.setenv("CLIPPYME_MAX_ESTIMATED_COST_USD", "0.20")
    within = preflight()["report"]["estimated_cost_usd"]
    assert within is not None and within < 0.20

    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-pricey")
    with pytest.raises(PreflightRejected, match="exceeds"):
        preflight()


def test_budget_gate_fails_closed_on_an_unpriced_fallback(preflight, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-cheap")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-unknown")
    monkeypatch.setenv("CLIPPYME_MAX_ESTIMATED_COST_USD", "100")
    with pytest.raises(PreflightRejected, match="pricing unknown"):
        preflight()
