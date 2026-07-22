"""Multi-platform, multi-channel content monitor.

Watches one or more creator channels across **kick / twitch / youtube** in one of
two modes:

- ``live`` (kick + twitch): poll until the channel goes live, skip the prelive
  window, then repeatedly capture fixed-length segments of the stream, submit
  each as a normal ClippyMe pipeline job (local-file, no download) and
  auto-publish every produced clip.
- ``vod`` (all three; for youtube it means "new long-form uploads"): poll a feed
  for new items, submit each item's URL as a normal pipeline job, and
  auto-publish the clips.

Every monitor is one long-running asyncio task. Multiple monitors run
concurrently, keyed by ``f"{platform}:{channel}"`` in a :class:`LiveMonitorRegistry`.
Publish spacing is GLOBAL: all monitors share one ``picked_slots`` list and one
publish lock, so the >=min_gap spacing holds across every clip from every monitor.

Per-platform detection/capture/vod I/O is isolated in small strategy objects
(``KickStrategy`` / ``TwitchStrategy`` / ``YoutubeStrategy``) whose network calls
are synchronous and wrapped in ``asyncio.to_thread`` by the loop — the pure
parsers they delegate to live in ``clippyme.integrations`` and are host-tested.

Shared mutable app state (jobs dict, queue, journal hook) is injected — this
module never imports ``api.app`` (no circular import).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from clippyme.domain.errors import ConflictError, NotFoundError, ValidationError
from clippyme.domain.job_results import MAX_INSTRUCTIONS_LEN
from clippyme.integrations.social_publisher import SmartScheduler

logger = logging.getLogger("clippyme")

_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")           # kick / twitch login
_YT_HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]{1,64}$")
_YT_UC_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,40}$")
_PLATFORMS = ("kick", "twitch", "youtube")
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "stopped"}
# A segment shorter than this (stream ended mid-capture) is only worth
# processing if it still holds enough content — matches the spec's 5-minute floor.
MIN_PROCESS_SECONDS = 300
STATE_FILENAME = "live_monitor.json"
# Zernio rate-limits the API-call burst (each publish = upload-URL + PUT +
# POST /posts), NOT the scheduled slots. Space consecutive publishes and
# back off + retry on 429 instead of dropping the clip.
PUBLISH_SPACING_SECONDS = 30
PUBLISH_429_RETRIES = 3
PUBLISH_429_BACKOFF_SECONDS = 90
# Zernio also enforces a per-account posts/day cap counted on the SCHEDULED
# day ("Daily limit reached ..."). Rolling start_date forward finds the next
# day with a free slot; these rolls are free (no sleep) and capped separately.
PUBLISH_MAX_DAY_ROLLS = 7


# ---------------------------------------------------------------------------
# Pure helpers (host-testable, no I/O)
# ---------------------------------------------------------------------------


def should_process_segment(duration: float, min_seconds: float = MIN_PROCESS_SECONDS) -> bool:
    """True when a captured segment is long enough to bother processing."""
    return duration is not None and duration >= min_seconds


def remaining_prelive(prelive_skip_seconds: int, started_at, now) -> int:
    """Seconds still to skip in the prelive window, anchored to the STREAM's
    actual start time rather than whenever the monitor happened to start
    polling. If the stream is already older than the window, returns 0 (skip
    is bypassed and capture starts immediately). Falls back to the full
    window when ``started_at`` is unknown (None)."""
    prelive_skip_seconds = max(0, int(prelive_skip_seconds))
    if started_at is None:
        return prelive_skip_seconds
    elapsed = (now - started_at).total_seconds()
    return max(0, int(prelive_skip_seconds - elapsed))


def render_template(template: str, clip: dict) -> str:
    """Fill ``{title}`` / ``{hook}`` placeholders from a clip dict.

    Unknown placeholders (or a malformed template) fall back to the raw string
    so a bad template can never crash the publish path.
    """
    if not template:
        return ""
    try:
        return template.format(
            title=clip.get("title", "") or "",
            hook=clip.get("viral_hook_text", "") or "",
        )
    except (KeyError, IndexError, ValueError):
        return template


def build_monitor_compose(platform: str, channel: str, clip: dict, override=None) -> dict:
    """Compose recipe a monitor burns before auto-publishing one clip.

    Default layout for a letterboxed (reframe 'disabled') monitor clip:
      - hook  → top black bar (position 'top', full-clip since reframe disabled),
      - banner → attribution pill attached under the video band (mode auto-
        selected to 'attach' by the compose layer for disabled clips),
      - subtitles → below the banner, left-aligned ('bottom' + align 'left').

    ``override`` (the start request's ``compose`` object) shallow-merges over the
    defaults: ``{toggles?, hook_params?, subtitle_params?, banner?}``. Pure /
    host-testable — no I/O. Returns kwargs for ``compose_layers``.
    """
    from clippyme.domain.banner import monitor_banner_params

    ov = override or {}
    banner = monitor_banner_params(platform, channel, ov.get("banner"))
    hook_text = str(clip.get("viral_hook_text") or clip.get("title") or "").strip()
    hook_params = {"text": hook_text, "position": "top", **(ov.get("hook_params") or {})}
    subtitle_params = {"position": "bottom", "align": "left", **(ov.get("subtitle_params") or {})}
    toggles = {
        "hook": bool(hook_params.get("text")),
        "subtitles": True,
        "banner": bool(banner),
        **(ov.get("toggles") or {}),
    }
    return {
        "toggles": toggles,
        "hook_params": hook_params,
        "subtitle_params": subtitle_params,
        "banner_params": banner or {},
    }


@dataclass
class SharedGapScheduler(SmartScheduler):
    """SmartScheduler that also avoids slots already picked this run.

    ``publish_clip`` feeds ``find_slot`` only the occupied list from Zernio's
    persisted posts for that single call, so back-to-back publishes wouldn't
    otherwise see each other. Merging ``picked_slots`` enforces the minimum gap
    across every clip scheduled. The registry injects ONE shared ``picked_slots``
    list into every monitor's scheduler so the gap is GLOBAL across monitors.
    """
    picked_slots: list = field(default_factory=list)

    def find_slot(self, day, occupied, now=None):
        slot = super().find_slot(day, list(occupied) + self.picked_slots, now=now)
        self.picked_slots.append(slot)
        return slot


def _validate_channel(platform: str, raw) -> str:
    """Per-platform channel validation. Returns the canonical channel string."""
    ch = str(raw or "").strip()
    if not ch:
        raise ValidationError("channel is required")
    if platform in ("kick", "twitch"):
        ch = ch.lower()
        if len(ch) > 64 or not _SLUG_RE.match(ch):
            raise ValidationError(f"invalid {platform} channel (use a-z, 0-9, '_' or '-')")
        return ch
    # youtube: @handle, UC id, or a youtube.com URL. It flows through yt_dlp
    # resolution / the SSRF-guarded URL submit path, so we only reject the
    # obviously-hostile (whitespace / control chars / overlong).
    if len(ch) > 256 or any(c.isspace() for c in ch):
        raise ValidationError("invalid youtube channel (@handle, UC id, or channel URL)")
    if not (_YT_HANDLE_RE.match(ch) or _YT_UC_RE.match(ch)
            or ch.lower().startswith(("http://", "https://", "youtube.com", "www.youtube.com"))):
        raise ValidationError("youtube channel must be an @handle, UC… id, or channel URL")
    return ch


def validate_monitor_config(config: dict, default_timezone: str = "Europe/Rome") -> dict:
    """Coerce + bound a raw start payload into the monitor's config dict.

    Raises ``ValidationError`` on a bad platform/mode/channel. Numeric knobs are
    clamped to sane ranges (defence in depth — the API schema also bounds them).
    """
    platform = str(config.get("platform") or "kick").strip().lower()
    if platform not in _PLATFORMS:
        raise ValidationError(f"platform must be one of {list(_PLATFORMS)}")
    mode = str(config.get("mode") or "live").strip().lower()
    if mode not in ("live", "vod"):
        raise ValidationError("mode must be 'live' or 'vod'")
    if platform == "youtube" and mode == "live":
        raise ValidationError("live mode not supported for youtube (use mode='vod')")

    channel = _validate_channel(platform, config.get("channel") or config.get("slug"))

    platforms = config.get("platforms") or []
    if not isinstance(platforms, list) or not platforms:
        raise ValidationError("at least one platform target is required")
    for entry in platforms:
        if not isinstance(entry, dict) or not entry.get("platform") or not entry.get("accountId"):
            raise ValidationError("each platform target needs 'platform' and 'accountId'")

    def _clamp_int(value, default, lo, hi):
        try:
            n = int(value)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, n))

    # vod feeds lag minutes→hours; live wants a fast go-live poll.
    default_poll = 600 if mode == "vod" else 60
    return {
        "platform": platform,
        "mode": mode,
        "channel": channel,
        "slug": channel,  # back-compat alias
        "platforms": platforms,
        "segment_seconds": _clamp_int(config.get("segment_seconds"), 1800, 60, 3600),
        "prelive_skip_seconds": _clamp_int(config.get("prelive_skip_seconds"), 1800, 0, 7200),
        "min_gap_seconds": _clamp_int(config.get("min_gap_seconds"), 900, 0, 86400),
        "poll_interval": _clamp_int(config.get("poll_interval"), default_poll, 30, 3600),
        "loop": bool(config.get("loop", False)),
        # Optional AI instructions steering Gemini viral-clip selection —
        # mirrors ProcessRequest.instructions (same MAX_INSTRUCTIONS_LEN cap,
        # again downstream by build_main_cmd/gemini_request).
        "instructions": str(config.get("instructions") or "").strip()[:MAX_INSTRUCTIONS_LEN],
        "caption_template": str(config.get("caption_template") or "")[:2200],
        "title_template": str(config.get("title_template") or "")[:500],
        "timezone": str(config.get("timezone") or default_timezone or "Europe/Rome")[:64],
        # Banner + compose overrides for the auto-publish flow (None = defaults).
        # Kept as-is here; build_monitor_compose / monitor_banner_params own the
        # semantics. The API schema already bounds them.
        "banner": config.get("banner") if isinstance(config.get("banner"), dict) else None,
        "compose": config.get("compose") if isinstance(config.get("compose"), dict) else None,
    }


# Fields a running monitor's config may be safely mutated to at runtime.
# platform/mode/channel/slug/loop/publisher_mode are identity/lifecycle knobs
# — changing them mid-run would need a restart, not a config patch.
_UPDATABLE_CONFIG_FIELDS = (
    "instructions", "caption_template", "title_template", "min_gap_seconds",
    "segment_seconds", "prelive_skip_seconds", "platforms", "banner", "compose",
    "poll_interval",
)

# The full set of cfg keys worth persisting/restoring (mirrors
# validate_monitor_config's return shape). No secrets ever live in cfg.
_SNAPSHOT_CONFIG_FIELDS = (
    "platform", "mode", "channel", "slug", "platforms", "segment_seconds",
    "prelive_skip_seconds", "min_gap_seconds", "poll_interval", "loop",
    "instructions", "caption_template", "title_template", "timezone",
    "banner", "compose",
)


def validate_monitor_partial_update(partial: dict, current_cfg: dict) -> dict:
    """Validate a runtime config-update payload against a running monitor's
    current config. Only ``_UPDATABLE_CONFIG_FIELDS`` may be changed; anything
    else (platform/mode/channel/slug/loop/publisher_mode/...) is rejected.
    Returns the fully re-validated merged config (same shape as
    ``validate_monitor_config``'s return)."""
    if not isinstance(partial, dict) or not partial:
        raise ValidationError("no updatable fields provided")
    bad = set(partial) - set(_UPDATABLE_CONFIG_FIELDS)
    if bad:
        raise ValidationError(f"cannot update field(s): {sorted(bad)}")
    merged = dict(current_cfg)
    merged.update(partial)
    return validate_monitor_config(merged, default_timezone=current_cfg.get("timezone"))


def _hhmmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _safe_remove(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def backfill_windows(elapsed_seconds, prelive_skip_seconds, segment_seconds,
                     min_seconds: int = MIN_PROCESS_SECONDS) -> list:
    """Chunk the missed span [prelive_skip, elapsed] into (start, end) second
    pairs of length ``segment_seconds``. Drops a trailing chunk shorter than
    ``min_seconds`` (matching the live-capture floor). Returns [] when there is
    nothing to recover. Clamps hostile inputs (negative elapsed, zero/negative
    segment)."""
    try:
        elapsed = int(elapsed_seconds)
        start = max(0, int(prelive_skip_seconds))
        seg = int(segment_seconds)
    except (TypeError, ValueError):
        return []
    if seg <= 0 or elapsed <= start:
        return []
    windows = []
    t = start
    while t < elapsed:
        end = min(t + seg, elapsed)
        if end - t >= min_seconds:  # short trailing chunk dropped
            windows.append((t, end))
        t = end
    return windows


def effective_backfill_start(prelive_skip_seconds: int, covered_elapsed: int,
                             covered_stream_start, started_at_iso) -> int:
    """Where backfill windows should begin, stream-relative.

    Prior coverage only counts when it belongs to the SAME stream session
    (matching stream start time) — a new stream starts from the plain
    prelive skip."""
    start = max(0, int(prelive_skip_seconds))
    if covered_stream_start and started_at_iso and covered_stream_start == started_at_iso:
        start = max(start, int(covered_elapsed or 0))
    return start


def build_backfill_cmd(vod_url: str, start_s: int, end_s: int, out_path: str) -> list:
    """yt-dlp argv to download an exact [start, end] range of a VOD."""
    return [sys.executable, "-m", "yt_dlp", vod_url,
            "--download-sections", f"*{_hhmmss(start_s)}-{_hhmmss(end_s)}",
            "-o", out_path, "--force-overwrites", "-q"]


# ---------------------------------------------------------------------------
# Per-platform strategies (network calls are sync → wrapped in to_thread)
# ---------------------------------------------------------------------------


class KickStrategy:
    def __init__(self, channel: str):
        from clippyme.integrations.kick_client import KickClient
        self.channel = channel
        self._client = KickClient()

    def get_live_state(self):
        from clippyme.integrations.kick_client import is_live, playback_url, stream_started_at
        ch = self._client.get_channel(self.channel)
        return is_live(ch), playback_url(ch), stream_started_at(ch)

    def capture_args(self, seg_path: str, seconds: int, url):
        if url:
            return ["ffmpeg", "-hide_banner", "-loglevel", "warning",
                    "-i", url, "-c", "copy", "-t", str(seconds), "-y", seg_path]
        if shutil.which("streamlink"):
            return ["streamlink", "--hls-duration", _hhmmss(seconds),
                    f"https://kick.com/{self.channel}", "best", "-o", seg_path]
        return None

    def fetch_vods(self):
        from clippyme.integrations.kick_client import extract_vods
        vods = extract_vods(self._client.get_channel(self.channel))
        if not vods:
            vods = extract_vods(self._client.get_channel_videos(self.channel))
        return vods


class TwitchStrategy:
    def __init__(self, channel: str, client):
        self.channel = channel
        self._client = client
        self._user_id = None

    def get_live_state(self):
        from clippyme.integrations.twitch_client import stream_is_live, stream_started_at
        streams = self._client.get_stream(self.channel)
        return stream_is_live(streams), None, stream_started_at(streams)

    def capture_args(self, seg_path: str, seconds: int, url):
        if not shutil.which("streamlink"):
            return None
        return ["streamlink", "--twitch-disable-ads", "--hls-duration", _hhmmss(seconds),
                f"twitch.tv/{self.channel}", "best", "-o", seg_path]

    def fetch_vods(self):
        from clippyme.integrations.twitch_client import parse_vods
        if self._user_id is None:
            self._user_id = self._client.get_user_id(self.channel)
        if not self._user_id:
            return []
        return parse_vods(self._client.get_videos(self._user_id))

    def live_vod_url(self):
        """URL of the in-progress archive VOD for the current live stream, or
        None (offline, no user id, or 'store past broadcasts' disabled)."""
        from clippyme.integrations.twitch_client import find_live_vod
        data = (self._client.get_stream(self.channel) or {}).get("data") or []
        stream_id = data[0].get("id") if data else None
        if not stream_id:
            return None
        if self._user_id is None:
            self._user_id = self._client.get_user_id(self.channel)
        if not self._user_id:
            return None
        return find_live_vod(self._client.get_videos(self._user_id), stream_id)


class YoutubeStrategy:
    def __init__(self, channel: str):
        self._input = channel
        self._channel_id = None

    def resolve(self):
        from clippyme.integrations.youtube_feed import resolve_channel_id
        self._channel_id = resolve_channel_id(self._input)

    def fetch_vods(self):
        from clippyme.integrations.youtube_feed import (
            fetch_feed, feed_url, parse_feed, uploads_playlist_id,
        )
        pid = uploads_playlist_id(self._channel_id)
        return parse_feed(fetch_feed(feed_url(pid)))


# ---------------------------------------------------------------------------
# LiveMonitor — one asyncio task per (platform, channel)
# ---------------------------------------------------------------------------


class LiveMonitor:
    """One long-running asyncio task driving detect→process→publish for a channel."""

    def __init__(self, *, id: str, jobs: dict, job_queue, output_dir: str,
                 upload_dir: str = "uploads", on_job_change=None,
                 picked_slots: list | None = None,
                 publish_lock: asyncio.Lock | None = None,
                 on_state_change=None):
        self.id = id
        self._jobs = jobs
        self._job_queue = job_queue
        self._output_dir = output_dir
        self._upload_dir = upload_dir
        self._on_job_change = on_job_change
        self._picked_slots = picked_slots if picked_slots is not None else []
        self._publish_lock = publish_lock or asyncio.Lock()
        self._on_state_change = on_state_change

        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._publish_tasks: set[asyncio.Task] = set()
        self._ffmpeg_proc = None
        self._backfill_proc = None
        self._strategy = None
        self._scheduler: SharedGapScheduler | None = None
        self._published: set[str] = set()
        self._seen_ids: set[str] = set()
        self._gemini_key = None
        self._zernio_key = None

        self.cfg: dict = {}
        self.platform = id.split(":", 1)[0] if ":" in id else ""
        self.mode = "live"
        self.state = "idle"
        # Persisted across a snapshot/restore round-trip. True for any monitor
        # that runs indefinitely (loop=True live monitors, all vod pollers) —
        # a durable process restart should bring it back up automatically.
        self.resume_on_start: bool = False
        self.last_error: str | None = None
        self.current_job_id: str | None = None
        self.segments_captured = 0   # live: segments; vod: items processed
        self.clips_published = 0
        self.backfill_pending = 0    # missed-window recoveries still to process
        # ponytail: missed windows live only in-process — a restart mid-session
        # loses any pending backfill. Persist self._missed_windows if that ever
        # needs to survive a crash.
        self._missed_windows: list = []
        # Stream-relative coverage (persisted): how far into the CURRENT stream
        # this monitor has already captured or queued for backfill. Keyed to the
        # stream's own start time so a restart mid-marathon doesn't recompute
        # backfill windows over hours it already handled (duplicate clips), while
        # a genuinely new stream starts from scratch.
        self._covered_elapsed: int = 0
        self._covered_stream_start: str | None = None
        self._vod_baseline_ids: set = set()

    # -- public API ------------------------------------------------------

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "mode": self.mode,
            "running": self.is_running(),
            "state": self.state,
            "channel": self.cfg.get("channel"),
            "slug": self.cfg.get("channel"),  # back-compat alias
            "loop": self.cfg.get("loop", False),
            "segments_captured": self.segments_captured,
            "clips_published": self.clips_published,
            "current_job_id": self.current_job_id,
            "backfill_pending": self.backfill_pending,
            "last_error": self.last_error,
            "resume_on_start": self.resume_on_start,
        }

    def snapshot(self) -> dict:
        """Persistable per-monitor state (never secrets / Popen / logs)."""
        return {
            "platform": self.platform,
            "mode": self.mode,
            "channel": self.cfg.get("channel"),
            # Full cfg (no secrets — validate_monitor_config never puts any
            # in there) so a restart/auto-resume picks up runtime updates too.
            "config": {k: self.cfg.get(k) for k in _SNAPSHOT_CONFIG_FIELDS} if self.cfg else None,
            "seen_ids": sorted(self._seen_ids),
            "published": sorted(self._published),
            "segments_captured": self.segments_captured,
            "clips_published": self.clips_published,
            "covered_elapsed": int(self._covered_elapsed),
            "covered_stream_start": self._covered_stream_start,
            "state": self.state,
            "resume_on_start": self.resume_on_start,
            "updated_at": datetime.now().isoformat(),
        }

    def restore(self, snap: dict) -> None:
        """Rehydrate the double-publish / already-seen guards from disk."""
        if not snap:
            return
        self._seen_ids = set(snap.get("seen_ids") or [])
        self._published = set(snap.get("published") or [])
        self.segments_captured = int(snap.get("segments_captured") or 0)
        self.clips_published = int(snap.get("clips_published") or 0)
        self._covered_elapsed = int(snap.get("covered_elapsed") or 0)
        self._covered_stream_start = snap.get("covered_stream_start") or None
        self.resume_on_start = bool(snap.get("resume_on_start", False))

    def start(self, cfg: dict) -> dict:
        """Resolve secrets, build the platform strategy, and launch the task.

        ``cfg`` is already validated by :func:`validate_monitor_config`.
        """
        if self.is_running():
            raise ConflictError(f"monitor already running: {self.id}")

        from clippyme.storage.config_store import load_persistent_config, load_zernio_config
        pc = load_persistent_config() or {}
        self._gemini_key = pc.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not self._gemini_key:
            raise ValidationError("Gemini API key not configured")
        self._zernio_key = load_zernio_config().get("api_key")
        if not self._zernio_key:
            raise ValidationError("Zernio API key not configured")

        self.cfg = cfg
        self.platform = cfg["platform"]
        self.mode = cfg["mode"]
        # A loop=True live monitor restarts itself after every stream, and a
        # vod poller runs forever — both are durable across a process
        # restart, so mark them for registry.auto_resume() on next startup.
        self.resume_on_start = bool(cfg.get("loop")) or self.mode == "vod"
        self._strategy = self._make_strategy(cfg, pc)
        self._scheduler = SharedGapScheduler(
            min_gap_seconds=cfg["min_gap_seconds"], picked_slots=self._picked_slots)
        self._stop = asyncio.Event()
        self.last_error = None
        self.current_job_id = None

        coro = self._run()
        try:
            self._task = asyncio.create_task(coro)
        except RuntimeError:
            # No running event loop (e.g. a synchronous caller) — record the
            # start state without scheduling the background task.
            coro.close()
            logger.warning(
                "LiveMonitor %s: no running event loop, task not scheduled", self.id)
            self._task = None
        logger.info("LiveMonitor started: %s (mode=%s)", self.id, self.mode)
        return self.status()

    def update_config(self, partial: dict) -> dict:
        """Apply a validated partial config update while running.

        Swaps ``self.cfg`` in one atomic assignment — every per-segment /
        per-publish read site reads ``self.cfg[...]`` at use time, so the new
        values apply to the NEXT segment/publish only, never retroactively.
        """
        new_cfg = validate_monitor_partial_update(partial, self.cfg)
        self.cfg = new_cfg
        self._persist()
        return {k: new_cfg.get(k) for k in _SNAPSHOT_CONFIG_FIELDS}

    def _make_strategy(self, cfg: dict, pc: dict):
        platform, channel = cfg["platform"], cfg["channel"]
        if platform == "kick":
            return KickStrategy(channel)
        if platform == "twitch":
            cid = pc.get("TWITCH_CLIENT_ID") or os.environ.get("TWITCH_CLIENT_ID")
            secret = pc.get("TWITCH_CLIENT_SECRET") or os.environ.get("TWITCH_CLIENT_SECRET")
            if not cid or not secret:
                raise ValidationError(
                    "Twitch monitoring requires TWITCH_CLIENT_ID and "
                    "TWITCH_CLIENT_SECRET (set them in Settings or the environment)")
            from clippyme.integrations.twitch_client import TwitchClient
            return TwitchStrategy(channel, TwitchClient(cid, secret))
        if platform == "youtube":
            return YoutubeStrategy(channel)
        raise ValidationError(f"unsupported platform: {platform}")

    async def stop(self) -> dict:
        """Signal the loop, kill any in-flight capture, and await teardown."""
        self._stop.set()
        for proc in (self._ffmpeg_proc, self._backfill_proc):
            if proc is not None and proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self.state = "idle"
        self._persist()
        logger.info("LiveMonitor stopped: %s", self.id)
        return self.status()

    # -- main loop -------------------------------------------------------

    async def _run(self) -> None:
        try:
            if self.mode == "vod":
                await self._run_vod()
            else:
                await self._run_live()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("LiveMonitor run loop crashed: %s", self.id)
            self.last_error = "monitor loop crashed"
        finally:
            # Let any in-flight publish tasks finish so scheduled posts aren't lost.
            pending = [t for t in self._publish_tasks if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self.state = "idle"
            self.current_job_id = None
            self._persist()

    # -- live mode -------------------------------------------------------

    async def _run_live(self) -> None:
        self.state = "waiting_live"
        while not self._stop.is_set():
            live, _, started_at = await asyncio.to_thread(self._strategy.get_live_state)
            if live:
                await self._marathon(started_at)
                if not self.cfg["loop"]:
                    break
            self.state = "waiting_live"
            await self._interruptible_sleep(self._jittered_poll())

    async def _marathon(self, started_at=None) -> None:
        """Handle one live session: prelive skip, then the capture loop.

        ``started_at`` is the stream's own start time (from the
        ``get_live_state`` call that discovered it live), used to skip only
        the REMAINDER of the prelive window if the stream was already
        running before this monitor noticed it.
        """
        from clippyme.pipeline.media_probe import probe_duration

        # Everything between (stream_start + prelive_skip) and now was missed —
        # schedule its recovery before we start capturing forward.
        await self._schedule_backfill(started_at)

        self.state = "prelive"
        if not await self._skip_prelive(started_at):
            return  # stream ended (or stop requested) during prelive

        self.state = "capturing"
        while not self._stop.is_set():
            live, url, _ = await asyncio.to_thread(self._strategy.get_live_state)
            if not live:
                break
            seg_path = await self._capture_segment(url)
            if seg_path is None:
                break
            duration = await asyncio.to_thread(probe_duration, seg_path)
            early_exit = duration < self.cfg["segment_seconds"] - 30
            if not should_process_segment(duration):
                _safe_remove(seg_path)
                break
            self.segments_captured += 1
            job_id = await self._submit_segment_job(seg_path)
            self.current_job_id = job_id
            task = asyncio.create_task(self._await_and_publish(job_id, seg_path))
            self._publish_tasks.add(task)
            task.add_done_callback(self._publish_tasks.discard)
            if started_at is not None:
                self._covered_elapsed = max(
                    self._covered_elapsed,
                    int((datetime.now(timezone.utc) - started_at).total_seconds()))
            self._persist()
            if early_exit:  # capture stopped before a full segment → stream ended
                break
        self.state = "draining"
        # Kick has no in-progress VOD — recover the missed window now that the
        # session is over and the replay VOD can appear.
        if self.platform == "kick" and self._missed_windows:
            self._track_task(asyncio.create_task(self._recover_kick_backfill()))

    async def _skip_prelive(self, started_at=None) -> bool:
        """Sleep out the (remainder of the) prelive window, aborting if the
        stream ends. Skips the first N minutes of the STREAM, not N minutes
        from monitor start — if the stream was already older than the window
        when detected, ``remaining`` collapses to 0 and capture starts
        immediately. Returns True to proceed to capture, False if we should
        stop this session."""
        remaining = remaining_prelive(
            self.cfg["prelive_skip_seconds"], started_at, datetime.now(timezone.utc))
        if remaining < self.cfg["prelive_skip_seconds"]:
            logger.info(
                "LiveMonitor %s: stream already live (started_at=%s) — "
                "prelive skip shortened to %ss", self.id, started_at, remaining)
        step = min(self.cfg["poll_interval"], 60)
        while remaining > 0 and not self._stop.is_set():
            await self._interruptible_sleep(min(step, remaining))
            remaining -= step
            live, _, _ = await asyncio.to_thread(self._strategy.get_live_state)
            if not live:
                return False
        return not self._stop.is_set()

    async def _capture_segment(self, url: str | None) -> str | None:
        """Capture up to ``segment_seconds`` of the live stream to a file."""
        os.makedirs(self._upload_dir, exist_ok=True)
        seg_path = os.path.join(
            self._upload_dir, f"live_{self.platform}_{self.cfg['channel']}_{int(time.time())}.mp4")
        args = self._strategy.capture_args(seg_path, self.cfg["segment_seconds"], url)
        if args is None:
            logger.warning("LiveMonitor %s: no capture method (streamlink not installed?)", self.id)
            self.last_error = "no capture tool available (streamlink not installed?)"
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except FileNotFoundError:
            logger.error("LiveMonitor %s: capture tool not found (%s)", self.id, args[0])
            self.last_error = f"{args[0]} not installed"
            return None
        self._ffmpeg_proc = proc
        try:
            await proc.wait()
        finally:
            self._ffmpeg_proc = None

        if not os.path.isfile(seg_path) or os.path.getsize(seg_path) == 0:
            _safe_remove(seg_path)
            return None
        return seg_path

    # -- backfill (recover the window missed before capture started) ------

    def _track_task(self, task: asyncio.Task) -> None:
        """Register a task so ``_run``'s finally drains it before teardown."""
        self._publish_tasks.add(task)
        task.add_done_callback(self._publish_tasks.discard)

    async def _schedule_backfill(self, started_at) -> None:
        """Compute the missed window(s) and arrange their recovery.

        Twitch: an in-progress archive VOD exists → backfill in parallel now.
        Kick: no live VOD → stash the windows + a pre-session VOD-id baseline and
        recover after the session ends, from the newly-published replay."""
        self._missed_windows = []
        self._vod_baseline_ids = set()
        if started_at is None:
            return
        started_iso = started_at.isoformat()
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        start = effective_backfill_start(
            self.cfg["prelive_skip_seconds"], self._covered_elapsed,
            self._covered_stream_start, started_iso)
        windows = backfill_windows(elapsed, start, self.cfg["segment_seconds"])
        # Everything up to now is either captured (prior session), queued as a
        # window, or deliberately skipped — record it so a restart doesn't redo it.
        if self._covered_stream_start != started_iso:
            self._covered_elapsed = 0
        self._covered_stream_start = started_iso
        self._covered_elapsed = max(self._covered_elapsed, int(elapsed))
        self._persist()
        if not windows:
            return
        if self.platform == "twitch":
            self.backfill_pending = len(windows)
            self._track_task(asyncio.create_task(self._backfill_from_vod(windows)))
        elif self.platform == "kick":
            try:
                baseline = await asyncio.to_thread(self._strategy.fetch_vods)
                self._vod_baseline_ids = {v["id"] for v in baseline}
            except Exception:
                logger.warning("LiveMonitor %s: kick backfill baseline failed — "
                               "skipping recovery", self.id, exc_info=True)
                return
            self.backfill_pending = len(windows)
            self._missed_windows = windows

    async def _backfill_from_vod(self, windows) -> None:
        """Twitch: resolve the in-progress VOD url and process each missed window."""
        if not hasattr(self._strategy, "live_vod_url"):
            return
        try:
            vod_url = await asyncio.to_thread(self._strategy.live_vod_url)
        except Exception:
            logger.exception("LiveMonitor %s: live VOD lookup failed", self.id)
            self.backfill_pending = 0
            return
        if not vod_url:
            logger.warning("LiveMonitor %s: backfill unavailable (no in-progress "
                           "VOD — past broadcasts disabled?)", self.id)
            self.backfill_pending = 0
            return
        await self._backfill_windows(vod_url, windows)

    async def _recover_kick_backfill(self) -> None:
        """Kick: poll for the replay VOD that appears after the session ends
        (an id not in the pre-session baseline), then process the missed windows."""
        windows = self._missed_windows
        for _ in range(30):  # ponytail: fixed cap; replay usually lands in minutes
            if self._stop.is_set():
                return
            try:
                vods = await asyncio.to_thread(self._strategy.fetch_vods)
            except Exception:
                logger.warning("LiveMonitor %s: kick backfill VOD poll failed",
                               self.id, exc_info=True)
                vods = []
            for v in vods or []:
                if v["id"] not in self._vod_baseline_ids:
                    await self._backfill_windows(v["url"], windows)
                    return
            await self._interruptible_sleep(self.cfg["poll_interval"])
        logger.warning("LiveMonitor %s: kick backfill gave up (no replay VOD)", self.id)

    async def _backfill_windows(self, vod_url: str, windows) -> None:
        """Sequentially download + submit + publish each missed window (kept
        sequential so forward live capture keeps priority)."""
        from clippyme.pipeline.media_probe import probe_duration

        for t1, t2 in windows:
            if self._stop.is_set():
                break
            seg_path = await self._download_vod_range(vod_url, t1, t2)
            if seg_path is not None:
                duration = await asyncio.to_thread(probe_duration, seg_path)
                if should_process_segment(duration):
                    self.segments_captured += 1
                    job_id = await self._submit_segment_job(seg_path)
                    self.current_job_id = job_id
                    await self._await_and_publish(job_id, seg_path)
                else:
                    _safe_remove(seg_path)
            self.backfill_pending = max(0, self.backfill_pending - 1)
            self._persist()

    async def _download_vod_range(self, vod_url: str, t1: int, t2: int) -> str | None:
        """Download the [t1, t2] range of a VOD via yt-dlp. None on missing/empty."""
        os.makedirs(self._upload_dir, exist_ok=True)
        seg_path = os.path.join(
            self._upload_dir,
            f"backfill_{self.platform}_{self.cfg['channel']}_{t1}_{t2}_{int(time.time())}.mp4")
        args = build_backfill_cmd(vod_url, t1, t2, seg_path)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except FileNotFoundError:
            logger.error("LiveMonitor %s: yt-dlp not found for backfill", self.id)
            return None
        self._backfill_proc = proc
        try:
            await proc.wait()
        finally:
            self._backfill_proc = None
        if not os.path.isfile(seg_path) or os.path.getsize(seg_path) == 0:
            _safe_remove(seg_path)
            return None
        return seg_path

    # -- vod mode --------------------------------------------------------

    async def _run_vod(self) -> None:
        """Poll a feed; process each item that appeared AFTER activation."""
        if self.platform == "youtube":
            try:
                await asyncio.to_thread(self._strategy.resolve)
            except Exception as exc:
                logger.exception("LiveMonitor %s: channel resolve failed", self.id)
                self.last_error = f"channel resolve failed: {exc}"
                return

        self.state = "watching"
        baseline_done = bool(self._seen_ids)  # resumed monitor keeps its baseline
        while not self._stop.is_set():
            try:
                items = await asyncio.to_thread(self._strategy.fetch_vods)
            except Exception as exc:
                logger.exception("LiveMonitor %s: vod fetch failed", self.id)
                self.last_error = f"vod fetch failed: {exc}"
                items = None

            if items and not baseline_done:
                # First successful poll: record existing items so only NEW ones
                # (published after activation) get processed.
                self._seen_ids = {it["id"] for it in items}
                baseline_done = True
                self._persist()
            elif items:
                for it in reversed(items):  # oldest-new first
                    if self._stop.is_set():
                        break
                    if it["id"] in self._seen_ids:
                        continue
                    self._seen_ids.add(it["id"])
                    await self._process_vod_item(it)

            await self._interruptible_sleep(self._jittered_poll())
        self.state = "idle"

    async def _process_vod_item(self, item: dict) -> None:
        self.segments_captured += 1
        job_id = await self._submit_url_job(item["url"])
        self.current_job_id = job_id
        self._persist()
        # vod jobs run one at a time (no overlapping live capture to keep up
        # with), so await then publish inline. A failed download (e.g. a
        # sub-only Twitch VOD 403) ends non-'completed' and just logs + moves on.
        await self._await_and_publish(job_id, None)

    # -- job submission --------------------------------------------------

    def _new_job_dir(self) -> tuple[str, str, dict]:
        job_id = str(uuid.uuid4())
        job_dir = os.path.join(self._output_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)
        env = os.environ.copy()
        env["GEMINI_API_KEY"] = self._gemini_key
        return job_id, job_dir, env

    async def _submit_segment_job(self, seg_path: str) -> str:
        from clippyme.domain.job_results import build_main_cmd
        from clippyme.domain.job_submission import submit_job

        job_id, job_dir, env = self._new_job_dir()
        # Letterbox (reframe disabled): the monitor recipe places a hook in the
        # top bar, the attribution banner attached under the video band, and
        # subtitles below it — all of which need the un-reframed 9:16 layout.
        cmd = build_main_cmd(input_path=os.path.abspath(seg_path), output_dir=job_dir,
                             reframe_mode="disabled", instructions=self.cfg.get("instructions") or None)
        await submit_job(
            jobs=self._jobs, job_queue=self._job_queue, job_id=job_id,
            cmd=cmd, env=env, job_output_dir=job_dir, on_change=self._on_job_change)
        logger.info("LiveMonitor %s submitted segment job %s", self.id, job_id)
        return job_id

    async def _submit_url_job(self, url: str) -> str:
        from clippyme.domain.job_results import build_main_cmd
        from clippyme.domain.job_submission import submit_job

        job_id, job_dir, env = self._new_job_dir()
        cookies_path = os.path.join("data", "cookies.txt")
        cmd = build_main_cmd(url=url, output_dir=job_dir, cookies_path=cookies_path,
                             reframe_mode="disabled", instructions=self.cfg.get("instructions") or None)
        await submit_job(
            jobs=self._jobs, job_queue=self._job_queue, job_id=job_id,
            cmd=cmd, env=env, job_output_dir=job_dir, on_change=self._on_job_change)
        logger.info("LiveMonitor %s submitted url job %s (%s)", self.id, job_id, url)
        return job_id

    # -- publish ---------------------------------------------------------

    async def _await_and_publish(self, job_id: str, seg_path: str | None) -> None:
        """Wait for a job to finish, publish its clips, then drop any segment."""
        try:
            while not self._stop.is_set():
                await asyncio.sleep(5)
                status = self._jobs.get(job_id, {}).get("status")
                if status is None or status in _TERMINAL_STATUSES:
                    break
            status = self._jobs.get(job_id, {}).get("status")
            if status not in ("completed", "stopped"):
                logger.warning("LiveMonitor %s: job %s ended '%s' — no clips published",
                               self.id, job_id, status)
                return
            clips = (self._jobs.get(job_id, {}).get("result") or {}).get("clips") or []
            for i, clip in enumerate(clips):
                if i:
                    await asyncio.sleep(PUBLISH_SPACING_SECONDS)
                await self._publish_one(job_id, clip)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LiveMonitor %s: publish flow failed for job %s", self.id, job_id)
        finally:
            _safe_remove(seg_path)

    async def _compose_for_publish(self, job_id: str, clip: dict, base_path: str) -> str:
        """Burn the monitor recipe (hook top → banner attached → subtitles
        bottom-left) onto the clip and return the composed path. Falls back to
        ``base_path`` (raw clip) on any resolution/compose failure so a publish
        is never lost to a compose hiccup."""
        from clippyme.domain.clip_resolve import resolve_clip
        from clippyme.domain.compose import compose_layers

        idx = clip.get("original_index")
        if idx is None:
            return base_path
        try:
            resolved = await asyncio.to_thread(
                resolve_clip, job_id, idx, self._output_dir, require_file=True)
            recipe = build_monitor_compose(
                self.platform, self.cfg["channel"], clip, self.cfg.get("compose"))
            composed = await compose_layers(
                base_clip=resolved.clip_path, job_dir=resolved.job_dir, clip_index=idx,
                metadata=resolved.metadata, clip_info=resolved.clip_info, **recipe)
            return os.path.join(resolved.job_dir, composed)
        except Exception:
            logger.exception("LiveMonitor %s: compose-before-publish failed for %s/%s",
                             self.id, job_id, idx)
            return base_path

    async def _publish_one(self, job_id: str, clip: dict) -> None:
        from clippyme.integrations.social_publisher import ZernioError, publish_clip

        video_url = clip.get("video_url") or ""
        clip_path = os.path.join(self._output_dir, job_id, os.path.basename(video_url))
        if not os.path.isfile(clip_path):
            logger.warning("LiveMonitor %s: clip file missing, skipping: %s", self.id, clip_path)
            return
        # Dedupe on the BASE clip path (stable), then compose the publish recipe.
        if clip_path in self._published:
            return
        upload_path = await self._compose_for_publish(job_id, clip, clip_path)

        title = render_template(self.cfg["title_template"], clip) or clip.get("title") or "Clip"
        caption = render_template(self.cfg["caption_template"], clip)
        # Serialise publishes GLOBALLY (shared lock) so the shared scheduler's
        # picked_slots list (mutated inside publish_clip's worker thread) stays
        # race-free across every monitor.
        # Held across the 429 backoff on purpose: while Zernio is rate-limiting
        # us, no other monitor should burn attempts against the same limit.
        async with self._publish_lock:
            attempt = 0
            day_rolls = 0
            start_date = None  # None → scheduler picks today/tomorrow
            while True:
                try:
                    await asyncio.to_thread(
                        publish_clip,
                        api_key=self._zernio_key,
                        clip_path=upload_path,
                        title=title[:100],
                        caption=caption,
                        platform_targets=self.cfg["platforms"],
                        schedule_mode="auto",
                        timezone=self.cfg["timezone"],
                        scheduler=self._scheduler,
                        start_date=start_date,
                    )
                    break
                except (ZernioError, ValueError) as exc:
                    body = getattr(exc, "body", None) or ""
                    is_429 = getattr(exc, "status_code", None) == 429
                    if is_429 and "Daily limit" in body and day_rolls < PUBLISH_MAX_DAY_ROLLS:
                        base = date.fromisoformat(start_date) if start_date else date.today()
                        start_date = (base + timedelta(days=1)).isoformat()
                        day_rolls += 1
                        logger.warning(
                            "LiveMonitor %s: Zernio daily limit for %s — rolling to %s",
                            self.id, clip_path, start_date)
                        continue
                    if is_429 and attempt < PUBLISH_429_RETRIES - 1:
                        attempt += 1
                        logger.warning(
                            "LiveMonitor %s: Zernio 429 for %s (body=%r) — retry %d/%d in %ds",
                            self.id, clip_path, body, attempt, PUBLISH_429_RETRIES - 1,
                            PUBLISH_429_BACKOFF_SECONDS)
                        await asyncio.sleep(PUBLISH_429_BACKOFF_SECONDS)
                        continue
                    logger.error("LiveMonitor %s: publish failed for %s: %s (body=%r)",
                                 self.id, clip_path, exc, body)
                    self.last_error = f"publish failed: {exc}"
                    return
        self._published.add(clip_path)
        self.clips_published += 1
        self._persist()

    # -- misc ------------------------------------------------------------

    def _jittered_poll(self) -> float:
        base = self.cfg["poll_interval"]
        return base + random.uniform(-min(15, base * 0.25), min(15, base * 0.25))

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep, but wake immediately if stop() is called."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=max(0.0, seconds))
        except asyncio.TimeoutError:
            pass

    def _persist(self) -> None:
        if self._on_state_change is not None:
            try:
                self._on_state_change()
            except Exception:
                logger.warning("LiveMonitor %s: state persist failed", self.id, exc_info=True)


# ---------------------------------------------------------------------------
# LiveMonitorRegistry — owns every monitor + the GLOBAL publish spacing store
# ---------------------------------------------------------------------------


class LiveMonitorRegistry:
    """Registry of concurrent monitors keyed by ``platform:channel``.

    Owns the one shared ``picked_slots`` list + publish lock (global spacing) and
    the single persisted state file (``data/live_monitor.json``).
    """

    def __init__(self, *, jobs: dict, job_queue, output_dir: str,
                 upload_dir: str = "uploads", on_job_change=None,
                 state_path: str = os.path.join("data", STATE_FILENAME)):
        self._jobs = jobs
        self._job_queue = job_queue
        self._output_dir = output_dir
        self._upload_dir = upload_dir
        self._on_job_change = on_job_change
        self._state_path = state_path

        self._monitors: dict[str, LiveMonitor] = {}
        self._picked_slots: list = []
        self._publish_lock = asyncio.Lock()
        self._snapshots: dict[str, dict] = {}  # restored, not-yet-started state
        self._load_state()

    # -- public API ------------------------------------------------------

    def start(self, config: dict) -> dict:
        from clippyme.storage.config_store import load_zernio_config
        cfg = validate_monitor_config(config, default_timezone=load_zernio_config().get("timezone"))
        mid = f"{cfg['platform']}:{cfg['channel']}"

        existing = self._monitors.get(mid)
        if existing is not None and existing.is_running():
            raise ConflictError(f"monitor already running: {mid}")

        mon = LiveMonitor(
            id=mid, jobs=self._jobs, job_queue=self._job_queue,
            output_dir=self._output_dir, upload_dir=self._upload_dir,
            on_job_change=self._on_job_change, picked_slots=self._picked_slots,
            publish_lock=self._publish_lock, on_state_change=self.persist)
        mon.restore(self._snapshots.get(mid) or {})
        self._monitors[mid] = mon
        try:
            status = mon.start(cfg)
        except Exception:
            self._monitors.pop(mid, None)
            raise
        self._snapshots.pop(mid, None)
        self.persist()
        return status

    async def stop(self, monitor_id: str | None = None) -> dict:
        if monitor_id:
            mon = self._monitors.get(monitor_id)
            if mon is None:
                raise NotFoundError(f"no such monitor: {monitor_id}")
            status = await mon.stop()
            self._retire(monitor_id, mon)
            self.persist()
            return status
        for mid, mon in list(self._monitors.items()):
            try:
                await mon.stop()
            except Exception:
                logger.exception("LiveMonitor %s failed to stop cleanly", mon.id)
            self._retire(mid, mon)
        self.persist()
        return {"monitors": [m.status() for m in self._monitors.values()]}

    def _retire(self, mid: str, mon, *, disable_resume: bool = True) -> None:
        """Drop a stopped monitor from the visible list.

        Its snapshot is kept in ``_snapshots`` (and thus on disk) so the
        seen-VOD / published guards survive a later restart of the same
        channel — only the status-list entry goes away.

        ``disable_resume`` clears ``resume_on_start`` on the retired snapshot
        for an explicit user/API stop (the monitor should stay down). A
        graceful process shutdown passes ``disable_resume=False`` so
        ``registry.auto_resume()`` brings it back on the next startup.
        """
        try:
            snap = mon.snapshot()
            if disable_resume:
                snap = dict(snap)
                snap["resume_on_start"] = False
            self._snapshots[mid] = snap
        except Exception:
            logger.warning("LiveMonitor %s: snapshot on retire failed", mid, exc_info=True)
        self._monitors.pop(mid, None)

    async def shutdown(self) -> None:
        """Graceful process shutdown: stop every monitor task WITHOUT
        disabling ``resume_on_start``, persisting the last coverage point
        before the process exits."""
        for mid, mon in list(self._monitors.items()):
            try:
                await mon.stop()
            except Exception:
                logger.exception("LiveMonitor %s failed to stop cleanly", mon.id)
            self._retire(mid, mon, disable_resume=False)
        self.persist()

    async def auto_resume(self) -> dict:
        """Restart every persisted snapshot with ``resume_on_start`` truthy.

        Credentials are always reloaded from ``config_store`` inside the
        normal ``LiveMonitor.start()`` path — never from the snapshot. A
        failure for one monitor is recorded (readable via ``status()``) and
        does not raise, so it can never fail FastAPI startup.
        """
        resumed: list[str] = []
        failed: list[dict] = []
        for mid, snap in list(self._snapshots.items()):
            if not snap.get("resume_on_start"):
                continue
            cfg = snap.get("config")
            if not isinstance(cfg, dict):
                continue
            mon = LiveMonitor(
                id=mid, jobs=self._jobs, job_queue=self._job_queue,
                output_dir=self._output_dir, upload_dir=self._upload_dir,
                on_job_change=self._on_job_change, picked_slots=self._picked_slots,
                publish_lock=self._publish_lock,
                on_state_change=self.persist)
            mon.restore(snap)
            try:
                mon.start(cfg)
            except Exception as exc:
                logger.exception("LiveMonitor %s: auto-resume failed", mid)
                mon.state = "auto_resume_failed"
                mon.last_error = str(exc)
                self._monitors[mid] = mon
                failed.append({"id": mid, "error": str(exc)})
                continue
            self._monitors[mid] = mon
            self._snapshots.pop(mid, None)
            resumed.append(mid)
        self.persist()
        return {"resumed": resumed, "failed": failed}

    def update_config(self, monitor_id: str, partial: dict) -> dict:
        """Apply a runtime config patch to a running monitor; persists the
        new state so it survives restart/auto-resume."""
        mon = self._monitors.get(monitor_id)
        if mon is None:
            raise NotFoundError(f"no such monitor: {monitor_id}")
        result = mon.update_config(partial)
        self.persist()
        return result

    def status(self, monitor_id: str | None = None) -> dict:
        if monitor_id:
            mon = self._monitors.get(monitor_id)
            if mon is None:
                raise NotFoundError(f"no such monitor: {monitor_id}")
            return mon.status()
        return {"monitors": [m.status() for m in self._monitors.values()]}

    # -- persistence (atomic) --------------------------------------------

    def persist(self) -> None:
        from clippyme.domain.job_artifacts import save_job_metadata
        snapshots = {mid: m.snapshot() for mid, m in self._monitors.items()}
        # Keep restored-but-not-started monitors in the file so their guards
        # survive a start of a *different* monitor.
        for mid, snap in self._snapshots.items():
            snapshots.setdefault(mid, snap)
        data = {
            "monitors": snapshots,
            "picked_slots": [d.isoformat() for d in self._picked_slots],
            "updated_at": datetime.now().isoformat(),
        }
        try:
            os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
            save_job_metadata(self._state_path, data)  # tmp + os.replace, 0o600
        except Exception:
            logger.warning("LiveMonitorRegistry: state persist failed", exc_info=True)

    def _load_state(self) -> None:
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        monitors = data.get("monitors")
        if not isinstance(monitors, dict):
            # Migrate the legacy single-Kick-monitor shape (top-level slug/published).
            monitors = {}
            if data.get("slug"):
                monitors[f"kick:{data['slug']}"] = {
                    "platform": "kick", "mode": "live", "channel": data["slug"],
                    "seen_ids": [], "published": data.get("published") or [],
                    "segments_captured": data.get("segments_captured") or 0,
                    "clips_published": data.get("clips_published") or 0,
                }
        self._snapshots = {k: v for k, v in monitors.items() if isinstance(v, dict)}
        for iso in data.get("picked_slots") or []:
            try:
                self._picked_slots.append(datetime.fromisoformat(iso))
            except (ValueError, TypeError):
                continue
