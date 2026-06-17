"""Tests for clippyme.pipeline.diarization (pure overlap logic, host-runnable)."""
from clippyme.pipeline.diarization import assign_speakers_to_words


def test_no_words_or_turns_is_noop():
    words = []
    assign_speakers_to_words(words, [(0, 1, 0)])
    assert words == []
    w = [{"start": 0, "end": 1}]
    assign_speakers_to_words(w, [])
    assert "speaker" not in w[0]


def test_assigns_by_max_overlap():
    words = [{"start": 0.0, "end": 1.0}, {"start": 5.0, "end": 6.0}]
    turns = [(0.0, 2.0, 0), (4.0, 7.0, 1)]
    assign_speakers_to_words(words, turns)
    assert words[0]["speaker"] == 0
    assert words[1]["speaker"] == 1


def test_word_in_gap_gets_no_speaker():
    words = [{"start": 2.5, "end": 2.9}]  # between turns
    turns = [(0.0, 2.0, 0), (3.0, 5.0, 1)]
    assign_speakers_to_words(words, turns)
    assert "speaker" not in words[0]


def test_overlapping_turns_pick_larger_overlap():
    # word [1,4]; turn A overlaps [1,2]=1.0, turn B overlaps [2,4]=2.0 -> B wins
    words = [{"start": 1.0, "end": 4.0}]
    turns = [(0.0, 2.0, 7), (2.0, 6.0, 9)]
    assign_speakers_to_words(words, turns)
    assert words[0]["speaker"] == 9


def test_unsorted_words_are_handled():
    words = [{"start": 5.0, "end": 6.0}, {"start": 0.0, "end": 1.0}]
    turns = [(0.0, 2.0, 0), (4.0, 7.0, 1)]
    assign_speakers_to_words(words, turns)
    by_start = {w["start"]: w.get("speaker") for w in words}
    assert by_start[0.0] == 0
    assert by_start[5.0] == 1
