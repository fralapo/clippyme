"""Host-unit tests for cut_ops — word-boundary snapping + audio-fade filter.

Pure module (no cv2/ffmpeg), so these run in the fast `not integration` suite.
"""
from clippyme.pipeline.cut_ops import (
    audio_fade_filter,
    flatten_words,
    snap_clip_to_words,
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
