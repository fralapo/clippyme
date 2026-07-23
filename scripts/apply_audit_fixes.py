"""Apply surgical audit fixes to large files without rewriting unrelated code."""
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"expected block not found in {path}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1))


replace_once(
    "src/clippyme/api/schemas.py",
    "\n\nclass LiveMonitorStartRequest(BaseModel):\n",
    "\n\nclass LiveMonitorPublishingRequest(BaseModel):\n"
    "    # Strict prevents strings such as 'false' from being coerced to True.\n"
    "    enabled: bool = Field(strict=True)\n\n\n"
    "class LiveMonitorStartRequest(BaseModel):\n",
)

replace_once(
    "src/clippyme/api/app.py",
    "    LiveMonitorStartRequest,\n    ProcessRequest,",
    "    LiveMonitorPublishingRequest,\n    LiveMonitorStartRequest,\n    ProcessRequest,",
)

replace_once(
    "src/clippyme/api/app.py",
    '''@app.post("/api/live-monitor/{monitor_id}/publishing")
async def live_monitor_set_publishing(monitor_id: str, request: Request):
    """Pause/resume auto-publishing for a running monitor (body:
    ``{"enabled": bool}``). While paused, finished clips accumulate and are
    drained through the normal publish path on resume."""
    require_trusted_config_request(request)
    enforce_rate_limit(request, "livemonitor", capacity=10, refill_per_sec=10 / 60)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed JSON body")
    enabled = bool(body.get("enabled")) if isinstance(body, dict) else False
    return {"monitor": live_monitor.set_publishing(monitor_id, enabled)}
''',
    '''@app.post("/api/live-monitor/{monitor_id}/publishing")
async def live_monitor_set_publishing(
    monitor_id: str, req: LiveMonitorPublishingRequest, request: Request
):
    """Pause/resume auto-publishing with a strict boolean request body."""
    require_trusted_config_request(request)
    enforce_rate_limit(request, "livemonitor", capacity=10, refill_per_sec=10 / 60)
    return {"monitor": live_monitor.set_publishing(monitor_id, req.enabled)}
''',
)

replace_once(
    "src/clippyme/domain/live_monitor.py",
    '        "max_clips": max(1, min(50, int(config.get("max_clips", 5) or 5))),',
    '        "max_clips": _clamp_int(config.get("max_clips"), 5, 1, 50),',
)

replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''        # ponytail: missed windows live only in-process — a restart mid-session
        # loses any pending backfill. Persist self._missed_windows if that ever
        # needs to survive a crash.
        self._missed_windows: list = []
''',
    '''        # Pending backfill is durable: a crash must not silently discard
        # footage that was already identified as missing.
        self._missed_windows: list[tuple[int, int]] = []
        self._backfill_baseline_ready: bool = False
''',
)

replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''            "covered_elapsed": int(self._covered_elapsed),
            "covered_stream_start": self._covered_stream_start,
            "state": self.state,
''',
    '''            "covered_elapsed": int(self._covered_elapsed),
            "covered_stream_start": self._covered_stream_start,
            "missed_windows": [list(w) for w in self._missed_windows],
            "vod_baseline_ids": sorted(self._vod_baseline_ids),
            "backfill_baseline_ready": self._backfill_baseline_ready,
            "state": self.state,
''',
)

replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''        self._covered_elapsed = int(snap.get("covered_elapsed") or 0)
        self._covered_stream_start = snap.get("covered_stream_start") or None
        self.resume_on_start = bool(snap.get("resume_on_start", False))
''',
    '''        self._covered_elapsed = int(snap.get("covered_elapsed") or 0)
        self._covered_stream_start = snap.get("covered_stream_start") or None
        restored_windows = []
        for window in snap.get("missed_windows") or []:
            if (isinstance(window, (list, tuple)) and len(window) == 2
                    and all(isinstance(v, (int, float)) for v in window)):
                start, end = int(window[0]), int(window[1])
                if end > start >= 0:
                    restored_windows.append((start, end))
        self._missed_windows = sorted(set(restored_windows))
        self.backfill_pending = len(self._missed_windows)
        self._vod_baseline_ids = set(snap.get("vod_baseline_ids") or [])
        self._backfill_baseline_ready = bool(
            snap.get("backfill_baseline_ready", False))
        self.resume_on_start = bool(snap.get("resume_on_start", False))
''',
)

replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''            if self.publishing_enabled and self._pending_publish:
                self._track_task(asyncio.create_task(self._drain_pending()))
''',
    '''            if self.publishing_enabled and self._pending_publish:
                self._track_task(asyncio.create_task(self._drain_pending()))
            if self._missed_windows:
                self._track_task(asyncio.create_task(self._resume_backfill()))
''',
)

replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''    async def _schedule_backfill(self, started_at) -> None:
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
        if self.cfg.get("catchup") == "live_only":
            # No historical recovery — coverage starts at "now" (current
            # stream elapsed), never before this monitor session started.
            if self._covered_stream_start != started_iso:
                self._covered_elapsed = 0
            self._covered_stream_start = started_iso
            self._covered_elapsed = max(self._covered_elapsed, int(elapsed))
            self._persist()
            return
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
''',
    '''    async def _resume_backfill(self) -> None:
        """Resume durable missed windows after a process restart."""
        if not self._missed_windows or self.cfg.get("catchup") == "live_only":
            return
        try:
            live, _, _ = await asyncio.to_thread(self._strategy.get_live_state)
        except Exception:
            logger.warning("LiveMonitor %s: backfill resume state check failed",
                           self.id, exc_info=True)
            return
        if self.platform == "kick" and not live:
            await self._recover_kick_backfill()

    async def _schedule_backfill(self, started_at) -> None:
        """Compute missed windows and arrange crash-safe recovery."""
        if started_at is None:
            return
        started_iso = started_at.isoformat()
        same_stream = self._covered_stream_start == started_iso
        carried = list(self._missed_windows) if same_stream else []
        if not same_stream:
            self._missed_windows = []
            self._vod_baseline_ids = set()
            self._backfill_baseline_ready = False
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        if self.cfg.get("catchup") == "live_only":
            self._missed_windows = []
            self.backfill_pending = 0
            if not same_stream:
                self._covered_elapsed = 0
            self._covered_stream_start = started_iso
            self._covered_elapsed = max(self._covered_elapsed, int(elapsed))
            self._persist()
            return
        start = effective_backfill_start(
            self.cfg["prelive_skip_seconds"], self._covered_elapsed,
            self._covered_stream_start, started_iso)
        newly_missed = backfill_windows(elapsed, start, self.cfg["segment_seconds"])
        windows = sorted(set(carried + newly_missed))
        if not same_stream:
            self._covered_elapsed = 0
        self._covered_stream_start = started_iso
        self._covered_elapsed = max(self._covered_elapsed, int(elapsed))
        self._missed_windows = windows
        self.backfill_pending = len(windows)
        self._persist()
        if not windows:
            return
        if self.platform == "twitch":
            self._track_task(asyncio.create_task(
                self._backfill_from_vod(list(windows))))
        elif self.platform == "kick" and not self._backfill_baseline_ready:
            try:
                baseline = await asyncio.to_thread(self._strategy.fetch_vods)
                self._vod_baseline_ids = {v["id"] for v in baseline}
                self._backfill_baseline_ready = True
                self._persist()
            except Exception:
                logger.warning("LiveMonitor %s: kick backfill baseline failed — "
                               "recovery remains pending", self.id, exc_info=True)
''',
)

replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''        except Exception:
            logger.exception("LiveMonitor %s: live VOD lookup failed", self.id)
            self.backfill_pending = 0
            return
        if not vod_url:
            logger.warning("LiveMonitor %s: backfill unavailable (no in-progress "
                           "VOD — past broadcasts disabled?)", self.id)
            self.backfill_pending = 0
            return
''',
    '''        except Exception:
            logger.exception("LiveMonitor %s: live VOD lookup failed", self.id)
            self.backfill_pending = len(self._missed_windows)
            self._persist()
            return
        if not vod_url:
            logger.warning("LiveMonitor %s: backfill unavailable (no in-progress "
                           "VOD — past broadcasts disabled?)", self.id)
            self.backfill_pending = len(self._missed_windows)
            self._persist()
            return
''',
)

replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''        for t1, t2 in windows:
            if self._stop.is_set():
                break
''',
    '''        for t1, t2 in list(windows):
            if self._stop.is_set():
                break
''',
)

replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''            self.backfill_pending = max(0, self.backfill_pending - 1)
            self._persist()
''',
    '''            try:
                self._missed_windows.remove((int(t1), int(t2)))
            except ValueError:
                pass
            self.backfill_pending = len(self._missed_windows)
            self._persist()
''',
)

replace_once(
    "tests/api/test_request_schema_contracts.py",
    "from clippyme.api.schemas import BatchRequest, LiveMonitorStartRequest, ProcessRequest\n",
    "from clippyme.api.schemas import (\n"
    "    BatchRequest, LiveMonitorPublishingRequest, LiveMonitorStartRequest, ProcessRequest,\n"
    ")\n",
)

with Path("tests/api/test_request_schema_contracts.py").open("a") as file:
    text = Path("tests/api/test_request_schema_contracts.py").read_text()
    marker = "def test_live_monitor_publishing_requires_a_strict_boolean():"
    if marker not in text:
        file.write(
            "\n\ndef test_live_monitor_publishing_requires_a_strict_boolean():\n"
            "    assert LiveMonitorPublishingRequest(enabled=False).enabled is False\n"
            "    with pytest.raises(ValidationError):\n"
            "        LiveMonitorPublishingRequest(enabled=\"false\")\n"
        )

with Path("tests/domain/test_live_monitor.py").open("a") as file:
    text = Path("tests/domain/test_live_monitor.py").read_text()
    marker = "def test_monitor_snapshot_restores_pending_backfill():"
    if marker not in text:
        file.write(
            "\n\ndef test_validate_config_malformed_max_clips_uses_default():\n"
            "    cfg = validate_monitor_config(_base_cfg(max_clips=\"not-an-int\"))\n"
            "    assert cfg[\"max_clips\"] == 5\n\n\n"
            "def test_monitor_snapshot_restores_pending_backfill(tmp_path):\n"
            "    import json\n"
            "    monitor = LiveMonitorRegistry.__new__(LiveMonitorRegistry)\n"
            "    from clippyme.domain.live_monitor import LiveMonitor\n"
            "    original = LiveMonitor(id=\"kick:chan\", jobs={}, job_queue=None, "
            "output_dir=str(tmp_path))\n"
            "    original._missed_windows = [(1800, 3600), (3600, 5400)]\n"
            "    original._vod_baseline_ids = {\"old-vod\"}\n"
            "    original._backfill_baseline_ready = True\n"
            "    snap = json.loads(json.dumps(original.snapshot()))\n"
            "    restored = LiveMonitor(id=\"kick:chan\", jobs={}, job_queue=None, "
            "output_dir=str(tmp_path))\n"
            "    restored.restore(snap)\n"
            "    assert restored._missed_windows == [(1800, 3600), (3600, 5400)]\n"
            "    assert restored.backfill_pending == 2\n"
            "    assert restored._vod_baseline_ids == {\"old-vod\"}\n"
            "    assert restored._backfill_baseline_ready is True\n"
        )
