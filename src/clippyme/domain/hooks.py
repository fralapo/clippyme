import os
import re
import subprocess
import urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_URL = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSerif/NotoSerif-Bold.ttf"

# Hard cap for runtime font downloads — defends against a hostile/compromised
# mirror serving a multi-GB payload (or a decompression bomb) into memory.
_FONT_MAX_BYTES = 25 * 1024 * 1024
_FONT_HTTP_TIMEOUT = 30


def _download_capped(req, out_path):
    """Stream a urllib request to disk, aborting past _FONT_MAX_BYTES."""
    with urllib.request.urlopen(req, timeout=_FONT_HTTP_TIMEOUT) as response, open(out_path, "wb") as out_file:
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _FONT_MAX_BYTES:
                raise RuntimeError("font download exceeded size cap")
            out_file.write(chunk)

# Resolve bundled fonts dir by walking up from __file__ (→ repo-root/fonts).
# A bare CWD-relative "fonts" broke for any caller not launched from the
# repo root (reframe subprocess, tests, ad-hoc CLI from /tmp). Env override
# lets operators point at a different install prefix.
_REPO_ROOT_FROM_HERE = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
FONT_DIR = os.environ.get("CLIPPYME_FONTS_DIR") or os.path.join(_REPO_ROOT_FROM_HERE, "fonts")
if not os.path.isdir(FONT_DIR):
    _cwd_fallback = os.path.abspath("fonts")
    if os.path.isdir(_cwd_fallback):
        FONT_DIR = _cwd_fallback
FONT_PATH = os.path.join(FONT_DIR, "NotoSerif-Bold.ttf")


def download_font_if_needed():
    """Downloads a serif font for the hook text if not present."""
    os.makedirs(FONT_DIR, exist_ok=True)
    if not os.path.exists(FONT_PATH):
        print(f"⬇️ Downloading font from {FONT_URL}...")
        try:
            req = urllib.request.Request(FONT_URL, headers={"User-Agent": "Mozilla/5.0"})
            _download_capped(req, FONT_PATH)
            print("✅ Font downloaded.")
        except Exception as e:
            print(f"❌ Failed to download font: {e}")


EMOJI_FONT_URL = "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji.ttf"
EMOJI_FONT_PATH = os.path.join(FONT_DIR, "NotoColorEmoji.ttf")


def download_emoji_font_if_needed():
    """Downloads the Noto Color Emoji font if not present."""
    os.makedirs(FONT_DIR, exist_ok=True)
    if not os.path.exists(EMOJI_FONT_PATH):
        print(f"Downloading emoji font...")
        try:
            req = urllib.request.Request(EMOJI_FONT_URL, headers={"User-Agent": "Mozilla/5.0"})
            _download_capped(req, EMOJI_FONT_PATH)
            print("Emoji font downloaded.")
        except Exception as e:
            print(f"Failed to download emoji font: {e}")


def has_emoji(text):
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF"
        "\U0000FE00-\U0000FE0F\U0000200D]+")
    return bool(emoji_pattern.search(text))


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _hex_to_rgba(hex_str, alpha=255, default=(0, 0, 0)):
    """#RRGGBB → (r, g, b, alpha). Falls back to `default` on a bad value so a
    malformed colour can never crash the render."""
    if isinstance(hex_str, str) and _HEX_RE.match(hex_str):
        h = hex_str.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(alpha))
    return (*default, int(alpha))


def _resolve_hook_font_path(font_name):
    """Map a font NAME (e.g. 'Anton-Regular', an uploaded 'Stratos-Medium') to a
    TTF/OTF path. Searches the bundled fonts dir + the writable user-fonts dir
    (shared with the subtitle pipeline). Falls back to the bundled serif."""
    if font_name:
        dirs = [FONT_DIR]
        try:
            from clippyme.domain.subtitles import USER_FONTS_DIR
            dirs.append(USER_FONTS_DIR)
        except Exception:
            pass
        for d in dirs:
            for ext in (".ttf", ".otf", ".ttc"):
                p = os.path.join(d, f"{font_name}{ext}")
                if os.path.exists(p):
                    return p
    download_font_if_needed()
    return FONT_PATH


# Instagram-Stories-style defaults: bannerless white Anton with a thin black
# outline (the bannerless path auto-adds a soft drop shadow for legibility).
# Kept in sync with the frontend HOOK_STYLE_DEFAULT (redesign/data.js) so that
# any path sending partial/no style (legacy clips, restored history jobs)
# renders the same look the live preview shows.
HOOK_STYLE_DEFAULTS = {
    "text_color": "#FFFFFF",
    "bg_enabled": False,
    "bg_color": "#FFFFFF",
    "bg_opacity": 0.94,
    "corner_radius": 20,
    "outline_color": "#000000",
    "outline_width": 4,
    "font": "Anton-Regular",
    "shadow": None,          # None → auto (shadow only when no banner)
    "animate": False,        # True → fade+slide-up entrance (build_hook_overlay_filter)
}


def create_hook_image(text, target_width, output_image_path="hook_overlay.png",
                      font_scale=1.0, style=None):
    """Render a hook text overlay PNG (transparent canvas).

    `style` (all optional, see HOOK_STYLE_DEFAULTS) makes the overlay behave
    like Instagram Stories text: a toggleable coloured banner behind the text,
    independent text/background colours, a text outline (stroke) and a font
    choice. With no style it reproduces the legacy white-box / black-serif look.

    target_width: max width the box should occupy (e.g. 90% of video width).
    """
    s = {**HOOK_STYLE_DEFAULTS, **(style or {})}
    bg_enabled = bool(s["bg_enabled"])
    bg_opacity = max(0.0, min(1.0, float(s["bg_opacity"])))
    text_rgba = _hex_to_rgba(s["text_color"], 255, default=(0, 0, 0))
    bg_rgba = _hex_to_rgba(s["bg_color"], int(round(bg_opacity * 255)), default=(255, 255, 255))
    outline_w = max(0, min(20, int(s["outline_width"])))
    outline_rgba = _hex_to_rgba(s["outline_color"], 255, default=(0, 0, 0))
    corner_radius = max(0, min(80, int(s["corner_radius"])))
    # Drop shadow lifts text off the video; auto-on only when there's no banner
    # to provide contrast (matches IG's bannerless styles).
    shadow = (not bg_enabled) if s["shadow"] is None else bool(s["shadow"])

    padding_x = 30 if bg_enabled else 12
    padding_y = 25 if bg_enabled else 10
    line_spacing = 20

    base_font_size = int(target_width * 0.05)
    font_size = max(8, int(base_font_size * font_scale))

    font_path = _resolve_hook_font_path(s["font"])
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        try:
            font = ImageFont.truetype(FONT_PATH, font_size)
        except Exception:
            font = ImageFont.load_default()

    # Pixel-based word wrapping
    dummy_img = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    max_text_width = target_width - (2 * padding_x)

    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current_line = []
        for word in paragraph.split():
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font, stroke_width=outline_w)
            if bbox[2] - bbox[0] <= max_text_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))

    # Measure lines
    max_line_width = 0
    text_heights = []
    for line in lines:
        if not line:
            text_heights.append(font_size)
            continue
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=outline_w)
        max_line_width = max(max_line_width, bbox[2] - bbox[0])
        text_heights.append(bbox[3] - bbox[1])

    min_box = int(target_width * 0.3) if bg_enabled else max_line_width
    box_width = max(max_line_width + 2 * padding_x, min_box)
    total_text_height = sum(text_heights) + (len(text_heights) - 1) * line_spacing if text_heights else font_size
    box_height = total_text_height + 2 * padding_y

    # Canvas margin leaves room for the soft shadow / stroke overflow.
    margin = 20
    canvas_w = box_width + 2 * margin
    canvas_h = box_height + 2 * margin
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    if shadow:
        shadow_offset = (4, 4)
        draw = ImageDraw.Draw(img)
        if bg_enabled:
            draw.rounded_rectangle(
                [(margin + shadow_offset[0], margin + shadow_offset[1]),
                 (margin + box_width + shadow_offset[0], margin + box_height + shadow_offset[1])],
                radius=corner_radius, fill=(0, 0, 0, 110))
        else:
            # Bannerless: a soft text-shaped shadow for legibility.
            cy = margin + padding_y - 2
            for i, line in enumerate(lines):
                if line:
                    bb = draw.textbbox((0, 0), line, font=font, stroke_width=outline_w)
                    lw = bb[2] - bb[0]
                    lx = margin + (box_width - lw) // 2
                    draw.text((lx + shadow_offset[0], cy + shadow_offset[1]), line, font=font,
                              fill=(0, 0, 0, 150), stroke_width=outline_w)
                cy += (text_heights[i] if i < len(text_heights) else font_size) + line_spacing
        img = img.filter(ImageFilter.GaussianBlur(5))

    draw_final = ImageDraw.Draw(img)
    if bg_enabled:
        # Pillow throws / renders lobes when radius exceeds half the shorter
        # side — clamp it for short single-line banners.
        r = min(corner_radius, box_height // 2, box_width // 2)
        draw_final.rounded_rectangle(
            [(margin, margin), (margin + box_width, margin + box_height)],
            radius=r, fill=bg_rgba)

    # Emoji font (loaded lazily only when needed)
    emoji_font = None
    if any(has_emoji(line) for line in lines if line):
        download_emoji_font_if_needed()
        try:
            emoji_font = ImageFont.truetype(EMOJI_FONT_PATH, font_size)
        except Exception:
            emoji_font = None

    current_y = margin + padding_y - 2
    for i, line in enumerate(lines):
        if not line:
            current_y += font_size + line_spacing
            continue
        bbox = draw_final.textbbox((0, 0), line, font=font, stroke_width=outline_w)
        line_w = bbox[2] - bbox[0]
        x = margin + (box_width - line_w) // 2

        # Pillow rejects stroke_width together with embedded_color (emoji), so
        # emoji lines render without the outline.
        if emoji_font and has_emoji(line):
            draw_final.text((x, current_y), line, font=font, fill=text_rgba, embedded_color=True)
        elif outline_w > 0:
            draw_final.text((x, current_y), line, font=font, fill=text_rgba,
                            stroke_width=outline_w, stroke_fill=outline_rgba)
        else:
            draw_final.text((x, current_y), line, font=font, fill=text_rgba)

        current_y += (text_heights[i] if i < len(text_heights) else bbox[3] - bbox[1]) + line_spacing

    img.save(output_image_path)
    return output_image_path, canvas_w, canvas_h


def build_hook_overlay_filter(x, y0, animate=False, dur=0.4, slide_px=40):
    """Build the ffmpeg `-filter_complex` graph that overlays the hook PNG
    (input [1:v]) onto the video ([0:v]) at (x, y0).

    Pure (returns a string) so it is host-unit-testable.

    - animate=False → the legacy static overlay, byte-identical to before.
    - animate=True  → an Instagram-Reels-style entrance: the PNG fades in over
      `dur` seconds while sliding up `slide_px` px into place with an
      ease-out-cubic curve (`pow(1-p, 3)` — never linear, video-use rule). The
      hold frame is the final placed position, so the hook stays visible for
      the rest of the clip.
    """
    x = int(x)
    y0 = int(y0)
    if not animate:
        return f"[0:v][1:v]overlay={x}:{y0}"
    # offset = slide_px * (1-eased) = slide_px * pow(1-p, 3); commas inside the
    # expression must be escaped so ffmpeg doesn't read them as filter splits.
    y_expr = f"{y0}+{int(slide_px)}*pow(1-min(t/{dur}\\,1)\\,3)"
    return (
        f"[1:v]format=yuva420p,fade=t=in:st=0:d={dur}:alpha=1[hk];"
        f"[0:v][hk]overlay={x}:{y_expr}"
    )


def add_hook_to_video(video_path, text, output_path, position="top", font_scale=1.0,
                      offset_y=0, style=None):
    """
    Overlays a text hook box onto a video.
    position: 'top', 'center', 'bottom'
    font_scale: float multiplier (0.8 = small, 1.0 = medium, 1.3 = large)
    offset_y: vertical offset as percentage of video height (-50 to +50)
    style: optional Instagram-Stories-style dict (see HOOK_STYLE_DEFAULTS) —
      banner toggle/colour/opacity, text colour, outline, font.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video {video_path} not found")

    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", video_path]
        res = subprocess.check_output(cmd).decode().strip()
        dims = res.split("\n")[0].split("x")
        video_width, video_height = int(dims[0]), int(dims[1])
    except Exception:
        video_width, video_height = 1080, 1920

    target_box_width = int(video_width * 0.9)
    hook_filename = f"temp_hook_{os.getpid()}_{os.path.basename(video_path)}.png"

    try:
        img_path, box_w, box_h = create_hook_image(text, target_box_width, hook_filename,
                                                    font_scale=font_scale, style=style)

        overlay_x = (video_width - box_w) // 2
        position_norm = "center" if position == "middle" else position
        if position_norm == "center":
            overlay_y = (video_height - box_h) // 2
        elif position_norm == "bottom":
            overlay_y = int(video_height * 0.70)
        else:
            overlay_y = int(video_height * 0.20)

        # Apply manual vertical offset (percentage of video height)
        overlay_y += int(video_height * offset_y / 100)
        overlay_y = max(0, min(overlay_y, video_height - box_h))

        animate = bool((style or {}).get("animate", False))
        filter_complex = build_hook_overlay_filter(overlay_x, overlay_y, animate=animate)

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", img_path,
            "-filter_complex", filter_complex,
            "-c:a", "copy",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            # -pix_fmt yuv420p: the hook overlay composites an RGBA PNG, so
            # without this libx264 can pick yuv444p and the result is undecodable
            # in Safari / many social players. +faststart for progressive play.
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            output_path,
        ]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"✅ Hook added to {output_path}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg Error: {e.stderr.decode() if e.stderr else 'Unknown'}")
        raise
    finally:
        if os.path.exists(hook_filename):
            os.remove(hook_filename)
