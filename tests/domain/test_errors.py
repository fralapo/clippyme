"""Tests for the clippyme.domain.errors hierarchy.

These lock the contract the API exception handler relies on: every domain error
carries a `status_code` + `detail`, and the subclasses map to the right codes.
"""
from clippyme.domain.errors import (
    ClippyMeError,
    ComposeError,
    NotFoundError,
    ValidationError,
)


def test_base_defaults_to_500():
    e = ClippyMeError("boom")
    assert e.status_code == 500
    assert e.detail == "boom"
    assert str(e) == "boom"


def test_validation_error_is_400():
    e = ValidationError("bad input")
    assert e.status_code == 400
    assert isinstance(e, ClippyMeError)


def test_not_found_error_is_404():
    e = NotFoundError("missing")
    assert e.status_code == 404
    assert isinstance(e, ClippyMeError)


def test_compose_error_is_400():
    assert ComposeError("x").status_code == 400


def test_status_code_override():
    e = ClippyMeError("custom", status_code=503)
    assert e.status_code == 503


def test_all_are_catchable_as_base():
    for exc in (ValidationError("a"), NotFoundError("b"), ComposeError("c")):
        try:
            raise exc
        except ClippyMeError as caught:
            assert caught.detail in ("a", "b", "c")
