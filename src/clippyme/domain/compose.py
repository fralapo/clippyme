"""Compose-on-download pipeline (Smart Cut → Hook → Subtitles).

Extracted from app.py compose_clip endpoint. This module owns the layer
composition logic; the FastAPI endpoint stays a thin wrapper that handles
validation, path resolution and HTTP error mapping.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess

from clippyme.domain.clip_locks import clip_lock
from clippyme.domain.errors import ValidationError

logger = logging.getLogger(__name__)

from clippyme.domain.smartcut import smart_cut
from clippyme.domain.subtitles import generate_ass_karaoke, generate_srt, burn_subtitles


_SIZE_MAP = {"S": 0.8, "M": 1.0, "L": 1.3}

# Persisted brand logo (uploaded via /api/config/logo). Overridable for tests.
LOGO_PATH = os.environ.get("CLIPPYME_LOGO_PATH") or os.path.join("data", "logo.png")
# Logo size presets → width as a fraction of the video width.
_LOGO_SIZE_MAP = {"S": 0.12, "M": 0.18, "L": 0.26}


async def _apply_logo(
    current_input: str,
    job_dir: str,
    clip_index: int,
    logo_params: dict,
    intermediate_files: list,
) -> str:
    from clippyme.domain.logo import add_logo_to_video, DEFAULT_POSITION

    logo_output = os.path.join(job_dir, f"composed_logo_{clip_index}.mp4")
    intermediate_files.append(logo_output)
    lp = logo_params or {}
    position = lp.get("position", DEFAULT_POSITION)
    size = lp.get("size")
    scale = lp.get("scale", _LOGO_SIZE_MAP.get(size, 0.18))
    opacity = lp.get("opacity", 1.0)
    margin = lp.get("margin", 0.04)
    await asyncio.to_thread(
        add_logo_to_video,
        current_input,
        LOGO_PATH,
        logo_output,
        position,
        scale,
        opacity,
        margin,
    )
    return logo_output


async def _apply_grade(
    current_input: str,
    job_dir: str,
    clip_index: int,
    grade_params: dict,
    intermediate_files: list,
) -> str:
    """Apply an optional colour grade. Runs FIRST (before subtitles) so overlay
    colours are not shifted by the grade. Silently keeps the input if the
    preset is none/unknown or ffmpeg fails."""
    from clippyme.domain.grade import apply_grade_async, DEFAULT_GRADE

    preset = (grade_params or {}).get("preset", DEFAULT_GRADE)
    grade_output = os.path.join(job_dir, f"composed_grade_{clip_index}.mp4")
    ok = await apply_grade_async(current_input, grade_output, preset)
    if not ok:
        return current_input
    intermediate_files.append(grade_output)
    return grade_output


def _probe_qa(path: str) -> tuple:
    """(duration_seconds | None, has_audio, size_bytes | None) via ffprobe.
    Best-effort: any failure returns (None, True, size) so QA never blocks."""
    size = os.path.getsize(path) if os.path.exists(path) else None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
        )
        info = json.loads(proc.stdout or b"{}")
        dur = info.get("format", {}).get("duration")
        dur = float(dur) if dur is not None else None
        has_audio = any(
            s.get("codec_type") == "audio" for s in info.get("streams", [])
        )
        return dur, has_audio, size
    except Exception:
        return None, True, size


async def _self_eval(
    composed_path: str, clip_info: dict, smartcut_applied: bool, clip_index: int,
) -> None:
    """video-use step 7 / superpowers verification: probe the rendered output and
    log any QA issues. Never raises — a QA miss surfaces a warning, not a 500."""
    from clippyme.domain.clip_qa import evaluate_clip_qa

    try:
        dur, has_audio, size = await asyncio.to_thread(_probe_qa, composed_path)
        try:
            expected = float(clip_info.get("end", 0)) - float(clip_info.get("start", 0))
        except (TypeError, ValueError):
            expected = None
        report = evaluate_clip_qa(
            actual_duration=dur,
            expected_duration=expected if expected and expected > 0 else None,
            has_audio=has_audio,
            size_bytes=size,
            smartcut_applied=smartcut_applied,
        )
        if report["ok"]:
            logger.info("self_eval: clip_index=%d ✓ output looks sane", clip_index)
        else:
            logger.warning(
                "self_eval: clip_index=%d ⚠️ QA issues: %s",
                clip_index, "; ".join(report["issues"]),
            )
    except Exception as e:  # pragma: no cover — QA must never break compose
        logger.debug("self_eval skipped (probe error): %s", e)


async def _apply_smartcut(
    current_input: str,
    base_clip: str,
    metadata: dict,
    clip_info: dict,
    intermediate_files: list,
    drop_ranges=None,
) -> str:
    # Smart Cut caching is delegated entirely to smart_cut() itself, which
    # writes a plan-hashed output (`{base}_smartcut_{hash}.mp4`) and validates
    # cache hits against the source mtime (plus a legacy bare-`_smartcut.mp4`
    # back-compat candidate). The previous fixed-name sidecar shortcut here
    # built `{base}_smartcut.mp4` — a name smart_cut NEVER produces under the
    # current Subtitles→Smart Cut ordering (current_input is `composed_sub_N.mp4`)
    # — so it could only ever match stale artifacts that smart_cut already
    # handles itself. Removed: always delegate to smart_cut's own correct cache.
    transcript = metadata.get("transcript", {})
    sc_output, _ = await asyncio.to_thread(
        smart_cut,
        current_input,
        transcript,
        clip_info.get("start", 0),
        clip_info.get("end", 0),
        transcript.get("language"),
        drop_ranges,
    )
    # Track the smart-cut artefact so _cleanup_intermediates can remove
    # it at the end of compose_layers (unless it ends up as the final
    # composed_clip_*.mp4, in which case the cleanup helper preserves it).
    if sc_output and sc_output != current_input:
        intermediate_files.append(sc_output)
    return sc_output or current_input


async def _apply_hook(
    current_input: str,
    job_dir: str,
    clip_index: int,
    hook_params: dict,
    intermediate_files: list,
    logo_params: dict = None,
) -> str:
    """Hook overlay pass. When ``logo_params`` is given the brand logo is
    composited in the SAME encode (hook below, logo topmost — identical
    z-order to the sequential Hook → Logo passes, one generation cheaper)."""
    from clippyme.domain.hooks import add_hook_to_video

    hook_output = os.path.join(job_dir, f"composed_hook_{clip_index}.mp4")
    intermediate_files.append(hook_output)
    position = hook_params.get("position", "top")
    font_scale = _SIZE_MAP.get(hook_params.get("size", "M"), 1.0)
    offset_y = hook_params.get("offset_y", 0)
    # Instagram-Stories-style text customisation. Only forward keys the user
    # actually set so create_hook_image's defaults fill the rest.
    _style_keys = ("text_color", "bg_enabled", "bg_color", "bg_opacity",
                   "corner_radius", "outline_color", "outline_width", "font", "shadow",
                   "animate")
    style = {k: hook_params[k] for k in _style_keys if k in hook_params}
    logo = None
    if logo_params is not None:
        lp = logo_params or {}
        logo = {
            "path": LOGO_PATH,
            "position": lp.get("position"),
            "scale": lp.get("scale", _LOGO_SIZE_MAP.get(lp.get("size"), 0.18)),
            "opacity": lp.get("opacity", 1.0),
            "margin": lp.get("margin", 0.04),
        }
        from clippyme.domain.logo import DEFAULT_POSITION
        logo["position"] = logo["position"] or DEFAULT_POSITION
    await asyncio.to_thread(
        add_hook_to_video,
        current_input,
        hook_params["text"],
        hook_output,
        position,
        font_scale,
        offset_y,
        style or None,
        logo,
    )
    return hook_output


async def _apply_subtitles(
    current_input: str,
    job_dir: str,
    clip_index: int,
    metadata: dict,
    clip_info: dict,
    subtitle_params: dict,
    intermediate_files: list,
    pre_vf: str = None,
) -> str:
    sub_output = os.path.join(job_dir, f"composed_sub_{clip_index}.mp4")
    intermediate_files.append(sub_output)
    transcript = metadata.get("transcript", {})
    clip_start = clip_info.get("start", 0)
    clip_end = clip_info.get("end", 0)
    sub_mode = subtitle_params.get("mode", "karaoke")
    sub_offset_y = subtitle_params.get("offset_y", 0)

    if sub_mode == "karaoke":
        ass_path = os.path.join(job_dir, f"composed_subs_{clip_index}.ass")
        intermediate_files.append(ass_path)
        success = await asyncio.to_thread(
            lambda: generate_ass_karaoke(
                transcript,
                clip_start,
                clip_end,
                ass_path,
                preset=subtitle_params.get("preset", "classic_white"),
                mode=subtitle_params.get("display_mode", "word_group"),
                words_per_group=subtitle_params.get("words_per_group", 3),
                # Default None → honour the preset's own casing (mrbeast_box /
                # minimal_clean are lower-case presets). Only an explicit
                # frontend value overrides it.
                uppercase=subtitle_params.get("uppercase"),
                font_color=subtitle_params.get("font_color"),
                highlight_color=subtitle_params.get("highlight_color"),
                outline_width=subtitle_params.get("outline_width"),
                font_name=subtitle_params.get("font"),
                font_size=subtitle_params.get("font_size"),
                position=subtitle_params.get("position", "bottom"),
                offset_y=sub_offset_y,
                outline_color=subtitle_params.get("outline_color"),
                align=subtitle_params.get("align", "center"),
            ),
        )
        if not success:
            raise ValidationError("No words found for this clip range.")
        await asyncio.to_thread(
            lambda: burn_subtitles(
                current_input,
                ass_path,
                sub_output,
                2,
                16,
                "Verdana",
                "#FFFFFF",
                "#000000",
                2,
                "#000000",
                0.0,
                sub_offset_y,
                pre_vf=pre_vf,
            ),
        )
    else:
        srt_path = os.path.join(job_dir, f"composed_subs_{clip_index}.srt")
        intermediate_files.append(srt_path)
        success = await asyncio.to_thread(
            generate_srt, transcript, clip_start, clip_end, srt_path
        )
        if not success:
            raise ValidationError("No words found for this clip range.")
        await asyncio.to_thread(
            lambda: burn_subtitles(
                current_input,
                srt_path,
                sub_output,
                alignment=subtitle_params.get("position", "bottom"),
                fontsize=subtitle_params.get("font_size", 16),
                font_name=subtitle_params.get("font", "Verdana"),
                font_color=subtitle_params.get("font_color", "#FFFFFF"),
                border_color=subtitle_params.get("border_color", "#000000"),
                border_width=subtitle_params.get("border_width", 2),
                bg_color=subtitle_params.get("bg_color", "#000000"),
                bg_opacity=subtitle_params.get("bg_opacity", 0.0),
                offset_y=sub_offset_y,
                h_align=subtitle_params.get("align", "center"),
                pre_vf=pre_vf,
            ),
        )
    return sub_output


def _cleanup_intermediates(files: list, keep_path: str) -> None:
    """Best-effort removal of intermediate files.

    Never raises — cleanup failures must NOT mask the original composition
    error. ``keep_path`` is the final artifact path; any intermediate
    matching it is preserved.
    """
    keep_abs = os.path.abspath(keep_path) if keep_path else None
    for temp_file in files:
        if not temp_file:
            continue
        if not os.path.exists(temp_file):
            continue
        if keep_abs and os.path.abspath(temp_file) == keep_abs:
            continue
        try:
            os.remove(temp_file)
        except OSError:
            pass


async def compose_layers(
    *,
    base_clip: str,
    job_dir: str,
    clip_index: int,
    metadata: dict,
    clip_info: dict,
    toggles: dict,
    hook_params: dict,
    subtitle_params: dict,
    logo_params: dict = None,
    grade_params: dict = None,
    drop_ranges=None,
) -> str:
    """Run the active layer pipeline. Returns the final composed filename (basename).

    Cleans up intermediate files on BOTH success and failure. If any layer
    raises (ffmpeg crash, bad params, HTTPException) we still remove every
    partial file we created before re-raising the original error.

    Serialised per (job_dir, clip_index): every intermediate filename is
    deterministic by clip index, so two overlapping composes for the same clip
    (Download racing Publish's compose_first) would delete/overwrite each
    other's in-flight files. Different clips compose in parallel as before.
    """
    async with clip_lock(job_dir, clip_index):
        return await _compose_layers_impl(
            base_clip=base_clip, job_dir=job_dir, clip_index=clip_index,
            metadata=metadata, clip_info=clip_info, toggles=toggles,
            hook_params=hook_params, subtitle_params=subtitle_params,
            logo_params=logo_params, grade_params=grade_params,
            drop_ranges=drop_ranges,
        )


async def _compose_layers_impl(
    *,
    base_clip: str,
    job_dir: str,
    clip_index: int,
    metadata: dict,
    clip_info: dict,
    toggles: dict,
    hook_params: dict,
    subtitle_params: dict,
    logo_params: dict = None,
    grade_params: dict = None,
    drop_ranges=None,
) -> str:
    active = {k: v for k, v in toggles.items() if v}
    logger.info(
        "compose_layers: clip_index=%d active=%s hook_text_len=%d subtitle_mode=%s",
        clip_index, list(active.keys()),
        len((hook_params or {}).get("text", "") or ""),
        (subtitle_params or {}).get("mode", "karaoke"),
    )
    if not active:
        logger.info("compose_layers: no active toggles → returning base clip unmodified")
        return os.path.basename(base_clip)

    current_input = base_clip
    intermediate_files: list = []
    composed_filename = f"composed_clip_{clip_index}.mp4"
    composed_path = os.path.join(job_dir, composed_filename)
    # Always wipe a stale composed file from a previous compose pass so
    # we never accidentally upload yesterday's version when the user has
    # changed toggles in the meantime.
    if os.path.exists(composed_path):
        try:
            os.remove(composed_path)
        except OSError:
            pass

    layers_applied: list[str] = []

    try:
        # --- Ordering matters ---
        # Earlier revisions ran Smart Cut FIRST, then burned subtitles on
        # the resulting shorter clip. The subtitle timestamps are derived
        # from the original transcript using absolute ``clip_start`` and
        # ``clip_end`` seconds, so the subs expected a clip of length
        # (clip_end - clip_start). After Smart Cut removed silences and
        # filler words, the clip was strictly shorter than that, so the
        # subs accumulated drift relative to the audio — very visible on
        # fast speakers, where Smart Cut removes many micro-gaps and the
        # error snowballs over the clip.
        #
        # Correct order: GRADE → SUBTITLES → SMART CUT → HOOK → LOGO.
        #
        # Grade runs FIRST so the colour transform applies only to the source
        # frames — burning it before subtitles/hook/logo means those overlays
        # keep their exact authored colours instead of being tinted too.
        #
        # Step 1 burns the subs into the raw frames with perfect timing
        # (since the base clip still has the original length). Step 2
        # re-encodes to remove silence segments; because the subs are
        # already pixels at that point, they travel with the frames and
        # stay locked to the audio, no drift regardless of speech speed.
        # Step 3 overlays the static Hook on top of everything so it
        # remains visible for every surviving frame.
        # Grade + Subtitles fusion: when BOTH are active, the grade chain rides
        # as pre_vf on the subtitle burn — inside one filtergraph the colour
        # transform still applies to the source pixels BEFORE the glyphs are
        # composited, so the Grade→Subtitles semantics are identical, one
        # encode generation cheaper. Grade-only keeps its own pass.
        merged_grade_vf = None
        if active.get("grade") and active.get("subtitles"):
            from clippyme.domain.grade import DEFAULT_GRADE, build_grade_filter
            merged_grade_vf = build_grade_filter(
                (grade_params or {}).get("preset", DEFAULT_GRADE)) or None

        if active.get("grade") and not merged_grade_vf:
            current_input = await _apply_grade(
                current_input, job_dir, clip_index, grade_params, intermediate_files,
            )
            layers_applied.append("grade")
            logger.info("compose_layers: ✓ grade → %s", os.path.basename(current_input))

        if active.get("subtitles"):
            current_input = await _apply_subtitles(
                current_input,
                job_dir,
                clip_index,
                metadata,
                clip_info,
                subtitle_params,
                intermediate_files,
                pre_vf=merged_grade_vf,
            )
            if merged_grade_vf:
                layers_applied.append("grade")
            layers_applied.append("subtitles")
            logger.info(
                "compose_layers: ✓ %ssubtitles → %s",
                "grade+" if merged_grade_vf else "", os.path.basename(current_input),
            )

        if active.get("smartcut"):
            current_input = await _apply_smartcut(
                current_input, base_clip, metadata, clip_info, intermediate_files,
                drop_ranges,
            )
            layers_applied.append("smartcut")
            logger.info("compose_layers: ✓ smartcut → %s", os.path.basename(current_input))

        # Hook last: it's a static overlay that should appear on every
        # kept frame, regardless of how many silences Smart Cut removed.
        hook_text = (hook_params or {}).get("text", "")
        if isinstance(hook_text, str):
            hook_text = hook_text.strip()
        hook_active = bool(active.get("hook"))
        if hook_active and not hook_text:
            logger.warning(
                "compose_layers: hook toggle ON but text is empty — "
                "skipping hook layer. Ensure PublishModal / ResultCard "
                "sends a non-empty hook_params.text.",
            )
            hook_active = False
        logo_active = bool(active.get("logo"))
        if logo_active and not os.path.exists(LOGO_PATH):
            logger.warning(
                "compose_layers: logo toggle ON but no logo uploaded at %s "
                "— skipping logo layer.", LOGO_PATH,
            )
            logo_active = False

        if hook_active and logo_active:
            # Hook + Logo fusion: both are static overlays applied after Smart
            # Cut, so they composite in ONE encode (hook below, logo topmost —
            # the exact z-order of the sequential passes), one generation
            # cheaper on a fully-toggled clip.
            hp_clean = {**hook_params, "text": hook_text}
            current_input = await _apply_hook(
                current_input, job_dir, clip_index, hp_clean, intermediate_files,
                logo_params=logo_params or {},
            )
            layers_applied += ["hook", "logo"]
            logger.info("compose_layers: ✓ hook+logo → %s", os.path.basename(current_input))
        elif hook_active:
            hp_clean = {**hook_params, "text": hook_text}
            current_input = await _apply_hook(
                current_input, job_dir, clip_index, hp_clean, intermediate_files
            )
            layers_applied.append("hook")
            logger.info("compose_layers: ✓ hook → %s", os.path.basename(current_input))
        elif logo_active:
            # Logo absolutely last: a static brand mark that must sit on top of
            # subtitles AND hook, on every kept frame.
            current_input = await _apply_logo(
                current_input, job_dir, clip_index, logo_params, intermediate_files
            )
            layers_applied.append("logo")
            logger.info("compose_layers: ✓ logo → %s", os.path.basename(current_input))

        if os.path.abspath(current_input) != os.path.abspath(composed_path):
            shutil.copy2(current_input, composed_path)

        logger.info(
            "compose_layers: ✅ final = %s (applied=%s)",
            os.path.basename(composed_path), layers_applied or ["<none>"],
        )
        # video-use step 7 / superpowers verification — probe the rendered
        # output and log any QA issues before handing it back. Soft check.
        await _self_eval(
            composed_path, clip_info, "smartcut" in layers_applied, clip_index,
        )
        _cleanup_intermediates(intermediate_files, composed_path)
        return composed_filename
    except Exception:
        # Failure path: remove any partial composed output AND every
        # intermediate we created. Then re-raise the original exception
        # so the endpoint layer can map it to an HTTP error.
        _cleanup_intermediates(intermediate_files, "")
        if os.path.exists(composed_path):
            try:
                os.remove(composed_path)
            except OSError:
                pass
        raise
