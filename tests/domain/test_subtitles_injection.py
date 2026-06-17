"""Regression tests for ASS-injection guards in generate_ass_karaoke."""
import pytest

from clippyme.domain.subtitles import generate_ass_karaoke


def _transcript(word):
    return {"segments": [{"words": [
        {"word": word, "start": 0.0, "end": 0.5},
    ]}]}


def test_karaoke_rejects_malicious_font_name(tmp_path):
    out = tmp_path / "x.ass"
    with pytest.raises(ValueError):
        generate_ass_karaoke(
            transcript=_transcript("hi"),
            clip_start=0.0, clip_end=1.0,
            output_path=str(out),
            font_name="Arial,100,&H0&\\pos(0,0)",  # injection attempt
        )


def test_karaoke_strips_override_braces_from_words(tmp_path):
    out = tmp_path / "y.ass"
    ok = generate_ass_karaoke(
        transcript=_transcript("{\\pos(0,0)}evil"),
        clip_start=0.0, clip_end=1.0,
        output_path=str(out),
    )
    assert ok
    content = out.read_text(encoding="utf-8")
    # The only braces present are our own {\kNN} karaoke tags — the injected
    # \pos directive must have had its braces stripped.
    assert "\\pos" not in content
