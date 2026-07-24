"""Per-clip attribution banner rendering and source-platform helpers."""
from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
from urllib.parse import urlparse

logger = logging.getLogger("clippyme")

_LOGO_FILES = {
    "kick": "kick_logo.svg",
    "youtube": "YouTube_logo.svg",
    "twitch": "twitch_logo.svg",
}
_PLATFORMS = tuple(_LOGO_FILES)

_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "assets", "platform_logos"
)
BANNER_CACHE_DIR = os.path.join("data", "cache", "banner_logos")

DEFAULT_BANNER_Y_PCT = 0.85
_Y_PCT_MIN = 0.60
_Y_PCT_MAX = 0.87

_HANDLE_ALLOWED = re.compile(r"[^A-Za-z0-9_.-]")
_HANDLE_MAX = 40
_HOST_PREFIXES = (
    "https://", "http://", "www.",
    "kick.com/", "twitch.tv/", "m.twitch.tv/",
    "youtube.com/", "m.youtube.com/", "youtu.be/",
)


def sanitize_handle(raw) -> str | None:
    """Normalize a channel handle and return None when nothing usable remains."""
    if not raw:
        return None
    handle = str(raw).strip()
    lowered = handle.lower()
    for prefix in _HOST_PREFIXES:
        if lowered.startswith(prefix):
            handle = handle[len(prefix):]
            lowered = handle.lower()
    handle = handle.split("?", 1)[0].split("#", 1)[0].split("/", 1)[0]
    handle = handle.lstrip("@")
    handle = _HANDLE_ALLOWED.sub("", handle)
    handle = handle[:_HANDLE_MAX]
    return handle or None


def _host_platform(host: str) -> str | None:
    host = (host or "").lower()
    if host.startswith("www.") or host.startswith("m."):
        host = host.split(".", 1)[1]
    if host == "kick.com":
        return "kick"
    if host == "twitch.tv":
        return "twitch"
    if host in ("youtube.com", "youtu.be"):
        return "youtube"
    return None


def suggest_banner(source_or_platform, channel_hint=None) -> dict | None:
    """Best-effort ``{platform, handle}`` from a source URL or platform name."""
    raw = str(source_or_platform or "").strip()
    if not raw:
        return None
    if raw.lower() in _PLATFORMS:
        return {"platform": raw.lower(), "handle": sanitize_handle(channel_hint)}

    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    platform = _host_platform(parsed.hostname or "")
    if platform is None:
        return None

    segments = [segment for segment in (parsed.path or "").split("/") if segment]
    handle = None
    if platform in ("kick", "twitch"):
        handle = sanitize_handle(segments[0]) if segments else None
    else:
        if segments and segments[0].startswith("@"):
            handle = sanitize_handle(segments[0])
        elif len(segments) >= 2 and segments[0] in ("channel", "c", "user"):
            handle = sanitize_handle(segments[1])
    if handle is None:
        handle = sanitize_handle(channel_hint)
    return {"platform": platform, "handle": handle}


def banner_text(platform, handle) -> str | None:
    """Return the display string for a valid platform/handle pair."""
    clean = sanitize_handle(handle)
    if not clean or platform not in _PLATFORMS:
        return None
    if platform == "kick":
        return f"kick.com/{clean}"
    if platform == "twitch":
        return f"twitch.tv/{clean}"
    return f"youtube.com/@{clean}"


def clamp_y_pct(value, default: float = DEFAULT_BANNER_Y_PCT) -> float:
    """Clamp a requested banner vertical-center fraction to [0.60, 0.87]."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(_Y_PCT_MIN, min(_Y_PCT_MAX, parsed))


def monitor_banner_params(platform, channel, override=None) -> dict | None:
    """Resolve the banner params a live monitor should burn before publishing."""
    values = override or {}
    if override is not None and values.get("enabled") is False:
        return None
    auto = suggest_banner(values.get("platform") or platform, channel_hint=channel) or {}
    resolved_platform = values.get("platform") or auto.get("platform")
    handle = sanitize_handle(values.get("handle")) or auto.get("handle")
    if not banner_text(resolved_platform, handle):
        return None
    return {
        "enabled": True,
        "platform": resolved_platform,
        "handle": handle,
        "y_pct": clamp_y_pct(values.get("y_pct")),
    }


def _rasterize_logo(platform: str, height: int) -> str | None:
    """Rasterize a committed platform SVG to an atomic cached PNG."""
    filename = _LOGO_FILES.get(platform)
    if not filename:
        return None
    svg_path = os.path.join(_ASSETS_DIR, filename)
    if not os.path.exists(svg_path):
        logger.warning("banner: logo asset missing: %s", svg_path)
        return None
    height = max(8, int(height))
    out_path = os.path.join(BANNER_CACHE_DIR, f"{platform}_{height}.png")
    try:
        if os.path.exists(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(svg_path):
            return out_path
    except OSError:
        pass

    tmp_path = None
    try:
        import cairosvg

        os.makedirs(BANNER_CACHE_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{platform}_{height}-", suffix=".png.tmp", dir=BANNER_CACHE_DIR
        )
        os.close(fd)
        cairosvg.svg2png(url=svg_path, write_to=tmp_path, output_height=height)
        os.replace(tmp_path, out_path)
        tmp_path = None
        return out_path
    except Exception as exc:
        logger.warning("banner: SVG rasterize failed for %s (%s)", platform, exc)
        return None
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)


def render_banner_png(platform, handle, width, out_path) -> tuple[str, int, int]:
    """Render the transparent attribution pill and return path/width/height."""
    from PIL import Image, ImageDraw, ImageFont

    from clippyme.domain.hooks import _resolve_hook_font_path

    text = banner_text(platform, handle) or ""
    logo_h = max(8, int(width * 56 / 1080))
    font_size = max(10, int(logo_h * 0.72))
    pad_x = max(8, int(logo_h * 0.32))
    pad_y = max(4, int(logo_h * 0.18))
    gap = max(6, int(logo_h * 0.28))
    stroke_w = max(1, font_size // 14)

    font_path = _resolve_hook_font_path(None)
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    logo_img = None
    logo_w = 0
    logo_png = _rasterize_logo(platform, logo_h)
    if logo_png:
        try:
            logo_img = Image.open(logo_png).convert("RGBA")
            logo_w = logo_img.width
        except Exception as exc:
            logger.warning("banner: logo load failed (%s)", exc)

    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text_box = measure.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    text_w, text_h = text_box[2] - text_box[0], text_box[3] - text_box[1]

    content_h = max(logo_h, text_h)
    inner_w = (logo_w + gap if logo_img else 0) + text_w
    box_w = inner_w + 2 * pad_x
    box_h = content_h + 2 * pad_y
    radius = min(box_h // 2, 40)

    image = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [(0, 0), (box_w - 1, box_h - 1)],
        radius=radius,
        fill=(0, 0, 0, int(round(0.55 * 255))),
    )

    x = pad_x
    if logo_img is not None:
        image.paste(logo_img, (x, (box_h - logo_img.height) // 2), logo_img)
        x += logo_w + gap
    text_y = (box_h - text_h) // 2 - text_box[1]
    draw.text(
        (x, text_y), text, font=font, fill=(255, 255, 255, 255),
        stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255),
    )

    image.save(out_path)
    return out_path, box_w, box_h


def letterbox_band_bottom(width: int, height: int) -> int:
    """Y of the video band's bottom edge for disabled/letterbox reframe."""
    return int((height + width * 3 / 4) / 2)


def add_banner_to_video(video_path, banner_params, out_path) -> bool:
    """Overlay an attribution banner onto a clip using a unique temp PNG."""
    import subprocess

    from clippyme.domain.encode import ffmpeg_timeout, x264_video_args
    from clippyme.pipeline.media_probe import probe_dimensions

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video {video_path} not found")

    params = banner_params or {}
    platform, handle = params.get("platform"), params.get("handle")
    if not banner_text(platform, handle):
        raise ValueError("banner requires a resolvable platform + handle")

    width, height = probe_dimensions(video_path)
    fd, banner_png = tempfile.mkstemp(prefix="clippyme-banner-", suffix=".png")
    os.close(fd)
    try:
        _, box_w, box_h = render_banner_png(platform, handle, width, banner_png)
        overlay_x = (width - box_w) // 2
        if params.get("mode") == "attach":
            overlay_y = letterbox_band_bottom(width, height)
        else:
            overlay_y = int(height * clamp_y_pct(params.get("y_pct"))) - box_h // 2
        overlay_y = max(0, min(overlay_y, height - box_h))
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", banner_png,
            "-filter_complex", f"[0:v][1:v]overlay={overlay_x}:{overlay_y}",
            "-c:a", "copy",
            *x264_video_args(),
            out_path,
        ]
        subprocess.run(
            ffmpeg_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=ffmpeg_timeout(),
        )
        logger.info("✅ Banner added → %s", os.path.basename(out_path))
        return True
    except subprocess.TimeoutExpired:
        logger.error("❌ Banner ffmpeg timed out after %ss", ffmpeg_timeout())
        raise
    except subprocess.CalledProcessError as exc:
        logger.error(
            "❌ Banner ffmpeg error: %s",
            exc.stderr.decode() if exc.stderr else "unknown",
        )
        raise
    finally:
        with contextlib.suppress(OSError):
            os.remove(banner_png)
