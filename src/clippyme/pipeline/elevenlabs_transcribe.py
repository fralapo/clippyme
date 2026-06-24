"""ElevenLabs Scribe transcription backend for ClippyMe.

Third transcription provider, alongside Faster-Whisper (local) and Deepgram
Nova-3 (cloud). Returns the **same dict shape** as ``main.transcribe_video`` so
the rest of the pipeline (Gemini analysis, Smart Cut, karaoke subtitles) keeps
working unchanged::

    {
        "text": str,            # full transcript (audio events woven in)
        "segments": [
            {
                "text": str,
                "start": float,
                "end": float,
                "words": [       # SPOKEN words only — never audio events
                    {"word": str, "start": float, "end": float,
                     "probability": float, "speaker"?: int},
                    ...
                ],
                "speaker"?: int,
            },
            ...
        ],
        "language": str,
        "audio_events": [        # ClippyMe extension (laughter/applause/…)
            {"text": str, "start": float, "end": float}, ...
        ],
    }

Design notes
------------
Talks to ElevenLabs' REST API directly (``POST /v1/speech-to-text``) via
``requests`` so we don't add the ``elevenlabs`` SDK dependency — same rationale
as the Deepgram backend. Defensive: transcription is the most expensive step in
the pipeline, so a transient 429 must not abort a batch job.

Two genuine wins over Deepgram, both wired here:

1. **Audio-event tagging** — Scribe emits ``(laughter)`` / ``(applause)`` /
   ``(music)`` tokens (``type == "audio_event"``). Deepgram does not. These are
   a direct, free signal for viral-moment detection, so we keep them OUT of the
   subtitle/smart-cut word stream (which must stay spoken-only) but weave them
   into the top-level ``text`` that the Gemini prompt reads, and surface them
   as an ``audio_events`` list.
2. **Voice isolation** (``isolate_audio``) — ``POST /v1/audio-isolation``
   strips background noise/music before ASR for cleaner transcripts on noisy
   YouTube sources. Opt-in (``ELEVENLABS_AUDIO_ISOLATION``).

Env vars
~~~~~~~~
- ``ELEVENLABS_API_KEY`` (required for the cloud path)
- ``ELEVENLABS_MODEL`` (default ``scribe_v1``; ``scribe_v2`` is newer/better)
- ``ELEVENLABS_LANGUAGE`` (ISO code; blank / ``multi`` → auto-detect)
- ``ELEVENLABS_DIARIZE`` (default ``true``)
- ``ELEVENLABS_NUM_SPEAKERS`` (optional int hint, 1–32)
- ``ELEVENLABS_TAG_AUDIO_EVENTS`` (default ``true``)
- ``ELEVENLABS_NO_VERBATIM`` (default ``false``; strips fillers — scribe_v2 only)
- ``ELEVENLABS_AUDIO_ISOLATION`` (default ``false``; pre-ASR noise removal)
- ``ELEVENLABS_HTTP_TIMEOUT`` (default 600 s)
- ``ELEVENLABS_MAX_RETRIES`` (default 3)
- ``ELEVENLABS_MAX_FILE_MB`` (default 2900, safely below the ~3 GB cap)
"""
from __future__ import annotations

import contextlib
import logging
import math
import os
import re
import tempfile
import time
from typing import Any

import requests

logger = logging.getLogger("clippyme")

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_ISOLATION_URL = "https://api.elevenlabs.io/v1/audio-isolation"
DEFAULT_MODEL = "scribe_v1"
DEFAULT_TIMEOUT = 600
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_FILE_MB = 2900  # ElevenLabs cap is ~3 GB / 10 h
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
SENTENCE_END = (".", "!", "?")
MAX_SEGMENT_DURATION = 12.0

# Module-level session → keeps TLS connections warm across a batch job.
_SESSION: requests.Session | None = None


class ElevenLabsError(RuntimeError):
    """Raised when ElevenLabs transcription fails unrecoverably."""


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


def _reset_session() -> None:
    """Drop the pooled session after a network error or 5xx so the retry
    reconnects on a clean socket (a poisoned keep-alive can fail every retry).
    """
    global _SESSION
    if _SESSION is not None:
        with contextlib.suppress(Exception):
            _SESSION.close()
        _SESSION = None


def _is_v2(model: str) -> bool:
    """``no_verbatim`` is a scribe_v2-only feature."""
    return "v2" in model.lower()


def _should_retry(status: int) -> bool:
    return status in RETRYABLE_STATUS


def _compute_backoff(attempt: int, retry_after: str | None) -> float:
    """Honour Retry-After when present, else exponential backoff (capped)."""
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return min(30.0, 2.0 ** attempt)


def _check_file(audio_path: str) -> int:
    if not os.path.exists(audio_path):
        raise ElevenLabsError(f"File not found: {audio_path}")
    size = os.path.getsize(audio_path)
    if size == 0:
        raise ElevenLabsError(f"File is empty: {audio_path}")
    max_mb = float(os.getenv("ELEVENLABS_MAX_FILE_MB", str(DEFAULT_MAX_FILE_MB)))
    max_bytes = int(max_mb * 1024 * 1024)
    if size > max_bytes:
        raise ElevenLabsError(
            f"File too large for ElevenLabs: {size / 1024 / 1024:.0f} MB "
            f"exceeds the configured cap of {max_mb:.0f} MB"
        )
    return size


def _build_form(model: str, language: str) -> dict[str, str]:
    """Multipart text fields for /v1/speech-to-text.

    Booleans must be lowercase strings in multipart form data. We let
    ``requests`` set the multipart boundary, so callers never set Content-Type.
    """
    form: dict[str, str] = {
        "model_id": model,
        "timestamps_granularity": "word",
        "diarize": (os.getenv("ELEVENLABS_DIARIZE", "true").strip().lower() or "true"),
        "tag_audio_events": (
            os.getenv("ELEVENLABS_TAG_AUDIO_EVENTS", "true").strip().lower() or "true"
        ),
    }
    # Auto-detect on blank / 'multi'; otherwise lock to the requested ISO code.
    if language and language.lower() != "multi":
        form["language_code"] = language
    num_speakers = (os.getenv("ELEVENLABS_NUM_SPEAKERS") or "").strip()
    if num_speakers.isdigit():
        form["num_speakers"] = num_speakers
    # Filler stripping is scribe_v2-only; sending it to v1 would 422.
    if _is_v2(model) and (os.getenv("ELEVENLABS_NO_VERBATIM", "false").strip().lower()
                          in ("1", "true", "yes")):
        form["no_verbatim"] = "true"
    return form


def _post_with_retries(
    url: str,
    headers: dict[str, str],
    form: dict[str, str],
    file_path: str,
    file_field: str,
    timeout: float,
    max_retries: int,
) -> requests.Response:
    """Multipart POST with retry/backoff, re-opening the file each attempt."""
    session = _get_session()
    last_exc: Exception | None = None
    attempt = 0

    while attempt <= max_retries:
        try:
            with open(file_path, "rb") as f:
                files = {file_field: (os.path.basename(file_path), f, "application/octet-stream")}
                response = session.post(
                    url, headers=headers, data=form, files=files, timeout=timeout
                )
        except requests.RequestException as exc:
            last_exc = exc
            _reset_session()
            session = _get_session()
            if attempt >= max_retries:
                raise ElevenLabsError(
                    f"Network error talking to ElevenLabs after {attempt + 1} attempts: {exc}"
                ) from exc
            wait = _compute_backoff(attempt + 1, None)
            print(f"   ⚠️  ElevenLabs network error ({exc}); retrying in {wait:.1f}s…")
            time.sleep(wait)
            attempt += 1
            continue

        if response.status_code == 200:
            return response

        if _should_retry(response.status_code) and attempt < max_retries:
            if response.status_code >= 500:
                _reset_session()
                session = _get_session()
            wait = _compute_backoff(attempt + 1, response.headers.get("Retry-After"))
            print(
                f"   ⚠️  ElevenLabs HTTP {response.status_code}; retrying in {wait:.1f}s "
                f"(attempt {attempt + 1}/{max_retries})…"
            )
            time.sleep(wait)
            attempt += 1
            continue

        # Non-retryable → raise with a sanitized body snippet (strip control/ANSI
        # bytes so a crafted error body can't inject escape sequences into logs).
        snippet = re.sub(r"[\x00-\x1f\x7f]", " ", (response.text or "")[:400])
        # Redact the API key in case the upstream echoes the xi-api-key header
        # back in the error body — it must never reach a log line or exception.
        _secret = headers.get("xi-api-key", "").strip()
        if _secret:
            snippet = snippet.replace(_secret, "***REDACTED***")
        raise ElevenLabsError(f"ElevenLabs returned HTTP {response.status_code}: {snippet}")

    if last_exc:
        raise ElevenLabsError(f"ElevenLabs transcription failed: {last_exc}") from last_exc
    raise ElevenLabsError("ElevenLabs transcription failed: retries exhausted")


def _prob_from_logprob(word: dict[str, Any]) -> float:
    """Scribe returns a per-word ``logprob`` (log-probability), not a 0–1
    confidence. Convert to a probability, clamped to [0, 1]. Default 1.0.
    """
    lp = word.get("logprob")
    if lp is None:
        return 1.0
    try:
        return max(0.0, min(1.0, math.exp(float(lp))))
    except (TypeError, ValueError, OverflowError):
        return 1.0


def _speaker_int(word: dict[str, Any]) -> int | None:
    """``speaker_id`` is a string like ``"speaker_0"`` — map to a 0-based int
    so it matches the Deepgram/Whisper ``speaker`` field shape."""
    sid = word.get("speaker_id")
    if sid is None:
        return None
    m = re.search(r"(\d+)", str(sid))
    if m:
        with contextlib.suppress(ValueError):
            return int(m.group(1))
    return None


def _parse_words(raw_words: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split Scribe's flat token stream into spoken words + audio events.

    Returns ``(spoken_words, audio_events)``. ``spoken_words`` are pipeline-shaped
    dicts (feed subtitles/smart-cut). ``audio_events`` carry ``(laughter)``-style
    markers for the Gemini viral signal — never mixed into the word stream.
    Tokens of ``type == "spacing"`` are dropped.
    """
    spoken: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for w in raw_words or []:
        wtype = (w.get("type") or "word").lower()
        text = (w.get("text") or "").strip()
        if wtype == "spacing" or not text:
            continue
        start = float(w.get("start", 0.0) or 0.0)
        end = float(w.get("end", start) or start)
        if wtype == "audio_event":
            events.append({"text": text, "start": start, "end": end})
            continue
        out = {
            "word": text,
            "start": start,
            "end": end,
            "probability": _prob_from_logprob(w),
        }
        sp = _speaker_int(w)
        if sp is not None:
            out["speaker"] = sp
        spoken.append(out)
    return spoken, events


def _segments_from_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chunk a flat spoken-word list into Whisper-sized segments (break on
    sentence-final punctuation or every ~12 s)."""
    segments: list[dict[str, Any]] = []
    if not words:
        return segments

    current: list[dict[str, Any]] = []
    current_start = float(words[0]["start"])

    def _flush(end_time: float) -> None:
        if not current:
            return
        seg: dict[str, Any] = {
            "text": " ".join(cw["word"] for cw in current).strip(),
            "start": current_start,
            "end": end_time,
            "words": [dict(cw) for cw in current],
        }
        # Majority speaker of the segment, when diarization is present.
        counts: dict[int, int] = {}
        for cw in current:
            sp = cw.get("speaker")
            if sp is not None:
                counts[sp] = counts.get(sp, 0) + 1
        if counts:
            seg["speaker"] = max(counts, key=counts.get)
        segments.append(seg)

    for idx, w in enumerate(words):
        current.append(w)
        end = float(w["end"])
        if w["word"].endswith(SENTENCE_END) or (end - current_start) >= MAX_SEGMENT_DURATION:
            _flush(end)
            current = []
            if idx + 1 < len(words):
                current_start = float(words[idx + 1]["start"])

    if current:
        _flush(float(current[-1]["end"]))
    return segments


def _weave_text(spoken: list[dict[str, Any]], events: list[dict[str, Any]],
                fallback_text: str) -> str:
    """Full transcript string with audio events woven in by timestamp, so the
    Gemini prompt sees ``…funny bit (laughter) and then…``. Falls back to
    Scribe's own ``text`` when there's nothing to weave."""
    if not events:
        return fallback_text
    tokens = [(w["start"], w["word"]) for w in spoken]
    tokens += [(e["start"], e["text"]) for e in events]
    tokens.sort(key=lambda t: t[0])
    woven = " ".join(tok for _, tok in tokens).strip()
    return woven or fallback_text


def isolate_audio(audio_path: str) -> str | None:
    """Voice Isolator: strip background noise/music via /v1/audio-isolation.

    Returns the path to a cleaned temp file, or ``None`` on any failure (the
    caller then transcribes the original audio). Opt-in — the dispatcher only
    calls this when ``ELEVENLABS_AUDIO_ISOLATION`` is enabled.
    """
    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        _check_file(audio_path)
    except ElevenLabsError as exc:
        logger.warning("Voice isolation skipped: %s", exc)
        return None

    timeout = float(os.getenv("ELEVENLABS_HTTP_TIMEOUT", str(DEFAULT_TIMEOUT)))
    max_retries = int(os.getenv("ELEVENLABS_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))
    headers = {"xi-api-key": api_key,
               "User-Agent": "ClippyMe/1.0 (+https://github.com/fralapo/clippyme)"}

    print("🔊 Isolating voice (ElevenLabs) — removing background noise…")
    try:
        # /v1/audio-isolation takes the binary under the `audio` field and
        # returns raw audio bytes (not JSON).
        response = _post_with_retries(
            ELEVENLABS_ISOLATION_URL, headers, {}, audio_path, "audio",
            timeout, max_retries,
        )
    except ElevenLabsError as exc:
        logger.warning("Voice isolation failed (%s) — using original audio", exc)
        print(f"   ⚠️  Voice isolation failed ({exc}); using original audio.")
        return None

    if not response.content:
        logger.warning("Voice isolation returned an empty body — using original audio")
        return None

    fd, out_path = tempfile.mkstemp(suffix="_isolated.mp3", prefix="clippyme_iso_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(response.content)
    except OSError as exc:
        logger.warning("Could not write isolated audio (%s) — using original", exc)
        with contextlib.suppress(OSError):
            os.remove(out_path)
        return None
    print(f"   ✅ Voice isolated ({len(response.content) / 1024:.0f} KB)")
    return out_path


def transcribe_with_elevenlabs(video_path: str) -> dict[str, Any]:
    """Transcribe a local audio/video file via ElevenLabs Scribe.

    Returns a dict matching ``main.transcribe_video``'s shape (plus an
    ``audio_events`` extension). Raises :class:`ElevenLabsError` on
    unrecoverable failure so the caller can fall back to Faster-Whisper.
    """
    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not api_key:
        raise ElevenLabsError("ELEVENLABS_API_KEY is not configured")

    size_bytes = _check_file(video_path)

    model = (os.getenv("ELEVENLABS_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL)
    language = (os.getenv("ELEVENLABS_LANGUAGE", "") or "").strip()
    timeout = float(os.getenv("ELEVENLABS_HTTP_TIMEOUT", str(DEFAULT_TIMEOUT)))
    max_retries = int(os.getenv("ELEVENLABS_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))

    form = _build_form(model, language)
    headers = {
        "xi-api-key": api_key,
        "User-Agent": "ClippyMe/1.0 (+https://github.com/fralapo/clippyme)",
    }

    size_mb = size_bytes / 1024 / 1024
    print(
        f"🎙️  Transcribing with ElevenLabs Scribe [{model}, lang={language or 'auto'}] "
        f"— uploading {size_mb:.1f} MB…"
    )
    logger.info(
        "ElevenLabs transcription start: file=%s size_mb=%.1f model=%s lang=%s",
        os.path.basename(video_path), size_mb, model, language,
    )

    t0 = time.monotonic()
    response = _post_with_retries(
        ELEVENLABS_STT_URL, headers, form, video_path, "file", timeout, max_retries
    )
    elapsed = time.monotonic() - t0

    try:
        payload = response.json()
    except ValueError as exc:
        raise ElevenLabsError(f"ElevenLabs returned non-JSON body: {exc}") from exc

    # Multichannel responses nest per-channel transcripts; collapse to channel 0.
    if "words" not in payload and isinstance(payload.get("transcripts"), list) and payload["transcripts"]:
        payload = payload["transcripts"][0]

    raw_words = payload.get("words") or []
    spoken, events = _parse_words(raw_words)
    segments = _segments_from_words(spoken)

    fallback_text = (payload.get("text") or "").strip()
    full_text = _weave_text(spoken, events, fallback_text)
    if not full_text:
        full_text = " ".join(seg["text"] for seg in segments).strip()

    language_detected = str(payload.get("language_code") or "unknown")
    audio_dur = float(payload.get("audio_duration_secs") or 0.0)

    speedup = (audio_dur / elapsed) if elapsed > 0 and audio_dur else 0.0
    speed_note = f" ({speedup:.1f}× realtime)" if speedup else ""

    speakers_seen = {
        w["speaker"] for seg in segments for w in seg.get("words", [])
        if "speaker" in w
    }
    speaker_note = f", speakers={len(speakers_seen)}" if speakers_seen else ""
    event_note = f", audio_events={len(events)}" if events else ""

    print(
        f"   ✅ ElevenLabs OK — {len(segments)} segments, "
        f"audio={audio_dur:.1f}s, wall={elapsed:.1f}s{speed_note}, "
        f"lang='{language_detected}'{speaker_note}{event_note}"
    )
    logger.info(
        "ElevenLabs transcription done: audio_s=%.1f wall_s=%.1f segments=%d events=%d",
        audio_dur, elapsed, len(segments), len(events),
    )

    return {
        "text": full_text,
        "segments": segments,
        "language": language_detected,
        "audio_events": events,
    }
