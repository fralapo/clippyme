"""Regression guard for the active-speaker MAR path in reframe.py.

A refactor extracted ``compute_mouth_aspect_ratio`` out of main.py but left its
``_MOUTH_*`` landmark constants behind, so the function raised ``NameError`` on
every frame. The corrupt-frame guard swallowed it, silently disabling
active-speaker selection and duplicating ~37% of output frames. These tests
catch that class of bug — a module-level name referenced but never defined.

Marked integration because importing reframe pulls in cv2/mediapipe/torch/YOLO,
which the host (non-integration) tier doesn't have.
"""
import dis

import pytest

pytestmark = pytest.mark.integration


def _loaded_globals(func):
    """Names the function looks up as globals (LOAD_GLOBAL opcodes)."""
    return {i.argval for i in dis.get_instructions(func)
            if i.opname == "LOAD_GLOBAL"}


def test_mouth_landmark_constants_defined():
    import clippyme.pipeline.reframe as r
    for name in ("_MOUTH_TOP", "_MOUTH_BOTTOM", "_MOUTH_LEFT", "_MOUTH_RIGHT"):
        assert isinstance(getattr(r, name), int), f"{name} missing/not int"


def test_compute_mar_has_no_undefined_globals():
    """Every global ``compute_mouth_aspect_ratio`` references must resolve.

    This would have failed when the _MOUTH_* constants lived only in main.py.
    """
    import builtins

    import clippyme.pipeline.reframe as r

    func = r.compute_mouth_aspect_ratio
    mod_globals = func.__globals__
    for name in _loaded_globals(func):
        assert name in mod_globals or hasattr(builtins, name), \
            f"compute_mouth_aspect_ratio references undefined global {name!r}"
