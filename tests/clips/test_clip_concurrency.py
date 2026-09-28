"""Concurrency contracts for the per-clip endpoints (reframe / smart cut /
compose / publish) that share one job's metadata document and one clip's files.

Every race is driven deterministically: fakes block on explicit events so the
test fixes the interleaving instead of hoping a scheduler produces it. No
ffmpeg, no real subprocess — ``create_subprocess_exec`` and the renderers are
stand-ins that write marker bytes, so each assertion reads WHICH version of a
file an operation saw.
"""
import asyncio
import itertools
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

from clippyme.editing import compose as compose_mod
from clippyme.editing import hooks as hooks_mod
from clippyme.clips import reframe_service
from clippyme.editing import smartcut
from clippyme.clips.clip_endpoints import run_smart_cut
from clippyme.clips.clip_resolve import composed_clip_basename, resolve_clip
from clippyme.core.errors import ClippyMeError
from clippyme.jobs.job_artifacts import load_job_metadata, record_clip_publish
from clippyme.monitoring.live_monitor import LiveMonitor
from clippyme.publishing.publish_service import publish_clip_flow
from clippyme.integrations import social_publisher

JOB_ID = "44444444-4444-4444-8444-444444444444"
# Blocking waits are bounded so a regression fails instead of hanging CI.
GATE_TIMEOUT = 10
# How long the test lets an operation run ahead before deciding it is blocked.
# Only the pre-fix demonstration depends on it; the final asserts do not.
OVERTAKE_WINDOW = 1.0

# Explicit, strictly increasing mtimes: the real operations are seconds or
# minutes apart, so the order in which they finish writing IS the mtime order.
_clock = itertools.count(int(time.time()) - 10_000, 10)


def _write(path, data):
    tmp = f"{path}.w.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    stamp = next(_clock)
    os.utime(tmp, (stamp, stamp))
    os.replace(tmp, path)


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _make_job(root, titles):
    job_dir = os.path.join(root, JOB_ID)
    os.makedirs(job_dir)
    shorts = []
    for i, title in enumerate(titles):
        name = f"clip{i}_clip_{i + 1}.mp4"
        shorts.append({"start": 0.0, "end": 5.0, "clip_filename": name,
                       "video_title_for_youtube_short": title,
                       "reframe_mode": "auto"})
        _write(os.path.join(job_dir, name), f"RAW{i}".encode())
        _write(os.path.join(job_dir, f"source_{name}"), f"SRC{i}".encode())
    with open(os.path.join(job_dir, "vid_metadata.json"), "w", encoding="utf-8") as fh:
        json.dump({"aspect": "9:16", "transcript": {"language": "en"}, "shorts": shorts}, fh)
    return job_dir


def _meta(root):
    return load_job_metadata(JOB_ID, root)[1]


class _GatedReframe:
    """``create_subprocess_exec`` stand-in for ``main.py --reframe-only``:
    records that the render started, waits for its gate, then atomically
    replaces the target clip with ``REFRAMED:<mode>``."""

    def __init__(self):
        self.started = {}
        self.gates = {}

    def gate(self, target):
        return self.gates.setdefault(os.path.abspath(target), asyncio.Event())

    def started_event(self, target):
        return self.started.setdefault(os.path.abspath(target), asyncio.Event())

    async def __call__(self, *cmd, **kwargs):
        target = cmd[cmd.index("-o") + 1]
        mode = cmd[cmd.index("--reframe-mode") + 1]
        started, gate = self.started_event(target), self.gate(target)

        class _Proc:
            returncode = 0

            async def communicate(self):
                started.set()
                await asyncio.wait_for(gate.wait(), GATE_TIMEOUT)
                _write(target, f"REFRAMED:{mode}".encode())
                return b"", None

        return _Proc()


def _reframe(root, index, mode, jobs=None):
    return reframe_service.run_reframe(job_id=JOB_ID, clip_index=index, mode=mode,
                                       output_root=root, jobs=jobs or {})


# ---------------------------------------------------------------------------
# A1 — job-level metadata vs clip-level lock
# ---------------------------------------------------------------------------

def test_sibling_reframes_do_not_lose_each_others_metadata(tmp_path, monkeypatch):
    """Two reframes on DIFFERENT clips of one job hold different clip locks but
    rewrite the same metadata file: the one that finishes last must not
    restore the other clip's pre-reframe state."""
    root = str(tmp_path)
    job_dir = _make_job(root, ["A", "B"])
    fake = _GatedReframe()
    monkeypatch.setattr(reframe_service.asyncio, "create_subprocess_exec", fake)
    clip0 = os.path.join(job_dir, "clip0_clip_1.mp4")
    clip1 = os.path.join(job_dir, "clip1_clip_2.mp4")

    async def scenario():
        first = asyncio.create_task(_reframe(root, 0, "subject"))
        second = asyncio.create_task(_reframe(root, 1, "disabled"))
        await asyncio.wait_for(fake.started_event(clip0).wait(), GATE_TIMEOUT)
        await asyncio.wait_for(fake.started_event(clip1).wait(), GATE_TIMEOUT)
        fake.gate(clip0).set()
        await first
        fake.gate(clip1).set()
        await second

    asyncio.run(scenario())

    shorts = _meta(root)["shorts"]
    assert [s["reframe_mode"] for s in shorts] == ["subject", "disabled"]
    assert _read(clip0) == b"REFRAMED:subject"
    assert _read(clip1) == b"REFRAMED:disabled"


def test_metadata_writers_interleaved_with_a_reframe_all_survive(tmp_path, monkeypatch):
    """Integration: while clip 0 re-renders (minutes in production), clip 1 is
    published (dashboard publish record) and clip 2 is published by a live
    monitor (delete-after-publish mark). All three updates must survive the
    reframe's own metadata write — a lost ``deleted_after_publish`` flag would
    resurrect a clip whose files are gone."""
    root = str(tmp_path)
    job_dir = _make_job(root, ["A", "B", "C"])
    fake = _GatedReframe()
    monkeypatch.setattr(reframe_service.asyncio, "create_subprocess_exec", fake)
    clip0 = os.path.join(job_dir, "clip0_clip_1.mp4")
    monitor = SimpleNamespace(_output_dir=root)

    async def scenario():
        reframe = asyncio.create_task(_reframe(root, 0, "subject"))
        await asyncio.wait_for(fake.started_event(clip0).wait(), GATE_TIMEOUT)
        await asyncio.to_thread(record_clip_publish, JOB_ID, 1, root, {"post_id": "p1"})
        LiveMonitor._mark_clip_deleted(monitor, JOB_ID, 2)
        fake.gate(clip0).set()
        await reframe

    asyncio.run(scenario())

    shorts = _meta(root)["shorts"]
    assert shorts[0]["reframe_mode"] == "subject"
    assert shorts[1].get("published") == [{"post_id": "p1"}]
    assert shorts[2].get("deleted_after_publish") is True


def test_failed_reframe_leaves_metadata_and_frees_the_clip(tmp_path, monkeypatch):
    root = str(tmp_path)
    job_dir = _make_job(root, ["A"])
    meta_path = os.path.join(job_dir, "vid_metadata.json")
    before = _read(meta_path)

    async def failing_exec(*cmd, **kwargs):
        class _Proc:
            returncode = 1

            async def communicate(self):
                return b"boom", None
        return _Proc()

    monkeypatch.setattr(reframe_service.asyncio, "create_subprocess_exec", failing_exec)
    with pytest.raises(ClippyMeError) as exc:
        asyncio.run(_reframe(root, 0, "subject"))
    assert exc.value.status_code == 500
    assert _read(meta_path) == before

    fake = _GatedReframe()
    fake.gate(os.path.join(job_dir, "clip0_clip_1.mp4")).set()
    monkeypatch.setattr(reframe_service.asyncio, "create_subprocess_exec", fake)
    asyncio.run(asyncio.wait_for(_reframe(root, 0, "subject"), GATE_TIMEOUT))
    assert _meta(root)["shorts"][0]["reframe_mode"] == "subject"


def test_reframe_updates_the_in_memory_clip_by_original_index(tmp_path, monkeypatch):
    """The in-memory result list skips deleted/missing clips, so list position
    != metadata index. The live registry must follow ``original_index``, not
    the position (which pointed the other clip's tile at this clip's file)."""
    root = str(tmp_path)
    job_dir = _make_job(root, ["A", "B", "C"])
    fake = _GatedReframe()
    fake.gate(os.path.join(job_dir, "clip2_clip_3.mp4")).set()
    monkeypatch.setattr(reframe_service.asyncio, "create_subprocess_exec", fake)
    # Clip 1 was deleted after a publish → absent from the in-memory result.
    live = [{"original_index": 0, "video_url": "/videos/j/clip0_clip_1.mp4", "reframe_mode": "auto"},
            {"original_index": 2, "video_url": "/videos/j/clip2_clip_3.mp4", "reframe_mode": "auto"}]
    jobs = {JOB_ID: {"status": "completed", "result": {"clips": live}}}

    asyncio.run(_reframe(root, 2, "subject", jobs=jobs))

    assert live[0]["reframe_mode"] == "auto"
    assert live[0]["video_url"] == "/videos/j/clip0_clip_1.mp4"
    assert live[1]["reframe_mode"] == "subject"
    assert live[1]["video_url"] == f"/videos/{JOB_ID}/clip2_clip_3.mp4"


# ---------------------------------------------------------------------------
# Reframe while the pipeline still owns the job
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["queued", "processing", "paused"])
def test_reframe_is_refused_while_the_job_is_active(tmp_path, monkeypatch, status):
    """While a job is active the orchestrator rewrites the whole metadata file
    from its own in-memory copy at every clip milestone (and may still be
    rendering the very clip), so a post-hoc reframe would be silently reverted
    or overwritten. It must be refused up front, before any render starts."""
    root = str(tmp_path)
    job_dir = _make_job(root, ["A"])
    spawned = []

    async def fake_exec(*cmd, **kwargs):
        spawned.append(cmd)
        raise AssertionError("reframe subprocess must not start for an active job")

    monkeypatch.setattr(reframe_service.asyncio, "create_subprocess_exec", fake_exec)
    before = _read(os.path.join(job_dir, "vid_metadata.json"))

    with pytest.raises(ClippyMeError) as exc:
        asyncio.run(_reframe(root, 0, "subject", jobs={JOB_ID: {"status": status}}))

    assert exc.value.status_code == 409
    assert spawned == []
    assert _read(os.path.join(job_dir, "vid_metadata.json")) == before


# ---------------------------------------------------------------------------
# A2 — standalone Smart Cut vs reframe on the same clip
# ---------------------------------------------------------------------------

def _stub_smartcut(monkeypatch, gate_first_render):
    """Real ``smart_cut`` (lock + plan-hash cache) over a fake renderer that
    reads the clip, then writes ``CUT:<clip bytes>`` — like auto-editor
    reading its input before emitting the output."""
    render_started = threading.Event()
    renders = []

    def fake_analyze(transcript, start, end, language=None, drop_ranges=None):
        return [(0.0, 1.0), (2.0, 5.0)], {
            "original_duration": 5.0, "new_duration": 4.0, "time_saved": 20.0,
            "silences_removed": 1, "fillers_removed": 0,
        }

    def fake_render(clip_path, segments, output_path):
        seen = _read(clip_path)
        renders.append(seen)
        if len(renders) == 1:
            render_started.set()
            assert gate_first_render.wait(GATE_TIMEOUT)
        _write(output_path, b"CUT:" + seen)
        return True

    monkeypatch.setattr(smartcut, "analyze_silences", fake_analyze)
    monkeypatch.setattr(smartcut, "_has_auto_editor", lambda: False)
    monkeypatch.setattr(smartcut, "_auto_editor_version", lambda: None)
    monkeypatch.setattr(smartcut, "_probe_duration", lambda path: 4.0)
    monkeypatch.setattr(smartcut, "_render_with_ffmpeg", fake_render)
    return render_started, renders


def test_smart_cut_racing_a_reframe_cannot_poison_the_cache(tmp_path, monkeypatch):
    """/api/smartcut only took smart_cut's own path lock, not the clip lock
    reframe/compose share. A reframe could replace the clip while the smart
    cut was still rendering the OLD pixels; the smart-cut file then carried a
    newer mtime than the reframed clip, so every later compose/publish with
    Smart Cut reused the stale framing as a cache hit."""
    root = str(tmp_path)
    job_dir = _make_job(root, ["A"])
    clip0 = os.path.join(job_dir, "clip0_clip_1.mp4")
    gate = threading.Event()
    render_started, _ = _stub_smartcut(monkeypatch, gate)
    fake = _GatedReframe()
    fake.gate(clip0).set()  # the reframe itself renders instantly once started
    monkeypatch.setattr(reframe_service.asyncio, "create_subprocess_exec", fake)

    async def scenario():
        resolved = await asyncio.to_thread(resolve_clip, JOB_ID, 0, root)
        cut = asyncio.create_task(run_smart_cut(job_id=JOB_ID, clip_index=0, resolved=resolved))
        assert await asyncio.to_thread(render_started.wait, GATE_TIMEOUT)
        reframe = asyncio.create_task(_reframe(root, 0, "subject"))
        await asyncio.wait({reframe}, timeout=OVERTAKE_WINDOW)
        gate.set()
        await cut
        await reframe
        # The next Smart Cut of this clip (what compose/publish run).
        return await asyncio.to_thread(
            smartcut.smart_cut, clip0, {"language": "en"}, 0.0, 5.0, "en")

    path, _ = asyncio.run(scenario())

    assert _read(clip0) == b"REFRAMED:subject"
    assert _read(path) == b"CUT:REFRAMED:subject"


# ---------------------------------------------------------------------------
# A4 — composed-file naming
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("titles", [
    ("Same title", "Same title"),
    ("a/b: c?", "ab c"),                      # sanitize to the same string
    ("x" * 81 + " one", "x" * 81 + " two"),   # identical after truncation
])
def test_composed_names_are_unique_per_clip(titles):
    names = {composed_clip_basename({"video_title_for_youtube_short": t}, i)
             for i, t in enumerate(titles)}
    assert len(names) == 2


def _stub_hook(monkeypatch, gate=None):
    """Hook pass writes ``HOOK:<text>:<input bytes>``; optionally blocks."""
    started = threading.Event()

    def fake_hook(input_path, text, output_path, *args, **kwargs):
        seen = _read(input_path)
        started.set()
        if gate is not None:
            assert gate.wait(GATE_TIMEOUT)
        _write(output_path, f"HOOK:{text}:".encode() + seen)

    monkeypatch.setattr(hooks_mod, "add_hook_to_video", fake_hook)
    monkeypatch.setattr(compose_mod, "_self_eval", _no_self_eval)
    return started


async def _no_self_eval(*args, **kwargs):
    return None


def _compose(root, index, text):
    resolved = resolve_clip(JOB_ID, index, root)
    return compose_mod.compose_layers(
        base_clip=resolved.clip_path, job_dir=resolved.job_dir, clip_index=index,
        metadata=resolved.metadata, clip_info=resolved.clip_info,
        toggles={"hook": True}, hook_params={"text": text}, subtitle_params={})


def _capture_uploads(monkeypatch):
    uploads = []

    def fake_publish_clip(*, clip_path, **kwargs):
        uploads.append(_read(clip_path))
        return {"post_id": f"p{len(uploads)}"}

    monkeypatch.setattr(social_publisher, "publish_clip", fake_publish_clip)
    return uploads


def _publish(root, index, **req):
    resolved = resolve_clip(JOB_ID, index, root, require_file=False)
    return publish_clip_flow(job_id=JOB_ID, clip_index=index, resolved=resolved,
                             req={"platforms": ["tiktok"], **req},
                             zernio_cfg={"api_key": "k"})


def test_same_title_clips_keep_their_own_composed_file(tmp_path, monkeypatch):
    """Bulk export composes clip after clip and the browser fetches each result
    afterwards; a publish without compose_first falls back to the composed
    file on disk. With one shared ``<title>.mp4`` both read the LAST clip."""
    root = str(tmp_path)
    job_dir = _make_job(root, ["Same title", "Same title"])
    _stub_hook(monkeypatch)
    uploads = _capture_uploads(monkeypatch)

    async def scenario():
        first = await _compose(root, 0, "h0")
        second = await _compose(root, 1, "h1")
        await _publish(root, 0)
        return first, second

    first, second = asyncio.run(scenario())

    assert first != second
    assert _read(os.path.join(job_dir, first)) == b"HOOK:h0:RAW0"
    assert _read(os.path.join(job_dir, second)) == b"HOOK:h1:RAW1"
    assert uploads == [b"HOOK:h0:RAW0"]


# ---------------------------------------------------------------------------
# A5 — publish vs compose on the same clip
# ---------------------------------------------------------------------------

def test_publish_waits_for_an_in_flight_compose_of_the_same_clip(tmp_path, monkeypatch):
    """compose deletes the old composed file first and writes the new one only
    at the end; a publish without compose_first resolving its upload in that
    window found no composed file and uploaded the RAW clip."""
    root = str(tmp_path)
    _make_job(root, ["A"])
    gate = threading.Event()
    _stub_hook(monkeypatch)
    uploads = _capture_uploads(monkeypatch)

    async def scenario():
        await _compose(root, 0, "v1")            # an earlier composed version
        started = _stub_hook(monkeypatch, gate)
        compose = asyncio.create_task(_compose(root, 0, "v2"))
        assert await asyncio.to_thread(started.wait, GATE_TIMEOUT)
        publish = asyncio.create_task(_publish(root, 0))
        await asyncio.wait({publish}, timeout=OVERTAKE_WINDOW)
        gate.set()
        await compose
        await publish

    asyncio.run(scenario())

    assert uploads == [b"HOOK:v2:RAW0"]


def test_publish_with_compose_first_does_not_deadlock_on_the_clip_lock(tmp_path, monkeypatch):
    root = str(tmp_path)
    _make_job(root, ["A"])
    _stub_hook(monkeypatch)
    uploads = _capture_uploads(monkeypatch)

    async def scenario():
        await asyncio.wait_for(
            _publish(root, 0, compose_first=True, toggles={"hook": True},
                     hook_params={"text": "fresh"}),
            GATE_TIMEOUT)

    asyncio.run(scenario())

    assert uploads == [b"HOOK:fresh:RAW0"]
