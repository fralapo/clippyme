"""Host-unit tests for conversational clip edit — pure prompt + parse."""
from clippyme.domain.clip_edit_ai import build_edit_prompt, parse_edit_response


SEGS = [
    {"index": 0, "text": "Hello and welcome", "start": 0.0, "end": 2.0},
    {"index": 1, "text": "today we talk shorts", "start": 2.0, "end": 5.0},
]


def test_prompt_includes_instruction_and_times():
    p = build_edit_prompt(SEGS, "cut the intro", 5.0)
    assert "cut the intro" in p
    assert "[0.00-2.00]" in p
    assert "5.00 seconds" in p


def test_prompt_truncates_long_instruction():
    p = build_edit_prompt(SEGS, "x" * 5000, 5.0)
    assert "x" * 1000 in p
    assert "x" * 1001 not in p


def test_parse_plain_json():
    r = parse_edit_response('{"drops": [[0.0, 2.0]], "explanation": "cut intro"}', 5.0)
    assert r["drops"] == [[0.0, 2.0]]
    assert r["explanation"] == "cut intro"


def test_parse_strips_fences_and_prose():
    txt = 'Sure!\n```json\n{"drops": [[1.0, 3.0]]}\n```'
    r = parse_edit_response(txt, 5.0)
    assert r["drops"] == [[1.0, 3.0]]


def test_parse_clamps_and_drops_invalid():
    txt = '{"drops": [[-1, 99], [3, 3], [4, 2], ["a", "b"]]}'
    r = parse_edit_response(txt, 5.0)
    # [-1,99]→clamped [0,5]; [3,3] zero; [4,2] inverted; ["a","b"] non-numeric.
    assert r["drops"] == [[0.0, 5.0]]


def test_parse_bare_array_and_garbage():
    assert parse_edit_response("not json at all", 5.0)["drops"] == []
    assert parse_edit_response("", 5.0)["drops"] == []


def test_parse_empty_drops():
    r = parse_edit_response('{"drops": [], "explanation": "nothing to cut"}', 5.0)
    assert r["drops"] == []
    assert "nothing" in r["explanation"]
