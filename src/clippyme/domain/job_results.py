"""Job result loading helpers + main.py command builder extracted from app.py."""
from __future__ import annotations

import glob
import json
import os
import re

ALLOWED_REFRAME_MODES = frozenset({"auto", "disabled"})
MAX_INSTRUCTIONS_LEN = 2000

# Per-job Gemini model override must look like a real Gemini model id. We don't
# pin an exact allow-list here (newer families like gemini-3* ship continuously
# and are surfaced via live discovery), but we DO enforce the family prefix +
# a safe charset so the value can't smuggle argv flags or shell metacharacters
# into the pipeline subprocess. The Settings discovery dropdown is the canonical
# source of valid ids; this is the boundary guard.
GEMINI_MODEL_RE = re.compile(r"^gemini-[A-Za-z0-9.\-]{1,64}$")

# Languages we explicitly allow the frontend to request for Deepgram.
# Keep this aligned with Nova-3's supported single-language codes:
# https://developers.deepgram.com/docs/models-languages-overview
# ``multi`` stays the default — the language override is OPT-IN per job.
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
) -> list[str]:
    """Build a `python -u -m clippyme.pipeline.main ...` command line for a single processing job."""
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

    # Reject argv-injection attempts: any value starting with "-" would
    # be interpreted as a new flag by argparse. yt-dlp URLs and uploaded
    # file paths never legitimately start with a dash.
    if url and url.lstrip().startswith("-"):
        raise ValueError("url must not start with '-'")
    if input_path and input_path.lstrip().startswith("-"):
        raise ValueError("input_path must not start with '-'")

    cmd = ["python", "-u", "-m", "clippyme.pipeline.main"]
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
    return cmd


def _build_clips(data: dict, base_name: str, job_id: str, output_dir: str, only_ready: bool) -> list:
    clips = data.get('shorts', [])

    # Defensive backfill: old metadata.json files (from jobs generated
    # before the viral_hook_text schema field existed) will be missing
    # hooks entirely. Rehydrate them here so the frontend always has a
    # non-empty hook regardless of job age. Transcript words may or
    # may not be present depending on how the pipeline dumped metadata.
    try:
        from clippyme.pipeline.gemini_parser import backfill_hook_text
        transcript = data.get('transcript') or {}
        words = []
        for segment in transcript.get('segments', []) or []:
            for w in segment.get('words', []) or []:
                words.append({
                    'w': w.get('word', ''),
                    's': w.get('start', 0.0),
                    'e': w.get('end', 0.0),
                })
        backfill_hook_text(clips, words, fallback_title=base_name)
    except Exception:
        # Never break result loading because of backfill logic —
        # stale metadata should still render even if hooks are empty.
        pass

    result = []
    for i, clip in enumerate(clips):
        clip_filename = f"{base_name}_clip_{i+1}.mp4"
        clip_path = os.path.join(output_dir, clip_filename)
        exists = os.path.exists(clip_path) and os.path.getsize(clip_path) > 0
        if only_ready and not exists:
            continue
        clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
        # Attach the ABSOLUTE position in the original `shorts` array.
        # This is the React key the frontend uses for useClipStates[]
        # and for the ResultsGrid map. Without it, partial-result
        # polling returns a growing subset and the frontend's
        # positional index shifts as more clips come online — causing
        # stale <video> elements to get reconciled with a different
        # clip's video_url (the "grey screen while processing" bug).
        clip['original_index'] = i
        result.append(clip)
    return result


def _pick_latest_metadata(output_dir: str) -> str | None:
    """Return the most-recently-modified ``*_metadata.json`` path.

    When a job directory accidentally ends up with more than one metadata
    file (e.g. reprocessing with a slightly different sanitized title),
    glob[0] is filesystem-order dependent and non-deterministic. Sort by
    mtime so the user always sees the latest run.
    """
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
    if not json_files:
        return None
    try:
        json_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    except OSError:
        pass
    return json_files[0]


def load_partial_result(job_id: str, output_dir: str) -> dict | None:
    """Read metadata + return result dict for clips already on disk. None if nothing ready."""
    try:
        target_json = _pick_latest_metadata(output_dir)
        if not target_json:
            return None
        if os.path.getsize(target_json) <= 0:
            return None
        with open(target_json, 'r') as f:
            data = json.load(f)
        base_name = os.path.basename(target_json).replace('_metadata.json', '')
        ready = _build_clips(data, base_name, job_id, output_dir, only_ready=True)
        if not ready:
            return None
        return {'clips': ready, 'cost_analysis': data.get('cost_analysis')}
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def load_final_result(job_id: str, output_dir: str) -> dict | None:
    """Read metadata + return result with all clips. None if no metadata file.

    Catches JSON / OSError so callers can treat a corrupt metadata file
    the same as a missing one instead of crashing the request handler.
    """
    try:
        target_json = _pick_latest_metadata(output_dir)
        if not target_json:
            return None
        with open(target_json, 'r') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None

    base_name = os.path.basename(target_json).replace('_metadata.json', '')
    clips = _build_clips(data, base_name, job_id, output_dir, only_ready=False)
    return {'clips': clips, 'cost_analysis': data.get('cost_analysis')}
