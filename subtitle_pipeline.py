"""Subtitle generation+burn pipeline extracted from app.py /api/subtitle endpoint."""
import asyncio
import os
import time
from typing import Any

from fastapi import HTTPException

from subtitles import (
    generate_srt,
    generate_ass_karaoke,
    burn_subtitles,
    SUBTITLE_PRESETS,
)


def resolve_clip_filename(req: Any, clip_data: dict, metadata_path: str) -> str:
    """Resolve the input clip filename for a subtitle request."""
    if req.input_filename:
        return os.path.basename(req.input_filename)
    filename = clip_data.get("video_url", "").split("/")[-1]
    if not filename:
        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")
        filename = f"{base_name}_clip_{req.clip_index + 1}.mp4"
    return filename


async def run_subtitle_pipeline(
    *,
    req: Any,
    output_dir: str,
    transcript: dict,
    clip_data: dict,
    input_path: str,
    output_filename: str,
) -> None:
    """Generate subtitle file (ASS or SRT) and burn it onto the video.

    Raises HTTPException(400) if no words are in the clip range.
    """
    use_karaoke = req.preset is not None and req.preset in SUBTITLE_PRESETS
    ts = int(time.time())
    sub_filename = f"subs_{req.clip_index}_{ts}.{'ass' if use_karaoke else 'srt'}"
    sub_path = os.path.join(output_dir, sub_filename)
    output_path = os.path.join(output_dir, output_filename)

    if use_karaoke:
        success = generate_ass_karaoke(
            transcript,
            clip_data["start"],
            clip_data["end"],
            sub_path,
            preset=req.preset,
            mode=req.karaoke_mode or "word_group",
            words_per_group=req.words_per_group,
            uppercase=req.uppercase,
            font_name=req.font_name if req.font_name != "Verdana" else None,
            font_color=req.font_color if req.font_color != "#FFFFFF" else None,
            highlight_color=req.highlight_color,
            font_size=req.font_size if req.font_size != 16 else None,
            outline_width=req.border_width if req.border_width != 2 else None,
            position=req.position,
        )
    else:
        success = generate_srt(transcript, clip_data["start"], clip_data["end"], sub_path)

    if not success:
        raise HTTPException(status_code=400, detail="No words found for this clip range.")

    def _burn():
        burn_subtitles(
            input_path,
            sub_path,
            output_path,
            alignment=req.position,
            fontsize=req.font_size,
            font_name=req.font_name,
            font_color=req.font_color,
            border_color=req.border_color,
            border_width=req.border_width,
            bg_color=req.bg_color,
            bg_opacity=req.bg_opacity,
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _burn)
