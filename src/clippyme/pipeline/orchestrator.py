"""Checkpointed backend entrypoint for the ClippyMe video pipeline.

The historical :mod:`clippyme.pipeline.main` remains the owner of the heavy CV,
transcription and Gemini functions. This module imports those functions and
replaces only the CLI orchestration used by queued backend jobs, adding atomic
phase checkpoints, per-clip resume, preflight, QA and operational progress.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from clippyme.jobs.runtime_state import RuntimeState
from clippyme.pipeline.ffmpeg_exec import FfmpegError, remove_quietly, run_ffmpeg_atomic
from clippyme.pipeline.gemini_request import DEFAULT_RETRY_MODEL, build_model_chain
from clippyme.pipeline.media_qa import inspect_clip, probe_media
from clippyme.pipeline.preflight import (
    PreflightInputs,
    PreflightRejected,
    build_preflight,
    enforce_preflight,
    format_preflight_log,
)
from clippyme.pipeline.reframe_ops import normalize_letterbox_zoom
from clippyme.pipeline.run_ops import (
    build_cut_command,
    clip_output_basename,
    resolve_output_dir,
    sanitize_windows_basename,
    should_use_fallback,
)

logger = logging.getLogger("clippyme")
_FALSE_VALUES = {"0", "false", "no", "off"}


def _atomic_json(path: str, payload: dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pipeline-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        tmp = ""
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _load_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _safe_output_artifact(path: str | None, output_dir: str) -> str | None:
    """Accept checkpoint paths only when contained by this job directory."""
    if not path:
        return None
    try:
        candidate = Path(path).resolve()
        root = Path(output_dir).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return str(candidate)


def _valid_file(path: str | None, minimum: int = 1) -> bool:
    try:
        return bool(path and os.path.isfile(path) and os.path.getsize(path) >= minimum)
    except OSError:
        return False


def _playable(path: str) -> bool:
    """ffprobe reads the container and finds a video stream with a duration."""
    report = probe_media(path)
    return bool(not report.get("probe_error") and report.get("has_video") and (report.get("duration") or 0) > 0)


# A complete cut can fall short of end-start by frame rounding or by the source
# ending first; an interrupted one (SIGTERM makes ffmpeg finalise what it has)
# falls short by far more.
_SLICE_SHORTFALL_SECONDS = 0.5


def _reusable_slice(path: str, expected_duration: float) -> bool:
    """Only a readable slice of (nearly) the planned length is resumed from."""
    if not _valid_file(path, 10_000):
        return False
    report = probe_media(path)
    duration = float(report.get("duration") or 0.0)
    return bool(
        not report.get("probe_error")
        and report.get("has_video")
        and duration >= expected_duration * 0.99 - _SLICE_SHORTFALL_SECONDS
    )


def _enabled(name: str, default: str = "1") -> bool:
    return str(os.getenv(name, default)).strip().lower() not in _FALSE_VALUES


def _nonnegative_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default)) or default))
    except (TypeError, ValueError):
        return max(0, int(default))


def _source_fingerprint(path: str) -> str | None:
    """Cheap stable identity: size + first/last MiB, not a full multi-GB hash."""
    try:
        size = os.path.getsize(path)
        digest = hashlib.sha256()
        digest.update(str(size).encode("ascii"))
        with open(path, "rb") as handle:
            digest.update(handle.read(1024 * 1024))
            if size > 1024 * 1024:
                handle.seek(max(0, size - 1024 * 1024))
                digest.update(handle.read(1024 * 1024))
        return digest.hexdigest()
    except OSError:
        return None


def _safe_clip_filename(value: str | None) -> str | None:
    if not value or "/" in value or "\\" in value or os.path.basename(value) != value:
        return None
    if value.startswith(".") or not value.lower().endswith(".mp4"):
        return None
    return value


def _save_metadata(path: str, data: dict[str, Any]) -> None:
    _atomic_json(path, data)
    print(f"   💾 checkpoint metadata: {os.path.basename(path)}", flush=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ClippyMe checkpointed pipeline orchestrator")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("-i", "--input", type=str)
    inputs.add_argument("-u", "--url", type=str)
    parser.add_argument("-o", "--output", type=str, required=True)
    parser.add_argument("--keep-original", action="store_true")
    parser.add_argument("--skip-analysis", action="store_true")
    parser.add_argument("-c", "--cookies", type=str)
    parser.add_argument("--instructions", type=str)
    parser.add_argument("--no-zoom", action="store_true")
    parser.add_argument(
        "--reframe-mode",
        choices=["auto", "disabled", "subject", "object"],
        default="auto",
    )
    parser.add_argument("--letterbox-zoom", type=float, default=0.0)
    parser.add_argument("--start-offset", type=float, default=0.0)
    parser.add_argument("--language", type=str, default=None)
    parser.add_argument("--aspect", choices=["9:16", "1:1", "16:9"], default="9:16")
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--model", type=str, default=None)
    return parser.parse_args(argv)


def _configure_overrides(args: argparse.Namespace) -> None:
    if args.model:
        if not re.match(r"^gemini-[A-Za-z0-9.\-]{1,64}$", args.model):
            raise ValueError(f"invalid --model: {args.model!r}")
        os.environ["GEMINI_MODEL"] = args.model
        print(f"🤖 Gemini model override: {args.model}", flush=True)
    if args.language:
        if not re.match(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{2,8})?$", args.language):
            raise ValueError(f"invalid --language: {args.language!r}")
        os.environ["DEEPGRAM_LANGUAGE"] = args.language
        os.environ["ELEVENLABS_LANGUAGE"] = args.language
        os.environ["CLIPPYME_LANGUAGE"] = args.language
        print(f"🌐 Language override: {args.language}", flush=True)


def _expected_aspect(label: str) -> float:
    return {"9:16": 9 / 16, "1:1": 1.0, "16:9": 16 / 9}.get(label, 9 / 16)


def _max_clips_from_env() -> int | None:
    try:
        value = int(os.getenv("CLIPPYME_MAX_CLIPS", "0") or 0)
        return value if value > 0 else None
    except ValueError:
        return None


def _transcript_cache_key(args: argparse.Namespace) -> str | None:
    """Cache slot for a URL job: the URL, plus the head trim when there is one."""
    if not args.url:
        return None
    try:
        offset = float(getattr(args, "start_offset", 0.0) or 0.0)
    except (TypeError, ValueError):
        offset = 0.0
    return f"{args.url}#start={int(offset)}" if offset > 0 else args.url


def _trim_head(input_video: str, output_dir: str, offset: float) -> tuple[str, float]:
    """Drop the first ``offset`` seconds of the source, stream-copied.

    This is the VOD counterpart of the live monitor's prelive skip: the
    recording of a stream starts with the waiting screen, which is worth
    nothing and costs transcription. Every downstream timestamp is relative to
    the trimmed file, so nothing else needs to know about the offset.

    Returns ``(path, seconds skipped)``. Falls back to the untouched source
    (skipped = 0) on any failure — a truncated container, a missing ffmpeg, an
    offset past the end, a wedged pass — because a bad skip must not fail a job.
    """
    try:
        seconds = float(offset or 0.0)
    except (TypeError, ValueError):
        return input_video, 0.0
    if seconds <= 0:
        return input_video, 0.0

    trimmed = os.path.join(output_dir, f"trimmed_{os.path.basename(input_video)}")
    try:
        run_ffmpeg_atomic(
            lambda dest: ["ffmpeg", "-y", "-ss", f"{seconds:.3f}", "-i", input_video,
                          "-c", "copy", "-avoid_negative_ts", "make_zero", dest],
            trimmed,
            validate=_playable,
        )
    except (FfmpegError, OSError) as exc:
        print(f"⚠️ start-offset trim failed ({exc}); using the untrimmed source", flush=True)
        return input_video, 0.0
    print(f"✂️ Skipped the first {seconds:.0f}s of the source", flush=True)
    return os.path.abspath(trimmed), seconds


def _reusable_source(args: argparse.Namespace, output_dir: str, state: RuntimeState) -> str | None:
    """The source a previous attempt acquired — already trimmed — if intact.

    The head trim belongs to acquisition: it is applied once, to the original
    download/upload, and later attempts resume from its result. Trimming
    whatever the checkpoint points at would skip the offset a second time and
    shift every reused transcript/clip timestamp by it. The fingerprint recorded
    with the artefact rejects a file that was replaced or torn since.
    """
    if not state.completed("acquiring") or state.artifact("source_url") != args.url:
        return None
    recorded = state.artifact("input_video")
    prior = _safe_output_artifact(recorded, output_dir)
    if prior is None and args.input and recorded and os.path.abspath(str(recorded)) == os.path.abspath(args.input):
        prior = os.path.abspath(args.input)  # an upload used untrimmed lives outside the job dir
    expected = state.artifact("source_fingerprint")
    if not _valid_file(prior) or not expected or _source_fingerprint(prior) != expected:
        return None
    return prior


def _prepare_input(args: argparse.Namespace, output_dir: str, state: RuntimeState, legacy):
    state.start("acquiring", "acquiring source media")
    prior = _reusable_source(args, output_dir, state)
    if prior:
        print(f"♻️ Resume: reusing acquired source {os.path.basename(prior)}", flush=True)
        state.complete_stage("acquiring", detail="source media ready")
        return prior, str(state.artifact("video_title") or Path(prior).stem)

    if args.input:
        original = os.path.abspath(args.input)
        if not _valid_file(original):
            raise FileNotFoundError(f"Input file not found or empty: {original}")
        video_title = os.path.splitext(os.path.basename(original))[0]
    else:
        original, video_title = legacy.download_youtube_video(
            args.url,
            output_dir,
            args.cookies,
        )
        original = os.path.abspath(original)
    if not _valid_file(original):
        raise FileNotFoundError(f"Input file not found or empty: {original}")
    input_video, skipped = _trim_head(original, output_dir, getattr(args, "start_offset", 0.0))
    state.complete_stage(
        "acquiring",
        artifacts={
            "input_video": input_video,
            "video_title": video_title,
            "source_url": args.url,
            "source_fingerprint": _source_fingerprint(input_video),
            "head_trim_seconds": skipped,
            # The download the trim was cut from: deleted with the source on
            # completion (an upload's original belongs to the uploads dir).
            "untrimmed_source": original if args.url and input_video != original else None,
        },
        detail="source media ready",
    )
    return input_video, video_title


def _run_preflight(args, input_video: str, output_dir: str, state: RuntimeState, legacy):
    state.start("preflight", "checking duration, cost and capacity")
    probe = probe_media(input_video)
    duration = float(probe.get("duration") or 0.0)
    if duration <= 0:
        cap = legacy.cv2.VideoCapture(input_video)
        try:
            fps = float(cap.get(legacy.cv2.CAP_PROP_FPS) or 0)
            frames = int(cap.get(legacy.cv2.CAP_PROP_FRAME_COUNT) or 0)
        finally:
            cap.release()
        duration = frames / fps if fps > 0 and frames > 0 else 0.0
    try:
        free_disk = shutil.disk_usage(output_dir).free
    except OSError:
        free_disk = None
    model = args.model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    fallback_env = os.getenv("GEMINI_FALLBACK_MODELS")
    report = build_preflight(
        PreflightInputs(
            duration_seconds=duration,
            input_bytes=int(probe.get("size_bytes") or os.path.getsize(input_video)),
            width=probe.get("width"),
            height=probe.get("height"),
            model=model,
            aspect=args.aspect,
            has_gpu=bool(getattr(legacy, "CUDA_AVAILABLE", False)),
            max_clips=_max_clips_from_env(),
            analysis_enabled=not args.skip_analysis,
            fallback_models=tuple(build_model_chain(model, fallback_env)[1:]),
            retry_models=tuple(build_model_chain(
                os.getenv("GEMINI_RETRY_MODEL") or DEFAULT_RETRY_MODEL, fallback_env)),
        ),
        pricing=getattr(legacy, "MODEL_PRICING", {}),
        free_disk_bytes=free_disk,
    )
    state.set_preflight(report)
    print(format_preflight_log(report), flush=True)
    enforce_preflight(report)
    state.complete_stage("preflight", detail="preflight passed")
    return report, duration


def _load_or_transcribe(args, input_video: str, state: RuntimeState, legacy):
    transcript_path = os.path.join(state.checkpoint_dir, "transcript.json")
    if args.skip_analysis:
        transcript = {"segments": [], "skipped": True}
        state.start("transcribing", "transcription skipped by request")
        _atomic_json(transcript_path, transcript)
        state.complete_stage(
            "transcribing",
            artifacts={"transcript": transcript_path},
            detail="transcription skipped",
        )
        return transcript
    if state.completed("transcribing"):
        transcript = _load_json(transcript_path)
        if transcript and isinstance(transcript.get("segments"), list):
            print("♻️ Resume: reusing transcript checkpoint", flush=True)
            return transcript

    state.start("transcribing", "transcribing speech")
    # A trimmed source has its own timeline, so it needs its own cache slot —
    # otherwise a later run with a different skip reuses shifted timestamps.
    cache_key = _transcript_cache_key(args)
    transcript = legacy._load_cached_transcript(cache_key) if cache_key else None
    if transcript:
        print("♻️ Reusing shared URL transcript cache", flush=True)
    else:
        transcript = legacy.transcribe_video(input_video)
        if cache_key:
            legacy._save_transcript_cache(cache_key, transcript)
    if not isinstance(transcript, dict):
        raise RuntimeError("transcription returned no structured result")
    _atomic_json(transcript_path, transcript)
    state.complete_stage(
        "transcribing",
        artifacts={"transcript": transcript_path},
        detail="transcript ready",
    )
    return transcript


def _whole_video_fallback(video_title: str, duration: float) -> dict[str, Any]:
    return {
        "shorts": [{
            "start": 0.0,
            "end": max(0.1, duration),
            "video_title_for_youtube_short": video_title,
            "video_description_for_tiktok": "",
            "video_description_for_instagram": "",
            "viral_hook_text": "",
            "viral_score": 0,
            "viral_reason": "Whole-video fallback because no valid candidate clips were available.",
        }]
    }


def _load_or_analyze(
    args,
    input_video: str,
    video_title: str,
    output_dir: str,
    duration: float,
    transcript: dict,
    state: RuntimeState,
    legacy,
):
    prior_metadata = _safe_output_artifact(state.artifact("metadata"), output_dir)
    safe_title = sanitize_windows_basename(video_title, max_len=100) or "video"
    default_metadata = os.path.join(output_dir, f"{safe_title}_metadata.json")
    metadata_file = prior_metadata or default_metadata
    if state.completed("analyzing"):
        saved = _load_json(metadata_file)
        if saved and isinstance(saved.get("shorts"), list):
            print("♻️ Resume: reusing analysis metadata checkpoint", flush=True)
            return saved, metadata_file

    state.start("analyzing", "selecting and validating clip candidates")
    if args.skip_analysis:
        clips_data = _whole_video_fallback(video_title, duration)
    else:
        clips_data = legacy.get_viral_clips(
            transcript,
            duration,
            instructions=args.instructions,
        )
        if not clips_data or "shorts" not in clips_data:
            if should_use_fallback(args.monitor):
                clips_data = legacy.build_texttiling_fallback(transcript, video_title)
        if not clips_data or not clips_data.get("shorts"):
            if not should_use_fallback(args.monitor):
                clips_data = {
                    "shorts": [],
                    "gemini_exhausted": bool(
                        getattr(legacy.get_viral_clips, "_last_gemini_exhausted", False)
                    ),
                }
            else:
                print("⚠️ No valid AI/topic clips; using whole-video fallback", flush=True)
                clips_data = _whole_video_fallback(video_title, duration)

    clips_data["transcript"] = transcript
    clips_data["aspect"] = args.aspect
    shorts = clips_data.get("shorts") or []
    max_clips = _max_clips_from_env()
    if max_clips and len(shorts) > max_clips:
        print(
            f"✂️ CLIPPYME_MAX_CLIPS={max_clips}: keeping the highest-ranked "
            f"{max_clips} of {len(shorts)} candidates",
            flush=True,
        )
        shorts = shorts[:max_clips]
        clips_data["shorts"] = shorts

    if shorts and not args.skip_analysis:
        from clippyme.pipeline.cut_ops import flatten_words, snap_clips_to_transcript

        words = flatten_words(transcript)
        silences: list = []
        if _enabled("CLIPPYME_SILENCE_SNAP"):
            try:
                from clippyme.pipeline.media_probe import detect_silences

                silences = detect_silences(input_video)
            except Exception as exc:  # noqa: BLE001
                print(f"⚠️ Silence snap unavailable: {exc}", flush=True)
        for event in snap_clips_to_transcript(
            shorts,
            words,
            source_duration=duration or None,
            silences=silences,
            default_reframe_mode=args.reframe_mode,
        ):
            print(
                f"🎯 snap[{event.path}]: [{event.old_start:.2f},{event.old_end:.2f}] "
                f"→ [{event.new_start:.2f},{event.new_end:.2f}]",
                flush=True,
            )

    source_info = _load_json(os.path.join(output_dir, "source_info.json"))
    if source_info:
        clips_data["source_info"] = source_info
    _save_metadata(metadata_file, clips_data)
    state.set_clip_total(len(shorts))
    state.complete_stage(
        "analyzing",
        artifacts={"metadata": metadata_file},
        detail="clip plan ready",
    )
    return clips_data, metadata_file


def _qa_status(report: dict[str, Any]) -> str:
    if report.get("critical"):
        return "failed"
    if report.get("warnings"):
        return "warning"
    return "ready"


def _clip_bounds(clip: dict[str, Any]) -> tuple[float, float]:
    start = float(clip["start"])
    end = float(clip["end"])
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError(f"invalid clip interval: start={start!r}, end={end!r}")
    return start, end


def _render_one_clip(
    *,
    index: int,
    total: int,
    clip: dict[str, Any],
    input_video: str,
    video_title: str,
    output_dir: str,
    metadata_file: str,
    clips_data: dict[str, Any],
    args: argparse.Namespace,
    aspect_ratio: float,
    state: RuntimeState,
    legacy,
) -> bool:
    start, end = _clip_bounds(clip)
    expected_duration = end - start
    title = clip.get("video_title_for_youtube_short") or clip.get("title")
    existing_name = _safe_clip_filename(clip.get("clip_filename"))
    clip_filename = existing_name or f"{clip_output_basename(title, index, video_title)}.mp4"
    clip["clip_filename"] = clip_filename
    clip_source = os.path.join(output_dir, f"source_{clip_filename}")
    clip_final = os.path.join(output_dir, clip_filename)
    _save_metadata(metadata_file, clips_data)

    if _valid_file(clip_final, 10_000):
        report = inspect_clip(
            clip_final,
            expected_duration=expected_duration,
            expected_aspect=aspect_ratio,
            run_signal_checks=_enabled("CLIPPYME_QA_SIGNAL"),
        )
        if not report.get("critical"):
            clip["qa"] = report
            state.mark_clip(index, _qa_status(report), report)
            _save_metadata(metadata_file, clips_data)
            print(f"♻️ Resume: clip {index + 1}/{total} already valid", flush=True)
            return True
        try:
            os.remove(clip_final)
        except OSError:
            pass

    state.start(
        "cutting",
        f"cutting clip {index + 1}/{total}",
        progress=62 + int(index / max(1, total) * 8),
    )
    if _reusable_slice(clip_source, expected_duration):
        print(f"♻️ Resume: reusing source slice for clip {index + 1}", flush=True)
    else:
        print(f"✂️ Clip {index + 1}/{total}: {start:.2f}s → {end:.2f}s", flush=True)
        try:
            run_ffmpeg_atomic(
                lambda dest: build_cut_command(input_video, start, end, dest),
                clip_source,
                validate=_playable,
            )
        except FfmpegError as exc:
            raise RuntimeError(f"ffmpeg cut failed for clip {index + 1}: {exc}") from exc

    state.start(
        "reframing",
        f"rendering clip {index + 1}/{total}",
        progress=70 + int(index / max(1, total) * 20),
    )
    retries = _nonnegative_int("CLIPPYME_RENDER_QA_RETRIES", 1)
    last_report: dict[str, Any] | None = None
    for render_attempt in range(1, retries + 2):
        temp_output = clip_final + ".render.tmp.mp4"
        # Includes the in-place post-pass temps a killed attempt can leave.
        for stale in (temp_output, temp_output + ".norm.mp4", temp_output + ".zoom.mp4"):
            remove_quietly(stale)
        success = legacy.process_video_to_vertical(
            clip_source,
            temp_output,
            reframe_mode=args.reframe_mode,
            zoom_end=None if args.no_zoom else 1.05,
            aspect_ratio=aspect_ratio,
            letterbox_zoom=normalize_letterbox_zoom(args.letterbox_zoom),
        )
        if not success or not _valid_file(temp_output, 10_000):
            last_report = {
                "ok": False,
                "critical": True,
                "issues": ["reframe produced no valid file"],
                "warnings": [],
            }
        else:
            legacy.normalize_audio(temp_output)
            state.start(
                "quality",
                f"verifying clip {index + 1}/{total}",
                progress=90 + int((index + 1) / max(1, total) * 6),
            )
            last_report = inspect_clip(
                temp_output,
                expected_duration=expected_duration,
                expected_aspect=aspect_ratio,
                run_signal_checks=_enabled("CLIPPYME_QA_SIGNAL"),
            )
        if last_report and not last_report.get("critical"):
            os.replace(temp_output, clip_final)
            # The cover must be based on the stable final basename; generating it
            # from the temporary render would orphan `*.render.tmp_cover.jpg`.
            legacy.select_cover_frame(clip_final)
            clip["qa"] = last_report
            status = _qa_status(last_report)
            state.mark_clip(index, status, last_report)
            _save_metadata(metadata_file, clips_data)
            warning_text = (
                f" with {len(last_report.get('warnings') or [])} warning(s)"
                if status == "warning"
                else ""
            )
            print(
                f"✅ Clip {index + 1}/{total} ready{warning_text}: {clip_filename}",
                flush=True,
            )
            return True
        try:
            os.remove(temp_output)
        except OSError:
            pass
        if render_attempt <= retries:
            print(
                f"🔁 QA rejected clip {index + 1}; render retry {render_attempt}/{retries}",
                flush=True,
            )

    clip["qa"] = last_report or {
        "ok": False,
        "critical": True,
        "issues": ["unknown render failure"],
        "warnings": [],
    }
    state.mark_clip(index, "failed", clip["qa"])
    _save_metadata(metadata_file, clips_data)
    print(f"❌ Clip {index + 1}/{total} failed QA; source slice preserved", flush=True)
    return False


def _cleanup_completed(
    *,
    output_dir: str,
    state: RuntimeState,
    input_video: str,
    is_url: bool,
    keep_original: bool,
    all_clips_ready: bool,
    untrimmed_source: str | None = None,
) -> None:
    if is_url and not keep_original:
        for path in dict.fromkeys(p for p in (input_video, untrimmed_source) if p):
            if not _valid_file(path):
                continue
            try:
                os.remove(path)
                print("🗑️ Cleaned downloaded source after successful completion", flush=True)
            except OSError as exc:
                print(f"⚠️ Could not clean downloaded source: {exc}", flush=True)
    if not all_clips_ready or _enabled("CLIPPYME_KEEP_CHECKPOINTS", "0"):
        return
    # Preserve source_<clip>.mp4: POST /api/reframe needs these slices
    # to change framing without downloading/transcribing again.
    try:
        shutil.rmtree(state.checkpoint_dir)
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"⚠️ Could not clean checkpoint cache: {exc}", flush=True)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = os.path.abspath(resolve_output_dir(args.output, default="."))
    os.makedirs(output_dir, exist_ok=True)
    state = RuntimeState(output_dir, job_id=os.getenv("CLIPPYME_JOB_ID"))
    state.begin_attempt(
        int(os.getenv("CLIPPYME_ATTEMPT", "1") or 1),
        int(os.getenv("CLIPPYME_JOB_MAX_ATTEMPTS", "3") or 3),
    )
    started = time.time()

    try:
        _configure_overrides(args)
        from clippyme.pipeline import main as legacy

        aspect_ratio = _expected_aspect(args.aspect)
        input_video, video_title = _prepare_input(args, output_dir, state, legacy)
        _preflight, duration = _run_preflight(args, input_video, output_dir, state, legacy)
        transcript = _load_or_transcribe(args, input_video, state, legacy)
        clips_data, metadata_file = _load_or_analyze(
            args,
            input_video,
            video_title,
            output_dir,
            duration,
            transcript,
            state,
            legacy,
        )
        clips = clips_data.get("shorts") or []
        if not clips:
            state.start("finalizing", "no valid clips for this source", progress=99)
            state.finish("completed with zero clips")
            _cleanup_completed(
                output_dir=output_dir,
                state=state,
                input_video=input_video,
                is_url=bool(args.url),
                keep_original=args.keep_original,
                untrimmed_source=_safe_output_artifact(state.artifact("untrimmed_source"), output_dir),
                all_clips_ready=True,
            )
            print("🚫 No valid clips generated for this job", flush=True)
            return 0

        ready = 0
        for index, clip in enumerate(clips):
            try:
                if _render_one_clip(
                    index=index,
                    total=len(clips),
                    clip=clip,
                    input_video=input_video,
                    video_title=video_title,
                    output_dir=output_dir,
                    metadata_file=metadata_file,
                    clips_data=clips_data,
                    args=args,
                    aspect_ratio=aspect_ratio,
                    state=state,
                    legacy=legacy,
                ):
                    ready += 1
            except Exception as exc:  # one bad candidate must not lose siblings
                clip["qa"] = {
                    "ok": False,
                    "critical": True,
                    "issues": [str(exc)],
                    "warnings": [],
                }
                state.mark_clip(index, "failed", clip["qa"])
                _save_metadata(metadata_file, clips_data)
                print(f"❌ Clip {index + 1}/{len(clips)} failed: {exc}", flush=True)
                logger.exception("clip %d failed", index + 1)

        state.start("finalizing", "writing final metadata", progress=98)
        _save_metadata(metadata_file, clips_data)
        if ready == 0:
            raise RuntimeError("all candidate clips failed rendering or QA")

        state.finish(f"completed: {ready}/{len(clips)} clips ready")
        _cleanup_completed(
            output_dir=output_dir,
            state=state,
            input_video=input_video,
            is_url=bool(args.url),
            keep_original=args.keep_original,
            untrimmed_source=_safe_output_artifact(state.artifact("untrimmed_source"), output_dir),
            all_clips_ready=ready == len(clips),
        )
        print(f"⏱️ Total execution time: {time.time() - started:.2f}s", flush=True)
        return 0
    except PreflightRejected as exc:
        state.fail(str(exc), resumable=False)
        print(f"❌ Preflight rejected job: {exc}", flush=True)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        state.fail(str(exc), resumable=False)
        print(f"❌ {exc}", flush=True)
        return 2
    except Exception as exc:  # noqa: BLE001
        state.fail(str(exc), resumable=True)
        logger.exception("checkpointed pipeline failed")
        print(f"❌ Pipeline failed: {exc}", flush=True)
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
