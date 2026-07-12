"""Host-unit tests for cut_ops — word-boundary snapping + audio-fade filter.

Pure module (no cv2/ffmpeg), so these run in the fast `not integration` suite.
"""
from clippyme.pipeline.cut_ops import (
    audio_fade_filter,
    flatten_words,
    snap_clip_to_words,
    snap_clip_to_sentences,
    sentence_boundaries,
    refine_edges_to_silence,
    _is_sentence_final,
)


def _t(words):
    return {"segments": [{"words": words}]}


# --- flatten_words ----------------------------------------------------------

def test_flatten_orders_and_drops_untimed():
    t = {"segments": [
        {"words": [{"start": 2.0, "end": 2.5, "word": "b"}]},
        {"words": [
            {"start": 0.0, "end": 0.4, "word": "a"},
            {"word": "no_timing"},                       # dropped
            {"start": "x", "end": 1.0, "word": "bad"},   # dropped
        ]},
    ]}
    out = flatten_words(t)
    assert [w["word"] for w in out] == ["a", "b"]


def test_flatten_empty():
    assert flatten_words(None) == []
    assert flatten_words({}) == []


# --- snap_clip_to_words -----------------------------------------------------

def test_snap_pulls_edges_to_word_boundaries_and_pads():
    words = [
        {"start": 1.00, "end": 1.40, "word": "hello"},
        {"start": 1.45, "end": 1.90, "word": "there"},
        {"start": 5.00, "end": 5.50, "word": "bye"},
    ]
    # Raw edges land mid-word; expect snap to word.start / word.end + pad.
    s, e = snap_clip_to_words(1.03, 5.46, words, pre_pad=0.05, post_pad=0.08)
    assert abs(s - (1.00 - 0.05)) < 1e-6   # snapped to "hello".start - pre_pad
    assert abs(e - (5.50 + 0.08)) < 1e-6   # snapped to "bye".end + post_pad


def test_snap_keeps_raw_edge_when_no_boundary_within_max_snap():
    words = [{"start": 10.0, "end": 10.5, "word": "far"}]
    # Edges nowhere near the only word → keep raw, only padding applied.
    s, e = snap_clip_to_words(1.0, 2.0, words, pre_pad=0.05, post_pad=0.08, max_snap=0.5)
    assert abs(s - max(0.0, 1.0 - 0.05)) < 1e-6
    assert abs(e - (2.0 + 0.08)) < 1e-6


def test_snap_no_words_is_pad_only():
    s, e = snap_clip_to_words(3.0, 9.0, [], pre_pad=0.05, post_pad=0.08)
    assert abs(s - 2.95) < 1e-6
    assert abs(e - 9.08) < 1e-6


def test_snap_clamps_to_zero_and_source_duration():
    words = [{"start": 0.02, "end": 0.10, "word": "x"}]
    s, e = snap_clip_to_words(0.03, 0.09, words, source_duration=0.12)
    assert s >= 0.0
    assert e <= 0.12


def test_snap_never_inverts():
    # Degenerate: end <= start returns unchanged.
    assert snap_clip_to_words(5.0, 5.0, []) == (5.0, 5.0)
    assert snap_clip_to_words(5.0, 4.0, []) == (5.0, 4.0)


# --- audio_fade_filter ------------------------------------------------------

def test_fade_filter_shape():
    f = audio_fade_filter(2.0, fade=0.03)
    assert "afade=t=in:st=0:d=0.03" in f
    assert "afade=t=out:st=1.9700:d=0.03" in f


def test_fade_filter_too_short_is_empty():
    assert audio_fade_filter(0.05, fade=0.03) == ""   # < fade*2
    assert audio_fade_filter(0.0) == ""
    assert audio_fade_filter(-1.0) == ""


# --- _is_sentence_final (false-friend guard) --------------------------------

def test_sentence_final_true_cases():
    for w in ("world.", "Davvero?!", "wow…", "Stop!", "really?"):
        assert _is_sentence_final(w) is True, w


def test_sentence_final_false_cases():
    # abbreviations, initials, decimals, acronyms, audio events, bare words
    for w in ("Dr.", "etc.", "U.", "U.S.", "p.m.", "3.", "3.5", "1,000.",
              "(laughter)", "hello", "", "  "):
        assert _is_sentence_final(w) is False, w


# --- sentence_boundaries ----------------------------------------------------

def _sw(word, s, e):
    return {"word": word, "start": s, "end": e}


def test_sentence_boundaries_splits_on_terminators():
    words = [
        _sw("Hi", 0.0, 0.3), _sw("there.", 0.3, 0.7),   # sentence 1 ends @0.7
        _sw("Next", 1.0, 1.3), _sw("one.", 1.3, 1.7),   # sentence 2 onset @1.0
    ]
    onsets, ends = sentence_boundaries(words)
    assert onsets == [0.0, 1.0]
    assert ends == [0.7, 1.7]


def test_sentence_boundaries_no_punctuation_is_empty_ends():
    words = [_sw("no", 0.0, 0.3), _sw("punctuation", 0.3, 0.9)]
    onsets, ends = sentence_boundaries(words)
    assert onsets == [0.0]   # first word always an onset
    assert ends == []        # nothing terminal → callers fall back to word-snap


# --- snap_clip_to_sentences -------------------------------------------------

def _para():
    # Three sentences, contiguous words with punctuation.
    return [
        _sw("Today", 10.0, 10.4), _sw("I", 10.4, 10.5), _sw("learned.", 10.5, 11.0),
        _sw("It", 12.0, 12.2), _sw("changed", 12.2, 12.7), _sw("everything.", 12.7, 13.4),
        _sw("You", 20.0, 20.3), _sw("should", 20.3, 20.7), _sw("too.", 20.7, 21.0),
    ]


def test_sentence_snap_extends_start_back_and_end_forward():
    words = _para()
    # Raw clip opens mid-sentence-2 ("changed everything") and ends mid-word.
    # word-snap edges would still sit mid-sentence; sentence snap pulls start
    # back to "It" onset (12.0) and end forward to "everything." (13.4).
    s, e, path = snap_clip_to_sentences(
        12.3, 13.0, words, word_start=12.2, word_end=13.0,
    )
    assert path == "sentence"
    assert abs(s - (12.0 - 0.05)) < 1e-6     # onset 12.0 - pre_pad
    assert abs(e - (13.4 + 0.08)) < 1e-6     # final end 13.4 + post_pad


def test_sentence_snap_falls_back_to_word_when_no_punctuation():
    words = [_sw("no", 0.0, 0.3), _sw("stops", 0.3, 0.9), _sw("here", 0.9, 1.4)]
    s, e, path = snap_clip_to_sentences(
        0.1, 1.2, words, word_start=0.05, word_end=1.28,
    )
    assert path == "word"
    assert (s, e) == (0.05, 1.28)


def test_sentence_snap_end_clamped_by_neighbor_falls_back():
    words = _para()
    # Forward end extension to 13.4 would cross a neighbour starting at 13.1 →
    # sentence_end clamped to 13.1; with the word_end fallback the function
    # must not overlap the neighbour.
    s, e, path = snap_clip_to_sentences(
        12.3, 13.0, words, word_start=12.2, word_end=13.0, neighbor_start=13.1,
    )
    assert e <= 13.1
    assert s < e


def test_sentence_snap_respects_max_duration():
    words = _para()
    # A tiny max_duration forces giving up the forward extension (cheaper start
    # move survives first); result must never exceed the cap.
    s, e, path = snap_clip_to_sentences(
        12.3, 13.0, words, word_start=12.2, word_end=13.0, max_duration=1.0,
    )
    assert (e - s) <= 1.0 + 1e-9


def test_sentence_snap_never_worse_than_word_edges():
    # No usable words at all → word edges returned verbatim.
    s, e, path = snap_clip_to_sentences(
        5.0, 9.0, [], word_start=4.95, word_end=9.08,
    )
    assert (s, e, path) == (4.95, 9.08, "word")


# --- refine_edges_to_silence (waveform polish) ------------------------------

def test_silence_refine_snaps_start_to_trough_end_and_end_to_trough_start():
    # Silence troughs: one ending just before the clip start, one starting just
    # after the clip end. Start snaps to first trough's END - lead; end snaps to
    # second trough's START + tail.
    silences = [(9.7, 10.0), (20.0, 20.6)]
    s, e, path = refine_edges_to_silence(
        10.05, 19.95, silences, lead=0.04, tail=0.06, window=0.35,
    )
    assert path == "silence"
    assert abs(s - (10.0 - 0.04)) < 1e-6   # trough end - lead
    assert abs(e - (20.0 + 0.06)) < 1e-6   # trough start + tail


def test_silence_refine_no_trough_in_window_is_noop():
    silences = [(0.0, 0.5), (100.0, 100.5)]
    s, e, path = refine_edges_to_silence(10.0, 20.0, silences, window=0.35)
    assert (s, e, path) == (10.0, 20.0, "none")


def test_silence_refine_empty_list_is_noop():
    assert refine_edges_to_silence(10.0, 20.0, []) == (10.0, 20.0, "none")


def test_silence_refine_respects_neighbor_and_source_clamps():
    silences = [(9.7, 10.0), (20.0, 20.6)]
    # neighbour_start caps the end below the trough+tail; source caps too.
    s, e, path = refine_edges_to_silence(
        10.05, 19.95, silences, neighbor_start=20.02, source_duration=25.0,
    )
    assert e <= 20.02
    assert s < e


def test_silence_refine_never_inverts():
    # neighbour_start clamps the end BELOW the refined start → would invert, so
    # the original edges are returned unchanged (never a collapsed clip).
    silences = [(9.7, 10.0)]   # start would snap to ~9.96
    s, e, path = refine_edges_to_silence(
        10.05, 19.95, silences, neighbor_start=9.5,
    )
    assert (s, e, path) == (10.05, 19.95, "none")
    assert e > s


# --- stage-2 polish pre-screen helpers --------------------------------------

def test_parse_margin_seconds_variants():
    from clippyme.pipeline.cut_ops import parse_margin_seconds

    assert parse_margin_seconds("0.2sec") == 0.2
    assert parse_margin_seconds("0.2s") == 0.2
    assert parse_margin_seconds("0.35") == 0.35
    assert parse_margin_seconds(" 1 second ") == 1.0
    assert parse_margin_seconds("garbage") == 0.2   # default
    assert parse_margin_seconds("") == 0.2
    assert parse_margin_seconds("-3sec") == 0.0     # negative clamps


def test_predict_polish_saving_subtracts_double_margin():
    from clippyme.pipeline.cut_ops import predict_polish_saving

    # 1.0s silence with 0.2s margin → 0.6s removable; 0.3s silence → nothing.
    silences = [(0.0, 1.0), (5.0, 5.3)]
    assert abs(predict_polish_saving(silences, 0.2) - 0.6) < 1e-9


def test_predict_polish_saving_edge_cases():
    from clippyme.pipeline.cut_ops import predict_polish_saving

    assert predict_polish_saving([], 0.2) == 0.0
    assert predict_polish_saving(None, 0.2) == 0.0
    # Silence exactly 2*margin long contributes zero, never negative.
    assert predict_polish_saving([(0.0, 0.4)], 0.2) == 0.0
    # Garbage tuples are skipped, valid ones still counted.
    assert abs(predict_polish_saving([("x", "y"), (0.0, 1.0)], 0.2) - 0.6) < 1e-9


# --- snap orchestration (moved from main.py __main__) -------------------------
# compute_neighbor_bounds + snap_clips_to_transcript used to be inline script
# code in the pipeline entrypoint with zero unit coverage. These tests pin the
# exact behaviours that mattered there.

from clippyme.pipeline.cut_ops import (  # noqa: E402
    compute_neighbor_bounds,
    snap_clips_to_transcript,
)

_WORDS = [
    {"start": 0.0, "end": 0.4, "word": "Hello"},
    {"start": 0.5, "end": 0.9, "word": "world."},
    {"start": 5.0, "end": 5.4, "word": "Second"},
    {"start": 5.5, "end": 5.9, "word": "sentence."},
]


def test_neighbor_bounds_score_sorted_list():
    # Shorts are score-sorted: list order is NOT time order.
    raw = [(10.0, 20.0), (30.0, 40.0), (0.0, 5.0), None]
    # Clip 0: next-in-time starts at 30, previous-in-time ends at 5.
    assert compute_neighbor_bounds(raw, 0) == (30.0, 5.0)
    # Clip 1 (latest): nothing follows; nearest preceding end is 20.
    assert compute_neighbor_bounds(raw, 1) == (None, 20.0)
    # Clip 2 (earliest): nearest following start is 10; nothing precedes.
    assert compute_neighbor_bounds(raw, 2) == (10.0, None)
    # Malformed entry: no bounds at all.
    assert compute_neighbor_bounds(raw, 3) == (None, None)


def test_snap_clips_mutates_in_place_and_reports_events():
    shorts = [{"start": 0.1, "end": 0.8}]
    events = snap_clips_to_transcript(
        shorts, _WORDS, source_duration=60.0, default_reframe_mode="subject")
    assert shorts[0]["reframe_mode"] == "subject"
    assert len(events) == 1
    ev = events[0]
    assert (ev.old_start, ev.old_end) == (0.1, 0.8)
    assert (shorts[0]["start"], shorts[0]["end"]) == (ev.new_start, ev.new_end)
    # Word/sentence snapping must land on the sentence, not drift into the
    # next one (which starts at 5.0).
    assert 0.0 <= shorts[0]["start"] < 0.5
    assert 0.9 <= shorts[0]["end"] < 5.0
    assert ev.path  # a non-empty snap path for observability


def test_snap_clips_without_word_timing_is_noop_but_sets_mode():
    shorts = [{"start": 3.0, "end": 9.0}, {"note": "malformed, no times"}]
    events = snap_clips_to_transcript(shorts, [], default_reframe_mode="auto")
    assert events == []
    assert shorts[0] == {"start": 3.0, "end": 9.0, "reframe_mode": "auto"}
    assert shorts[1]["reframe_mode"] == "auto"


def test_snap_clips_preserves_existing_reframe_mode():
    shorts = [{"start": 0.1, "end": 0.8, "reframe_mode": "disabled"}]
    snap_clips_to_transcript(shorts, _WORDS, default_reframe_mode="auto")
    assert shorts[0]["reframe_mode"] == "disabled"


def test_snap_clips_silence_stage_composes_path():
    # A silence trough right after the sentence end (word-snapped end ≈0.98):
    # stage 3 must nudge the edge and append its path segment.
    shorts = [{"start": 0.1, "end": 0.8}]
    events = snap_clips_to_transcript(
        shorts, _WORDS, source_duration=60.0,
        silences=[(1.0, 1.6)],
    )
    assert len(events) == 1
    assert "silence" in events[0].path
    assert "+" in events[0].path  # composed onto the sentence-stage path
    # End landed inside the trough (start + tail), before the next sentence.
    assert 1.0 <= shorts[0]["end"] <= 1.6


def test_snap_clips_neighbor_clamp_prevents_overlap():
    # Two clips adjacent in time (listed score-first): the earlier clip's
    # forward sentence extension must never cross the later clip's raw start.
    shorts = [
        {"start": 5.1, "end": 5.7},   # higher score, later in time
        {"start": 0.1, "end": 0.8},   # earlier in time
    ]
    snap_clips_to_transcript(shorts, _WORDS, source_duration=60.0)
    assert shorts[1]["end"] <= 5.1
