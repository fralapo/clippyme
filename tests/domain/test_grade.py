"""Host-unit tests for the colour-grade filter builder (pure)."""
from clippyme.domain.grade import GRADE_PRESETS, build_grade_filter


def test_none_and_unknown_are_empty():
    assert build_grade_filter("none") == ""
    assert build_grade_filter(None) == ""
    assert build_grade_filter("does_not_exist") == ""


def test_known_presets_return_filter_chains():
    for name in ("neutral_punch", "warm_cinematic", "cool_crisp", "vivid_pop"):
        f = build_grade_filter(name)
        assert f and "eq=" in f


def test_case_insensitive():
    assert build_grade_filter("Warm_Cinematic") == GRADE_PRESETS["warm_cinematic"]
