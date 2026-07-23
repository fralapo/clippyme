from clippyme.pipeline.gemini_parser import drop_wordless_clips

WORDS = [{"start": 10.0, "end": 10.5, "word": "ciao"},
         {"start": 11.0, "end": 11.4, "word": "mondo"}]


def test_keeps_clip_overlapping_words():
    clips = [{"start": 9.0, "end": 12.0}]
    assert drop_wordless_clips(clips, WORDS) == clips


def test_drops_clip_with_no_words_in_range():
    clips = [{"start": 100.0, "end": 130.0}]   # hallucinated timestamp
    assert drop_wordless_clips(clips, WORDS) == []


def test_empty_words_drops_all():
    assert drop_wordless_clips([{"start": 0, "end": 30}], []) == []


# build_viral_prompt emits TOON-abbreviated words {"w","s","e"} — the ACTUAL
# shape passed in the pipeline. Regression guard: this must not KeyError.
TOON_WORDS = [{"w": "ciao", "s": 10.0, "e": 10.5},
              {"w": "mondo", "s": 11.0, "e": 11.4}]


def test_keeps_clip_overlapping_toon_words():
    clips = [{"start": 9.0, "end": 12.0}]
    assert drop_wordless_clips(clips, TOON_WORDS) == clips


def test_drops_clip_no_toon_words_in_range():
    assert drop_wordless_clips([{"start": 100.0, "end": 130.0}], TOON_WORDS) == []


def test_words_missing_timing_are_skipped_not_raised():
    words = [{"w": "x"}, {"s": 10.0, "e": 10.5, "w": "ciao"}]
    assert drop_wordless_clips([{"start": 9.0, "end": 12.0}], words) == [{"start": 9.0, "end": 12.0}]
