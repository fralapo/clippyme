"""Kick.com live-marathon monitor.

Polls a Kick channel until it goes live, skips the prelive window, then
repeatedly captures fixed-length segments of the live stream, submits each as a
normal ClippyMe pipeline job (local-file, no download), and auto-publishes every
produced clip to Zernio with a SHARED scheduler enforcing a minimum gap across
ALL clips the monitor publishes.

State machine (``self.state``):
    idle → waiting_live → prelive → capturing → (draining) → stopped/idle

Capture and processing overlap on purpose: ffmpeg captures the live edge in
real time (a 30-min segment takes ~30 min of wall-clock), so submitting the job
and immediately starting the next capture keeps the stream covered while the
previous segment's pipeline job runs in the background queue. Each job's clips
are published by a fire-and-forget task; publishes are serialised through one
lock so the shared scheduler's slot list stays race-free.

Shared mutable app state (jobs dict, queue, journal hook) is injected — this
module never imports ``api.app`` (no circular import). Everything else (job
submission, Zernio publish, config, media probe) is imported directly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from clippyme.domain.errors import ConflictError, ValidationError
from clippyme.integrations.social_publisher import SmartScheduler

logger = logging.getLogger("clippyme")

_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "stopped"}
# A segment shorter than this (stream ended mid-capture) is only worth
# processing if it still holds enough content — matches the spec's 5-minute floor.
MIN_PROCESS_SECONDS = 300
STATE_FILENAME = "live_monitor.json"


# ---------------------------------------------------------------------------
# Pure helpers (host-testable, no I/O)
# ---------------------------------------------------------------------------


def should_process_segment(duration: float, min_seconds: float = MIN_PROCESS_SECONDS) -> bool:
    """True when a captured segment is long enough to bother processing."""
    return duration is not None and duration >= min_seconds


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


@dataclass
class SharedGapScheduler(SmartScheduler):
    """SmartScheduler that also avoids slots the monitor already picked this run.

    ``publish_clip`` feeds ``find_slot`` only the occupied list from Zernio's
    persisted posts for that single call, so back-to-back monitor publishes
    wouldn't otherwise see each other. Merging ``picked_slots`` enforces the
    minimum gap across every clip the monitor schedules (the spec's shared
    ">=15-minute spacing across ALL clips").
    """
    picked_slots: list = field(default_factory=list)

    def find_slot(self, day, occupied, now=None):
        slot = super().find_slot(day, list(occupied) + self.picked_slots, now=now)
        self.picked_slots.append(slot)
        return slot


def validate_monitor_config(config: dict, default_timezone: str = "Europe/Rome") -> dict:
    """Coerce + bound a raw start payload into the monitor's config dict.

    Raises ``ValidationError`` on a bad slug or missing platform target. Numeric
    knobs are clamped to sane ranges (defence in depth — the API schema also
    bounds them).
    """
    slug = str(config.get("slug", "")).strip().lower()
    if not slug or len(slug) > 64 or not _SLUG_RE.match(slug):
        raise ValidationError("invalid channel slug (use a-z, 0-9, '_' or '-')")

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

    return {
        "slug": slug,
        "platforms": platforms,
        "segment_seconds": _clamp_int(config.get("segment_seconds"), 1800, 60, 3600),
        "prelive_skip_seconds": _clamp_int(config.get("prelive_skip_seconds"), 1800, 0, 7200),
        "min_gap_seconds": _clamp_int(config.get("min_gap_seconds"), 900, 0, 86400),
        "poll_interval": _clamp_int(config.get("poll_interval"), 60, 30, 600),
        "loop": bool(config.get("loop", False)),
        "caption_template": str(config.get("caption_template") or "")[:2200],
        "title_template": str(config.get("title_template") or "")[:500],
        "timezone": str(config.get("timezone") or default_timezone or "Europe/Rome")[:64],
    }


def _hhmmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _safe_remove(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# LiveMonitor
# ---------------------------------------------------------------------------


class LiveMonitor:
    """One long-running asyncio task driving the capture→process→publish loop."""

    def __init__(self, *, jobs: dict, job_queue, output_dir: str,
                 upload_dir: str = "uploads", on_job_change=None,
                 state_path: str = os.path.join("data", STATE_FILENAME)):
        self._jobs = jobs
        self._job_queue = job_queue
        self._output_dir = output_dir
        self._upload_dir = upload_dir
        self._on_job_change = on_job_change
        self._state_path = state_path

        from clippyme.integrations.kick_client import KickClient
        self._client = KickClient()

        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._publish_lock = asyncio.Lock()
        self._publish_tasks: set[asyncio.Task] = set()
        self._ffmpeg_proc = None
        self._scheduler: SharedGapScheduler | None = None
        self._published: set[str] = set()
        self._gemini_key = None
        self._zernio_key = None

        self.cfg: dict = {}
        self.state = "idle"
        self.last_error: str | None = None
        self.current_job_id: str | None = None
        self.segments_captured = 0
        self.clips_published = 0

    # -- public API ------------------------------------------------------

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "state": self.state,
            "slug": self.cfg.get("slug"),
            "loop": self.cfg.get("loop", False),
            "segments_captured": self.segments_captured,
            "clips_published": self.clips_published,
            "current_job_id": self.current_job_id,
            "last_error": self.last_error,
        }

    def start(self, config: dict) -> dict:
        """Validate config, resolve secrets, and launch the monitor task."""
        if self.is_running():
            raise ConflictError("Live monitor is already running")

        from clippyme.storage.config_store import load_persistent_config, load_zernio_config
        cfg = validate_monitor_config(config, default_timezone=load_zernio_config().get("timezone"))

        self._gemini_key = (load_persistent_config() or {}).get("GEMINI_API_KEY") \
            or os.environ.get("GEMINI_API_KEY")
        if not self._gemini_key:
            raise ValidationError("Gemini API key not configured")
        self._zernio_key = load_zernio_config().get("api_key")
        if not self._zernio_key:
            raise ValidationError("Zernio API key not configured")

        self.cfg = cfg
        self._scheduler = SharedGapScheduler(min_gap_seconds=cfg["min_gap_seconds"])
        self._published = set()
        self._stop = asyncio.Event()
        self.segments_captured = 0
        self.clips_published = 0
        self.current_job_id = None
        self.last_error = None
        self._load_state()  # restore published-guard + picked slots for same slug

        self._task = asyncio.create_task(self._run())
        logger.info("LiveMonitor started for channel %s", cfg["slug"])
        return self.status()

    async def stop(self) -> dict:
        """Signal the loop, kill any in-flight ffmpeg, and await teardown."""
        self._stop.set()
        proc = self._ffmpeg_proc
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
        logger.info("LiveMonitor stopped")
        return self.status()

    # -- main loop -------------------------------------------------------

    async def _run(self) -> None:
        try:
            self.state = "waiting_live"
            while not self._stop.is_set():
                channel = await asyncio.to_thread(self._client.get_channel, self.cfg["slug"])
                from clippyme.integrations.kick_client import is_live
                if is_live(channel):
                    await self._marathon()
                    if not self.cfg["loop"]:
                        break
                self.state = "waiting_live"
                await self._interruptible_sleep(self._jittered_poll())
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("LiveMonitor run loop crashed")
            self.last_error = "monitor loop crashed"
        finally:
            # Let any in-flight publish tasks finish so scheduled posts aren't lost.
            pending = [t for t in self._publish_tasks if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self.state = "idle"
            self.current_job_id = None
            self._persist()

    async def _marathon(self) -> None:
        """Handle one live session: prelive skip, then the capture loop."""
        from clippyme.integrations.kick_client import is_live, playback_url
        from clippyme.pipeline.media_probe import probe_duration

        self.state = "prelive"
        if not await self._skip_prelive():
            return  # stream ended (or stop requested) during prelive

        self.state = "capturing"
        while not self._stop.is_set():
            channel = await asyncio.to_thread(self._client.get_channel, self.cfg["slug"])
            if not is_live(channel):
                break
            seg_path = await self._capture_segment(playback_url(channel))
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
            self._persist()
            if early_exit:  # ffmpeg stopped before a full segment → stream ended
                break
        self.state = "draining"

    async def _skip_prelive(self) -> bool:
        """Sleep out the prelive window, aborting if the stream ends. Returns
        True to proceed to capture, False if we should stop this session."""
        from clippyme.integrations.kick_client import is_live
        remaining = self.cfg["prelive_skip_seconds"]
        step = min(self.cfg["poll_interval"], 60)
        while remaining > 0 and not self._stop.is_set():
            await self._interruptible_sleep(min(step, remaining))
            remaining -= step
            channel = await asyncio.to_thread(self._client.get_channel, self.cfg["slug"])
            if not is_live(channel):
                return False
        return not self._stop.is_set()

    # -- capture ---------------------------------------------------------

    async def _capture_segment(self, url: str | None) -> str | None:
        """Capture up to ``segment_seconds`` of the live stream to a file.

        Prefers ffmpeg on the HLS playback URL; falls back to streamlink (if
        installed) when no playback URL is available. Returns the path, or None
        if nothing could be captured.
        """
        import shutil
        os.makedirs(self._upload_dir, exist_ok=True)
        seg_path = os.path.join(
            self._upload_dir, f"live_{self.cfg['slug']}_{int(time.time())}.mp4")
        seconds = self.cfg["segment_seconds"]

        if url:
            args = ["ffmpeg", "-hide_banner", "-loglevel", "warning",
                    "-i", url, "-c", "copy", "-t", str(seconds), "-y", seg_path]
        elif shutil.which("streamlink"):
            args = ["streamlink", "--hls-duration", _hhmmss(seconds),
                    f"https://kick.com/{self.cfg['slug']}", "best", "-o", seg_path]
        else:
            logger.warning("LiveMonitor: no playback_url and streamlink not installed — skipping segment")
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except FileNotFoundError:
            logger.error("LiveMonitor: capture tool not found (%s)", args[0])
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

    # -- job submission --------------------------------------------------

    async def _submit_segment_job(self, seg_path: str) -> str:
        from clippyme.domain.job_results import build_main_cmd
        from clippyme.domain.job_submission import submit_job

        job_id = str(uuid.uuid4())
        job_dir = os.path.join(self._output_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)
        env = os.environ.copy()
        env["GEMINI_API_KEY"] = self._gemini_key
        cmd = build_main_cmd(input_path=os.path.abspath(seg_path), output_dir=job_dir)
        await submit_job(
            jobs=self._jobs, job_queue=self._job_queue, job_id=job_id,
            cmd=cmd, env=env, job_output_dir=job_dir, on_change=self._on_job_change)
        logger.info("LiveMonitor submitted segment job %s", job_id)
        return job_id

    # -- publish ---------------------------------------------------------

    async def _await_and_publish(self, job_id: str, seg_path: str) -> None:
        """Wait for a job to finish, publish its clips, then drop the segment."""
        try:
            while not self._stop.is_set():
                await asyncio.sleep(5)
                status = self._jobs.get(job_id, {}).get("status")
                if status is None or status in _TERMINAL_STATUSES:
                    break
            status = self._jobs.get(job_id, {}).get("status")
            if status not in ("completed", "stopped"):
                logger.warning("LiveMonitor: job %s ended '%s' — no clips published", job_id, status)
                return
            clips = (self._jobs.get(job_id, {}).get("result") or {}).get("clips") or []
            for clip in clips:
                await self._publish_one(job_id, clip)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LiveMonitor: publish flow failed for job %s", job_id)
        finally:
            _safe_remove(seg_path)

    async def _publish_one(self, job_id: str, clip: dict) -> None:
        from clippyme.integrations.social_publisher import publish_clip, ZernioError

        video_url = clip.get("video_url") or ""
        clip_path = os.path.join(self._output_dir, job_id, os.path.basename(video_url))
        if not os.path.isfile(clip_path):
            logger.warning("LiveMonitor: clip file missing, skipping: %s", clip_path)
            return
        if clip_path in self._published:
            return

        title = render_template(self.cfg["title_template"], clip) or clip.get("title") or "Clip"
        caption = render_template(self.cfg["caption_template"], clip)
        # Serialise publishes so the shared scheduler's picked_slots list (mutated
        # inside publish_clip's worker thread) stays race-free.
        async with self._publish_lock:
            try:
                await asyncio.to_thread(
                    publish_clip,
                    api_key=self._zernio_key,
                    clip_path=clip_path,
                    title=title[:100],
                    caption=caption,
                    platform_targets=self.cfg["platforms"],
                    schedule_mode="auto",
                    timezone=self.cfg["timezone"],
                    scheduler=self._scheduler,
                )
            except (ZernioError, ValueError) as exc:
                logger.error("LiveMonitor: publish failed for %s: %s", clip_path, exc)
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

    # -- persistence (atomic, restart double-publish guard) --------------

    def _persist(self) -> None:
        from clippyme.domain.job_artifacts import save_job_metadata
        picked = [d.isoformat() for d in (self._scheduler.picked_slots if self._scheduler else [])]
        data = {
            "slug": self.cfg.get("slug"),
            "state": self.state,
            "published": sorted(self._published),
            "picked_slots": picked,
            "segments_captured": self.segments_captured,
            "clips_published": self.clips_published,
            "updated_at": datetime.now().isoformat(),
        }
        try:
            os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
            save_job_metadata(self._state_path, data)  # tmp + os.replace, 0o600
        except Exception:
            logger.warning("LiveMonitor: state persist failed", exc_info=True)

    def _load_state(self) -> None:
        """Restore the published-guard + picked slots when resuming the SAME slug."""
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if data.get("slug") != self.cfg.get("slug"):
            return
        self._published = set(data.get("published") or [])
        if self._scheduler is not None:
            for iso in data.get("picked_slots") or []:
                try:
                    self._scheduler.picked_slots.append(datetime.fromisoformat(iso))
                except (ValueError, TypeError):
                    continue
