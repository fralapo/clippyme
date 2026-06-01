"""Tests for clippyme.domain.compose — layer composition + cleanup.

The individual layer helpers (_apply_subtitles / _apply_smartcut /
_apply_hook) shell out to ffmpeg / auto-editor / Pillow, so they are
monkeypatched here. What we actually verify is compose_layers' own logic:
layer ORDER (subtitles → smartcut → hook), the empty-hook skip, the
no-active-toggles short-circuit, and intermediate-file cleanup on both the
success and failure paths.

Async functions are driven with asyncio.run() so the suite needs no
pytest-asyncio plugin (matching the existing tests/pipeline style).
"""
import asyncio
import os

import pytest

from clippyme.domain import compose
from clippyme.domain.compose import (
    _SIZE_MAP,
    _cleanup_intermediates,
    compose_layers,
)


def _touch(path):
    with open(path, "wb") as f:
        f.write(b"x")
    return path


def _install_recording_stubs(monkeypatch, order):
    """Replace the three layer helpers with async stubs that record the
    call order and emit a real file in job_dir (so the final copy2 works)."""

    async def fake_subtitles(current_input, job_dir, clip_index, metadata,
                             clip_info, subtitle_params, intermediate_files):
        order.append("subtitles")
        out = os.path.join(job_dir, f"composed_sub_{clip_index}.mp4")
        _touch(out)
        intermediate_files.append(out)
        return out

    async def fake_smartcut(current_input, base_clip, metadata, clip_info,
                            intermediate_files):
        order.append("smartcut")
        out = current_input.replace(".mp4", "_smartcut.mp4")
        _touch(out)
        intermediate_files.append(out)
        return out

    async def fake_hook(current_input, job_dir, clip_index, hook_params,
                        intermediate_files):
        order.append("hook")
        out = os.path.join(job_dir, f"composed_hook_{clip_index}.mp4")
        _touch(out)
        intermediate_files.append(out)
        return out

    monkeypatch.setattr(compose, "_apply_subtitles", fake_subtitles)
    monkeypatch.setattr(compose, "_apply_smartcut", fake_smartcut)
    monkeypatch.setattr(compose, "_apply_hook", fake_hook)


def _run_compose(tmp_path, toggles, *, hook_text="Watch this", base_name="clip_0.mp4"):
    base_clip = _touch(str(tmp_path / base_name))
    return asyncio.run(
        compose_layers(
            base_clip=base_clip,
            job_dir=str(tmp_path),
            clip_index=0,
            metadata={"transcript": {}},
            clip_info={"start": 0, "end": 30},
            toggles=toggles,
            hook_params={"text": hook_text, "position": "top", "size": "M"},
            subtitle_params={"mode": "karaoke"},
        )
    )


# --- _SIZE_MAP -------------------------------------------------------------

def test_size_map_values():
    assert _SIZE_MAP == {"S": 0.8, "M": 1.0, "L": 1.3}


# --- no active toggles -----------------------------------------------------

def test_no_active_toggles_returns_base_unmodified(tmp_path, monkeypatch):
    order = []
    _install_recording_stubs(monkeypatch, order)
    result = _run_compose(tmp_path, {"smartcut": False, "hook": False, "subtitles": False})
    assert result == "clip_0.mp4"
    assert order == []
    # No composed_clip_*.mp4 should be produced when nothing is active.
    assert not os.path.exists(tmp_path / "composed_clip_0.mp4")


# --- ordering --------------------------------------------------------------

def test_all_layers_run_in_subtitles_smartcut_hook_order(tmp_path, monkeypatch):
    order = []
    _install_recording_stubs(monkeypatch, order)
    result = _run_compose(tmp_path, {"smartcut": True, "hook": True, "subtitles": True})
    assert order == ["subtitles", "smartcut", "hook"]
    assert result == "composed_clip_0.mp4"
    assert os.path.exists(tmp_path / "composed_clip_0.mp4")


def test_subtitles_run_before_smartcut_when_hook_off(tmp_path, monkeypatch):
    # Regression guard: subtitles must be burned BEFORE smartcut removes
    # silences, otherwise subs drift relative to the shortened audio.
    order = []
    _install_recording_stubs(monkeypatch, order)
    _run_compose(tmp_path, {"smartcut": True, "hook": False, "subtitles": True})
    assert order == ["subtitles", "smartcut"]


# --- empty hook skip -------------------------------------------------------

def test_hook_toggle_on_but_empty_text_is_skipped(tmp_path, monkeypatch):
    order = []
    _install_recording_stubs(monkeypatch, order)
    result = _run_compose(
        tmp_path, {"smartcut": False, "hook": True, "subtitles": False}, hook_text="   "
    )
    # Hook layer skipped → no layer ran, but composed file is still emitted
    # (a copy of the base clip) so the caller gets a consistent path back.
    assert order == []
    assert result == "composed_clip_0.mp4"
    assert os.path.exists(tmp_path / "composed_clip_0.mp4")


# --- failure path cleanup --------------------------------------------------

def test_failure_cleans_intermediates_and_reraises(tmp_path, monkeypatch):
    order = []
    _install_recording_stubs(monkeypatch, order)

    async def boom_smartcut(current_input, base_clip, metadata, clip_info,
                            intermediate_files):
        order.append("smartcut")
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(compose, "_apply_smartcut", boom_smartcut)

    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        _run_compose(tmp_path, {"smartcut": True, "hook": False, "subtitles": True})

    # Subtitles ran first and created composed_sub_0.mp4; the failure path
    # must remove it and must not leave a half-written composed_clip_0.mp4.
    assert order == ["subtitles", "smartcut"]
    assert not os.path.exists(tmp_path / "composed_sub_0.mp4")
    assert not os.path.exists(tmp_path / "composed_clip_0.mp4")


# --- _cleanup_intermediates ------------------------------------------------

def test_cleanup_removes_files_except_keep_path(tmp_path):
    a = _touch(str(tmp_path / "a.mp4"))
    b = _touch(str(tmp_path / "b.mp4"))
    keep = _touch(str(tmp_path / "keep.mp4"))
    _cleanup_intermediates([a, b, keep], keep)
    assert not os.path.exists(a)
    assert not os.path.exists(b)
    assert os.path.exists(keep)


def test_cleanup_tolerates_missing_and_none_entries(tmp_path):
    existing = _touch(str(tmp_path / "real.mp4"))
    missing = str(tmp_path / "ghost.mp4")
    # None + a non-existent path must not raise.
    _cleanup_intermediates([None, missing, existing], "")
    assert not os.path.exists(existing)


def test_cleanup_with_empty_keep_path_removes_everything(tmp_path):
    a = _touch(str(tmp_path / "a.mp4"))
    b = _touch(str(tmp_path / "b.mp4"))
    _cleanup_intermediates([a, b], "")
    assert not os.path.exists(a)
    assert not os.path.exists(b)
