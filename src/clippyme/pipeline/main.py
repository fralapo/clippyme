import time
import logging
import cv2
import scenedetect
import subprocess
import argparse
import re
import sys
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
from ultralytics import YOLO
import torch
import os
import numpy as np
from tqdm import tqdm
import yt_dlp
import mediapipe as mp
# import whisper (replaced by faster_whisper inside function)
from google import genai
from dotenv import load_dotenv
import json

from clippyme.pipeline.reframe_ops import OneEuroFilter, drift_to_center, salient_crop_center

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='google.protobuf')

# Load environment variables
load_dotenv()

# --- Constants ---
# Reframe core (cv2/YOLO/MediaPipe) lives in clippyme.pipeline.reframe.
from clippyme.pipeline import reframe  # noqa: E402,F401
from clippyme.pipeline.reframe import (  # noqa: E402,F401
    process_video_to_vertical,
    select_cover_frame,
    analyze_scenes_strategy,
    detect_face_candidates,
    detect_person_yolo,
    compute_mouth_aspect_ratio,
    create_general_frame,
    create_disabled_reframe,
    # Camera/tracker classes + YOLO loader re-exported so existing consumers
    # (and the integration tests) can keep importing them from main.
    DetectionSmoother,
    SmoothedCameraman,
    SpeakerTracker,
    _get_yolo_model,
)
# Transcript cache helpers live in a stdlib-only module (host-testable). Aliased
# to the historical private names so the rest of main.py is unchanged.
from clippyme.pipeline.transcribe_cache import (  # noqa: E402
    CACHE_DIR,
    CACHE_TTL_DAYS,
    get_cache_path as _get_cache_path,
    load_cached_transcript as _load_cached_transcript,
    save_transcript_cache as _save_transcript_cache,
)
# Device + Whisper-model selection live in a shared module so transcription and
# reframe can import them without depending on main.
from clippyme.pipeline.hardware import (  # noqa: E402
    DEVICE,
    CUDA_AVAILABLE,
    GPU_VRAM_GB,
    WHISPER_MODEL,
)

# Pricing table + prompt template + pure request helpers live in the
# host-testable gemini_request module; re-imported here so existing callers
# (and the integration tests) keep finding them on main.
from clippyme.pipeline.gemini_request import (  # noqa: E402,F401
    GEMINI_PROMPT_TEMPLATE,
    MODEL_PRICING,
    backoff_seconds,
    build_reformat_prompt,
    build_viral_prompt,
    compute_gemini_cost,
    is_rate_limit_error,
)

# YOLO is lazy-loaded on first use. Keeping the model at import time
# forced every entry-point (including --reframe-only, which never calls
# detect_person_yolo) to pay the load + GPU transfer cost on startup.




# Whisper models are expensive to construct (weights load + device placement),
# so cache one per (model, device, compute_type) for the life of the process.
# Batch jobs re-using the same config reuse the loaded model instead of paying
# the init cost on every clip.
_whisper_models: dict = {}


def _get_whisper_model(model_name, device, compute_type):
    """Lazy-load + cache a faster-whisper model keyed by its config."""
    from faster_whisper import WhisperModel
    key = (model_name, device, compute_type)
    if key not in _whisper_models:
        _whisper_models[key] = WhisperModel(model_name, device=device, compute_type=compute_type)
    return _whisper_models[key]

# --- MediaPipe Setup ---
# Use standard Face Detection (BlazeFace) for speed

# FaceMesh is used to extract mouth landmarks for active-speaker detection.
# We process small ROIs (the face crop), not the full frame, to keep cost low.
# refine_landmarks=False keeps it fast (478 → 468 landmarks).

# MediaPipe FaceMesh landmark indices for the mouth region
# Upper lip top, lower lip bottom, left mouth corner, right mouth corner
_MOUTH_TOP = 13
_MOUTH_BOTTOM = 14
_MOUTH_LEFT = 78
_MOUTH_RIGHT = 308











# Scene detection (scenedetect+cv2) and download (yt_dlp) live in cv2/YOLO-free,
# host-importable modules. Imported back here so the orchestrator is unchanged.
from clippyme.pipeline.scene_detection import detect_scenes, get_video_resolution  # noqa: E402
from clippyme.pipeline.download import (  # noqa: E402
    download_youtube_video,
    sanitize_filename,
    _resolve_cookies_path,
)


# Audio normalize + Ken Burns zoom live in a cv2-free, host-testable module.
from clippyme.pipeline.postprocess import normalize_audio, apply_subtle_zoom  # noqa: E402
from clippyme.pipeline import texttiling_ops  # noqa: E402







def _diarize_with_pyannote(audio_path: str) -> list[tuple[float, float, int]] | None:
    """Run pyannote.audio speaker-diarization-3.1 on a local audio file.

    Returns a list of ``(start, end, speaker_int)`` tuples in chronological
    order, or ``None`` if diarization is disabled / unavailable / fails.

    Gating:
      - ``WHISPER_DIARIZE=false`` → skip entirely (fast path).
      - pyannote.audio not installed → soft warning + skip (no crash).
      - ``HUGGINGFACE_TOKEN`` missing → warning + skip (the model is gated).

    This keeps pyannote as a fully optional dependency: users who want
    speaker diarization on the Whisper path install it manually via
    ``pip install pyannote.audio>=3.1`` and accept the
    ``pyannote/speaker-diarization-3.1`` license on Hugging Face. The
    rest of the pipeline keeps working with or without speakers.
    """
    if (os.getenv("WHISPER_DIARIZE") or "true").strip().lower() == "false":
        return None

    hf_token = (
        os.getenv("HUGGINGFACE_TOKEN")
        or os.getenv("HF_TOKEN")
        or ""
    ).strip()
    if not hf_token:
        print(
            "   ⚠️  Whisper diarization skipped: HUGGINGFACE_TOKEN not set "
            "(required to download pyannote/speaker-diarization-3.1)."
        )
        return None

    try:
        from pyannote.audio import Pipeline as _PyannotePipeline  # type: ignore
    except ImportError:
        print(
            "   ⚠️  Whisper diarization skipped: pyannote.audio not installed. "
            "Install with `pip install pyannote.audio>=3.1` and accept the "
            "pyannote/speaker-diarization-3.1 license on Hugging Face."
        )
        return None

    try:
        print("   🗣️  Running pyannote speaker diarization (may take a while)…")
        t0 = time.time()
        pipeline = _PyannotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        if CUDA_AVAILABLE:
            try:
                import torch  # type: ignore
                pipeline.to(torch.device("cuda"))
            except Exception:  # noqa: BLE001
                pass
        diarization = pipeline(audio_path)
    except Exception as exc:  # noqa: BLE001 — any pyannote failure is non-fatal
        print(f"   ⚠️  Whisper diarization failed ({exc}); continuing without speakers.")
        return None

    # Normalize pyannote output into (start, end, speaker_int) tuples.
    # pyannote emits labels like "SPEAKER_00", "SPEAKER_01" — map to ints
    # so the downstream shape matches Deepgram's.
    label_to_int: dict[str, int] = {}
    turns: list[tuple[float, float, int]] = []
    for turn, _, label in diarization.itertracks(yield_label=True):
        if label not in label_to_int:
            label_to_int[label] = len(label_to_int)
        turns.append((float(turn.start), float(turn.end), label_to_int[label]))
    turns.sort(key=lambda t: t[0])

    elapsed = time.time() - t0
    n_speakers = len(label_to_int)
    print(
        f"   ✅ pyannote OK — {len(turns)} turns, {n_speakers} speakers, "
        f"wall={elapsed:.1f}s"
    )
    return turns


# Diarization helpers (pure / ffmpeg-only) live in a host-testable module.
from clippyme.pipeline.diarization import (  # noqa: E402
    assign_speakers_to_words as _assign_speakers_to_words,
    extract_audio_to_wav as _extract_audio_to_wav,
    extract_audio_for_asr as _extract_audio_for_asr,
)


def transcribe_video(video_path):
    """Dispatch to the configured transcription provider.

    Provider is selected via the ``TRANSCRIPTION_PROVIDER`` env var:
      - "deepgram" (default) → Deepgram Nova-3 REST API (requires DEEPGRAM_API_KEY)
      - "elevenlabs" → ElevenLabs Scribe REST API (requires ELEVENLABS_API_KEY)
      - anything else / "whisper" → local Faster-Whisper

    On any cloud-provider failure we automatically fall back to Faster-Whisper
    so a misconfigured key never breaks the pipeline.

    Whisper path: after transcription, optionally runs pyannote speaker
    diarization (if ``pyannote.audio`` is installed and a HF token is
    available) and merges speaker labels into the word timestamps so the
    downstream Gemini prompt + subtitle writer see the same ``speaker``
    field as the Deepgram path.
    """
    provider = (os.getenv("TRANSCRIPTION_PROVIDER") or "deepgram").strip().lower()

    # Strip to an audio-only track once so neither backend ingests the full
    # video (see diarization.extract_audio_for_asr). Massively shrinks the
    # Deepgram upload and skips Whisper's video demux at zero accuracy cost.
    # Opt out with CLIPPYME_TRANSCRIBE_AUDIO_ONLY=false; on extraction failure
    # we transparently fall back to the source file.
    asr_input = video_path
    _audio_tmp: str | None = None
    _iso_tmp: str | None = None
    if (os.getenv("CLIPPYME_TRANSCRIBE_AUDIO_ONLY") or "true").strip().lower() != "false":
        _audio_tmp = _extract_audio_for_asr(video_path)
        if _audio_tmp:
            asr_input = _audio_tmp

    # Optional ElevenLabs Voice Isolator pre-pass — strips background noise/music
    # before ASR for cleaner transcripts on noisy sources. Provider-agnostic
    # (helps Whisper/Deepgram too) but needs an ElevenLabs key. Opt-in via
    # ELEVENLABS_AUDIO_ISOLATION; non-fatal — falls back to the raw audio.
    if (os.getenv("ELEVENLABS_AUDIO_ISOLATION") or "false").strip().lower() in ("1", "true", "yes"):
        try:
            from clippyme.pipeline.elevenlabs_transcribe import isolate_audio
            _iso = isolate_audio(asr_input)
            if _iso:
                _iso_tmp = _iso
                asr_input = _iso
        except Exception as exc:  # noqa: BLE001 — isolation is best-effort
            logging.getLogger("clippyme").warning("Voice isolation errored (%s) — skipping", exc)

    try:
        if provider == "deepgram":
            try:
                from clippyme.pipeline.deepgram_transcribe import transcribe_with_deepgram, DeepgramError
                return transcribe_with_deepgram(asr_input)
            except Exception as exc:  # noqa: BLE001 — broad catch for safe fallback
                logging.getLogger("clippyme").warning(
                    "Deepgram transcription failed (%s) — falling back to Faster-Whisper", exc
                )
                print(f"⚠️  Deepgram transcription failed ({exc}); falling back to Faster-Whisper.")
        elif provider == "elevenlabs":
            try:
                from clippyme.pipeline.elevenlabs_transcribe import transcribe_with_elevenlabs
                return transcribe_with_elevenlabs(asr_input)
            except Exception as exc:  # noqa: BLE001 — broad catch for safe fallback
                logging.getLogger("clippyme").warning(
                    "ElevenLabs transcription failed (%s) — falling back to Faster-Whisper", exc
                )
                print(f"⚠️  ElevenLabs transcription failed ({exc}); falling back to Faster-Whisper.")

        device = "cuda" if CUDA_AVAILABLE else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        print(f"🎙️  Transcribing with Faster-Whisper [{WHISPER_MODEL}] ({device.upper()} mode)...")
        model = _get_whisper_model(WHISPER_MODEL, device, compute_type)
        # Honor per-job language override (set by main.py --language → CLIPPYME_LANGUAGE).
        # 'multi' / '' / unset → let Faster-Whisper auto-detect.
        _lang_override = (os.getenv("CLIPPYME_LANGUAGE") or "").strip().lower()
        _whisper_lang = _lang_override if _lang_override and _lang_override != "multi" else None
        if _whisper_lang:
            print(f"   🌐 Whisper language override: {_whisper_lang}")
        segments, info = model.transcribe(
            asr_input, word_timestamps=True, language=_whisper_lang
        )
        segments = list(segments)

        print(f"   Detected language '{info.language}' with probability {info.language_probability:.2f}")

        # Convert to openai-whisper compatible format
        transcript_segments = []
        full_text = ""

        for segment in segments:
            # Print progress to keep user informed (and prevent timeouts feeling)
            print(f"   [{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")

            seg_dict = {
                'text': segment.text,
                'start': segment.start,
                'end': segment.end,
                'words': []
            }

            if segment.words:
                for word in segment.words:
                    seg_dict['words'].append({
                        'word': word.word,
                        'start': word.start,
                        'end': word.end,
                        'probability': word.probability
                    })

            transcript_segments.append(seg_dict)
            full_text += segment.text + " "

        # --- Optional speaker diarization (pyannote.audio) ------------------
        # Runs only when pyannote is installed AND HF token is set AND
        # WHISPER_DIARIZE != "false". Short-circuit BEFORE extracting audio
        # so we don't pay the ffmpeg cost when diarization is disabled.
        wav_tmp: str | None = None
        diarize_enabled = (
            (os.getenv("WHISPER_DIARIZE") or "true").strip().lower() != "false"
            and bool((os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN") or "").strip())
        )
        try:
            if diarize_enabled:
                wav_tmp = _extract_audio_to_wav(video_path)
            if wav_tmp:
                turns = _diarize_with_pyannote(wav_tmp)
                if turns:
                    # Flatten words, merge speakers, then distribute back to
                    # their parent segments via majority vote.
                    flat_words: list[dict] = []
                    for seg in transcript_segments:
                        flat_words.extend(seg.get("words") or [])
                    _assign_speakers_to_words(flat_words, turns)

                    for seg in transcript_segments:
                        counts: dict[int, int] = {}
                        for w in seg.get("words") or []:
                            sp = w.get("speaker")
                            if sp is None:
                                continue
                            counts[sp] = counts.get(sp, 0) + 1
                        if counts:
                            seg["speaker"] = max(counts, key=counts.get)

                    speakers_seen = {sp for _, _, sp in turns}
                    print(f"   🗣️  Whisper transcript enriched with {len(speakers_seen)} speaker label(s).")
        finally:
            if wav_tmp and os.path.exists(wav_tmp):
                try:
                    os.remove(wav_tmp)
                except OSError:
                    pass

        return {
            'text': full_text.strip(),
            'segments': transcript_segments,
            'language': info.language
        }
    finally:
        for _tmp in (_audio_tmp, _iso_tmp):
            if _tmp and os.path.exists(_tmp):
                try:
                    os.remove(_tmp)
                except OSError:
                    pass

def get_viral_clips(transcript_result, video_duration, instructions=None):
    print("🤖  Analyzing with Gemini...")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY not found in environment variables.")
        return None

    client = genai.Client(api_key=api_key)
    
    # Use selected model from env, or default to gemini-3.5-flash
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

    print(f"🤖  Initializing Gemini with model: {model_name}")

    if any(old in model_name for old in ("1.0", "1.5", "2.0")):
        print(f"⚠️  WARNING: {model_name} is deprecated. Please switch to gemini-3.5-flash or later via the dashboard.")

    # Prompt building (word flattening, untrusted-instructions fencing,
    # template fill) is pure — it lives in gemini_request, host-tested.
    prompt, words = build_viral_prompt(transcript_result, video_duration, instructions)

    # Retry with exponential backoff for rate limits / transient errors.
    # 429 (quota) gets a longer base backoff because Google's "wait N
    # seconds" signal lives in the error message rather than structured
    # metadata in the python SDK — we can't honor it precisely, but we
    # can at least slow down instead of retrying immediately.
    response = None
    max_attempts = int(os.getenv("GEMINI_MAX_RETRIES", "3") or "3")
    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"http_options": {"timeout": 120000}},
            )
            break
        except Exception as e:
            is_rate_limit = is_rate_limit_error(e)
            wait = backoff_seconds(is_rate_limit, attempt)
            if attempt < max_attempts - 1:
                reason = "rate-limited" if is_rate_limit else "transient error"
                print(
                    f"⚠️  Gemini API {reason} (attempt {attempt + 1}/{max_attempts}): "
                    f"{e}. Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                print(f"❌ Gemini API failed after {max_attempts} attempts: {e}")
                return None

    if response is None:
        return None

    # --- Cost Calculation (pure math in gemini_request) ---
    cost_analysis = None
    try:
        usage = response.usage_metadata
        if usage:
            cost_analysis = compute_gemini_cost(
                usage.prompt_token_count, usage.candidates_token_count, model_name)
            print(f"💰 Token Usage ({model_name}):")
            print(f"   - Input Tokens: {cost_analysis['input_tokens']} (${cost_analysis['input_cost']:.6f})")
            print(f"   - Output Tokens: {cost_analysis['output_tokens']} (${cost_analysis['output_cost']:.6f})")
            print(f"   - Total Estimated Cost: ${cost_analysis['total_cost']:.6f}")
    except Exception as e:
        print(f"⚠️ Could not calculate cost: {e}")

    # Parse response JSON via the 5-level chain in gemini_parser.
    # See CLAUDE.md section "Gemini viral detection — parsing chain".
    try:
        from clippyme.pipeline.gemini_parser import parse_gemini_response, validate_and_dedupe, backfill_hook_text
        from pydantic import ValidationError

        text = response.text or ""

        def _retry_gemini(err_msg: str) -> str:
            """Level-4 retry: reformat ONLY, using the cheap flash model.

            The reasoning is already done in the primary call — if it
            produced text we just failed to parse, the bottleneck is
            formatting, not understanding. Decouple the two concerns
            (Gopalan, Google Cloud Community, Oct 2025) and hand the
            retry to gemini-2.5-flash which is ~10x cheaper than pro
            and plenty capable of reformatting JSON.

            Crucially, we do NOT resend the full transcript + prompt:
            we hand the model ONLY the previous broken output and ask
            it to reformat. That avoids paying the input-token cost of
            the transcript twice and keeps the retry latency-bounded.
            """
            retry_model = os.getenv("GEMINI_RETRY_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
            retry_prompt = build_reformat_prompt(err_msg, text)
            try:
                retry_resp = client.models.generate_content(
                    model=retry_model,
                    contents=retry_prompt,
                    config={"http_options": {"timeout": 120000}},
                )
                print(f"🔁 Retry via {retry_model} (cheap reformatter)")
                return retry_resp.text or ""
            except Exception as e:
                print(f"⚠️  Gemini retry failed: {e}")
                return ""

        parse_result = parse_gemini_response(
            text,
            retry_fn=_retry_gemini,
            request_id=os.urandom(4).hex(),
        )

        # Structured log line for observability.
        print(
            f"📊 gemini_parse path={parse_result.parse_path} "
            f"duration_ms={parse_result.duration_ms:.1f} "
            f"error={parse_result.error or 'none'}"
        )

        if parse_result.data is None:
            print(f"❌ Failed to parse Gemini response: {parse_result.error}")
            return None

        try:
            clips = validate_and_dedupe(
                parse_result.data,
                video_duration=video_duration,
                overlap_threshold=0.7,
                drop_generic=True,
            )
        except ValidationError as e:
            print(f"❌ Pydantic validation failed: {e}")
            return None

        if not clips:
            print("❌ No valid clips after Pydantic validation + dedupe")
            return None

        # Ensure every clip has a viral_hook_text. Logic lives in
        # gemini_parser.backfill_hook_text so both the main pipeline AND
        # the metadata-reload path in job_results.py use the exact same
        # strategy (no drift between live runs and restored jobs).
        backfill_hook_text(clips, words)

        print(f"✅ {len(clips)} clips passed validation + dedupe")
        result_json = {"shorts": clips}
        if cost_analysis:
            result_json["cost_analysis"] = cost_analysis
        return result_json
    except Exception as e:
        print(f"❌ Unexpected error in Gemini response processing: {e}")
        logging.getLogger("clippyme").exception("Unexpected error in Gemini response processing")
        return None


def build_texttiling_fallback(transcript_result, video_title):
    """No-AI fallback: topic-segment the transcript into clips via lexical TextTiling.

    Returns a ``{"shorts": [...]}`` dict shaped like ``get_viral_clips`` output so
    the clips flow through the identical downstream clip loop, or ``None`` when
    the transcript can't be usefully segmented (caller then renders whole-video).
    Clips carry ``viral_score=0`` and an explicit ``viral_reason`` so the UI shows
    they are heuristic, not AI-judged. See docs/clipsai-analysis.md.
    """
    try:
        segments = (transcript_result or {}).get('segments') or []
        topic_clips = texttiling_ops.find_topic_clips(segments)
        if not topic_clips:
            return None
        print(f"🧩 Gemini unavailable — lexical TextTiling found {len(topic_clips)} topic clips.")
        shorts = []
        for i, tc in enumerate(topic_clips):
            snippet = (tc.get('text') or '').strip()
            shorts.append({
                'start': float(tc['start']),
                'end': float(tc['end']),
                'video_title_for_youtube_short': f"{video_title} — part {i + 1}",
                'tiktok_caption': snippet[:150],
                'viral_score': 0,
                'viral_reason': "Topic-segmented fallback (no AI scoring — Gemini was unavailable).",
                'hook': '',
            })
        return {"shorts": shorts}
    except Exception as e:  # noqa: BLE001 — fallback must never break the pipeline
        print(f"⚠️  TextTiling fallback failed ({e}); will render whole video instead.")
        logging.getLogger("clippyme").exception("TextTiling fallback failed")
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="AutoCrop-Vertical with Viral Clip Detection.")
    
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('-i', '--input', type=str, help="Path to the input video file.")
    input_group.add_argument('-u', '--url', type=str, help="YouTube URL to download and process.")
    
    parser.add_argument('-o', '--output', type=str, help="Output directory or file (if processing whole video).")
    parser.add_argument('--keep-original', action='store_true', help="Keep the downloaded YouTube video.")
    parser.add_argument('--skip-analysis', action='store_true', help="Skip AI analysis and convert the whole video.")
    parser.add_argument('-c', '--cookies', type=str, help="Path to cookies.txt file for yt-dlp")
    parser.add_argument('--instructions', type=str, help="Custom instructions for AI clip selection (e.g., 'find the funniest parts')")
    parser.add_argument('--no-zoom', action='store_true', help="Disable subtle auto-zoom effect on clips")
    parser.add_argument('--reframe-mode', choices=['auto', 'disabled', 'subject', 'object'], default='auto',
                        help='Reframe mode: auto (face tracking), subject (FrameShift face-first '
                             'crop; "object" is a legacy alias), or disabled (4:3 crop with black bars)')
    parser.add_argument('--reframe-only', action='store_true',
                        help='Skip download/analysis/cutting: take --input (an existing 16:9 '
                             'source slice) and re-run reframing + zoom/normalize/cover only. '
                             'Used by POST /api/reframe to switch modes on an already-generated clip.')
    parser.add_argument('--language', type=str, default=None,
                        help="Override ASR language for this job (e.g. 'en', 'it', 'es', 'multi'). "
                             "When unset, Deepgram uses DEEPGRAM_LANGUAGE from env (default 'multi' "
                             "for native EN+IT code-switching). Single-language mode improves both "
                             "transcription accuracy AND speaker diarization reliability.")
    parser.add_argument('--aspect', choices=['9:16', '1:1', '16:9'], default='9:16',
                        help="Output aspect ratio: 9:16 vertical (default), 1:1 square, or 16:9 horizontal.")
    parser.add_argument('--model', type=str, default=None,
                        help="Override the Gemini model for viral detection on THIS job (e.g. "
                             "'gemini-2.5-pro', 'gemini-3.1-pro-preview'). When unset, the pipeline uses "
                             "GEMINI_MODEL from env / Settings (default gemini-3.5-flash).")

    args = parser.parse_args()

    # Output aspect ratio drives the crop dimensions + SmoothedCameraman crop
    # box. Passed explicitly to every process_video_to_vertical call below
    # (the old reframe.ASPECT_RATIO cross-module global is gone).
    aspect_ratio = {'9:16': 9 / 16, '1:1': 1.0, '16:9': 16 / 9}.get(args.aspect, 9 / 16)
    if args.aspect != '9:16':
        print(f"📐 Aspect ratio: {args.aspect} ({aspect_ratio:.3f})")

    # Per-job Gemini model override — set the env BEFORE get_viral_clips, which
    # reads GEMINI_MODEL at call time (main.py get_viral_clips). Lets the user
    # pick a different model per run without changing the global Settings value.
    if args.model:
        # Validate here too, not just at the API→subprocess boundary: a direct
        # CLI invocation (`--model '$(evil)'`) would otherwise set an arbitrary
        # value in the child env. Mirrors GEMINI_MODEL_RE in job_results.
        if not re.match(r"^gemini-[A-Za-z0-9.\-]{1,64}$", args.model):
            print(f"❌ invalid --model: {args.model!r}")
            sys.exit(2)
        os.environ["GEMINI_MODEL"] = args.model
        print(f"🤖  Gemini model override: {args.model}")

    # Per-job language override — propagate to the env BEFORE any transcription
    # call so deepgram_transcribe.transcribe_with_deepgram reads the user's
    # choice (it reads DEEPGRAM_LANGUAGE at call time). Also used to hint the
    # Whisper fallback path via faster-whisper's auto-detect being bypassed.
    if args.language:
        # Same defense-in-depth as --model: bound the CLI value before it lands
        # in the child env (consumed by the Deepgram/ElevenLabs REST calls).
        if not re.match(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{2,8})?$", args.language):
            print(f"❌ invalid --language: {args.language!r}")
            sys.exit(2)
        os.environ["DEEPGRAM_LANGUAGE"] = args.language
        os.environ["ELEVENLABS_LANGUAGE"] = args.language
        os.environ["CLIPPYME_LANGUAGE"] = args.language
        print(f"🌐  Language override: {args.language} (overrides default 'multi')")

    # --- Reframe-only fast path: reuse an existing 16:9 slice ----------------
    if args.reframe_only:
        if not args.input or not args.output:
            print("❌ --reframe-only requires both --input (source slice) and --output (target)")
            sys.exit(2)
        if not os.path.exists(args.input):
            print(f"❌ Source slice not found: {args.input}")
            sys.exit(2)
        reframe_start = time.time()
        print(f"🔁 Reframe-only mode ({args.reframe_mode}) on {os.path.basename(args.input)}")
        # Atomic write: render into <output>.reframe.tmp.mp4 so a crash
        # mid-rendering never leaves the user's existing clip truncated
        # or deleted. Only on full success do we os.replace() the temp
        # into the final output path. process_video_to_vertical has an
        # unconditional os.remove(final_output_video) at the top which
        # is what wiped clips on failure before this fix.
        final_output = args.output
        tmp_output = final_output + ".reframe.tmp.mp4"
        try:
            # Ken Burns zoom is folded into the master encode (zoom_end) —
            # one decode+encode generation cheaper than the old separate
            # apply_subtle_zoom pass; reframe.py falls back to the post-pass
            # itself if the fold is impossible.
            success = process_video_to_vertical(
                args.input, tmp_output, reframe_mode=args.reframe_mode,
                zoom_end=None if args.no_zoom else 1.05,
                aspect_ratio=aspect_ratio)
            if not success:
                print("❌ Reframe failed.")
                if os.path.exists(tmp_output):
                    try:
                        os.remove(tmp_output)
                    except OSError:
                        pass
                sys.exit(1)
            normalize_audio(tmp_output)
            select_cover_frame(tmp_output)
            os.replace(tmp_output, final_output)
            print(f"✅ Reframe-only done in {time.time() - reframe_start:.1f}s → {final_output}")
            sys.exit(0)
        except Exception as e:
            print(f"❌ Reframe-only crashed: {e}")
            if os.path.exists(tmp_output):
                try:
                    os.remove(tmp_output)
                except OSError:
                    pass
            sys.exit(1)
    # -------------------------------------------------------------------------


    script_start_time = time.time()

    from clippyme.pipeline.run_ops import build_cut_command, resolve_output_dir

    # 1. Get Input Video
    if args.url:
        output_dir = resolve_output_dir(args.output, default=".")
        input_video, video_title = download_youtube_video(args.url, output_dir, args.cookies)
    else:
        input_video = args.input
        video_title = os.path.splitext(os.path.basename(input_video))[0]
        output_dir = resolve_output_dir(
            args.output,
            default=os.path.dirname(input_video) or ".",
        )

    if not os.path.exists(input_video):
        print(f"❌ Input file not found: {input_video}")
        sys.exit(1)

    # 2. Decision: Analyze clips or process whole?
    if args.skip_analysis:
        print("⏩ Skipping analysis, processing entire video...")
        output_file = args.output if args.output else os.path.join(output_dir, f"{video_title}_vertical.mp4")
        process_video_to_vertical(input_video, output_file, reframe_mode=args.reframe_mode,
                                  aspect_ratio=aspect_ratio)
    else:
        # 3. Transcribe (with cache for URL-based jobs)
        cached = _load_cached_transcript(args.url) if args.url else None
        if cached:
            transcript = cached
        else:
            transcript = transcribe_video(input_video)
            if args.url:
                _save_transcript_cache(args.url, transcript)

        # Get duration
        cap = cv2.VideoCapture(input_video)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            cap.release()
        # OpenCV returns 0 for fps/frame_count on corrupt or unreadable files;
        # guard the division so the pipeline degrades to whole-video mode
        # instead of crashing with ZeroDivisionError.
        if fps and fps > 0 and frame_count > 0:
            duration = frame_count / fps
        else:
            print(f"   ⚠️ Could not read duration (fps={fps}, frames={frame_count}); defaulting to 0.")
            duration = 0.0

        # 4. Gemini Analysis
        clips_data = get_viral_clips(transcript, duration, instructions=args.instructions)

        # Smarter no-AI fallback: when Gemini is unavailable (no key) or its
        # output is unusable, segment the transcript into topic-coherent clips
        # via dependency-light lexical TextTiling instead of dumping the entire
        # source as one giant vertical clip. Topic clips flow through the exact
        # same proven clip loop below (source slice → reframe → zoom/normalize/
        # cover). If TextTiling can't find usable segments we fall through to the
        # original whole-video render. (Ported from ClipsAI — see
        # docs/clipsai-analysis.md.)
        if not clips_data or 'shorts' not in clips_data:
            clips_data = build_texttiling_fallback(transcript, video_title)

        if not clips_data or not clips_data.get('shorts'):
            print("❌ Failed to identify clips. Converting whole video as fallback.")
            output_file = os.path.join(output_dir, f"{video_title}_vertical.mp4")
            process_video_to_vertical(input_video, output_file, reframe_mode=args.reframe_mode,
                                      aspect_ratio=aspect_ratio)
        else:
            print(f"🔥 Found {len(clips_data['shorts'])} viral clips!")
            
            # Save metadata
            clips_data['transcript'] = transcript # Save full transcript for subtitles
            # Annotate each clip with the reframe mode used for the initial
            # render so the dashboard can render the correct per-clip state
            # without guessing (the /api/reframe endpoint updates this
            # field in place when the user flips the mode later on).
            # video-use Hard Rules 6+7: three-stage edge repair (word-snap →
            # sentence-snap → waveform-silence refine), done BEFORE the
            # metadata write so subtitles / Smart Cut (which key off
            # clip.start/end) stay aligned with the render. The whole
            # orchestration is pure and host-tested in cut_ops
            # (snap_clips_to_transcript / compute_neighbor_bounds) — here we
            # only probe the silences and print the returned events.
            from clippyme.pipeline.cut_ops import flatten_words, snap_clips_to_transcript
            _words = flatten_words(transcript)
            # Audio-aware final polish: detect the WAVEFORM silence troughs once
            # for the whole source, then nudge each transcript-snapped edge into
            # the nearest trough so a cut never clips a word's attack/release.
            # Default-on, fully graceful: missing ffmpeg / no silences / env
            # opt-out (CLIPPYME_SILENCE_SNAP=0) all leave the edges untouched.
            _silences: list = []
            if os.environ.get("CLIPPYME_SILENCE_SNAP", "1").lower() not in ("0", "false", "no"):
                try:
                    from clippyme.pipeline.media_probe import detect_silences
                    _silences = detect_silences(input_video)
                    if _silences:
                        print(f"   🔊 waveform: {len(_silences)} silence troughs detected")
                except Exception as _exc:  # never break the pipeline on audio probe
                    print(f"   ⚠️  silence detection skipped: {_exc}")
            for _ev in snap_clips_to_transcript(
                clips_data.get('shorts', []), _words,
                source_duration=duration or None,
                silences=_silences,
                default_reframe_mode=args.reframe_mode,
            ):
                print(f"   🎯 snap[{_ev.path}]: [{_ev.old_start:.2f},{_ev.old_end:.2f}] "
                      f"→ [{_ev.new_start:.2f},{_ev.new_end:.2f}]")
            # Persist the job's output aspect so the post-hoc /api/reframe
            # endpoint can re-render at the SAME ratio. Without this it defaults
            # to 9:16 and silently squashes a 1:1/16:9 job when the user flips
            # reframe mode after the run.
            clips_data['aspect'] = args.aspect
            metadata_file = os.path.join(output_dir, f"{video_title}_metadata.json")
            metadata_tmp = metadata_file + ".tmp"
            with open(metadata_tmp, 'w') as f:
                json.dump(clips_data, f, indent=2)
            os.replace(metadata_tmp, metadata_file)
            print(f"   Saved metadata to {metadata_file}")

            # 5. Process each clip
            for i, clip in enumerate(clips_data['shorts']):
                start = clip['start']
                end = clip['end']
                print(f"\n🎬 Processing Clip {i+1}: {start}s - {end}s")
                print(f"   Title: {clip.get('video_title_for_youtube_short', 'No Title')}")
                
                # Cut clip
                clip_filename = f"{video_title}_clip_{i+1}.mp4"
                # Keep the 16:9 source slice persistently so the user can
                # later switch reframe modes from the dashboard without
                # re-running the entire pipeline. Naming convention:
                # source_<clip_filename>  (picked up by /api/reframe).
                clip_source_path = os.path.join(output_dir, f"source_{clip_filename}")
                clip_final_path = os.path.join(output_dir, clip_filename)

                # ffmpeg cut with re-encoding for exact seconds — argv built by
                # run_ops.build_cut_command (host-tested; see its docstring for
                # the seek/CFR/x264 rationale). On very long sources (1h+) the
                # first cut's input seek can take 30-60s.
                clip_duration = float(end) - float(start)
                cut_command = build_cut_command(input_video, start, end, clip_source_path)
                # Emit a "beat" before/after so the user sees progress even
                # though ffmpeg runs silent (stdout=DEVNULL). Hard timeout of
                # 10 minutes per cut prevents an infinite hang on corrupt
                # sources — 10 min is ~10x the worst legitimate seek time
                # on a 1 hour input video.
                print(f"   ✂️  ffmpeg cut: seek→{start:.2f}s, duration={clip_duration:.2f}s …", flush=True)
                try:
                    cut_proc = subprocess.run(
                        cut_command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        timeout=600,  # 10 min hard cap
                    )
                    if cut_proc.returncode != 0:
                        err_tail = (cut_proc.stderr or b'').decode('utf-8', errors='replace')[-500:]
                        print(f"   ⚠️  ffmpeg cut failed (code {cut_proc.returncode}): {err_tail}", flush=True)
                        continue
                    else:
                        print(f"   ✅ ffmpeg cut done", flush=True)
                except subprocess.TimeoutExpired:
                    print(f"   ❌ ffmpeg cut TIMED OUT after 10 min — skipping this clip. Input may be corrupt or seek is stuck.", flush=True)
                    continue

                # Process vertical from the preserved source slice. Ken Burns
                # zoom rides inside the master encode (zoom_end) — see
                # process_video_to_vertical; the old apply_subtle_zoom pass
                # only runs as its internal fallback.
                success = process_video_to_vertical(
                    clip_source_path, clip_final_path,
                    reframe_mode=args.reframe_mode,
                    zoom_end=None if args.no_zoom else 1.05,
                    aspect_ratio=aspect_ratio)

                if success:
                    normalize_audio(clip_final_path)
                    select_cover_frame(clip_final_path)
                    print(f"   ✅ Clip {i+1} ready: {clip_final_path}")
                    print(f"      📼 Source slice preserved at: {clip_source_path}")
                else:
                    # Without this line the clip is simply ABSENT from the
                    # results grid with zero breadcrumb in the job log.
                    print(f"   ❌ Clip {i+1} reframe failed — skipping "
                          f"(source slice kept at {clip_source_path})", flush=True)

                # NOTE: we intentionally do NOT delete clip_source_path.
                # It's needed by POST /api/reframe/{job_id}/{clip_index} to
                # re-run reframing with a different mode on demand.

    # Clean up original if requested
    if args.url and not args.keep_original and os.path.exists(input_video):
        os.remove(input_video)
        print(f"🗑️  Cleaned up downloaded video.")

    total_time = time.time() - script_start_time
    print(f"\n⏱️  Total execution time: {total_time:.2f}s")
