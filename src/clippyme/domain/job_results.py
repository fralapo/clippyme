"""Job result loading helpers + checkpointed pipeline command builder."""
from __future__ import annotations

import glob
import json
import logging
import os
import re

from clippyme.domain.clip_resolve import clip_filename_for
from clippyme.domain.runtime_state import runtime_result_fields

logger = logging.getLogger("clippyme")

# Reframe modes. 'subject' (FrameShift face-first crop) was formerly named
# 'object'; 'object' is kept as a legacy alias so jobs/preselections persisted
# under the old name still work. Both are accepted at the boundary and
# normalized to 'subject' internally via canonical_reframe_mode().
ALLOWED_REFRAME_MODES = frozenset({"auto", "disabled", "subject", "object"})
REFRAME_MODE_ALIASES = {"object": "subject"}
MAX_INSTRUCTIONS_LEN = 5000


def canonical_reframe_mode(mode):
    """Map the legacy ``object`` alias to the canonical ``subject`` value."""
    return REFRAME_MODE_ALIASES.get(mode, mode)


# New Gemini families are discovered at runtime, therefore validate the family
# prefix and an argv-safe character set rather than pinning a stale allow-list.
GEMINI_MODEL_RE = re.compile(r"^gemini-[A-Za-z0-9.\-]{1,64}$")

ALLOWED_LANGUAGES = frozenset({
    "multi", "auto",
    "en", "it", "es", "fr", "de", "pt", "nl", "hi", "ja", "ru",
    "pl", "tr", "sv", "da", "nb", "fi", "cs", "uk", "el", "ko", "zh",
    "en-US", "en-GB", "es-ES", "es-419", "pt-BR", "pt-PT", "fr-CA",
})


def build_main_cmd(
    *,
    url: str | None = None,
    input_path: str | None = None,
    output_dir: str,
    instructions: str | None = None,
    reframe_mode: str | None = None,
    cookies_path: str | None = None,
    language: str | None = None,
    no_zoom: bool = False,
    skip_analysis: bool = False,
    aspect: str | None = None,
    model: str | None = None,
    monitor: bool = False,
) -> list[str]:
    """Build argv for the checkpointed backend pipeline.

    ``pipeline.main`` remains available for direct/legacy CLI usage and owns the
    heavy algorithms. Queued jobs use ``pipeline.orchestrator`` so retries and
    restarts can reuse phase and per-clip checkpoints safely.
    """
    if reframe_mode is not None and reframe_mode not in ALLOWED_REFRAME_MODES:
        raise ValueError(f"invalid reframe_mode: {reframe_mode!r}")
    if model is not None:
        model = model.strip()
        if model and not GEMINI_MODEL_RE.match(model):
            raise ValueError(f"invalid model: {model!r}")
    if aspect is not None and aspect not in ("9:16", "1:1", "16:9"):
        raise ValueError(f"invalid aspect: {aspect!r}")
    if instructions is not None and len(instructions) > MAX_INSTRUCTIONS_LEN:
        raise ValueError(f"instructions too long (>{MAX_INSTRUCTIONS_LEN} chars)")
    if language is not None:
        lang_norm = language.strip()
        if lang_norm and lang_norm not in ALLOWED_LANGUAGES:
            raise ValueError(f"unsupported language: {language!r}")

    if url and url.lstrip().startswith("-"):
        raise ValueError("url must not start with '-'")
    if input_path and input_path.lstrip().startswith("-"):
        raise ValueError("input_path must not start with '-'")

    cmd = ["python", "-u", "-m", "clippyme.pipeline.orchestrator"]
    if url:
        cmd.extend(["-u", url])
        if cookies_path and os.path.exists(cookies_path):
            cmd.extend(["-c", cookies_path])
    elif input_path:
        cmd.extend(["-i", input_path])
    cmd.extend(["-o", output_dir])
    if instructions:
        cmd.extend(["--instructions", instructions])
    if reframe_mode and reframe_mode != "auto":
        cmd.extend(["--reframe-mode", reframe_mode])
    if aspect and aspect != "9:16":
        cmd.extend(["--aspect", aspect])
    if language and language.strip() and language.strip() != "multi":
        cmd.extend(["--language", language.strip()])
    if no_zoom:
        cmd.append("--no-zoom")
    if skip_analysis:
        cmd.append("--skip-analysis")
    if model and model.strip():
        cmd.extend(["--model", model.strip()])
    if monitor:
        cmd.append("--monitor")
    return cmd


def _build_clips(data: dict, base_name: str, job_id: str, output_dir: str, only_ready: bool) -> list:
    clips = data.get("shorts", [])

    try:
        from clippyme.pipeline.gemini_parser import backfill_hook_text

        transcript = data.get("transcript") or {}
        words = []
        for segment in transcript.get("segments", []) or []:
            for word in segment.get("words", []) or []:
                words.append({
                    "w": word.get("word", ""),
                    "s": word.get("start", 0.0),
                    "e": word.get("end", 0.0),
                })
        backfill_hook_text(clips, words, fallback_title=base_name)
    except Exception as exc:
        logger.debug("backfill_hook_text failed: %s", exc)

    result = []
    fake_metadata_path = f"{base_name}_metadata.json"
    for index, clip in enumerate(clips):
        if clip.get("deleted_after_publish"):
            continue
        clip_filename = clip_filename_for(fake_metadata_path, clip, index)
        clip_path = os.path.join(output_dir, clip_filename)
        exists = os.path.exists(clip_path) and os.path.getsize(clip_path) > 0
        if only_ready and not exists:
            continue
        clip["video_url"] = f"/videos/{job_id}/{clip_filename}"
        clip["original_index"] = index
        result.append(clip)
    return result


def _pick_latest_metadata(output_dir: str) -> str | None:
    """Return the most-recently-modified ``*_metadata.json`` path."""
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
    if not json_files:
        return None
    try:
        json_files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    except OSError:
        pass
    return json_files[0]


def _result_payload(data: dict, clips: list, output_dir: str) -> dict:
    payload = {
        "clips": clips,
        "cost_analysis": data.get("cost_analysis"),
        "source_info": data.get("source_info"),
    }
    payload.update(runtime_result_fields(output_dir))
    return payload


def load_partial_result(job_id: str, output_dir: str) -> dict | None:
    """Read metadata and return clips already present plus runtime operations."""
    try:
        target_json = _pick_latest_metadata(output_dir)
        if not target_json:
            runtime = runtime_result_fields(output_dir)
            return {"clips": [], **runtime} if runtime else None
        if os.path.getsize(target_json) <= 0:
            return None
        with open(target_json, encoding="utf-8") as handle:
            data = json.load(handle)
        base_name = os.path.basename(target_json).replace("_metadata.json", "")
        ready = _build_clips(data, base_name, job_id, output_dir, only_ready=True)
        runtime = runtime_result_fields(output_dir)
        if not ready and not runtime:
            return None
        return _result_payload(data, ready, output_dir)
    except (OSError, json.JSONDecodeError, ValueError):
        runtime = runtime_result_fields(output_dir)
        return {"clips": [], **runtime} if runtime else None


def load_final_result(job_id: str, output_dir: str) -> dict | None:
    """Return the final metadata plus operational/QA state."""
    try:
        target_json = _pick_latest_metadata(output_dir)
        if not target_json:
            return None
        with open(target_json, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, ValueError):
        return None

    base_name = os.path.basename(target_json).replace("_metadata.json", "")
    clips = _build_clips(data, base_name, job_id, output_dir, only_ready=False)
    payload = _result_payload(data, clips, output_dir)
    payload["gemini_exhausted"] = data.get("gemini_exhausted")
    return payload
