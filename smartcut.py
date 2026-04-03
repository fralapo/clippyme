"""
Smart Cut — Remove dead silences and filler words from video clips.

Post-processing step: user triggers it after a clip is generated.
Analyzes word timestamps, identifies gaps > threshold and filler words,
produces a tighter version of the clip.
"""

import os
import subprocess
import json
import tempfile


# Filler words by language (lowercase, stripped)
FILLER_WORDS = {
    "it": {"ehm", "uhm", "eh", "ah", "mhm", "cioe", "cioè", "tipo", "praticamente",
           "diciamo", "insomma", "ecco", "allora", "niente", "vabbè", "vabbe"},
    "en": {"um", "uh", "uh huh", "like", "you know", "basically", "actually",
           "so yeah", "i mean", "right", "well", "anyway"},
    "es": {"ehm", "pues", "bueno", "o sea", "tipo", "digamos", "este"},
    "fr": {"euh", "ben", "genre", "en fait", "du coup", "voilà", "bah"},
    "de": {"ähm", "also", "halt", "sozusagen", "quasi", "na ja"},
}

# Default to English if language not in the map
DEFAULT_LANG = "en"

# Silence threshold in seconds — gaps longer than this between words are considered "dead silence"
SILENCE_THRESHOLD = 0.8

# Minimum remaining silence after trimming (don't remove ALL silence, keep a tiny breath)
SILENCE_KEEP = 0.3


def analyze_silences(transcript, clip_start, clip_end, language=None):
    """
    Analyze word timestamps to find removable silences and filler words.

    Returns:
        segments_to_keep: list of (start, end) tuples relative to clip_start
        stats: dict with removal info
    """
    lang = (language or DEFAULT_LANG).lower()[:2]
    fillers = FILLER_WORDS.get(lang, FILLER_WORDS[DEFAULT_LANG])

    # Extract words in clip range
    words = []
    for segment in transcript.get('segments', []):
        for word_info in segment.get('words', []):
            if word_info['end'] > clip_start and word_info['start'] < clip_end:
                words.append({
                    'word': word_info['word'].strip(),
                    'start': max(0, word_info['start'] - clip_start),
                    'end': max(0, word_info['end'] - clip_start),
                })

    if not words:
        return [], {"error": "No words found in clip range"}

    clip_duration = clip_end - clip_start
    segments_to_keep = []
    removed_silences = 0
    removed_fillers = 0
    silence_time_saved = 0.0

    # First word — keep from the very start
    current_start = 0.0

    for i, word in enumerate(words):
        is_filler = word['word'].lower().strip('.,!?') in fillers

        if is_filler:
            # End the current segment before this filler (if we have content)
            if current_start < word['start']:
                segments_to_keep.append((current_start, word['start']))
            current_start = word['end']
            removed_fillers += 1
            continue

        # Check gap before this word
        if i > 0:
            prev_end = words[i - 1]['end']
            gap = word['start'] - prev_end

            if gap > SILENCE_THRESHOLD:
                # Close segment before the silence
                segments_to_keep.append((current_start, prev_end + SILENCE_KEEP))
                # Start new segment just before this word
                current_start = word['start'] - 0.05  # tiny lead-in
                removed_silences += 1
                silence_time_saved += gap - SILENCE_KEEP

    # Close final segment
    if words:
        segments_to_keep.append((current_start, min(clip_duration, words[-1]['end'] + 0.2)))

    # Merge very close segments (< 0.1s gap)
    merged = []
    for seg in segments_to_keep:
        if merged and seg[0] - merged[-1][1] < 0.1:
            merged[-1] = (merged[-1][0], seg[1])
        else:
            merged.append(seg)

    original_duration = clip_duration
    new_duration = sum(end - start for start, end in merged)

    stats = {
        "original_duration": round(original_duration, 1),
        "new_duration": round(new_duration, 1),
        "time_saved": round(original_duration - new_duration, 1),
        "silences_removed": removed_silences,
        "fillers_removed": removed_fillers,
        "segments": len(merged),
    }

    return merged, stats


def smart_cut(clip_path, transcript, clip_start, clip_end, language=None):
    """
    Generate a smart-cut version of a clip by removing silences and filler words.

    Args:
        clip_path: path to the original clip
        transcript: full transcript dict with word-level timestamps
        clip_start/clip_end: original timestamps of this clip in the source video
        language: ISO language code (e.g., 'it', 'en')

    Returns:
        output_path: path to the smart-cut version, or None on failure
        stats: dict with removal statistics
    """
    segments, stats = analyze_silences(transcript, clip_start, clip_end, language)

    if not segments or len(segments) < 2:
        # Nothing meaningful to cut, or only one segment
        stats["skipped"] = True
        return None, stats

    if stats["time_saved"] < 1.0:
        # Less than 1 second saved, not worth it
        stats["skipped"] = True
        return None, stats

    output_path = os.path.splitext(clip_path)[0] + "_smartcut.mp4"

    try:
        # Use FFmpeg concat demuxer approach:
        # 1. Create a temporary file listing all segments
        # 2. Extract each segment as a temp file
        # 3. Concatenate them

        temp_dir = tempfile.mkdtemp(prefix="smartcut_")
        segment_files = []

        for i, (start, end) in enumerate(segments):
            seg_path = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(start), '-to', str(end),
                '-i', clip_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                '-c:a', 'aac',
                '-avoid_negative_ts', 'make_zero',
                seg_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if result.returncode == 0 and os.path.exists(seg_path):
                segment_files.append(seg_path)

        if len(segment_files) < 2:
            # Cleanup
            for f in segment_files:
                os.remove(f)
            os.rmdir(temp_dir)
            stats["skipped"] = True
            return None, stats

        # Create concat list file
        concat_list = os.path.join(temp_dir, "concat.txt")
        with open(concat_list, 'w') as f:
            for seg_path in segment_files:
                # Use forward slashes for FFmpeg compatibility
                safe_path = seg_path.replace('\\', '/')
                f.write(f"file '{safe_path}'\n")

        # Concatenate
        concat_cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', concat_list,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac',
            '-pix_fmt', 'yuv420p',
            output_path
        ]
        result = subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        # Cleanup temp files
        for f in segment_files:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(concat_list):
            os.remove(concat_list)
        try:
            os.rmdir(temp_dir)
        except OSError:
            pass

        if result.returncode == 0 and os.path.exists(output_path):
            print(f"✂️  Smart Cut: {stats['original_duration']}s → {stats['new_duration']}s "
                  f"(-{stats['time_saved']}s, {stats['silences_removed']} silences, "
                  f"{stats['fillers_removed']} fillers removed)")
            return output_path, stats
        else:
            stats["error"] = "FFmpeg concat failed"
            return None, stats

    except Exception as e:
        stats["error"] = str(e)
        print(f"❌ Smart Cut error: {e}")
        return None, stats
