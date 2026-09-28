"""Diarization helpers: audio extraction + speaker-turn → word merging.

Extracted from ``pipeline.main``. These two helpers are dependency-light
(``assign_speakers_to_words`` is pure; ``extract_audio_to_wav`` shells out to
ffmpeg), so they import and unit-test on the host. The pyannote model call
itself (``_diarize_with_pyannote``) stays in ``main`` because it pulls the
optional pyannote.audio + torch stack.
"""
import os
import subprocess
import time


def assign_speakers_to_words(
    words: list[dict],
    turns: list[tuple[float, float, int]],
) -> None:
    """Merge diarization turns into Whisper words by maximum overlap.

    Mutates ``words`` in place, adding a ``speaker`` key where a matching
    turn exists. Words that fall outside every turn (silence, non-speech)
    are left untouched. Runs in O(n+m) thanks to the ordered walk.
    """
    if not words or not turns:
        return
    # Sort words by start (Whisper generally emits them ordered, but the
    # cost is marginal and guarantees the two-pointer walk is correct).
    words.sort(key=lambda w: float(w.get("start", 0.0)))

    ti = 0
    for w in words:
        try:
            ws = float(w.get("start", 0.0))
            we = float(w.get("end", ws))
        except (TypeError, ValueError):
            continue

        # Advance ti until the current turn could still overlap this word.
        while ti < len(turns) and turns[ti][1] < ws:
            ti += 1
        if ti >= len(turns):
            break

        # Find the turn with the maximum overlap against [ws, we]. Because
        # turns are sorted and mostly non-overlapping (diarization emits
        # contiguous turns), at most 2-3 candidates need to be checked.
        best_speaker: int | None = None
        best_overlap = 0.0
        j = ti
        while j < len(turns) and turns[j][0] <= we:
            ts, te, sp = turns[j]
            overlap = max(0.0, min(te, we) - max(ts, ws))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = sp
            j += 1

        if best_speaker is not None:
            w["speaker"] = best_speaker


def extract_audio_to_wav(video_path: str) -> str | None:
    """ffmpeg-extract a mono 16 kHz WAV next to the source video.

    pyannote.audio needs a plain WAV (won't accept .mp4 directly), so we
    produce a temp file and return its path. Returns ``None`` if ffmpeg
    is missing or the extraction fails — caller should skip diarization.
    """
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(video_path)) or ".",
        f".diarize_{int(time.time())}_{os.getpid()}.wav",
    )
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", video_path,
                "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le",
                out_path,
            ],
            check=True,
            timeout=1800,
        )
        return out_path
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"   ⚠️  Could not extract audio for diarization: {exc}")
        return None


def extract_audio_for_asr(video_path: str) -> str | None:
    """ffmpeg-extract a compact mono 16 kHz FLAC track for transcription.

    Both transcription backends (Deepgram REST upload, Faster-Whisper local
    decode) only need the audio. Stripping the video first turns a 50-200 MB+
    mp4 into a few-MB FLAC, which:

    - slashes Deepgram upload time (the dominant wall-clock cost) and the odds
      of a mid-upload network error on long batch jobs;
    - keeps even hour-long videos far below Deepgram's file-size cap;
    - skips redundant video-frame demuxing inside Faster-Whisper.

    FLAC is lossless at 16 kHz mono — exactly the resolution ASR models consume
    internally — so there is zero accuracy cost vs sending the original.

    Returns ``None`` if ffmpeg is missing or extraction fails; the caller then
    falls back to handing the original video to the transcriber.
    """
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(video_path)) or ".",
        f".asr_{int(time.time())}_{os.getpid()}.flac",
    )
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", video_path,
                "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "flac",
                out_path,
            ],
            check=True,
            timeout=1800,
        )
        return out_path
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"   ⚠️  Could not extract audio for transcription ({exc}); using source file.")
        return None
