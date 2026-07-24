"""YouTube/Twitch/Kick download + filename/cookies helpers.

Extracted from ``pipeline.main`` as part of the decomposition. Depends only on
``yt_dlp`` + stdlib (no cv2/torch/mediapipe), so it imports and is testable on
the host.
"""
import ipaddress
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import yt_dlp

from clippyme.netutil import resolve_host_addresses


# Remote URL jobs are intentionally limited to the platforms ClippyMe actually
# supports.  The old validator accepted every public HTTP(S) host; because
# yt-dlp follows redirects and extractor-provided media URLs, that exposed a
# broad server-side fetch primitive even though the first hostname was checked
# for private IPs.  Exact official hosts + HTTPS keep user jobs on the expected
# trust boundary while still covering YouTube, Twitch clips/VODs and Kick VODs.
_SUPPORTED_SOURCE_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
    "twitch.tv",
    "www.twitch.tv",
    "m.twitch.tv",
    "clips.twitch.tv",
    "kick.com",
    "www.kick.com",
})


def validate_supported_source_url(url: str) -> str:
    """Validate a user/monitor URL before yt-dlp is allowed to resolve it."""
    raw = (url or "").strip()
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid source URL") from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in _SUPPORTED_SOURCE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError(
            "source URL must be an official HTTPS YouTube, Twitch, or Kick URL"
        )
    return raw


def _reject_rebound_internal(url: str) -> None:
    """Re-resolve the URL host at download time and refuse internal ranges.

    This is a second line of defence against DNS rebinding after the API-layer
    validation. Resolution failures are left to yt-dlp, but any internal address
    in a mixed answer is rejected.
    """
    try:
        host = urlparse(url).hostname
        if not host:
            return
        try:
            ip_obj = ipaddress.ip_address(host)
            addrs = [ip_obj]
        except ValueError:
            addrs = resolve_host_addresses(host, timeout=5.0)
        if any(
            a.is_private
            or a.is_loopback
            or a.is_link_local
            or a.is_reserved
            or a.is_multicast
            or a.is_unspecified
            for a in addrs
        ):
            raise ValueError(f"refusing download: {host} resolves to an internal address")
    except ValueError:
        raise
    except Exception:
        # A transient resolver failure is not an SSRF bypass now that the host
        # itself is an exact supported-platform allow-list entry. yt-dlp will
        # surface the actual network error to the job.
        return


def sanitize_filename(filename):
    """Remove invalid characters from filename."""
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = filename.replace(' ', '_')
    filename = filename.lstrip('-.')
    return filename[:100] or 'video'


def _resolve_cookies_path(explicit: str | None) -> str | None:
    """Resolve the cookies.txt path used by yt-dlp.

    Precedence:
      1. Explicit path passed on the CLI / by the caller.
      2. Repo-root ``data/cookies.txt`` (the path the dashboard writes to).
      3. ``YOUTUBE_COOKIES`` env var materialized into ``data/cookies_env.txt``.
      4. None (no cookies).
    """
    if explicit:
        return explicit
    repo_root_cookies = os.path.join("data", "cookies.txt")
    if os.path.exists(repo_root_cookies):
        return os.path.abspath(repo_root_cookies)
    env_cookies = os.environ.get("YOUTUBE_COOKIES")
    if env_cookies:
        env_path = os.path.join("data", "cookies_env.txt")
        os.makedirs(os.path.dirname(env_path) or ".", exist_ok=True)
        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(env_cookies)
        return os.path.abspath(env_path)
    return None


# Video format ladder. avc1 (H.264) first so downstream ffmpeg/x264 passes
# never have to transcode VP9/AV1; the generic tail stops AV1/VP9-only serves
# from hard-failing when no avc1 rendition exists.
_FORMAT_LADDER = (
    'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/'
    'bestvideo[vcodec^=avc1]+bestaudio/'
    'best[ext=mp4]/bestvideo*+bestaudio/best'
)

# Player-client fallback chain (mid-2026 verified bot-resistance order).
_DEFAULT_PLAYER_CLIENTS = ("default", "tv+tv_embedded", "web_safari")


def _player_client_chain():
    """Return player-client attempts, optionally overridden by the environment."""
    raw = (os.environ.get("YTDLP_PLAYER_CLIENTS") or "").strip()
    if raw:
        chain = [a.strip() for a in raw.split(",") if a.strip()]
        if chain:
            return chain
    return list(_DEFAULT_PLAYER_CLIENTS)


def _extractor_args_for(attempt: str):
    """Map an attempt spec to yt-dlp extractor_args, or None for defaults."""
    if not attempt or attempt.lower() == "default":
        return None
    clients = [c.strip() for c in attempt.split("+") if c.strip()]
    return {"youtube": {"player_client": clients}}


def classify_download_error(msg: str) -> str:
    """Classify a yt-dlp error as ``retry`` or ``fatal``."""
    m = (msg or "").lower()
    fatal_signals = (
        "sign in to confirm you're not a bot",
        "sign in to confirm youre not a bot",
        "confirm your age",
        "private video",
        "this video is private",
        "video has been removed",
        "removed by the user",
        "account associated with this video has been terminated",
        "video is no longer available",
        "video unavailable",
        "not available in your country",
        "not available in your location",
        "blocked it in your country",
        "geo-restrict",
        "geo restrict",
        "geoblock",
        "geo-block",
        "geo block",
    )
    if any(s in m for s in fatal_signals):
        return "fatal"
    retry_signals = (
        "http error 403",
        "403 forbidden",
        "403:",
        "requested format is not available",
        "requested format not available",
        "no formats found",
        "no video formats",
        "empty formats",
    )
    if any(s in m for s in retry_signals):
        return "retry"
    return "fatal"


SOURCE_INFO_FILENAME = "source_info.json"


def _write_source_info(output_dir, info):
    """Persist source-channel metadata as a best-effort sidecar."""
    try:
        from clippyme.domain.banner import suggest_banner

        channel_url = info.get("channel_url") or info.get("uploader_url")
        webpage_url = info.get("webpage_url") or info.get("original_url")
        uploader_id = info.get("uploader_id") or info.get("channel_id")
        banner = suggest_banner(channel_url or webpage_url or "", channel_hint=uploader_id)
        data = {
            "uploader_id": uploader_id,
            "channel_url": channel_url,
            "webpage_url": webpage_url,
            "banner": banner,
        }
        tmp = os.path.join(output_dir, SOURCE_INFO_FILENAME + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, os.path.join(output_dir, SOURCE_INFO_FILENAME))
    except Exception as exc:  # pragma: no cover - telemetry only, never fatal
        print(f"   ⚠️  source_info capture skipped: {exc}")


def download_youtube_video(url, output_dir=".", cookies_file_path=None):
    """Download a supported remote source with yt-dlp.

    Returns the downloaded path and sanitized title. Both metadata extraction
    and the actual download use the same player-client attempt.
    """
    url = validate_supported_source_url(url)
    _reject_rebound_internal(url)
    print(f"🔍 Debug: yt-dlp version: {yt_dlp.version.__version__}")
    print("📥 Downloading remote video...")
    step_start_time = time.time()

    cookies_path = _resolve_cookies_path(cookies_file_path)
    if cookies_path:
        print(f"🍪 Using cookies file: {cookies_path}")
    else:
        print("⚠️ No cookies file found.")

    # Verbose mode can leak paths, request URLs and headers into job logs, so it
    # stays opt-in. TLS verification stays on unless explicitly overridden.
    ydl_verbose = os.environ.get('YTDLP_VERBOSE') == '1'
    common_ydl_opts = {
        'quiet': not ydl_verbose,
        'verbose': ydl_verbose,
        'no_warnings': False,
        'cookiefile': cookies_path if cookies_path else None,
        'socket_timeout': 30,
        'retries': 10,
        'fragment_retries': 10,
        'nocheckcertificate': os.environ.get('YTDLP_NOCHECKCERT') == '1',
        'throttledratelimit': int(
            (os.environ.get('YTDLP_THROTTLED_RATE') or '').strip() or 100 * 1024
        ),
        'cachedir': False,
        'remote_components': ['ejs:github'],
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
        },
    }

    chain = _player_client_chain()
    last_error = RuntimeError("download attempt chain was empty")
    for i, attempt in enumerate(chain, 1):
        extractor_args = _extractor_args_for(attempt)
        attempt_opts = {**common_ydl_opts}
        if extractor_args:
            attempt_opts['extractor_args'] = extractor_args
        print(f"🔁 Download attempt {i}/{len(chain)} (player_client: {attempt})")
        try:
            with yt_dlp.YoutubeDL(attempt_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', 'remote_video')
                sanitized_title = sanitize_filename(video_title)
                _write_source_info(output_dir, info)

            output_template = os.path.join(output_dir, f'{sanitized_title}.%(ext)s')
            expected_file = os.path.join(output_dir, f'{sanitized_title}.mp4')
            if os.path.exists(expected_file):
                os.remove(expected_file)
                print("🗑️  Removed existing file to re-download with H.264 codec")

            ydl_opts = {
                **attempt_opts,
                'format': _FORMAT_LADDER,
                'outtmpl': output_template,
                'merge_output_format': 'mp4',
                'overwrites': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            downloaded_file = os.path.join(output_dir, f'{sanitized_title}.mp4')
            if not os.path.exists(downloaded_file):
                for filename in os.listdir(output_dir):
                    if filename.startswith(sanitized_title) and filename.endswith('.mp4'):
                        downloaded_file = os.path.join(output_dir, filename)
                        break
            if not os.path.isfile(downloaded_file):
                raise FileNotFoundError("yt-dlp completed without producing an MP4 file")

            step_end_time = time.time()
            print(
                f"✅ Video downloaded in {step_end_time - step_start_time:.2f}s: "
                f"{downloaded_file}"
            )
            return downloaded_file, sanitized_title
        except Exception as exc:
            last_error = exc
            kind = classify_download_error(str(exc))
            if kind == "retry" and i < len(chain):
                print(
                    f"⚠️ Attempt {i} failed (retryable: {exc}); "
                    "trying next player_client in 5s..."
                )
                time.sleep(5)
                continue
            break

    print("🚨 SOURCE DOWNLOAD ERROR 🚨", file=sys.stderr)
    error_msg = f"""

❌ ================================================================= ❌
❌ FATAL ERROR: SOURCE DOWNLOAD FAILED
❌ ================================================================= ❌

The remote platform refused or could not complete the download.

Suggested workaround:
1. Download the video manually to your computer.
2. Use the 'Upload Video' tab in this app to process it.

Technical Details: {last_error}
    """
    print(error_msg, file=sys.stdout)
    print(error_msg, file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    time.sleep(0.5)
    raise last_error
