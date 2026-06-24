"""Semantic subtitle line-splitting (VideoLingo-ported idea).

Pure-function tests for the boundary-aware grouping in
``clippyme.domain.subtitles`` — no ffmpeg, no model load, host-runnable.
The grouping helpers turn flat word lists (Deepgram/Whisper shape) into
caption lines that break at sentence/clause boundaries instead of mid-phrase.
"""
from clippyme.domain.subtitles import (
    _ends_sentence,
    _ends_soft,
    _group_words,
    _group_words_by_count,
    _is_connector,
    _strip_ass_braces,
    generate_srt,
)


def test_strip_ass_braces_removes_override_blocks():
    assert _strip_ass_braces("{\\an8}hello") == "\\an8hello"
    assert _strip_ass_braces("plain") == "plain"
    assert _strip_ass_braces("") == ""
    assert _strip_ass_braces(None) == ""


def test_generate_srt_strips_libass_override_braces(tmp_path):
    # ASR-echoed on-screen text with libass override braces must not survive
    # into the SRT body (it would be interpreted as a directive at render).
    out = tmp_path / "out.srt"
    transcript = {"segments": [{"words": [
        {"word": "{\\an8}top", "start": 0.0, "end": 0.4},
        {"word": "secret}", "start": 0.4, "end": 0.9},
    ]}]}
    generate_srt(transcript, 0.0, 1.0, str(out))
    body = out.read_text(encoding="utf-8")
    assert "{" not in body and "}" not in body
    assert "an8top" in body


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


def _seq(*tokens):
    """Build a 0.4s-per-word sequence from bare strings."""
    out = []
    t = 0.0
    for tok in tokens:
        out.append(_w(tok, t, t + 0.4))
        t += 0.4
    return out


# --- glyph predicates ------------------------------------------------------

def test_ends_sentence_basic_and_trailing_quote():
    assert _ends_sentence("world.")
    assert _ends_sentence('done!"')        # closing quote after the mark
    assert _ends_sentence("davvero?")
    assert not _ends_sentence("world")
    assert not _ends_sentence("well,")


def test_ends_soft_only_clause_marks():
    assert _ends_soft("first,")
    assert _ends_soft("listen:")
    assert not _ends_soft("first")
    assert not _ends_soft("done.")


def test_is_connector_multilingual_and_punct_tolerant():
    assert _is_connector("and")
    assert _is_connector("BUT")           # case-insensitive
    assert _is_connector("perché")        # Italian, accented
    assert _is_connector("because,")      # strips trailing punctuation
    assert _is_connector("und")           # German
    assert not _is_connector("banana")


# --- word_group mode (small N-word karaoke chunks) -------------------------

def test_count_mode_snaps_to_sentence_end_early():
    # "time." ends a sentence → it must close its chunk even though count=3,
    # so "The next" starts fresh instead of "time. The".
    words = _seq("all", "the", "time.", "The", "next", "one")
    groups = _group_words_by_count(words, 0.0, count=3)
    texts = [" ".join(w["word"] for w in g) for g in groups]
    assert texts == ["all the time.", "The next one"]


def test_count_mode_comma_closes_one_word_early():
    # count=3, but a comma on the 2nd word (>= count-1) closes the chunk early.
    words = _seq("hey", "wait,", "we", "go", "now")
    groups = _group_words_by_count(words, 0.0, count=3)
    texts = [" ".join(w["word"] for w in g) for g in groups]
    assert texts[0] == "hey wait,"


def test_count_mode_plain_falls_back_to_fixed_chunks():
    words = _seq("one", "two", "three", "four", "five")
    groups = _group_words_by_count(words, 0.0, count=3)
    assert [len(g) for g in groups] == [3, 2]


# --- full_line mode (semantic boundaries) ----------------------------------

def test_full_line_never_merges_two_sentences():
    words = _seq("short", "one.", "and", "another", "short", "two.")
    groups = _group_words(words, 0.0, max_chars=200, max_duration=999)
    texts = [" ".join(w["word"] for w in g) for g in groups]
    # Despite a huge char budget, the period forces a split.
    assert texts == ["short one.", "and another short two."]


def test_full_line_breaks_before_connector_when_line_is_full():
    # Long enough to pass the soft-length gate, then a connector opens a clause.
    words = _seq("this", "is", "a", "fairly", "long", "spoken", "clause",
                 "and", "then", "it", "keeps", "going")
    groups = _group_words(words, 0.0, max_chars=40, max_duration=999, soft_ratio=0.5)
    texts = [" ".join(w["word"] for w in g) for g in groups]
    assert any(t.startswith("and") for t in texts), texts
    # the connector must START a line, never dangle at a line's tail
    assert not any(t.endswith("and") for t in texts), texts


def test_full_line_hard_char_cap_still_enforced():
    words = _seq(*(["word"] * 30))  # no punctuation, no connectors
    groups = _group_words(words, 0.0, max_chars=25, max_duration=999)
    for g in groups:
        line = " ".join(w["word"] for w in g)
        assert len(line) <= 25 + len("word"), line  # cap honoured within one word


def test_full_line_hard_duration_cap_still_enforced():
    words = [_w("w", i * 2.0, i * 2.0 + 1.9) for i in range(6)]  # 2s apart
    groups = _group_words(words, 0.0, max_chars=999, max_duration=3.0)
    assert len(groups) > 1  # duration ceiling forces splits despite char room


def test_full_line_short_connector_does_not_shred_italian():
    # "e"/"o" are connectors but the soft gate (line must be >= soft_chars)
    # keeps a short Italian phrase intact.
    words = _seq("io", "e", "te")
    groups = _group_words(words, 0.0, max_chars=80, max_duration=999)
    assert len(groups) == 1
