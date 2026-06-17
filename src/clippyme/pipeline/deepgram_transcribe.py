"""Deepgram transcription backend for ClippyMe.

Drop-in alternative to the local Faster-Whisper path. Returns the same dict
shape as ``main.transcribe_video`` so the rest of the pipeline (Gemini
analysis, Smart Cut, karaoke subtitles) keeps working unchanged:

    {
        "text": str,
        "segments": [
            {
                "text": str,
                "start": float,
                "end": float,
                "words": [
                    {"word": str, "start": float, "end": float, "probability": float},
                    ...
                ],
            },
            ...
        ],
        "language": str,
    }

Design notes
------------
This module talks to Deepgram's REST API directly (``POST /v1/listen``) via
``requests`` so we don't have to add the ``deepgram-sdk`` dependency. The
implementation is intentionally defensive because transcription is the most
expensive step in the pipeline — a transient 429 should not abort a 45-minute
batch job.

Features
~~~~~~~~
- **Model-aware parameter stripping**: Nova-3 does *not* support
  ``filler_words`` (Nova-2 only). We silently drop any incompatible params
  when the configured model is on the Nova-3 line.
- **Multilingual code-switching**: Nova-3's ``language=multi`` handles
  English + Italian code-switching natively — the perfect default for
  ClippyMe's target audience (Italian creators who mix languages).
- **Keyterm prompting**: lets the caller boost recognition of specific terms
  (brand names, jargon) via ``DEEPGRAM_KEYTERMS`` env var. Nova-3 only.
- **Retry with exponential backoff**: 429 and 5xx responses are retried up to
  ``DEEPGRAM_MAX_RETRIES`` times, respecting ``Retry-After`` headers when
  present. Network errors (DNS, reset, timeout) also retry.
- **Session pooling**: a module-level ``requests.Session`` keeps the TLS
  connection warm across multiple clips in a batch job.
- **File-size guard**: raises early if the input exceeds
  ``DEEPGRAM_MAX_FILE_MB`` (default 1900, safely below Deepgram's 2 GB cap).
- **Utterances → segments**: we prefer Deepgram's utterance grouping (closer
  to Whisper's segment shape than raw word lists). If utterances are missing
  we fall back to chunking on sentence-ending punctuation or every ~12 s.
- **Progress logging**: prints file size, elapsed time, and the Deepgram
  ``request_id`` so a hanging upload is never a black box.

Env vars
~~~~~~~~
- ``DEEPGRAM_API_KEY`` (required)
- ``DEEPGRAM_MODEL`` (default ``nova-3``)
- ``DEEPGRAM_LANGUAGE`` (default ``multi``; use ``en``, ``it``, etc. for
  language-locked transcription — can help with single-language videos)
- ``DEEPGRAM_KEYTERMS`` (optional, comma-separated; Nova-3 only)
- ``DEEPGRAM_HTTP_TIMEOUT`` (default 600 s)
- ``DEEPGRAM_MAX_RETRIES`` (default 3)
- ``DEEPGRAM_MAX_FILE_MB`` (default 1900)
"""
from __future__ import annotations

import contextlib
import logging
import mimetypes
import os
import re
import time
from typing import Any

import requests

logger = logging.getLogger("clippyme")

DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"
DEFAULT_MODEL = "nova-3"
DEFAULT_LANGUAGE = "multi"
DEFAULT_TIMEOUT = 600
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_FILE_MB = 1900  # Deepgram hard limit is 2 GB
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# Module-level session → keeps TLS connections warm across a batch job.
_SESSION: requests.Session | None = None


class DeepgramError(RuntimeError):
    """Raised when Deepgram transcription fails unrecoverably."""


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


def _reset_session() -> None:
    """Drop the pooled session after a network error or 5xx.

    A ``requests.Session`` keeps a connection pool alive for TLS keep-alive
    across batch jobs, but a connection that errored (server 5xx, dropped
    socket) can linger in the pool and poison subsequent requests. Closing
    and clearing it forces a clean reconnect on the next call.
    """
    global _SESSION
    if _SESSION is not None:
        with contextlib.suppress(Exception):
            _SESSION.close()
        _SESSION = None


def _guess_content_type(path: str) -> str:
    ctype, _ = mimetypes.guess_type(path)
    if ctype:
        return ctype
    ext = os.path.splitext(path)[1].lower()
    return {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }.get(ext, "application/octet-stream")


def _is_nova3(model: str) -> bool:
    """Nova-3 and its variants don't support ``filler_words``."""
    return model.lower().startswith("nova-3")


def _build_params(model: str, language: str) -> list[tuple[str, str]]:
    """Query params for /v1/listen.

    Returned as a list of tuples so we can send repeated ``keyterm`` entries
    (``requests`` serializes list-valued query params correctly either way,
    but tuples make the multi-value intent explicit).
    """
    params: list[tuple[str, str]] = [
        ("model", model),
        ("smart_format", "true"),
        ("punctuate", "true"),
        ("paragraphs", "true"),
        ("utterances", "true"),
        ("numerals", "true"),        # "one hundred" → "100" — cleaner Gemini prompts
        ("measurements", "true"),    # "five meters" → "5 m"
        # Speaker diarization — free add-on on Nova-3, lets Gemini reason
        # about speaker alternation and clip boundaries, and lets the
        # subtitle writer color-code turns. Opt-out via DEEPGRAM_DIARIZE=false.
        ("diarize", os.getenv("DEEPGRAM_DIARIZE", "true").lower()),
        ("profanity_filter", "false"),
    ]
    if language:
        params.append(("language", language))

    # Nova-2 allows filler_words; Nova-3 rejects it as an unknown param.
    if not _is_nova3(model):
        params.append(("filler_words", "true"))

    # Keyterm prompting (Nova-3 only) — big accuracy win on brand/technical content
    if _is_nova3(model):
        keyterms_env = (os.getenv("DEEPGRAM_KEYTERMS") or "").strip()
        if keyterms_env:
            for term in keyterms_env.split(","):
                term = term.strip()
                if term:
                    params.append(("keyterm", term))

    return params


def _should_retry(status: int) -> bool:
    return status in RETRYABLE_STATUS


def _compute_backoff(attempt: int, retry_after: str | None) -> float:
    """Honour Retry-After when Deepgram sets it, otherwise exponential
    backoff with a small jitter-free ceiling.
    """
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    # attempt is 1-based at this point: 1 → 2s, 2 → 4s, 3 → 8s
    return min(30.0, 2.0 ** attempt)


def _flatten_words(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        alt = payload["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepgramError(f"Malformed Deepgram response: {exc}") from exc
    return alt.get("words") or []


def _detected_language(payload: dict[str, Any]) -> str:
    try:
        channel = payload["results"]["channels"][0]
    except (KeyError, IndexError, TypeError):
        return "unknown"
    lang = channel.get("detected_language")
    if lang:
        return str(lang)
    alt = (channel.get("alternatives") or [{}])[0]
    return str(alt.get("language") or "unknown")


def _word_to_pipeline(word: dict[str, Any]) -> dict[str, Any]:
    out = {
        "word": word.get("punctuated_word") or word.get("word") or "",
        "start": float(word.get("start", 0.0)),
        "end": float(word.get("end", 0.0)),
        "probability": float(word.get("confidence", 1.0)),
    }
    # Propagate diarization label when Deepgram emits one (0-indexed int).
    # Whisper fallback path never sets this, so downstream code treats
    # `speaker` as optional.
    if "speaker" in word:
        try:
            out["speaker"] = int(word["speaker"])
        except (TypeError, ValueError):
            pass
    return out


def _segments_from_utterances(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    utterances = (payload.get("results") or {}).get("utterances")
    if not utterances:
        return None
    segments: list[dict[str, Any]] = []
    for utt in utterances:
        words = utt.get("words") or []
        seg: dict[str, Any] = {
            "text": (utt.get("transcript") or "").strip(),
            "start": float(utt.get("start", 0.0)),
            "end": float(utt.get("end", 0.0)),
            "words": [_word_to_pipeline(w) for w in words],
        }
        # Deepgram attaches `speaker` on the utterance when diarize=true.
        # Fall back to the majority speaker of the words if not present.
        if "speaker" in utt:
            try:
                seg["speaker"] = int(utt["speaker"])
            except (TypeError, ValueError):
                pass
        elif any("speaker" in w for w in words):
            counts: dict[int, int] = {}
            for w in words:
                sp = w.get("speaker")
                if sp is None:
                    continue
                try:
                    counts[int(sp)] = counts.get(int(sp), 0) + 1
                except (TypeError, ValueError):
                    continue
            if counts:
                seg["speaker"] = max(counts, key=counts.get)
        segments.append(seg)
    return segments


def _segments_from_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback: chunk a flat word list into Whisper-sized segments."""
    segments: list[dict[str, Any]] = []
    if not words:
        return segments

    SENTENCE_END = (".", "!", "?")
    MAX_DURATION = 12.0

    current: list[dict[str, Any]] = []
    current_start = float(words[0].get("start", 0.0))

    def _flush(end_time: float) -> None:
        if not current:
            return
        segments.append(
            {
                "text": " ".join(
                    (cw.get("punctuated_word") or cw.get("word") or "")
                    for cw in current
                ).strip(),
                "start": current_start,
                "end": end_time,
                "words": [_word_to_pipeline(cw) for cw in current],
            }
        )

    for idx, w in enumerate(words):
        current.append(w)
        token = w.get("punctuated_word") or w.get("word") or ""
        end = float(w.get("end", 0.0))
        if token.endswith(SENTENCE_END) or (end - current_start) >= MAX_DURATION:
            _flush(end)
            current = []
            if idx + 1 < len(words):
                current_start = float(words[idx + 1].get("start", end))

    if current:
        _flush(float(current[-1].get("end", current_start)))

    return segments


def _check_file(video_path: str) -> int:
    if not os.path.exists(video_path):
        raise DeepgramError(f"File not found: {video_path}")
    size = os.path.getsize(video_path)
    if size == 0:
        raise DeepgramError(f"File is empty: {video_path}")
    max_mb = float(os.getenv("DEEPGRAM_MAX_FILE_MB", str(DEFAULT_MAX_FILE_MB)))
    max_bytes = int(max_mb * 1024 * 1024)
    if size > max_bytes:
        raise DeepgramError(
            f"File too large for Deepgram: {size / 1024 / 1024:.0f} MB "
            f"exceeds the configured cap of {max_mb:.0f} MB"
        )
    return size


def _post_with_retries(
    headers: dict[str, str],
    params: list[tuple[str, str]],
    video_path: str,
    timeout: float,
    max_retries: int,
) -> requests.Response:
    session = _get_session()
    last_exc: Exception | None = None
    attempt = 0

    while attempt <= max_retries:
        try:
            # Re-open the file every retry — the previous body has been
            # consumed and isn't rewindable with server-side upload.
            with open(video_path, "rb") as f:
                response = session.post(
                    DEEPGRAM_API_URL,
                    params=params,
                    headers=headers,
                    data=f,
                    timeout=timeout,
                )
        except requests.RequestException as exc:
            last_exc = exc
            # The pooled connection errored — drop it so the retry reconnects.
            _reset_session()
            session = _get_session()
            if attempt >= max_retries:
                raise DeepgramError(
                    f"Network error talking to Deepgram after {attempt + 1} attempts: {exc}"
                ) from exc
            wait = _compute_backoff(attempt + 1, None)
            print(f"   ⚠️  Deepgram network error ({exc}); retrying in {wait:.1f}s…")
            time.sleep(wait)
            attempt += 1
            continue

        if response.status_code == 200:
            return response

        if _should_retry(response.status_code) and attempt < max_retries:
            # 5xx (and 429/408/409/425): the upstream is unhealthy; recycle the
            # connection pool before retrying so we don't reuse a poisoned socket.
            if response.status_code >= 500:
                _reset_session()
                session = _get_session()
            retry_after = response.headers.get("Retry-After")
            wait = _compute_backoff(attempt + 1, retry_after)
            print(
                f"   ⚠️  Deepgram HTTP {response.status_code}; retrying in {wait:.1f}s "
                f"(attempt {attempt + 1}/{max_retries})…"
            )
            time.sleep(wait)
            attempt += 1
            continue

        # Non-retryable status → raise with body snippet. Strip control/ANSI
        # bytes first so a crafted error body can't inject escape sequences or
        # forged log lines when the message is printed to stdout/logs.
        snippet = re.sub(r"[\x00-\x1f\x7f]", " ", (response.text or "")[:400])
        raise DeepgramError(
            f"Deepgram returned HTTP {response.status_code}: {snippet}"
        )

    # Loop exited without returning → exhausted retries
    if last_exc:
        raise DeepgramError(f"Deepgram transcription failed: {last_exc}") from last_exc
    raise DeepgramError("Deepgram transcription failed: retries exhausted")


def transcribe_with_deepgram(video_path: str) -> dict[str, Any]:
    """Transcribe a local audio/video file via Deepgram's pre-recorded API.

    Returns a dict matching ``main.transcribe_video``'s shape. Raises
    :class:`DeepgramError` on unrecoverable failure so the caller can decide
    whether to fall back to Faster-Whisper.
    """
    api_key = (os.getenv("DEEPGRAM_API_KEY") or "").strip()
    if not api_key:
        raise DeepgramError("DEEPGRAM_API_KEY is not configured")

    size_bytes = _check_file(video_path)

    model = os.getenv("DEEPGRAM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    language = os.getenv("DEEPGRAM_LANGUAGE", DEFAULT_LANGUAGE).strip()
    timeout = float(os.getenv("DEEPGRAM_HTTP_TIMEOUT", str(DEFAULT_TIMEOUT)))
    max_retries = int(os.getenv("DEEPGRAM_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))

    params = _build_params(model, language)
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": _guess_content_type(video_path),
        "User-Agent": "ClippyMe/1.0 (+https://github.com/fralapo/clippyme)",
    }

    size_mb = size_bytes / 1024 / 1024
    print(
        f"🎙️  Transcribing with Deepgram [{model}, lang={language or 'auto'}] "
        f"— uploading {size_mb:.1f} MB…"
    )
    logger.info(
        "Deepgram transcription start: file=%s size_mb=%.1f model=%s lang=%s",
        os.path.basename(video_path), size_mb, model, language,
    )

    t0 = time.monotonic()
    response = _post_with_retries(headers, params, video_path, timeout, max_retries)
    elapsed = time.monotonic() - t0

    try:
        payload = response.json()
    except ValueError as exc:
        raise DeepgramError(f"Deepgram returned non-JSON body: {exc}") from exc

    request_id = (payload.get("metadata") or {}).get("request_id", "?")
    duration = (payload.get("metadata") or {}).get("duration", 0)

    # Prefer utterances (better segment boundaries) → fall back to word chunking
    segments = _segments_from_utterances(payload)
    if not segments:
        segments = _segments_from_words(_flatten_words(payload))

    # Full transcript text
    try:
        full_text = (
            payload["results"]["channels"][0]["alternatives"][0].get("transcript", "")
        ).strip()
    except (KeyError, IndexError, TypeError):
        full_text = " ".join(seg["text"] for seg in segments).strip()

    language_detected = _detected_language(payload)

    speedup = (float(duration) / elapsed) if elapsed > 0 and duration else 0.0
    speed_note = f" ({speedup:.1f}× realtime)" if speedup else ""

    # Count distinct speakers across all segments for observability + to
    # let the caller short-circuit the speaker-aware Gemini hints when
    # only one voice is present.
    speakers_seen: set[int] = set()
    for seg in segments:
        if "speaker" in seg:
            speakers_seen.add(seg["speaker"])
        for w in seg.get("words") or []:
            if "speaker" in w:
                speakers_seen.add(w["speaker"])
    speaker_note = (
        f", speakers={len(speakers_seen)}" if speakers_seen else ""
    )

    print(
        f"   ✅ Deepgram OK — {len(segments)} segments, "
        f"audio={duration:.1f}s, wall={elapsed:.1f}s{speed_note}, "
        f"lang='{language_detected}'{speaker_note}, request_id={request_id}"
    )
    logger.info(
        "Deepgram transcription done: request_id=%s audio_s=%.1f wall_s=%.1f segments=%d",
        request_id, float(duration or 0), elapsed, len(segments),
    )

    return {
        "text": full_text,
        "segments": segments,
        "language": language_detected,
    }
