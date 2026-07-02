"""Host tests for the compose pass-fusion (Wave 5).

Two merges cut a fully-toggled compose from 5 to 3 encode generations without
touching the load-bearing Grade → Subtitles → Smart Cut → Hook → Logo order:

* grade+subtitles: the grade chain rides as ``pre_vf`` on the subtitle burn —
  inside one filtergraph the colour transform still hits the source pixels
  BEFORE the glyphs are composited (identical semantics).
* hook+logo: both are static overlays after Smart Cut; one filter_complex
  composites hook below, logo topmost (identical z-order).

ffmpeg itself is exercised by the Docker integration suite; here the command
assembly and the compose_layers wiring are pinned with fakes.
"""
import asyncio
import os

from clippyme.domain import compose
from clippyme.domain import subtitles as subtitles_module
from clippyme.domain.hooks import build_hook_logo_filter
from clippyme.domain.logo import logo_filter_chain


# --- pure filter builders ----------------------------------------------------

def test_hook_logo_filter_static_structure():
    f = build_hook_logo_filter(10, 20, "scale=100:-1", "5", "7")
    # Hook composites first ([vh]), logo chain feeds [lg], logo overlays LAST
    # (topmost) — the z-order the sequential Hook → Logo passes produced.
    assert f == "[0:v][1:v]overlay=10:20[vh];[2:v]scale=100:-1[lg];[vh][lg]overlay=5:7"


def test_hook_logo_filter_animated_keeps_entrance():
    f = build_hook_logo_filter(10, 20, "c", "5", "7", animate=True)
    assert "fade=t=in" in f and "pow(1-min(t/0.4\\,1)\\,3)" in f
    assert f.endswith(";[2:v]c[lg];[vh][lg]overlay=5:7")


def test_logo_filter_chain_clamps_and_geometry():
    chain, x, y = logo_filter_chain(1000, scale=0.9, opacity=1.7, margin=0.04,
                                    position="top-right")
    assert chain.startswith("scale=500:-1,")            # scale clamped to 0.5
    assert chain.endswith("colorchannelmixer=aa=1.000")  # opacity clamped to 1
    assert x == "main_w-overlay_w-40" and y == "40"      # margin 4% of 1000


# --- burn_subtitles pre_vf ----------------------------------------------------

def _capture_burn(monkeypatch, tmp_path):
    captured = {}

    class _Ok:
        returncode = 0
        stderr = b""

    monkeypatch.setattr(subtitles_module.subprocess, "run",
                        lambda cmd, **k: captured.update(cmd=cmd) or _Ok())
    monkeypatch.setattr(subtitles_module, "effective_fonts_dir", lambda: str(tmp_path))
    return captured


def test_burn_subtitles_prepends_pre_vf(tmp_path, monkeypatch):
    captured = _capture_burn(monkeypatch, tmp_path)
    ass = tmp_path / "subs.ass"
    ass.write_text("[Script Info]\n", encoding="utf-8")
    subtitles_module.burn_subtitles("in.mp4", str(ass), "out.mp4",
                                    pre_vf="eq=contrast=1.06:saturation=1.1")
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert vf.startswith("eq=contrast=1.06:saturation=1.1,ass=")


def test_burn_subtitles_without_pre_vf_unchanged(tmp_path, monkeypatch):
    captured = _capture_burn(monkeypatch, tmp_path)
    ass = tmp_path / "subs.ass"
    ass.write_text("[Script Info]\n", encoding="utf-8")
    subtitles_module.burn_subtitles("in.mp4", str(ass), "out.mp4")
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert vf.startswith("ass=")


# --- compose_layers wiring ------------------------------------------------------

def _run_compose(tmp_path, monkeypatch, toggles, **kwargs):
    base = tmp_path / "clip.mp4"
    base.write_bytes(b"fake")
    calls = {"grade": 0, "logo": 0, "hook_logo_params": "unset", "pre_vf": "unset"}

    async def fake_grade(current_input, job_dir, clip_index, grade_params, files):
        calls["grade"] += 1
        return current_input

    async def fake_subs(current_input, job_dir, clip_index, metadata, clip_info,
                        subtitle_params, files, pre_vf=None):
        calls["pre_vf"] = pre_vf
        out = os.path.join(job_dir, "subbed.mp4")
        with open(out, "wb") as f:
            f.write(b"s")
        files.append(out)
        return out

    async def fake_hook(current_input, job_dir, clip_index, hook_params, files,
                        logo_params=None):
        calls["hook_logo_params"] = logo_params
        out = os.path.join(job_dir, "hooked.mp4")
        with open(out, "wb") as f:
            f.write(b"h")
        files.append(out)
        return out

    async def fake_logo(current_input, job_dir, clip_index, logo_params, files):
        calls["logo"] += 1
        return current_input

    monkeypatch.setattr(compose, "_apply_grade", fake_grade)
    monkeypatch.setattr(compose, "_apply_subtitles", fake_subs)
    monkeypatch.setattr(compose, "_apply_hook", fake_hook)
    monkeypatch.setattr(compose, "_apply_logo", fake_logo)

    async def no_eval(*a, **k):
        return None

    monkeypatch.setattr(compose, "_self_eval", no_eval)

    result = asyncio.run(compose.compose_layers(
        base_clip=str(base), job_dir=str(tmp_path), clip_index=0,
        metadata={}, clip_info={}, toggles=toggles,
        hook_params=kwargs.get("hook_params", {}),
        subtitle_params=kwargs.get("subtitle_params", {}),
        logo_params=kwargs.get("logo_params"),
        grade_params=kwargs.get("grade_params"),
    ))
    return result, calls


def test_grade_fuses_into_subtitle_burn(tmp_path, monkeypatch):
    _, calls = _run_compose(
        tmp_path, monkeypatch,
        {"grade": True, "subtitles": True},
        grade_params={"preset": "warm_cinematic"},
    )
    assert calls["grade"] == 0, "standalone grade pass must be skipped when fused"
    assert calls["pre_vf"] and "eq=" in calls["pre_vf"]


def test_grade_alone_keeps_its_own_pass(tmp_path, monkeypatch):
    _, calls = _run_compose(
        tmp_path, monkeypatch,
        {"grade": True},
        grade_params={"preset": "warm_cinematic"},
    )
    assert calls["grade"] == 1


def test_unknown_grade_preset_falls_back_to_standalone_noop(tmp_path, monkeypatch):
    # build_grade_filter('') is empty → fusion impossible → the standalone
    # apply path runs (and no-ops), exactly like before the merge.
    _, calls = _run_compose(
        tmp_path, monkeypatch,
        {"grade": True, "subtitles": True},
        grade_params={"preset": "does_not_exist"},
    )
    assert calls["grade"] == 1
    assert calls["pre_vf"] is None


def test_hook_and_logo_fuse_into_one_pass(tmp_path, monkeypatch):
    logo_png = tmp_path / "logo.png"
    logo_png.write_bytes(b"\x89PNG")
    monkeypatch.setattr(compose, "LOGO_PATH", str(logo_png))
    _, calls = _run_compose(
        tmp_path, monkeypatch,
        {"hook": True, "logo": True},
        hook_params={"text": "WATCH"},
        logo_params={"position": "top-right", "size": "M"},
    )
    assert calls["logo"] == 0, "standalone logo pass must be skipped when fused"
    assert calls["hook_logo_params"] is not None
    assert calls["hook_logo_params"] != "unset"


def test_logo_alone_keeps_its_own_pass(tmp_path, monkeypatch):
    logo_png = tmp_path / "logo.png"
    logo_png.write_bytes(b"\x89PNG")
    monkeypatch.setattr(compose, "LOGO_PATH", str(logo_png))
    _, calls = _run_compose(tmp_path, monkeypatch, {"logo": True},
                            logo_params={"size": "M"})
    assert calls["logo"] == 1


def test_hook_without_text_still_applies_logo_standalone(tmp_path, monkeypatch):
    logo_png = tmp_path / "logo.png"
    logo_png.write_bytes(b"\x89PNG")
    monkeypatch.setattr(compose, "LOGO_PATH", str(logo_png))
    _, calls = _run_compose(
        tmp_path, monkeypatch,
        {"hook": True, "logo": True},
        hook_params={"text": "   "},
        logo_params={"size": "M"},
    )
    assert calls["hook_logo_params"] == "unset", "hook layer must be skipped"
    assert calls["logo"] == 1
