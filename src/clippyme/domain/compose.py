"""Compose-on-download pipeline (Smart Cut → Hook → Subtitles).

Extracted from app.py compose_clip endpoint. This module owns the layer
composition logic; the FastAPI endpoint stays a thin wrapper that handles
validation, path resolution and HTTP error mapping.
"""
import asyncio
import logging
import os
import shutil

from clippyme.domain.errors import ValidationError

logger = logging.getLogger(__name__)

from clippyme.domain.smartcut import smart_cut
from clippyme.domain.subtitles import generate_ass_karaoke, generate_srt, burn_subtitles


_SIZE_MAP = {"S": 0.8, "M": 1.0, "L": 1.3}


async def _apply_smartcut(
    current_input: str,
    base_clip: str,
    metadata: dict,
    clip_info: dict,
    intermediate_files: list,
) -> str:
    # Cache key must follow the ACTUAL input. The previous implementation
    # keyed off `base_clip` unconditionally, which meant that if we'd
    # smart-cut the raw clip before, we'd return the stale raw smart-cut
    # even when the current call is operating on a subtitled/hooked
    # variant. Use current_input instead so each input gets its own
    # sidecar _smartcut.mp4.
    smartcut_path = current_input.replace(".mp4", "_smartcut.mp4")
    if os.path.exists(smartcut_path):
        intermediate_files.append(smartcut_path)
        return smartcut_path
    transcript = metadata.get("transcript", {})
    loop = asyncio.get_event_loop()
    sc_output, _ = await loop.run_in_executor(
        None,
        smart_cut,
        current_input,
        transcript,
        clip_info.get("start", 0),
        clip_info.get("end", 0),
        transcript.get("language"),
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
) -> str:
    from clippyme.domain.hooks import add_hook_to_video

    hook_output = os.path.join(job_dir, f"composed_hook_{clip_index}.mp4")
    intermediate_files.append(hook_output)
    position = hook_params.get("position", "top")
    font_scale = _SIZE_MAP.get(hook_params.get("size", "M"), 1.0)
    offset_y = hook_params.get("offset_y", 0)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        add_hook_to_video,
        current_input,
        hook_params["text"],
        hook_output,
        position,
        font_scale,
        offset_y,
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
) -> str:
    sub_output = os.path.join(job_dir, f"composed_sub_{clip_index}.mp4")
    intermediate_files.append(sub_output)
    transcript = metadata.get("transcript", {})
    clip_start = clip_info.get("start", 0)
    clip_end = clip_info.get("end", 0)
    sub_mode = subtitle_params.get("mode", "karaoke")
    sub_offset_y = subtitle_params.get("offset_y", 0)
    loop = asyncio.get_event_loop()

    if sub_mode == "karaoke":
        ass_path = os.path.join(job_dir, f"composed_subs_{clip_index}.ass")
        intermediate_files.append(ass_path)
        success = await loop.run_in_executor(
            None,
            lambda: generate_ass_karaoke(
                transcript,
                clip_start,
                clip_end,
                ass_path,
                preset=subtitle_params.get("preset", "classic_white"),
                mode=subtitle_params.get("display_mode", "word_group"),
                uppercase=subtitle_params.get("uppercase", True),
                highlight_color=subtitle_params.get("highlight_color"),
                font_name=subtitle_params.get("font"),
                font_size=subtitle_params.get("font_size"),
                position=subtitle_params.get("position", "bottom"),
                offset_y=sub_offset_y,
            ),
        )
        if not success:
            raise ValidationError("No words found for this clip range.")
        await loop.run_in_executor(
            None,
            burn_subtitles,
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
        )
    else:
        srt_path = os.path.join(job_dir, f"composed_subs_{clip_index}.srt")
        intermediate_files.append(srt_path)
        success = await loop.run_in_executor(
            None, generate_srt, transcript, clip_start, clip_end, srt_path
        )
        if not success:
            raise ValidationError("No words found for this clip range.")
        await loop.run_in_executor(
            None,
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
) -> str:
    """Run the active layer pipeline. Returns the final composed filename (basename).

    Cleans up intermediate files on BOTH success and failure. If any layer
    raises (ffmpeg crash, bad params, HTTPException) we still remove every
    partial file we created before re-raising the original error.
    """
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
        # Correct order: SUBTITLES → SMART CUT → HOOK.
        #
        # Step 1 burns the subs into the raw frames with perfect timing
        # (since the base clip still has the original length). Step 2
        # re-encodes to remove silence segments; because the subs are
        # already pixels at that point, they travel with the frames and
        # stay locked to the audio, no drift regardless of speech speed.
        # Step 3 overlays the static Hook on top of everything so it
        # remains visible for every surviving frame.
        if active.get("subtitles"):
            current_input = await _apply_subtitles(
                current_input,
                job_dir,
                clip_index,
                metadata,
                clip_info,
                subtitle_params,
                intermediate_files,
            )
            layers_applied.append("subtitles")
            logger.info("compose_layers: ✓ subtitles → %s", os.path.basename(current_input))

        if active.get("smartcut"):
            current_input = await _apply_smartcut(
                current_input, base_clip, metadata, clip_info, intermediate_files
            )
            layers_applied.append("smartcut")
            logger.info("compose_layers: ✓ smartcut → %s", os.path.basename(current_input))

        # Hook last: it's a static overlay that should appear on every
        # kept frame, regardless of how many silences Smart Cut removed.
        hook_text = (hook_params or {}).get("text", "")
        if isinstance(hook_text, str):
            hook_text = hook_text.strip()
        if active.get("hook"):
            if not hook_text:
                logger.warning(
                    "compose_layers: hook toggle ON but text is empty — "
                    "skipping hook layer. Ensure PublishModal / ResultCard "
                    "sends a non-empty hook_params.text.",
                )
            else:
                hp_clean = {**hook_params, "text": hook_text}
                current_input = await _apply_hook(
                    current_input, job_dir, clip_index, hp_clean, intermediate_files
                )
                layers_applied.append("hook")
                logger.info("compose_layers: ✓ hook → %s", os.path.basename(current_input))

        if os.path.abspath(current_input) != os.path.abspath(composed_path):
            shutil.copy2(current_input, composed_path)

        logger.info(
            "compose_layers: ✅ final = %s (applied=%s)",
            os.path.basename(composed_path), layers_applied or ["<none>"],
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
