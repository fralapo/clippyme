"""Tests for clippyme.pipeline.gemini_parser.

The parser is the resilience layer between Gemini's frequently-malformed
output and the rest of the pipeline. These tests pin the 5-level fallback
chain, the IoU dedupe, the generic-reason heuristic, and hook backfill.
"""
import sys

import pytest

from clippyme.pipeline import gemini_parser as gp
from clippyme.pipeline.gemini_parser import (
    _clean_json,
    _extract_json_section,
    _viral_reason_is_generic,
    backfill_hook_text,
    parse_gemini_response,
    validate_and_dedupe,
)


def _clip(start, end, score, reason='The speaker reveals the "secret" pricing tactic in detail'):
    """A ViralClip dict that passes Pydantic (duration 10-75, score 1-100,
    reason >= 20 chars)."""
    return {
        "start": start, "end": end, "viral_score": score, "viral_reason": reason,
        "video_description_for_tiktok": "", "video_title_for_youtube_short": "",
        "viral_hook_text": "",
    }


# --- _extract_json_section -------------------------------------------------

def test_extract_takes_text_after_last_delimiter():
    text = 'reasoning here\n### JSON ###\n{"shorts": []}'
    assert _extract_json_section(text) == '{"shorts": []}'


def test_extract_strips_code_fences():
    text = '```json\n{"shorts": []}\n```'
    assert _extract_json_section(text) == '{"shorts": []}'


def test_extract_uses_last_delimiter_when_echoed():
    text = '### JSON ### (mentioned in reasoning)\n### JSON ###\n{"a": 1}'
    assert _extract_json_section(text) == '{"a": 1}'


# --- _clean_json -----------------------------------------------------------

def test_clean_converts_smart_quotes_and_trailing_comma():
    raw = '{“key”: “val”, "list": [1, 2,],}'
    cleaned = _clean_json(raw)
    assert "“" not in cleaned and "”" not in cleaned
    assert ",]" not in cleaned and ",}" not in cleaned


# --- parse_gemini_response (5-level chain) ---------------------------------

def test_strict_path_on_clean_json():
    r = parse_gemini_response('### JSON ###\n{"shorts": []}')
    assert r.parse_path == "strict"
    assert r.data == {"shorts": []}


def test_clean_path_on_trailing_comma():
    r = parse_gemini_response('### JSON ###\n{"shorts": [],}')
    assert r.parse_path == "clean"
    assert r.data == {"shorts": []}


def test_retry_path_invoked_when_earlier_levels_fail(monkeypatch):
    # Force level-3 (json_repair) to be unavailable so the chain reaches retry.
    monkeypatch.setitem(sys.modules, "json_repair", None)
    r = parse_gemini_response("totally not json", retry_fn=lambda err: '{"shorts": []}')
    assert r.parse_path == "retry"
    assert r.data == {"shorts": []}


def test_fallback_path_when_unparseable_and_no_retry(monkeypatch):
    monkeypatch.setitem(sys.modules, "json_repair", None)
    r = parse_gemini_response("totally not json", retry_fn=None)
    assert r.parse_path == "fallback"
    assert r.data is None
    assert r.error


# --- _viral_reason_is_generic ----------------------------------------------

def test_generic_marker_flagged():
    assert _viral_reason_is_generic("This is a cool moment in the video") is True


def test_specific_reason_with_quote_not_generic():
    assert _viral_reason_is_generic('He names the "3-second rule" that doubled signups') is False


# --- validate_and_dedupe ---------------------------------------------------

def test_overlapping_clips_keep_higher_score():
    data = {"shorts": [_clip(0, 30, 90), _clip(2, 31, 50)]}  # IoU ~0.90 > 0.7
    kept = validate_and_dedupe(data)
    assert len(kept) == 1
    assert kept[0]["viral_score"] == 90


def test_non_overlapping_clips_both_kept():
    data = {"shorts": [_clip(0, 30, 90), _clip(40, 70, 80)]}
    kept = validate_and_dedupe(data)
    assert len(kept) == 2


def test_video_duration_filters_out_of_range_clips():
    data = {"shorts": [_clip(0, 30, 90), _clip(50, 70, 80)]}
    kept = validate_and_dedupe(data, video_duration=40)
    assert len(kept) == 1
    assert kept[0]["end"] == 30


def test_invalid_clip_dropped_not_whole_batch():
    # Second clip's duration (3s) is below the 10s floor → dropped alone.
    data = {"shorts": [_clip(0, 30, 90), _clip(0, 3, 80)]}
    kept = validate_and_dedupe(data)
    assert len(kept) == 1


def test_drop_generic_removes_placeholder_reasons():
    data = {"shorts": [
        _clip(0, 30, 90, reason='He names the "3-second rule" that doubled signups'),
        _clip(40, 70, 80, reason="This is a cool moment in the video"),
    ]}
    kept = validate_and_dedupe(data, drop_generic=True)
    assert len(kept) == 1
    assert kept[0]["viral_score"] == 90


# --- backfill_hook_text ----------------------------------------------------

def test_backfill_uses_existing_hook_truncated():
    clips = [{"viral_hook_text": "  one two three four five six seven eight nine ten  "}]
    out = backfill_hook_text(clips, words=[])
    assert out[0]["viral_hook_text"] == "one two three four five six seven eight"


def test_backfill_falls_back_to_title():
    clips = [{"viral_hook_text": "", "video_title_for_youtube_short": "The pricing tactic"}]
    out = backfill_hook_text(clips, words=[], fallback_title="Source title")
    assert out[0]["viral_hook_text"]  # never left empty
