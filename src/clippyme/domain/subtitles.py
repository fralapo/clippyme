import os
import re
import subprocess

from clippyme.domain.encode import x264_video_args


def _strip_ass_braces(text: str) -> str:
    """Remove ASS/libass override-block braces from transcript text.

    A word token like ``{\\pos(0,0)}`` or ``{\\an8}`` (ASR can echo adversarial
    on-screen/audio text) would otherwise be interpreted as a libass directive
    when the SRT/ASS file is later rendered via the ``subtitles=``/``ass=``
    filter. Applies to BOTH the karaoke ASS and the classic SRT paths.
    """
    return (text or "").replace('{', '').replace('}', '')


_cuda_works = None  # cached after first check

def _check_cuda():
    global _cuda_works
    if _cuda_works is not None:
        return _cuda_works
    import torch
    if not torch.cuda.is_available():
        _cuda_works = False
        return False
    try:
        import numpy as _np
        from faster_whisper import WhisperModel
        _m = WhisperModel("tiny", device="cuda", compute_type="float16")
        _m.transcribe(_np.zeros(16000, dtype=_np.float32))
        del _m
        _cuda_works = True
    except Exception:
        _cuda_works = False
    return _cuda_works

def _select_whisper_model():
    """Auto-select Whisper model based on hardware."""
    import os
    override = os.getenv("WHISPER_MODEL")
    if override:
        return override
    if _check_cuda():
        import torch
        vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        if vram >= 6: return "large-v3"
        if vram >= 3: return "medium"
        return "small"
    else:
        import psutil
        ram = psutil.virtual_memory().total / (1024**3)
        if ram >= 16: return "medium"
        if ram >= 8: return "small"
        return "base"

def transcribe_audio(video_path):
    """
    Transcribe audio from a video file using faster-whisper.
    Returns transcript in the same format as main.py for compatibility.
    """
    from faster_whisper import WhisperModel

    device = "cuda" if _check_cuda() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    whisper_model = _select_whisper_model()
    print(f"🎙️  Transcribing audio [{whisper_model}] from: {video_path} ({device.upper()} mode)")
    model = WhisperModel(whisper_model, device=device, compute_type=compute_type)
    segments, info = model.transcribe(video_path, word_timestamps=True)
    segments = list(segments)

    transcript = {
        "segments": [],
        "language": info.language
    }

    for segment in segments:
        seg_data = {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "words": []
        }
        if segment.words:
            for word in segment.words:
                seg_data["words"].append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end
                })
        transcript["segments"].append(seg_data)

    print(f"✅ Transcription complete. Language: {info.language}")
    return transcript


def generate_srt_from_video(video_path, output_path, max_chars=20, max_duration=2.0):
    """
    Transcribe a video and generate SRT directly.
    Used for dubbed videos that don't have a pre-existing transcript.
    """
    transcript = transcribe_audio(video_path)

    # Get video duration to use as clip_end
    import cv2
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps else 0
    cap.release()

    return generate_srt(transcript, 0, duration, output_path, max_chars, max_duration)


def generate_srt(transcript, clip_start, clip_end, output_path, max_chars=20, max_duration=2.0):
    """
    Generates an SRT file from the transcript for a specific time range.
    Groups words into short lines suitable for vertical video.
    """
    
    words = []
    # 1. Extract and flatten words within range
    for segment in transcript.get('segments', []):
        for word_info in segment.get('words', []):
            # Check overlap
            if word_info['end'] > clip_start and word_info['start'] < clip_end:
                words.append(word_info)
    
    if not words:
        return False

    srt_content = ""
    index = 1
    
    current_block = []
    block_start = None
    
    for i, word in enumerate(words):
        # Adjust times relative to clip
        start = max(0, word['start'] - clip_start)
        end = max(0, word['end'] - clip_start)
        
        # Clip to video duration logic handled by ffmpeg usually, but good to be safe
        
        if not current_block:
            current_block.append(word)
            block_start = start
        else:
            # Decide whether to close block
            current_text_len = sum(len(w['word']) + 1 for w in current_block)
            duration = end - block_start
            # Close early on a sentence-final mark so two sentences never share
            # one caption line (same semantic-boundary rule as the ASS path).
            sentence_break = _ends_sentence(_word_text(current_block[-1]))

            if (sentence_break
                    or current_text_len + len(word['word']) > max_chars
                    or duration > max_duration):
                # Finalize current block
                # End time of block is start of this word (gap) or end of last word?
                # Usually end of last word.
                block_end = current_block[-1]['end'] - clip_start
                
                text = " ".join([_strip_ass_braces(w['word']) for w in current_block]).strip()
                srt_content += format_srt_block(index, block_start, block_end, text)
                index += 1
                
                current_block = [word]
                block_start = start
            else:
                current_block.append(word)
    
    # Final block
    if current_block:
        block_end = current_block[-1]['end'] - clip_start
        text = " ".join([_strip_ass_braces(w['word']) for w in current_block]).strip()
        srt_content += format_srt_block(index, block_start, block_end, text)
        
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(srt_content)
        
    return True

def format_srt_block(index, start, end, text):
    def format_time(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        
    return f"{index}\n{format_time(start)} --> {format_time(end)}\n{text}\n\n"

def hex_to_ass_color(hex_color, opacity=1.0):
    """Convert #RRGGBB to ASS &HAABBGGRR format. opacity: 0.0=transparent, 1.0=opaque"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        hex_color = "FFFFFF"
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    alpha = round((1.0 - opacity) * 255)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


# --- Viral Subtitle Presets ---
SUBTITLE_PRESETS = {
    "classic_white": {
        "font": "Montserrat-Black",
        "text_color": "#FFFFFF",
        "highlight_color": "#FFFF00",
        "outline_color": "#000000",
        "outline_width": 4,
        "border_style": 1,
        "shadow": 0,
        "margin_v": 350,
        "uppercase": True,
        "fontsize": 40,
    },
    "hormozi_bold": {
        "font": "Bangers-Regular",
        "text_color": "#FFFFFF",
        "highlight_color": "#00FF00",
        "outline_color": "#000000",
        "outline_width": 5,
        "border_style": 1,
        "shadow": 2,
        "margin_v": 350,
        "uppercase": True,
        "fontsize": 43,
    },
    "neon_glow": {
        "font": "Montserrat-Black",
        "text_color": "#FFFFFF",
        "highlight_color": "#00FFFF",
        "outline_color": "#00AAAA",
        "outline_width": 3,
        "border_style": 1,
        "shadow": 3,
        "margin_v": 350,
        "uppercase": True,
        "fontsize": 40,
    },
    "mrbeast_box": {
        "font": "Poppins-Black",
        "text_color": "#FFFFFF",
        "highlight_color": "#FFFF00",
        "outline_color": "#000000",
        "outline_width": 1,
        "border_style": 3,
        "shadow": 0,
        "margin_v": 350,
        "uppercase": False,
        "fontsize": 38,
    },
    "minimal_clean": {
        "font": "Poppins-Medium",
        "text_color": "#FFFFFF",
        "highlight_color": "#FFFFFF",
        "outline_color": "#000000",
        "outline_width": 2,
        "border_style": 1,
        "shadow": 0,
        "margin_v": 350,
        "uppercase": False,
        "fontsize": 35,
    },
    "fire_impact": {
        "font": "Anton-Regular",
        "text_color": "#FFFFFF",
        "highlight_color": "#FF4444",
        "outline_color": "#000000",
        "outline_width": 5,
        "border_style": 1,
        "shadow": 0,
        "margin_v": 350,
        "uppercase": True,
        "fontsize": 43,
    },
}

# Bundled TTF fonts live at repo-root `fonts/` and are also mounted by
# the FastAPI static handler at /fonts. We resolve the repo root by
# walking 3 levels up from this file (src/clippyme/domain/subtitles.py
# → src/clippyme/domain → src/clippyme → src → repo-root). CWD-based
# resolution was fragile: any caller running from a different directory
# (tests, reframe subprocess, ad-hoc scripts) got a bogus path and
# libass silently fell back to Fontconfig. Override via env var for
# alternate layouts (installed package on a different prefix, etc.).
_REPO_ROOT_FROM_HERE = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
_DEFAULT_FONTS_DIR = os.path.join(_REPO_ROOT_FROM_HERE, "fonts")
# Fallback #2: if the walked-up path doesn't actually contain fonts
# (e.g. editable install in an unusual layout), try a CWD-relative
# `fonts/` before giving up. libass tolerates a missing fontsdir by
# using system fonts, so we never want to crash here.
if not os.path.isdir(_DEFAULT_FONTS_DIR):
    _cwd_fallback = os.path.abspath("fonts")
    if os.path.isdir(_cwd_fallback):
        _DEFAULT_FONTS_DIR = _cwd_fallback
FONTS_DIR = os.environ.get("CLIPPYME_FONTS_DIR") or _DEFAULT_FONTS_DIR

# Writable directory for user-uploaded fonts (e.g. a licensed Stratos TTF the
# client needs). The bundled `fonts/` dir is part of the image/repo and is not
# reliably writable by the non-root container user, so uploads land in the
# `data/` volume instead. `effective_fonts_dir()` then merges both into a single
# directory because libass's `ass`/`subtitles` filter only accepts one fontsdir.
USER_FONTS_DIR = os.environ.get("CLIPPYME_USER_FONTS_DIR") or os.path.join("data", "fonts")
_FONT_EXTS = (".ttf", ".otf", ".ttc")


def list_available_fonts():
    """Basenames (no extension) of every font face available for burn-in —
    bundled + user-uploaded. Used by the GET /api/config/fonts endpoint to
    populate the classic-subtitle font dropdown."""
    names = set()
    for d in (FONTS_DIR, USER_FONTS_DIR):
        if d and os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.lower().endswith(_FONT_EXTS):
                    names.add(os.path.splitext(fn)[0])
    return sorted(names)


def effective_fonts_dir():
    """Single directory libass should scan. Seeds the writable user-fonts dir
    with copies of the bundled faces so uploaded + bundled fonts coexist behind
    one `fontsdir` path. Falls back to the bundled dir if the user dir can't be
    created/written (read-only host)."""
    import shutil
    try:
        os.makedirs(USER_FONTS_DIR, exist_ok=True)
        if os.path.isdir(FONTS_DIR) and os.path.abspath(FONTS_DIR) != os.path.abspath(USER_FONTS_DIR):
            for fn in os.listdir(FONTS_DIR):
                if not fn.lower().endswith(_FONT_EXTS):
                    continue
                dst = os.path.join(USER_FONTS_DIR, fn)
                if not os.path.exists(dst):
                    shutil.copy2(os.path.join(FONTS_DIR, fn), dst)
        return USER_FONTS_DIR
    except OSError:
        return FONTS_DIR


# --- Shared subtitle-style helpers (pure, host-tested) --------------------
# Fontsize bounds shared by both subtitle paths. The karaoke ASS resolution is
# 1080x1920 (preset sizes ~35-43); the SRT path scales by 0.85 afterwards. The
# cap stops an out-of-range API value (validated up to 100000 by the generic
# overlay validator) from reaching ffmpeg.
_SUB_FONTSIZE_MIN = 10
_SUB_FONTSIZE_MAX = 120


def _clamp_fontsize(size, default):
    """Coerce a requested fontsize into [_SUB_FONTSIZE_MIN, _SUB_FONTSIZE_MAX].

    Garbage (None / non-numeric) falls back to ``default`` so a missing override
    keeps the preset size.
    """
    try:
        s = int(size)
    except (TypeError, ValueError):
        return default
    return max(_SUB_FONTSIZE_MIN, min(_SUB_FONTSIZE_MAX, s))


def _offset_margin(position_norm, base_margin_v, offset_y):
    """Apply a vertical offset (percent of the 1920px frame) to a base MarginV.

    Convention shared by the karaoke ASS path and the classic SRT path: a
    POSITIVE ``offset_y`` moves the caption DOWN on screen, negative moves it UP
    — matching the frontend slider where +50 ≈ bottom and -50 ≈ top.

    MarginV semantics depend on the anchor: for a TOP-anchored caption MarginV
    is the gap from the top edge (larger = lower) so we ADD; for bottom/center it
    is the gap from the bottom edge (larger = higher) so we SUBTRACT. The result
    is clamped at 0 so an aggressive offset never produces a negative margin.
    """
    try:
        delta = int(1920 * float(offset_y) / 100)
    except (TypeError, ValueError):
        delta = 0
    if position_norm == "top":
        return base_margin_v + delta
    return max(0, base_margin_v - delta)


def generate_ass_karaoke(transcript, clip_start, clip_end, output_path,
                         preset="classic_white", mode="word_group",
                         words_per_group=3, uppercase=True,
                         font_name=None, font_color=None, highlight_color=None,
                         font_size=None, outline_width=None, position="bottom",
                         offset_y=0):
    """
    Generate an ASS subtitle file with karaoke word-by-word highlighting.
    Uses \\k tags so the current word snaps from secondary (base) to primary (highlight) color.

    Args:
        transcript: dict with 'segments' containing word-level timestamps
        clip_start/clip_end: time range in seconds
        output_path: where to save the .ass file
        preset: one of SUBTITLE_PRESETS keys, or None for custom
        mode: 'word_group' (2-3 words at a time) or 'full_line' (full phrase with karaoke)
        words_per_group: how many words per subtitle event (word_group mode)
        uppercase: convert text to uppercase
        font_name/font_color/highlight_color/font_size/outline_width: overrides for preset
        position: 'top', 'center', 'bottom'
    """
    # Resolve preset
    style = SUBTITLE_PRESETS.get(preset, SUBTITLE_PRESETS["classic_white"]).copy()

    # Apply overrides
    if font_name:
        # Same guard as burn_subtitles: a font name is interpolated verbatim
        # into the ASS [V4+ Styles] block, so reject anything outside the safe
        # alphabet to prevent ASS-directive injection into the style line.
        if not _FONT_NAME_RE.match(font_name):
            raise ValueError(f"invalid font_name: {font_name!r}")
        style["font"] = font_name
    # Validate caller-supplied colours the same way burn_subtitles does — they
    # are interpolated into the .ass file and must not silently coerce to white
    # (hex_to_ass_color's fallback) on a malformed value.
    for _label, _val in (("font_color", font_color), ("highlight_color", highlight_color)):
        if _val and not _HEX_RE.match(str(_val)):
            raise ValueError(f"invalid {_label}: {_val!r}")
    if font_color:
        style["text_color"] = font_color
    if highlight_color:
        style["highlight_color"] = highlight_color
    if font_size:
        style["fontsize"] = _clamp_fontsize(font_size, style["fontsize"])
    if outline_width is not None:
        style["outline_width"] = max(0, min(20, int(outline_width)))
    if uppercase is not None:
        style["uppercase"] = uppercase

    # Position → ASS alignment + margin. Positive offset_y moves the caption
    # DOWN (see _offset_margin).
    position_norm = str(position).lower()
    if position_norm == "middle":
        position_norm = "center"  # frontend alias
    if position_norm == "top":
        ass_alignment = 8  # top-center
        margin_v = _offset_margin("top", 260, offset_y)
    elif position_norm == "center":
        if offset_y:
            # libass IGNORES MarginV for the centred anchor (\an5), so a non-zero
            # nudge would silently no-op. Re-anchor to the top anchor (\an8) with
            # an absolute margin measured from the vertical centre (960px of the
            # 1920px frame) so the slider actually moves the caption.
            ass_alignment = 8
            margin_v = _offset_margin("top", 960, offset_y)
        else:
            ass_alignment = 5  # center-center
            margin_v = 0
    else:
        ass_alignment = 2  # bottom-center
        margin_v = _offset_margin("bottom", style.get("margin_v", 350), offset_y)

    # Extract words in range
    words = []
    for segment in transcript.get('segments', []):
        for word_info in segment.get('words', []):
            if word_info['end'] > clip_start and word_info['start'] < clip_end:
                words.append(word_info)

    if not words:
        return False

    # Colors: primary = highlight (what word becomes), secondary = base (what word starts as)
    primary_colour = hex_to_ass_color(style["highlight_color"], 1.0)
    secondary_colour = hex_to_ass_color(style["text_color"], 1.0)
    outline_colour = hex_to_ass_color(style.get("outline_color", "#000000"), 1.0)
    back_colour = hex_to_ass_color("#000000", 0.0)

    # ASS header
    ass_content = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Viral,{style['font']},{style['fontsize']},"
        f"{primary_colour},{secondary_colour},{outline_colour},{back_colour},"
        f"-1,0,0,0,100,100,0,0,{style['border_style']},{style['outline_width']},{style.get('shadow', 0)},"
        f"{ass_alignment},110,110,{margin_v},1\n\n"  # MarginL/R 110px ≈ 10% safe zone (TikTok/Reels)
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def format_ass_time(seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds - int(seconds)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    if mode == "full_line":
        # Full line mode: group words into sentences (~20 chars), show whole line with karaoke
        groups = _group_words(words, clip_start, max_chars=60, max_duration=5.0)
    else:
        # Word group mode: small groups of N words
        groups = _group_words_by_count(words, clip_start, words_per_group)

    for group in groups:
        event_start = max(0, group[0]['start'] - clip_start)
        event_end = max(0, group[-1]['end'] - clip_start)

        karaoke_parts = []
        for w in group:
            duration_cs = max(1, int((w['end'] - w['start']) * 100))
            text = _strip_ass_braces(w['word'].strip())
            if style["uppercase"]:
                text = text.upper()
            karaoke_parts.append(f"{{\\k{duration_cs}}}{text}")

        line_text = " ".join(karaoke_parts)
        # Fix: \k tags shouldn't have space before them inside the line
        # Actually the space goes between words, which is correct

        ass_content += (
            f"Dialogue: 0,{format_ass_time(event_start)},{format_ass_time(event_end)},"
            f"Viral,,0,0,0,,{line_text}\n"
        )

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(ass_content)

    return True


# --- Semantic subtitle line-splitting -------------------------------------
# Ported (idea, not code) from VideoLingo's `spacy_utils/` (split_by_mark /
# split_by_comma / split_by_connector). VideoLingo runs a heavy spaCy POS pass
# to break captions at clause boundaries (the "Netflix single-line" standard)
# so a line never cuts mid-phrase. We don't need spaCy: Deepgram `smart_format`
# (and Whisper) already attach punctuation to the word tokens, so we can find
# the same boundaries with a pure lexical pass — zero new deps, host-testable.
# See docs/videolingo-analysis.md.

# Sentence-final marks → ALWAYS end the current caption (never merge two
# sentences onto one karaoke line). Includes CJK forms for safety.
_SENTENCE_END = ".?!…。？！"
# Soft clause marks → a *preferred* break point once the line is substantial.
_SOFT_PUNCT = ",;:，；：、"
# Trailing characters to peel off a token before inspecting its last glyph
# (closing quotes/brackets sit AFTER the punctuation: `world."` / `(sì)`).
_TRAIL_STRIP = "\"')]}»”’）」』"

# Connectors to break *before* (VideoLingo splits ahead of the connector so the
# new line opens on it: "… / and then …"). Languages mirror ClippyMe's filler
# coverage (EN/IT/ES/FR/DE). Single-letter conjunctions (it `e`/`o`, es `y`)
# are intentionally included but only ever fire once a line is already long
# enough (the soft-length guard), so they don't shred short Italian lines.
_SUB_CONNECTORS = {
    # English
    "and", "but", "or", "so", "because", "that", "which", "who", "when",
    "where", "while", "if", "though", "although", "since", "than", "nor", "yet",
    # Italian
    "e", "ma", "o", "perché", "perche", "che", "quale", "dove", "quando",
    "mentre", "se", "però", "pero", "quindi", "oppure", "anche", "come",
    # Spanish
    "y", "pero", "porque", "que", "cuando", "donde", "mientras", "aunque",
    # French
    "et", "mais", "ou", "parce", "qui", "où", "quand", "pendant", "donc", "comme",
    # German
    "und", "aber", "oder", "weil", "dass", "welche", "wo", "wann", "während",
    "wenn", "obwohl", "als",
}


def _word_text(w):
    return (w.get("word") or "").strip()


def _ends_sentence(text):
    t = text.rstrip(_TRAIL_STRIP)
    return bool(t) and t[-1] in _SENTENCE_END


def _ends_soft(text):
    t = text.rstrip(_TRAIL_STRIP)
    return bool(t) and t[-1] in _SOFT_PUNCT


def _is_connector(text):
    t = text.strip().lower().strip(".,;:!?…\"'()[]»«")
    return t in _SUB_CONNECTORS


def _group_words_by_count(words, clip_start, count=3):
    """Group words into ~N-word karaoke chunks, snapping the break to natural
    boundaries: a sentence-final mark always closes the chunk, and a comma may
    close it one word early. Keeps the punchy small-group look while avoiding
    fragments that straddle a period (`time. The` → two chunks, not one)."""
    groups = []
    current = []
    soft_at = max(1, count - 1)
    for word in words:
        current.append(word)
        text = _word_text(word)
        if (len(current) >= count
                or _ends_sentence(text)
                or (len(current) >= soft_at and _ends_soft(text))):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _group_words(words, clip_start, max_chars=60, max_duration=5.0, soft_ratio=0.6):
    """Group words into full-line blocks at semantic boundaries (for full_line
    mode). A block closes when:
      * the next word would blow the char / duration ceiling (hard cap), OR
      * the current word ends a sentence (always — never merge two sentences), OR
      * the block is already ``soft_ratio`` of the char budget AND we're at a
        clean boundary — a comma/clause mark on the current word, or a connector
        opening the next word (break *before* the connector, VideoLingo-style).
    The soft boundary keeps lines from cutting mid-clause at the hard cap."""
    groups = []
    current = []
    soft_chars = max(1, int(max_chars * soft_ratio))

    def char_len(ws):
        return sum(len(_word_text(w)) + 1 for w in ws)

    for word in words:
        if not current:
            current.append(word)
            continue
        prev_text = _word_text(current[-1])
        prospective = char_len(current) + len(_word_text(word))
        duration = word["end"] - current[0]["start"]
        hard = prospective > max_chars or duration > max_duration
        sentence = _ends_sentence(prev_text)
        soft = char_len(current) >= soft_chars and (
            _ends_soft(prev_text) or _is_connector(_word_text(word))
        )
        if hard or sentence or soft:
            groups.append(current)
            current = [word]
        else:
            current.append(word)
    if current:
        groups.append(current)
    return groups


def _ffmpeg_filter_escape(value: str) -> str:
    """Escape a string so it is safe to inject inside an ffmpeg filtergraph
    single-quoted argument. Order matters: backslashes first, then the chars
    that have special meaning to libavfilter's lexer.
    """
    return (
        value.replace('\\', '\\\\')
             .replace(':', '\\:')
             .replace("'", "\\'")
             .replace(',', '\\,')
             .replace(';', '\\;')
             .replace('[', '\\[')
             .replace(']', '\\]')
    )


# Whitelists used by burn_subtitles to defend against ffmpeg filtergraph
# injection. Pydantic already enforces the same patterns at the API boundary
# but we re-validate here so direct callers (smartcut/compose) cannot bypass.
_HEX_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')
_FONT_NAME_RE = re.compile(r'^[A-Za-z0-9 _\-]{1,40}$')


def burn_subtitles(video_path, srt_path, output_path, alignment=2, fontsize=16,
                   font_name="Verdana", font_color="#FFFFFF",
                   border_color="#000000", border_width=2,
                   bg_color="#000000", bg_opacity=0.0, offset_y=0):
    """
    Burns subtitles into the video using FFmpeg.
    Supports .srt (with force_style) and .ass (native ASS rendering with fontsdir).
    """
    if not _FONT_NAME_RE.match(font_name):
        raise ValueError(f"invalid font_name: {font_name!r}")
    for label, color in (("font_color", font_color), ("border_color", border_color), ("bg_color", bg_color)):
        if not _HEX_RE.match(color):
            raise ValueError(f"invalid {label}: {color!r}")

    safe_sub_path = _ffmpeg_filter_escape(srt_path.replace('\\', '/'))
    is_ass = srt_path.lower().endswith('.ass')
    # Single dir libass scans (bundled + user-uploaded fonts merged). Used by
    # both the ASS and SRT branches so an uploaded face (e.g. Stratos) resolves.
    fonts_path = _ffmpeg_filter_escape(effective_fonts_dir().replace('\\', '/'))

    if is_ass:
        # ASS files have their own embedded styles (including karaoke tags).
        # Use the 'ass' filter with fontsdir so custom fonts are found.
        vf_filter = f"ass='{safe_sub_path}':fontsdir='{fonts_path}'"
    else:
        # SRT: build force_style for legacy subtitle rendering
        ass_alignment = 2
        align_lower = str(alignment).lower()
        if align_lower == 'top':
            ass_alignment = 6
        elif align_lower in ('middle', 'center'):
            # 'center' is the value the frontend always sends; alias it to the
            # legacy SSA middle-centre code (it used to fall through to bottom).
            ass_alignment = 10
        elif align_lower == 'bottom':
            ass_alignment = 2

        final_fontsize = _clamp_fontsize(int(fontsize * 0.85), 10)

        primary_colour = hex_to_ass_color(font_color, 1.0)

        if bg_opacity > 0:
            border_style = 3
            outline_colour = hex_to_ass_color(bg_color, bg_opacity)
            outline_w = 1
        else:
            border_style = 1
            outline_colour = hex_to_ass_color(border_color, 1.0)
            outline_w = max(1, border_width)

        back_colour = hex_to_ass_color("#000000", 0.0)

        # Same down-for-positive convention as the karaoke path.
        srt_margin_v = _offset_margin('top' if align_lower == 'top' else 'bottom', 350, offset_y)
        style_string = (
            f"Alignment={ass_alignment},"
            f"Fontname={font_name},"
            f"Fontsize={final_fontsize},"
            f"PrimaryColour={primary_colour},"
            f"OutlineColour={outline_colour},"
            f"BackColour={back_colour},"
            f"BorderStyle={border_style},"
            f"Outline={outline_w},"
            f"Shadow=0,"
            f"MarginV={srt_margin_v},"
            f"Bold=1"
        )
        vf_filter = f"subtitles='{safe_sub_path}':fontsdir='{fonts_path}':force_style='{style_string}'"

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:a', 'copy',
        # Shared near-visually-lossless encode (CRF 18 / medium) + faststart so a
        # subtitle-only composed clip streams progressively. See domain/encode.py.
        *x264_video_args(),
        output_path
    ]

    # Don't print the full command: it embeds absolute filesystem paths that
    # would surface in the job log served by /api/status. Terse line only.
    print("🎬 Burning subtitles…")
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if result.returncode != 0:
        print(f"❌ FFmpeg Subtitle Error: {result.stderr.decode()}")
        raise Exception(f"FFmpeg failed: {result.stderr.decode()}")

    return True

