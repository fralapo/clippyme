import os
import re
import subprocess


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
            
            if current_text_len + len(word['word']) > max_chars or duration > max_duration:
                # Finalize current block
                # End time of block is start of this word (gap) or end of last word?
                # Usually end of last word.
                block_end = current_block[-1]['end'] - clip_start
                
                text = " ".join([w['word'] for w in current_block]).strip()
                srt_content += format_srt_block(index, block_start, block_end, text)
                index += 1
                
                current_block = [word]
                block_start = start
            else:
                current_block.append(word)
    
    # Final block
    if current_block:
        block_end = current_block[-1]['end'] - clip_start
        text = " ".join([w['word'] for w in current_block]).strip()
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
    if font_color:
        style["text_color"] = font_color
    if highlight_color:
        style["highlight_color"] = highlight_color
    if font_size:
        style["fontsize"] = font_size
    if outline_width is not None:
        style["outline_width"] = outline_width
    if uppercase is not None:
        style["uppercase"] = uppercase

    # Position → ASS alignment + margin
    position_norm = str(position).lower()
    if position_norm == "middle":
        position_norm = "center"  # frontend alias
    if position_norm == "top":
        ass_alignment = 8  # top-center
        base_margin_v = 260
    elif position_norm == "center":
        ass_alignment = 5  # center-center
        base_margin_v = 0
    else:
        ass_alignment = 2  # bottom-center
        base_margin_v = style.get("margin_v", 350)

    # Apply manual vertical offset (percentage of 1920px frame height)
    margin_v = base_margin_v + int(1920 * offset_y / 100)

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
            text = w['word'].strip()
            # Strip ASS override-block braces from transcript text so a word
            # token like "{\pos(0,0)}" can't smuggle libass directives into
            # the Dialogue event (ASR can echo adversarial on-screen/audio text).
            text = text.replace('{', '').replace('}', '')
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


def _group_words_by_count(words, clip_start, count=3):
    """Group words into chunks of N words."""
    groups = []
    for i in range(0, len(words), count):
        group = words[i:i + count]
        if group:
            groups.append(group)
    return groups


def _group_words(words, clip_start, max_chars=60, max_duration=5.0):
    """Group words into blocks by char limit and duration (for full_line mode)."""
    groups = []
    current = []
    for word in words:
        if not current:
            current.append(word)
        else:
            text_len = sum(len(w['word']) + 1 for w in current) + len(word['word'])
            duration = word['end'] - current[0]['start']
            if text_len > max_chars or duration > max_duration:
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

    if is_ass:
        # ASS files have their own embedded styles (including karaoke tags).
        # Use the 'ass' filter with fontsdir so custom fonts are found.
        fonts_path = _ffmpeg_filter_escape(FONTS_DIR.replace('\\', '/'))
        vf_filter = f"ass='{safe_sub_path}':fontsdir='{fonts_path}'"
    else:
        # SRT: build force_style for legacy subtitle rendering
        ass_alignment = 2
        align_lower = str(alignment).lower()
        if align_lower == 'top':
            ass_alignment = 6
        elif align_lower == 'middle':
            ass_alignment = 10
        elif align_lower == 'bottom':
            ass_alignment = 2

        final_fontsize = int(fontsize * 0.85)
        if final_fontsize < 10:
            final_fontsize = 10

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

        srt_margin_v = 350 - int(1920 * offset_y / 100)
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
        vf_filter = f"subtitles='{safe_sub_path}':force_style='{style_string}'"

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:a', 'copy',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23',
        output_path
    ]

    print(f"🎬 Burning subtitles: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if result.returncode != 0:
        print(f"❌ FFmpeg Subtitle Error: {result.stderr.decode()}")
        raise Exception(f"FFmpeg failed: {result.stderr.decode()}")

    return True

