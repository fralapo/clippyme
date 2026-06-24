"""YouTube download + filename/cookies helpers.

Extracted from ``pipeline.main`` as part of the decomposition. Depends only on
``yt_dlp`` + stdlib (no cv2/torch/mediapipe), so it imports and is testable on
the host. The bot-detection-resistant yt-dlp options and the cookies-resolution
precedence are preserved verbatim from the original ``main``.
"""
import ipaddress
import os
import re
import socket
import sys
import time
from urllib.parse import urlparse

import yt_dlp


def _reject_rebound_internal(url: str) -> None:
    """Re-resolve the URL host at download time and refuse if it now points
    only at internal/loopback ranges (defeats DNS-rebinding past the API-layer
    SSRF check). Best-effort: resolution failures are left to yt-dlp."""
    try:
        host = urlparse(url).hostname
        if not host:
            return
        try:
            ip_obj = ipaddress.ip_address(host)
            addrs = [ip_obj]
        except ValueError:
            _prev_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(5)
            try:
                infos = socket.getaddrinfo(host, None)
            finally:
                socket.setdefaulttimeout(_prev_timeout)
            addrs = []
            for info in infos:
                try:
                    addrs.append(ipaddress.ip_address(info[4][0]))
                except ValueError:
                    continue
        if any(
            a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_unspecified
            for a in addrs
        ):
            # Reject if ANY resolved address is internal: a split-horizon /
            # round-robin host that returns one public + one loopback address
            # would otherwise pass an all()-check, then yt-dlp could connect to
            # the internal one (SSRF via DNS).
            raise ValueError(f"refusing download: {host} resolves to an internal address")
    except ValueError:
        raise
    except Exception:
        # resolution hiccup — don't block legit downloads; yt-dlp will handle it
        return


def sanitize_filename(filename):
    """Remove invalid characters from filename."""
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = filename.replace(' ', '_')
    # Strip leading dashes/dots so the name can never be mistaken for a CLI
    # flag by a downstream tool that takes it as a positional argument, and so
    # it can't become a hidden dotfile. Fall back to a safe default if nothing
    # is left.
    filename = filename.lstrip('-.')
    return filename[:100] or 'video'


def _resolve_cookies_path(explicit: str | None) -> str | None:
    """Resolve the cookies.txt path used by yt-dlp.

    Precedence:
      1. Explicit path passed on the CLI / by the caller.
      2. Repo-root ``data/cookies.txt`` (the path the dashboard writes to).
      3. ``YOUTUBE_COOKIES`` env var → materialized into ``data/cookies_env.txt``.
      4. None (no cookies).

    The repo-root resolution uses the current working directory, which
    matches how the FastAPI backend and the Docker container launch the
    pipeline (both run from the repo root). This replaces the pre-refactor
    ``os.path.dirname(__file__)`` logic that silently pointed at
    ``src/clippyme/pipeline/data/`` after the src-layout migration.
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
        # Cookies are session credentials — write 0o600 so they're not
        # world-readable under the default umask (matches data/cookies.txt).
        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(env_cookies)
        return os.path.abspath(env_path)
    return None


def download_youtube_video(url, output_dir=".", cookies_file_path=None):
    """
    Downloads a YouTube video using yt-dlp.
    Returns the path to the downloaded video and the video title.
    """
    _reject_rebound_internal(url)
    print(f"🔍 Debug: yt-dlp version: {yt_dlp.version.__version__}")
    print("📥 Downloading video from YouTube...")
    step_start_time = time.time()

    cookies_path = _resolve_cookies_path(cookies_file_path)
    if cookies_path:
        print(f"🍪 Using cookies file: {cookies_path}")
    else:
        print("⚠️ No cookies file found.")

    # Common yt-dlp options to work around YouTube bot detection.
    # Avoid the OAuth/PO-token checks that block server IPs.
    # yt-dlp verbose mode prints the resolved cookies path, request URLs, and
    # HTTP headers — all of which end up in the job's log buffer that
    # /api/status returns to any client holding the job_id. Default it OFF so
    # those internals don't leak; opt back in with YTDLP_VERBOSE=1 for debugging
    # YouTube bot-detection issues.
    _ydl_verbose = os.environ.get('YTDLP_VERBOSE') == '1'
    _COMMON_YDL_OPTS = {
        'quiet': not _ydl_verbose,
        'verbose': _ydl_verbose,
        'no_warnings': False,
        'cookiefile': cookies_path if cookies_path else None,
        'socket_timeout': 30,
        'retries': 10,
        'fragment_retries': 10,
        # SSL verification stays ON (security) — previously disabled. If a
        # legitimate cert chain issue resurfaces in a sandbox, set the
        # YTDLP_NOCHECKCERT=1 env var to opt out temporarily.
        'nocheckcertificate': os.environ.get('YTDLP_NOCHECKCERT') == '1',
        # Detect YouTube's per-fragment throttling and re-fetch the slow
        # segment. Threshold is bytes/sec — 100 KB/s catches the 16-23h
        # evening throttle window without tripping on legit slow networks.
        'throttledratelimit': int((os.environ.get('YTDLP_THROTTLED_RATE') or '').strip() or 100 * 1024),
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

    with yt_dlp.YoutubeDL(_COMMON_YDL_OPTS) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            video_title = info.get('title', 'youtube_video')
            sanitized_title = sanitize_filename(video_title)
        except Exception as e:
            # Force print to stderr/stdout immediately so it's captured before crash.
            print("🚨 YOUTUBE DOWNLOAD ERROR 🚨", file=sys.stderr)

            error_msg = f"""

❌ ================================================================= ❌
❌ FATAL ERROR: YOUTUBE DOWNLOAD FAILED
❌ ================================================================= ❌

REASON: YouTube has blocked the download request (Error 429/Unavailable).
        This is likely a temporary IP ban on this server.

👇 SOLUTION FOR USER 👇
---------------------------------------------------------------------
1. Download the video manually to your computer.
2. Use the 'Upload Video' tab in this app to process it.
---------------------------------------------------------------------

Technical Details: {str(e)}
            """
            # Print to both streams to ensure capture
            print(error_msg, file=sys.stdout)
            print(error_msg, file=sys.stderr)

            # Force flush
            sys.stdout.flush()
            sys.stderr.flush()

            # Wait a split second to allow buffer to drain before raising
            time.sleep(0.5)

            raise e

    output_template = os.path.join(output_dir, f'{sanitized_title}.%(ext)s')
    expected_file = os.path.join(output_dir, f'{sanitized_title}.mp4')
    if os.path.exists(expected_file):
        os.remove(expected_file)
        print(f"🗑️  Removed existing file to re-download with H.264 codec")

    ydl_opts = {
        **_COMMON_YDL_OPTS,
        'format': 'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[vcodec^=avc1]+bestaudio/best[ext=mp4]/best',
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'overwrites': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    downloaded_file = os.path.join(output_dir, f'{sanitized_title}.mp4')

    if not os.path.exists(downloaded_file):
        for f in os.listdir(output_dir):
            if f.startswith(sanitized_title) and f.endswith('.mp4'):
                downloaded_file = os.path.join(output_dir, f)
                break

    step_end_time = time.time()
    print(f"✅ Video downloaded in {step_end_time - step_start_time:.2f}s: {downloaded_file}")

    return downloaded_file, sanitized_title
