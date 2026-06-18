"""Logo / watermark overlay — burns a user-supplied PNG onto a clip.

Mirrors the hook overlay approach (single ffmpeg overlay pass) but the image is
provided by the user instead of rendered from text. Used as the topmost compose
layer so the brand mark stays visible on every kept frame.

Pure ffmpeg; the only Python-side work is computing the overlay placement
expression from a position preset + margin. The geometry helper is host-unit
tested (no ffmpeg needed) via `logo_overlay_xy`.
"""
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

# Anchor presets → (x_expr, y_expr) using ffmpeg overlay variables. `M` is the
# margin in pixels (substituted before building the filter). main_* = base video
# size, overlay_* = scaled logo size, so we never need to know the logo's exact
# pixel dimensions up front.
_POSITIONS = {
    "top-left": ("{M}", "{M}"),
    "top-right": ("main_w-overlay_w-{M}", "{M}"),
    "top-center": ("(main_w-overlay_w)/2", "{M}"),
    "bottom-left": ("{M}", "main_h-overlay_h-{M}"),
    "bottom-right": ("main_w-overlay_w-{M}", "main_h-overlay_h-{M}"),
    "bottom-center": ("(main_w-overlay_w)/2", "main_h-overlay_h-{M}"),
    "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
}

DEFAULT_POSITION = "top-right"


def logo_overlay_xy(position: str, margin_px: int) -> tuple[str, str]:
    """Return the (x, y) ffmpeg overlay expressions for a position preset.

    Falls back to the default corner for an unknown preset. Pure string math →
    host-unit-testable without ffmpeg or a real video.
    """
    x_tpl, y_tpl = _POSITIONS.get(position, _POSITIONS[DEFAULT_POSITION])
    m = max(0, int(margin_px))
    return x_tpl.format(M=m), y_tpl.format(M=m)


def add_logo_to_video(
    video_path: str,
    logo_path: str,
    output_path: str,
    position: str = DEFAULT_POSITION,
    scale: float = 0.18,
    opacity: float = 1.0,
    margin: float = 0.04,
) -> bool:
    """Overlay a logo PNG onto a video.

    position: one of _POSITIONS keys (default top-right)
    scale:    logo width as a fraction of the video width (0.05–0.5)
    opacity:  0.0–1.0 alpha multiplier
    margin:   gap from the frame edge as a fraction of the video width
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video {video_path} not found")
    if not os.path.exists(logo_path):
        raise FileNotFoundError(f"Logo {logo_path} not found")

    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
               "-of", "csv=s=x:p=0", video_path]
        dims = subprocess.check_output(cmd).decode().strip().split("\n")[0].split("x")
        video_width, video_height = int(dims[0]), int(dims[1])
    except Exception:
        video_width, video_height = 1080, 1920

    scale = min(0.5, max(0.05, float(scale)))
    opacity = min(1.0, max(0.0, float(opacity)))
    logo_w = max(1, int(video_width * scale))
    margin_px = int(video_width * max(0.0, float(margin)))
    x_expr, y_expr = logo_overlay_xy(position, margin_px)

    # Scale the logo to the target width (height auto, aspect preserved), force
    # an alpha channel, then apply the opacity multiplier before overlaying.
    logo_chain = f"scale={logo_w}:-1,format=rgba,colorchannelmixer=aa={opacity:.3f}"
    filter_complex = f"[1:v]{logo_chain}[lg];[0:v][lg]overlay={x_expr}:{y_expr}"

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", logo_path,
        "-filter_complex", filter_complex,
        "-c:a", "copy",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "22",
        output_path,
    ]
    try:
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("✅ Logo overlaid → %s", os.path.basename(output_path))
        return True
    except subprocess.CalledProcessError as e:
        logger.error("❌ Logo ffmpeg error: %s", e.stderr.decode() if e.stderr else "unknown")
        raise
