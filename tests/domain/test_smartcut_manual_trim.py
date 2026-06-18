"""Manual transcript-trim engine (flycut-caption-ported idea).

Pure/host-runnable — exercises the interval arithmetic + analyze_silences
manual path without ffmpeg. See docs/flycut-caption-analysis.md.
"""
from clippyme.domain import smartcut as sc


# --- normalize_drop_ranges -------------------------------------------------

def test_normalize_accepts_pairs_and_dicts():
    assert sc.normalize_drop_ranges([[1, 2], [3.5, 4.5]]) == [(1.0, 2.0), (3.5, 4.5)]
    assert sc.normalize_drop_ranges([{"start": 1, "end": 2}]) == [(1.0, 2.0)]


def test_normalize_discards_garbage_and_empty():
    assert sc.normalize_drop_ranges(None) == []
    assert sc.normalize_drop_ranges([]) == []
    # bad span (end <= start), wrong types, missing keys → all dropped
    assert sc.normalize_drop_ranges([[5, 5], [4, 3], "x", {"start": 1}]) == []


def test_normalize_caps_count():
    out = sc.normalize_drop_ranges([[i, i + 0.5] for i in range(1000)], max_ranges=10)
    assert len(out) == 10


# --- subtract_ranges -------------------------------------------------------

def test_subtract_splits_interior_drop():
    assert sc.subtract_ranges([(0, 10)], [(3, 5)]) == [(0, 3), (5, 10)]


def test_subtract_trims_edges_and_drops_fully_covered():
    assert sc.subtract_ranges([(0, 10)], [(0, 2)]) == [(2, 10)]
    assert sc.subtract_ranges([(0, 10)], [(8, 10)]) == [(0, 8)]
    assert sc.subtract_ranges([(2, 6)], [(0, 10)]) == []  # whole span cut


def test_subtract_multiple_drops_across_segments():
    keep = [(0, 5), (10, 15)]
    drops = [(1, 2), (12, 13)]
    assert sc.subtract_ranges(keep, drops) == [(0, 1), (2, 5), (10, 12), (13, 15)]


def test_subtract_noop_returns_clean_copy():
    assert sc.subtract_ranges([(0, 5), (5, 5)], []) == [(0, 5)]


# --- analyze_silences manual path ------------------------------------------

def _transcript(words):
    return {"language": "en", "segments": [{"words": words}]}


def test_analyze_manual_drop_on_clean_speech():
    # No fillers, no gaps → auto keeps the whole clip; manual drop cuts a span.
    words = [{"word": "one", "start": 0.0, "end": 1.0},
             {"word": "two", "start": 1.0, "end": 2.0},
             {"word": "three", "start": 2.0, "end": 3.0}]
    segs, stats = sc.analyze_silences(_transcript(words), 0, 3.0, "en",
                                      drop_ranges=[[1.0, 2.0]])
    assert stats["manual_drops"] == 1
    assert stats["time_saved"] >= 0.9
    # the [1,2] span is gone
    assert all(not (s < 2.0 and e > 1.0 and s >= 1.0 and e <= 2.0) for s, e in segs)


def test_analyze_manual_drop_without_word_timing():
    # Segment-level transcript (no per-word timestamps): auto no-ops, but a
    # manual span is still cut against the whole clip.
    transcript = {"language": "en", "segments": [{"text": "hello world"}]}
    segs, stats = sc.analyze_silences(transcript, 0, 10.0, "en",
                                      drop_ranges=[[4, 6]])
    assert segs == [(0.0, 4.0), (6.0, 10.0)]
    assert stats["manual_drops"] == 1
    assert stats["time_saved"] == 2.0


def test_analyze_no_drops_is_unchanged_shape():
    words = [{"word": "a", "start": 0.0, "end": 1.0},
             {"word": "b", "start": 1.0, "end": 2.0}]
    segs, stats = sc.analyze_silences(_transcript(words), 0, 2.0, "en")
    assert "manual_drops" not in stats
    assert segs and segs[0][0] == 0.0


# --- clip_transcript_segments (manual-trim UI feed) ------------------------

def test_clip_transcript_segments_word_level_relative_times():
    t = {"language": "en", "segments": [
        {"words": [{"word": "hello", "start": 10.0, "end": 10.5},
                   {"word": "world", "start": 10.5, "end": 11.0}]},
        {"words": [{"word": "second", "start": 12.0, "end": 12.4},
                   {"word": "line", "start": 12.4, "end": 12.9}]},
    ]}
    segs = sc.clip_transcript_segments(t, 10.0, 13.0)
    assert [s["text"] for s in segs] == ["hello world", "second line"]
    assert segs[0]["start"] == 0.0 and segs[0]["end"] == 1.0
    assert segs[1]["start"] == 2.0  # 12.0 - 10.0
    assert [s["index"] for s in segs] == [0, 1]


def test_clip_transcript_segments_trims_straddling_segment():
    # Only the words inside the clip window contribute.
    t = {"language": "en", "segments": [
        {"words": [{"word": "before", "start": 4.0, "end": 4.5},
                   {"word": "inside", "start": 5.2, "end": 5.6}]},
    ]}
    segs = sc.clip_transcript_segments(t, 5.0, 8.0)
    assert len(segs) == 1
    assert segs[0]["text"] == "inside"
    assert segs[0]["start"] == 0.2  # 5.2 - 5.0


def test_clip_transcript_segments_segment_level_fallback():
    t = {"segments": [{"text": "no word timing", "start": 3.0, "end": 6.0}]}
    segs = sc.clip_transcript_segments(t, 2.0, 10.0)
    assert segs == [{"index": 0, "text": "no word timing", "start": 1.0, "end": 4.0}]
