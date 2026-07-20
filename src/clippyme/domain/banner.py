"""Per-clip attribution banner — a bottom-of-clip pill showing the source
platform logo + channel handle (e.g. logo + "kick.com/grenbaud",
"youtube.com/@GrenBaudLounge", "twitch.tv/grenbaud").

Two halves, split so the useful logic stays host-testable:

* **Pure** (no PIL / cairosvg / ffmpeg): ``suggest_banner`` (URL/platform →
  {platform, handle}), ``banner_text`` (→ display string), handle sanitization,
  ``clamp_y_pct`` and ``monitor_banner_params``. These import only stdlib and
  are exercised by the host suite.
* **Render** (``render_banner_png`` via Pillow, ``add_banner_to_video`` via
  ffmpeg, ``_rasterize_logo`` via cairosvg): heavy deps are imported LAZILY
  inside the functions so importing this module never needs them. The
  platform SVGs can't be read by ffmpeg/Pillow, so cairosvg rasterizes them to
  a per-(platform, height) PNG cached under ``data/cache/banner_logos/``.

Font loading + hook helpers are reused from ``clippyme.domain.hooks`` rather
than re-implemented.
"""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlparse

logger = logging.getLogger("clippyme")

# Platform → committed SVG asset filename (rasterized at runtime by cairosvg).
_LOGO_FILES = {
    "kick": "kick_logo.svg",
    "youtube": "YouTube_logo.svg",
    "twitch": "twitch_logo.svg",
}
_PLATFORMS = tuple(_LOGO_FILES)

_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "platform_logos")
# Rasterized-logo cache. Separate sub-dir from the transcript cache so retention
# sweeps of one never touch the other.
BANNER_CACHE_DIR = os.path.join("data", "cache", "banner_logos")

# Default banner vertical CENTER as a fraction of frame height. The default
# karaoke subtitle sits bottom-anchored with MarginV≈350px of a 1920 frame, so
# its lower edge lands at ~1570px (≈0.82H) and text grows UPWARD from there; the
# platform-UI safe zone is the bottom ~13% (≈0.87H→1.0H). 0.85 drops the banner
# into the ~1570–1670px gap between the two — clear of both. Users can nudge it
# with y_pct (clamped 0.60–0.87). See CLAUDE.md compose ordering.
DEFAULT_BANNER_Y_PCT = 0.85
_Y_PCT_MIN = 0.60
_Y_PCT_MAX = 0.87

_HANDLE_ALLOWED = re.compile(r"[^A-Za-z0-9_.-]")
_HANDLE_MAX = 40
# Host prefixes we strip when a raw handle is actually a pasted URL fragment.
_HOST_PREFIXES = (
    "https://", "http://", "www.",
    "kick.com/", "twitch.tv/", "m.twitch.tv/",
    "youtube.com/", "m.youtube.com/", "youtu.be/",
)


# ---------------------------------------------------------------------------
# Pure helpers (host-testable — stdlib only)
# ---------------------------------------------------------------------------


def sanitize_handle(raw) -> str | None:
    """Normalize a channel handle: strip URL host prefixes + a leading '@',
    keep only ``[A-Za-z0-9_.-]``, cap length. Returns None when nothing usable
    remains (so callers can drop the banner rather than render an empty pill)."""
    if not raw:
        return None
    h = str(raw).strip()
    low = h.lower()
    for pref in _HOST_PREFIXES:
        if low.startswith(pref):
            h = h[len(pref):]
            low = h.lower()
    # A URL-ish leftover keeps only the first path segment.
    h = h.split("?", 1)[0].split("#", 1)[0].split("/", 1)[0]
    h = h.lstrip("@")
    h = _HANDLE_ALLOWED.sub("", h)
    h = h[:_HANDLE_MAX]
    return h or None


def _host_platform(host: str) -> str | None:
    host = (host or "").lower()
    if host.startswith("www.") or host.startswith("m."):
        host = host.split(".", 1)[1]
    if host in ("kick.com",):
        return "kick"
    if host in ("twitch.tv",):
        return "twitch"
    if host in ("youtube.com", "youtu.be"):
        return "youtube"
    return None


def suggest_banner(source_or_platform, channel_hint=None) -> dict | None:
    """Best-effort {platform, handle} from a source URL or a bare platform name.

    - ``kick.com/<slug>`` / ``twitch.tv/<slug>`` → that platform + slug.
    - ``youtube.com/@handle`` / ``/channel/UC…`` / ``/c/<name>`` / ``/user/<name>``
      → youtube + the handle. ``watch``/``shorts``/``youtu.be`` watch URLs carry
      no handle → ``handle`` is None unless ``channel_hint`` supplies one.
    - A bare platform name ("kick"/"twitch"/"youtube") uses ``channel_hint`` as
      the handle.

    Returns None when the platform can't be determined. ``handle`` may be None
    (platform known, handle unknown) so a caller can still pick the logo.
    """
    raw = str(source_or_platform or "").strip()
    if not raw:
        return None

    # Bare platform name (monitor path).
    if raw.lower() in _PLATFORMS:
        return {"platform": raw.lower(), "handle": sanitize_handle(channel_hint)}

    # Treat as a URL. Prepend a scheme so a bare "kick.com/x" still parses.
    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    platform = _host_platform(parsed.hostname or "")
    if platform is None:
        return None

    segs = [s for s in (parsed.path or "").split("/") if s]
    handle = None
    if platform in ("kick", "twitch"):
        handle = sanitize_handle(segs[0]) if segs else None
    else:  # youtube
        if segs and segs[0].startswith("@"):
            handle = sanitize_handle(segs[0])
        elif len(segs) >= 2 and segs[0] in ("channel", "c", "user"):
            handle = sanitize_handle(segs[1])
        # /watch, /shorts/<id>, youtu.be/<id> → no channel handle in the URL.
    if handle is None:
        handle = sanitize_handle(channel_hint)
    return {"platform": platform, "handle": handle}


def banner_text(platform, handle) -> str | None:
    """Display string: ``kick.com/<h>`` · ``twitch.tv/<h>`` · ``youtube.com/@<h>``
    (the '@' is ensured for youtube). None when platform/handle is unusable."""
    h = sanitize_handle(handle)
    if not h or platform not in _PLATFORMS:
        return None
    if platform == "kick":
        return f"kick.com/{h}"
    if platform == "twitch":
        return f"twitch.tv/{h}"
    return f"youtube.com/@{h}"  # youtube


def clamp_y_pct(value, default: float = DEFAULT_BANNER_Y_PCT) -> float:
    """Clamp a requested banner vertical-center fraction to [0.60, 0.87].
    Garbage falls back to ``default``."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(_Y_PCT_MIN, min(_Y_PCT_MAX, v))


def monitor_banner_params(platform, channel, override=None) -> dict | None:
    """Resolve the banner params a live monitor should burn before publishing.

    ``override`` (per-monitor ``banner`` field) semantics:
      - None / absent → auto-enabled from the monitor's own platform + channel.
      - ``{"enabled": False}`` → disabled (returns None).
      - a dict → merged over the auto defaults (override platform/handle/y_pct).

    Returns ``{enabled, platform, handle, y_pct}`` ready for
    :func:`add_banner_to_video`, or None when disabled / no handle resolvable.
    """
    ov = override or {}
    if override is not None and ov.get("enabled") is False:
        return None
    auto = suggest_banner(ov.get("platform") or platform, channel_hint=channel) or {}
    plat = ov.get("platform") or auto.get("platform")
    handle = sanitize_handle(ov.get("handle")) or auto.get("handle")
    if not banner_text(plat, handle):
        return None
    return {
        "enabled": True,
        "platform": plat,
        "handle": handle,
        "y_pct": clamp_y_pct(ov.get("y_pct")),
    }


# ---------------------------------------------------------------------------
# Render (heavy deps imported lazily)
# ---------------------------------------------------------------------------


def _rasterize_logo(platform: str, height: int) -> str | None:
    """Rasterize a platform SVG to a cached PNG at ``height`` px (cairosvg).

    Cached per (platform, height) under ``BANNER_CACHE_DIR``; a cache hit newer
    than the source SVG is reused. Returns the PNG path, or None if the platform
    is unknown / cairosvg unavailable / rasterization fails (banner then renders
    text-only rather than crashing the compose)."""
    fname = _LOGO_FILES.get(platform)
    if not fname:
        return None
    svg_path = os.path.join(_ASSETS_DIR, fname)
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
    try:
        import cairosvg  # lazy: not in the host-test env; Docker installs it
        os.makedirs(BANNER_CACHE_DIR, exist_ok=True)
        tmp = out_path + ".tmp"
        # output_height drives the raster size; width follows the SVG aspect.
        # YouTube_logo.svg has nested <svg> + a <style> block — cairosvg handles
        # both (verified in the integration suite).
        cairosvg.svg2png(url=svg_path, write_to=tmp, output_height=height)
        os.replace(tmp, out_path)
        return out_path
    except Exception as exc:  # missing cairosvg/libcairo, bad SVG, …
        logger.warning("banner: SVG rasterize failed for %s (%s)", platform, exc)
        return None


def render_banner_png(platform, handle, width, out_path) -> tuple[str, int, int]:
    """Render the attribution pill (transparent PNG): platform logo left + handle
    text right, white text with a black stroke, on a semi-transparent dark
    rounded rect. ``width`` is the video width (used to scale the logo/text).

    Reuses ``hooks._resolve_hook_font_path`` / ``hooks._hex_to_rgba`` for font +
    colour handling. Returns (out_path, canvas_w, canvas_h)."""
    from PIL import Image, ImageDraw, ImageFont  # lazy (host-test dep, but keep top clean)

    from clippyme.domain.hooks import _resolve_hook_font_path

    text = banner_text(platform, handle) or ""
    logo_h = max(8, int(width * 56 / 1080))          # ~56px logo at 1080-wide
    font_size = max(10, int(logo_h * 0.72))
    pad_x = max(8, int(logo_h * 0.32))
    pad_y = max(4, int(logo_h * 0.18))
    gap = max(6, int(logo_h * 0.28))
    stroke_w = max(1, font_size // 14)
    radius = 0  # set after we know the pill height

    font_path = _resolve_hook_font_path(None)
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    # Optional logo raster (banner still renders text-only if it fails).
    logo_img = None
    logo_w = 0
    logo_png = _rasterize_logo(platform, logo_h)
    if logo_png:
        try:
            logo_img = Image.open(logo_png).convert("RGBA")
            logo_w = logo_img.width
        except Exception as exc:
            logger.warning("banner: logo load failed (%s)", exc)
            logo_img = None

    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tb = measure.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    text_w, text_h = tb[2] - tb[0], tb[3] - tb[1]

    content_h = max(logo_h, text_h)
    inner_w = (logo_w + gap if logo_img else 0) + text_w
    box_w = inner_w + 2 * pad_x
    box_h = content_h + 2 * pad_y
    radius = min(box_h // 2, 40)

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (box_w - 1, box_h - 1)], radius=radius,
                           fill=(0, 0, 0, int(round(0.55 * 255))))

    x = pad_x
    if logo_img is not None:
        img.paste(logo_img, (x, (box_h - logo_img.height) // 2), logo_img)
        x += logo_w + gap
    # Vertically center the text; tb[1] compensates the font's top bearing.
    text_y = (box_h - text_h) // 2 - tb[1]
    draw.text((x, text_y), text, font=font, fill=(255, 255, 255, 255),
              stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255))

    img.save(out_path)
    return out_path, box_w, box_h


def letterbox_band_bottom(width: int, height: int) -> int:
    """Y of the video band's bottom edge for a ``reframe_mode='disabled'`` clip.

    The disabled path (``reframe.create_disabled_reframe``) center-crops the
    source to 4:3 and scales it to the FULL output width, so the visible band is
    ``width * 3/4`` tall, vertically centered → its bottom edge is
    ``(H + W*3/4)/2``. Pure geometry (host-testable)."""
    return int((height + width * 3 / 4) / 2)


def add_banner_to_video(video_path, banner_params, out_path) -> bool:
    """Overlay the attribution banner (horizontally centered) onto a clip and
    encode via the shared x264 settings. Positions scale to the ACTUAL video
    geometry (read via ffprobe), never hardcoded pixels.

    ``banner_params``: ``{platform, handle, y_pct?, mode?}``.
      - ``mode='attach'`` → the banner's TOP edge sits at the letterbox video
        band's bottom edge (for ``reframe_mode='disabled'`` clips). y_pct ignored.
      - otherwise → banner vertical CENTER at ``y_pct`` (clamped 0.60–0.87,
        default 0.85: below the default subtitle band, above the platform-UI
        safe zone)."""
    import subprocess

    from clippyme.domain.encode import ffmpeg_timeout, x264_video_args
    from clippyme.pipeline.media_probe import probe_dimensions

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video {video_path} not found")

    bp = banner_params or {}
    platform, handle = bp.get("platform"), bp.get("handle")
    if not banner_text(platform, handle):
        raise ValueError("banner requires a resolvable platform + handle")

    width, height = probe_dimensions(video_path)

    banner_png = f"temp_banner_{os.getpid()}_{os.path.basename(video_path)}.png"
    try:
        _, box_w, box_h = render_banner_png(platform, handle, width, banner_png)
        overlay_x = (width - box_w) // 2
        if bp.get("mode") == "attach":
            overlay_y = letterbox_band_bottom(width, height)
        else:
            overlay_y = int(height * clamp_y_pct(bp.get("y_pct"))) - box_h // 2
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
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=ffmpeg_timeout())
        logger.info("✅ Banner added → %s", os.path.basename(out_path))
        return True
    except subprocess.TimeoutExpired:
        logger.error("❌ Banner ffmpeg timed out after %ss", ffmpeg_timeout())
        raise
    except subprocess.CalledProcessError as e:
        logger.error("❌ Banner ffmpeg error: %s", e.stderr.decode() if e.stderr else "unknown")
        raise
    finally:
        if os.path.exists(banner_png):
            os.remove(banner_png)
