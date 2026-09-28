"""A retried attempt reuses the transcript and the clip plan it already paid for.

Each ``RuntimeState`` is re-read from disk, as the next attempt (a new
orchestrator process) would; ``legacy`` counts the billable calls
(transcription provider, Gemini).
"""
import types

from clippyme.jobs.runtime_state import RuntimeState
from clippyme.pipeline import orchestrator


class _Legacy:
    def __init__(self):
        self.transcribed = 0
        self.analyzed = 0

    def transcribe_video(self, path):
        self.transcribed += 1
        return {"segments": [{"start": 0.0, "end": 1.0, "text": "hi", "words": []}]}

    def get_viral_clips(self, transcript, duration, instructions=None):
        self.analyzed += 1
        return {"shorts": [{"start": 0.0, "end": 30.0, "title": "T"}]}


def _args():
    return types.SimpleNamespace(skip_analysis=False, url=None, instructions=None,
                                 monitor=False, aspect="9:16", reframe_mode="auto")


def test_next_attempt_reuses_the_transcript_checkpoint(tmp_path):
    legacy = _Legacy()
    first = orchestrator._load_or_transcribe(_args(), "in.mp4", RuntimeState(str(tmp_path)), legacy)
    again = orchestrator._load_or_transcribe(_args(), "in.mp4", RuntimeState(str(tmp_path)), legacy)
    assert again == first and legacy.transcribed == 1

    # A torn checkpoint is not trusted: transcribe again rather than resume on it.
    (tmp_path / ".clippyme_checkpoint" / "transcript.json").write_text("{", encoding="utf-8")
    orchestrator._load_or_transcribe(_args(), "in.mp4", RuntimeState(str(tmp_path)), legacy)
    assert legacy.transcribed == 2


def test_next_attempt_reuses_the_clip_plan_without_a_second_gemini_call(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPYME_SILENCE_SNAP", "0")
    monkeypatch.delenv("CLIPPYME_MAX_CLIPS", raising=False)
    legacy = _Legacy()
    transcript = {"segments": []}

    def analyze():
        return orchestrator._load_or_analyze(_args(), "in.mp4", "vid", str(tmp_path), 60.0,
                                             transcript, RuntimeState(str(tmp_path)), legacy)

    plan, metadata_file = analyze()
    reused, reused_file = analyze()
    assert legacy.analyzed == 1
    assert reused_file == metadata_file
    assert reused["shorts"] == plan["shorts"]
