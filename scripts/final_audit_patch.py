"""One-shot patch used by CI to apply coordinated audit fixes safely."""
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected block not found in {path}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1))


# Strict stop payload: malformed JSON must never degrade into the destructive
# "stop every monitor" operation.
replace_once(
    "src/clippyme/api/schemas.py",
    "\n\nclass LiveMonitorPublishingRequest(BaseModel):\n",
    "\n\nclass LiveMonitorStopRequest(BaseModel):\n"
    "    monitor_id: Optional[str] = Field(\n"
    "        None, min_length=1, max_length=128, pattern=r\"^[A-Za-z0-9:_-]+$\"\n"
    "    )\n\n\n"
    "class LiveMonitorPublishingRequest(BaseModel):\n",
)
replace_once(
    "src/clippyme/api/app.py",
    "    LiveMonitorPublishingRequest,\n    LiveMonitorStartRequest,",
    "    LiveMonitorPublishingRequest,\n    LiveMonitorStartRequest,\n    LiveMonitorStopRequest,",
)
replace_once(
    "src/clippyme/api/app.py",
    '''@app.post("/api/live-monitor/stop")
async def live_monitor_stop(request: Request):
    """Stop one monitor (body ``{"monitor_id": "..."}``) or ALL monitors (no
    body). Lets in-flight publishes drain first."""
    require_trusted_config_request(request)
    monitor_id = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            monitor_id = body.get("monitor_id")
    except Exception:
        pass  # no/invalid body → stop all
    return await live_monitor.stop(monitor_id)
''',
    '''@app.post("/api/live-monitor/stop")
async def live_monitor_stop(
    request: Request, req: LiveMonitorStopRequest | None = None
):
    """Stop one monitor, or all monitors only when the body is truly absent."""
    require_trusted_config_request(request)
    return await live_monitor.stop(req.monitor_id if req else None)
''',
)

# Path-safe, stable monitor IDs. YouTube channels may be full URLs containing
# slashes; those cannot safely be embedded in FastAPI path parameters.
replace_once(
    "src/clippyme/domain/live_monitor.py",
    "import asyncio\nimport json\n",
    "import asyncio\nimport hashlib\nimport json\n",
)
replace_once(
    "src/clippyme/domain/live_monitor.py",
    "\ndef should_process_segment(duration: float, min_seconds: float = MIN_PROCESS_SECONDS) -> bool:\n",
    "\ndef monitor_id_for(platform: str, channel: str) -> str:\n"
    "    \"\"\"Return a stable path-safe ID without exposing URL-shaped channels.\"\"\"\n"
    "    platform = str(platform or \"\").strip().lower()\n"
    "    channel = str(channel or \"\").strip()\n"
    "    if platform != \"youtube\":\n"
    "        return f\"{platform}:{channel}\"\n"
    "    digest = hashlib.sha256(channel.encode(\"utf-8\")).hexdigest()[:20]\n"
    "    return f\"youtube:{digest}\"\n\n\n"
    "def should_process_segment(duration: float, min_seconds: float = MIN_PROCESS_SECONDS) -> bool:\n",
)
replace_once(
    "src/clippyme/domain/live_monitor.py",
    "        mid = f\"{cfg['platform']}:{cfg['channel']}\"\n",
    "        mid = monitor_id_for(cfg[\"platform\"], cfg[\"channel\"])\n",
)
replace_once(
    "src/clippyme/domain/live_monitor.py",
    "        self._snapshots = {k: v for k, v in monitors.items() if isinstance(v, dict)}\n",
    '''        normalized = {}
        for old_mid, snap in monitors.items():
            if not isinstance(snap, dict):
                continue
            cfg = snap.get("config") if isinstance(snap.get("config"), dict) else {}
            platform = cfg.get("platform") or snap.get("platform")
            channel = cfg.get("channel") or snap.get("channel")
            if platform and channel:
                normalized[monitor_id_for(platform, channel)] = snap
            else:
                normalized[old_mid] = snap
        self._snapshots = normalized
''',
)

# Failed downloads remain pending for retry. Kick recovery is unsafe without a
# pre-session VOD baseline because an arbitrary older replay could be selected.
replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''        if self.cfg.get("catchup") == "live_only":
            return  # ponytail: defence-in-depth — _schedule_backfill never calls us in this mode
        windows = self._missed_windows
''',
    '''        if self.cfg.get("catchup") == "live_only":
            return  # defence-in-depth — _schedule_backfill never calls us in this mode
        if not self._backfill_baseline_ready:
            logger.warning(
                "LiveMonitor %s: kick backfill remains pending because the "
                "pre-session VOD baseline is unavailable", self.id)
            self.backfill_pending = len(self._missed_windows)
            self._persist()
            return
        windows = list(self._missed_windows)
''',
)
replace_once(
    "src/clippyme/domain/live_monitor.py",
    '''        for t1, t2 in list(windows):
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
            try:
                self._missed_windows.remove((int(t1), int(t2)))
            except ValueError:
                pass
            self.backfill_pending = len(self._missed_windows)
            self._persist()
''',
    '''        for t1, t2 in list(windows):
            if self._stop.is_set():
                break
            completed = False
            seg_path = await self._download_vod_range(vod_url, t1, t2)
            if seg_path is not None:
                duration = await asyncio.to_thread(probe_duration, seg_path)
                if should_process_segment(duration):
                    self.segments_captured += 1
                    job_id = await self._submit_segment_job(seg_path)
                    self.current_job_id = job_id
                    await self._await_and_publish(job_id, seg_path)
                    completed = True
                else:
                    _safe_remove(seg_path)
                    completed = True
            if completed:
                try:
                    self._missed_windows.remove((int(t1), int(t2)))
                except ValueError:
                    pass
            self.backfill_pending = len(self._missed_windows)
            self._persist()
''',
)

# Encode IDs at the client boundary as defence in depth for any legacy state.
replace_once(
    "dashboard/src/redesign/realApi.js",
    "getApiUrl(`/api/live-monitor/${monitorId}/config`)",
    "getApiUrl(`/api/live-monitor/${encodeURIComponent(monitorId)}/config`)",
)
replace_once(
    "dashboard/src/redesign/realApi.js",
    "getApiUrl(`/api/live-monitor/${monitorId}/publishing`)",
    "getApiUrl(`/api/live-monitor/${encodeURIComponent(monitorId)}/publishing`)",
)

# Regression tests.
replace_once(
    "tests/api/test_request_schema_contracts.py",
    "    BatchRequest, LiveMonitorPublishingRequest, LiveMonitorStartRequest, ProcessRequest,\n",
    "    BatchRequest, LiveMonitorPublishingRequest, LiveMonitorStartRequest,\n"
    "    LiveMonitorStopRequest, ProcessRequest,\n",
)
api_tests = Path("tests/api/test_request_schema_contracts.py")
text = api_tests.read_text()
if "def test_live_monitor_stop_id_is_path_safe" not in text:
    text += '''


def test_live_monitor_stop_id_is_path_safe():
    assert LiveMonitorStopRequest(monitor_id="youtube:0123456789abcdefabcd").monitor_id
    with pytest.raises(ValidationError):
        LiveMonitorStopRequest(monitor_id="youtube:https://example.com/channel")
'''
    api_tests.write_text(text)

replace_once(
    "tests/domain/test_live_monitor.py",
    "    remaining_prelive,\n    render_template,\n",
    "    remaining_prelive,\n    render_template,\n    monitor_id_for,\n",
)
domain_tests = Path("tests/domain/test_live_monitor.py")
text = domain_tests.read_text().replace(
    "    monitor = LiveMonitorRegistry.__new__(LiveMonitorRegistry)\n", ""
)
if "def test_youtube_monitor_id_is_stable_and_path_safe" not in text:
    text += '''


def test_youtube_monitor_id_is_stable_and_path_safe():
    channel = "https://www.youtube.com/@ExampleCreator"
    first = monitor_id_for("youtube", channel)
    assert first == monitor_id_for("youtube", channel)
    assert first.startswith("youtube:")
    assert "/" not in first
    assert len(first) == len("youtube:") + 20


def test_non_youtube_monitor_id_remains_human_readable():
    assert monitor_id_for("kick", "creator") == "kick:creator"
'''
domain_tests.write_text(text)
