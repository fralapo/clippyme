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


def create_hook_image(text, target_width, output_image_path="hook_overlay.png", font_scale=1.0):
    """
    Generates a white rounded-corner box with black serif text.
    target_width: max width the box should occupy (e.g. 85% of video width).
    """
    download_font_if_needed()

    padding_x = 30
    padding_y = 25
    line_spacing = 20
    corner_radius = 20
    shadow_offset = (5, 5)

    base_font_size = int(target_width * 0.05)
    font_size = int(base_font_size * font_scale)

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
            bbox = draw.textbbox((0, 0), test_line, font=font)
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
        bbox = draw.textbbox((0, 0), line, font=font)
        max_line_width = max(max_line_width, bbox[2] - bbox[0])
        text_heights.append(bbox[3] - bbox[1])

    box_width = max(max_line_width + 2 * padding_x, int(target_width * 0.3))
    total_text_height = sum(text_heights) + (len(text_heights) - 1) * line_spacing if text_heights else font_size
    box_height = total_text_height + 2 * padding_y

    # Canvas with shadow
    canvas_w = box_width + 40
    canvas_h = box_height + 40
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Shadow
    shadow_box = [
        (20 + shadow_offset[0], 20 + shadow_offset[1]),
        (20 + box_width + shadow_offset[0], 20 + box_height + shadow_offset[1]),
    ]
    draw.rounded_rectangle(shadow_box, radius=corner_radius, fill=(0, 0, 0, 100))
    img = img.filter(ImageFilter.GaussianBlur(5))

    # White box
    draw_final = ImageDraw.Draw(img)
    main_box = [(20, 20), (20 + box_width, 20 + box_height)]
    draw_final.rounded_rectangle(main_box, radius=corner_radius, fill=(255, 255, 255, 240))

    # Emoji font (loaded lazily only when needed)
    emoji_font = None
    if any(has_emoji(line) for line in lines if line):
        download_emoji_font_if_needed()
        try:
            emoji_font = ImageFont.truetype(EMOJI_FONT_PATH, font_size)
        except Exception:
            emoji_font = None

    # Text
    current_y = 20 + padding_y - 2
    for i, line in enumerate(lines):
        if not line:
            current_y += font_size + line_spacing
            continue
        bbox = draw_final.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = 20 + (box_width - line_w) // 2

        if emoji_font and has_emoji(line):
            draw_final.text((x, current_y), line, font=font, fill="black", embedded_color=True)
        else:
            draw_final.text((x, current_y), line, font=font, fill="black")

        current_y += (text_heights[i] if i < len(text_heights) else bbox[3] - bbox[1]) + line_spacing

    img.save(output_image_path)
    return output_image_path, canvas_w, canvas_h


def add_hook_to_video(video_path, text, output_path, position="top", font_scale=1.0, offset_y=0):
    """
    Overlays a text hook box onto a video.
    position: 'top', 'center', 'bottom'
    font_scale: float multiplier (0.8 = small, 1.0 = medium, 1.3 = large)
    offset_y: vertical offset as percentage of video height (-50 to +50)
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
        img_path, box_w, box_h = create_hook_image(text, target_box_width, hook_filename, font_scale=font_scale)

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

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", img_path,
            "-filter_complex", f"[0:v][1:v]overlay={overlay_x}:{overlay_y}",
            "-c:a", "copy",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
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
