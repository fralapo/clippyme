"""Host-unit tests for the pure lexical TextTiling fallback (no cv2/torch).

Pins the math ported from ClipsAI (gap → smooth → depth → boundary) and the
``find_topic_clips`` duration shaping used as ClippyMe's no-AI whole-video
fallback. See docs/research/clipsai.md.
"""
from collections import Counter

from clippyme.pipeline import texttiling_ops as tt


# --- primitives ------------------------------------------------------------

def test_tokenize_lowercases_and_drops_stopwords():
    toks = tt.tokenize("The Quick brown FOX and the dog")
    assert toks == ["quick", "brown", "fox", "dog"]  # the/and removed, lowercased


def test_tokenize_drops_digits_and_punctuation():
    assert tt.tokenize("hello, world! 123 v2") == ["hello", "world", "v"]


def test_cosine_identical_and_disjoint():
    a = Counter(["space", "star", "star"])
    assert abs(tt._cosine(a, a) - 1.0) < 1e-9
    assert tt._cosine(a, Counter(["cake", "flour"])) == 0.0
    assert tt._cosine(a, Counter()) == 0.0


def test_gap_scores_length_is_n_minus_1():
    blocks = [["a"], ["a"], ["b"], ["b"]]
    assert len(tt.gap_scores(blocks, k=1)) == 3
    assert tt.gap_scores([["a"]], k=1) == []


def test_gap_scores_low_at_topic_switch():
    # identical vocab within topic → 1.0; disjoint across the switch → 0.0
    blocks = [["x"], ["x"], ["y"], ["y"]]
    g = tt.gap_scores(blocks, k=1)
    assert g[0] == 1.0 and g[2] == 1.0  # within-topic gaps
    assert g[1] == 0.0  # the x→y boundary


def test_smooth_noop_below_width():
    assert tt.smooth_scores([1.0, 2.0], 3) == [1.0, 2.0]  # series shorter than width
    assert tt.smooth_scores([1.0, 2.0, 3.0], 2) == [1.0, 2.0, 3.0]  # width < 3


def test_smooth_averages_window():
    out = tt.smooth_scores([0.0, 3.0, 0.0, 3.0, 0.0], 3)
    # edge-clamped centered mean of width 3
    assert round(out[2], 3) == 2.0  # (3+0+3)/3
    assert len(out) == 5


def test_depth_scores_marks_valley():
    gaps = [1.0, 1.0, 0.0, 1.0, 1.0]
    depths = tt.depth_scores(gaps)
    assert depths[2] == 2.0  # (1-0)+(1-0) deepest at the valley
    assert max(depths) == depths[2]


def test_identify_boundaries_picks_peak_above_cutoff():
    depths = [0.0, 0.0, 2.0, 0.0, 0.0]
    assert tt.identify_boundaries(depths, "high") == [2]


def test_identify_boundaries_empty():
    assert tt.identify_boundaries([], "high") == []


def test_segment_indices_covers_all_blocks_contiguously():
    blocks = [["x"]] * 4 + [["y"]] * 4
    spans = tt.segment_indices(blocks, k=2)
    # contiguous, non-overlapping, union == full range
    assert spans[0][0] == 0 and spans[-1][1] == len(blocks) - 1
    for (a, b) in spans:
        assert a <= b
    for (prev, nxt) in zip(spans, spans[1:]):
        assert nxt[0] == prev[1] + 1


def test_segment_indices_short_inputs():
    assert tt.segment_indices([], k=7) == []
    assert tt.segment_indices([["a"]], k=7) == [(0, 0)]


# --- find_topic_clips end-to-end ------------------------------------------

def _segs(texts, dur):
    out, t = [], 0.0
    for txt in texts:
        out.append({"text": txt, "start": t, "end": t + dur})
        t += dur
    return out


def test_find_topic_clips_too_few_segments_returns_empty():
    assert tt.find_topic_clips(_segs(["hello world"], 10), ) == []
    assert tt.find_topic_clips([], ) == []


def test_find_topic_clips_splits_at_topic_change():
    cooking = ["recipe flour butter sugar oven bake cake dough"] * 6
    space = ["galaxy nebula telescope orbit planet rocket star comet"] * 6
    clips = tt.find_topic_clips(_segs(cooking + space, 10),
                                min_clip_duration=15, max_clip_duration=90)
    assert len(clips) >= 2
    # clips sorted by start, each within bounds, non-overlapping
    for c in clips:
        assert 15 <= (c["end"] - c["start"]) <= 90
    for a, b in zip(clips, clips[1:]):
        assert a["start"] < b["start"]
        assert a["end"] <= b["start"] + 1e-6


def test_find_topic_clips_merges_short_span_forward():
    # 3 short blocks (9s) then 6 long blocks (60s); the 9s span < min → merged
    short = ["alpha beta gamma delta"] * 3
    long = ["zeta eta theta iota"] * 6
    segs = _segs(short, 3) + _segs(long, 10)
    # rebuild monotonic timeline
    t = 0.0
    for s in segs:
        d = s["end"] - s["start"]
        s["start"], s["end"] = t, t + d
        t += d
    clips = tt.find_topic_clips(segs, min_clip_duration=15, max_clip_duration=120)
    assert clips, "expected at least one merged clip"
    assert all((c["end"] - c["start"]) >= 15 for c in clips)


def test_find_topic_clips_slices_overlong_monotopic_block():
    mono = ["interview question answer story detail example point"] * 12  # 120s
    clips = tt.find_topic_clips(_segs(mono, 10),
                                min_clip_duration=15, max_clip_duration=90)
    assert len(clips) >= 2  # 120s sliced into <=90s chunks
    for c in clips:
        assert (c["end"] - c["start"]) <= 90


def test_find_topic_clips_respects_max_clips_cap():
    blocks = []
    for i in range(40):
        word = f"topic{i}word uniq{i} term{i}"
        blocks.append(word)
    clips = tt.find_topic_clips(_segs(blocks, 20),
                                min_clip_duration=15, max_clip_duration=40, max_clips=5)
    assert len(clips) <= 5
