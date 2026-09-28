"""Publication consistency & idempotency (manual + automatic publish paths).

Provider behaviour is modelled on Zernio's documented idempotency rules
(docs.zernio.com/guides/idempotency, /guides/media-uploads):

* ``Idempotency-Key``: a repeat within 24 h returns the original post; the
  match is on the key alone, so a re-uploaded media URL still replays.
* ``x-request-id``: replays only when the content fingerprint (account,
  content, media URLs) also matches.
* content-hash dedup: ``(platform, accountId, content + media URLs)`` → 409
  with ``details.existingPostId``.
* a repeat while the first request is still processing → 409
  ``code: "idempotency_conflict"`` + ``Retry-After`` (no post may exist yet).
* every presign returns a new unique key / public URL; a failed first
  request releases its key.

Concurrency is driven with Events (no sleeps): each test pins the exact
interleaving it needs.
"""
import asyncio
import json
import os
import shutil
import threading

import httpx
import pytest
import requests
from fastapi.testclient import TestClient

from clippyme.api import app as app_module
from clippyme.domain import clip_locks
from clippyme.domain import compose as compose_mod
from clippyme.domain import live_monitor as lm
from clippyme.domain.clip_locks import clip_lock
from clippyme.domain.clip_resolve import composed_clip_basename
from clippyme.domain.job_artifacts import load_job_metadata
from clippyme.domain.live_monitor import LiveMonitor, validate_monitor_config
from clippyme.integrations import social_publisher as sp
from clippyme.integrations.social_publisher import ZernioError

JOB = "77777777-7777-4777-8777-777777777777"
ORIGIN = {"Origin": "http://localhost:5175"}
PUBLISH = {"platforms": [{"platform": "tiktok", "accountId": "acc"}]}


def _cfg(**over):
    raw = {"platform": "twitch", "channel": "foo",
           "platforms": [{"platform": "tiktok", "accountId": "a"}],
           "loop": True, "prelive_skip_seconds": 0, "poll_interval": 60,
           "segment_seconds": 600, "timezone": "UTC"}
    raw.update(over)
    return validate_monitor_config(raw, default_timezone="UTC")


def _monitor(output_dir, **cfg):
    mon = LiveMonitor(id="twitch:foo", jobs={JOB: {"status": "completed"}},
                      job_queue=None, output_dir=str(output_dir))
    mon.cfg = _cfg(**cfg)
    mon.cfg["delete_after_publish"] = False
    mon.platform = "twitch"
    mon._zernio_key = "sk_test"
    return mon


def _job(output_dir, titles=("Same title",)):
    """A finished job dir: raw clips + metadata, one short per title."""
    job_dir = output_dir / JOB
    job_dir.mkdir(parents=True, exist_ok=True)
    shorts = []
    for i, title in enumerate(titles):
        name = f"vid_clip_{i + 1}.mp4"
        (job_dir / name).write_bytes(b"RAW%d" % i)
        shorts.append({"start": 0, "end": 5, "title": title,
                       "video_url": f"/videos/{JOB}/{name}"})
    (job_dir / "vid_metadata.json").write_text(json.dumps({"shorts": shorts}))
    return job_dir


def _clip(i=0, title="Same title"):
    return {"original_index": i, "index": i, "title": title,
            "video_url": f"/videos/{JOB}/vid_clip_{i + 1}.mp4", "start": 0, "end": 5}


def _held(job_dir, clip_index) -> bool:
    entry = clip_locks._LOCKS.get((os.path.abspath(str(job_dir)), clip_index))
    return bool(entry and entry[0].locked())


class _FakeCompose:
    """compose_layers stand-in with the real file contract: holds the clip
    lock, deletes the previous composed file up front, writes it at the end."""

    async def __call__(self, *, job_dir, clip_index, clip_info, tag=b"MONITOR",
                       gate=None, on_deleted=None, **_):
        async with clip_lock(job_dir, clip_index):
            name = composed_clip_basename(clip_info, clip_index)
            path = os.path.join(job_dir, name)
            if os.path.exists(path):
                os.remove(path)
            if on_deleted:
                on_deleted()
            if gate:
                await gate.wait()
            with open(path, "wb") as f:
                f.write(tag)
        return name


# ---------------------------------------------------------------------------
# Provider idempotency (documented Zernio semantics)
# ---------------------------------------------------------------------------

class FakeZernio:
    """HTTP-level Zernio stand-in following the documented replay rules."""

    def __init__(self):
        self.posts = []
        self.by_key = {}
        self.by_request_id = {}
        self.presigns = 0
        self.lose_next_create_response = False
        # Seconds of Retry-After for the next N repeats of a key whose first
        # request is "still processing" (409 idempotency_conflict).
        self.in_progress = []

    def request(self, method, url, **kwargs):
        path = url.split("/api/v1", 1)[-1] if "/api/v1" in url else url
        if method == "GET" and path.startswith("/posts"):
            return _Resp(200, {"posts": []})
        if method == "POST" and path.startswith("/media/presign"):
            self.presigns += 1
            n = self.presigns
            return _Resp(200, {"uploadUrl": f"https://up.example/{n}",
                               "publicUrl": f"https://cdn.example/temp/{n}_rnd.mp4"})
        if method == "POST" and path.startswith("/posts"):
            return self._create(kwargs.get("json") or {}, kwargs.get("headers") or {})
        raise AssertionError(f"unexpected {method} {url}")

    def _create(self, body, headers):
        media = tuple(m["url"] for m in body.get("mediaItems", []))
        fingerprint = (json.dumps(body.get("platforms"), sort_keys=True), body.get("content"), media)
        key = headers.get("Idempotency-Key")
        if key and key in self.by_key and self.in_progress:
            return _Resp(409, {"error": "Request in progress", "code": "idempotency_conflict"},
                         {"Retry-After": str(self.in_progress.pop(0))})
        if key and key in self.by_key:
            return _Resp(200, {"post": self.by_key[key]})
        rid = headers.get("x-request-id")
        if rid and self.by_request_id.get(rid, (None, None))[0] == fingerprint:
            return _Resp(200, {"post": self.by_request_id[rid][1]})
        for post in self.posts:
            if post["fingerprint"] == fingerprint:
                return _Resp(409, {"error": "duplicate", "details": {"existingPostId": post["_id"]}})
        post = {"_id": f"post{len(self.posts) + 1}", "status": "scheduled",
                "fingerprint": fingerprint}
        self.posts.append(post)
        if key:
            self.by_key[key] = post
        if rid:
            self.by_request_id[rid] = (fingerprint, post)
        if self.lose_next_create_response:
            self.lose_next_create_response = False
            raise requests.ConnectionError("read timed out")  # created, answer lost
        return _Resp(201, {"post": post})


class _Resp:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


@pytest.fixture
def zernio(monkeypatch):
    server = FakeZernio()
    monkeypatch.setattr(requests.Session, "request",
                        lambda self, method, url, **kw: server.request(method, url, **kw))
    monkeypatch.setattr(sp.requests, "put", lambda *a, **k: _Resp(200, {}))
    monkeypatch.setattr(sp, "_reject_internal_upload_url", lambda url: None)
    return server


def test_retry_after_a_lost_create_response_does_not_duplicate_the_post(tmp_path, zernio):
    """Ambiguous outcome → retry. The retry re-uploads (new media URL), so
    only a key-only replay (Idempotency-Key) can return the first post."""
    mon = _monitor(tmp_path)
    composed = tmp_path / "consolidated.mp4"
    composed.write_bytes(b"COMPOSED")
    entry = {"job_id": JOB, "clip": _clip(), "composed_path": str(composed)}

    zernio.lose_next_create_response = True
    asyncio.run(mon._publish_one(entry))
    assert entry["state"] == "retry_wait"          # outcome unknown → retried
    asyncio.run(mon._publish_one(entry))

    assert [p["_id"] for p in zernio.posts] == ["post1"]
    assert mon._pending_publish == [] and mon._failed_publish == []


def test_in_progress_conflict_over_http_waits_retry_after_and_keeps_the_key(tmp_path, zernio):
    """Lost answer → the retry finds the first request still processing: 409
    ``idempotency_conflict`` with a Retry-After header, through the real HTTP
    client. The next attempt waits at least that long, with the same key, and
    then replays the one post."""
    mon = _monitor(tmp_path)
    composed = tmp_path / "consolidated.mp4"
    composed.write_bytes(b"COMPOSED")
    entry = {"job_id": JOB, "clip": _clip(), "composed_path": str(composed)}

    zernio.lose_next_create_response = True
    asyncio.run(mon._publish_one(entry))
    key = entry["request_id"]
    zernio.in_progress = [900]
    before = lm.time.time()
    asyncio.run(mon._publish_one(entry))
    assert entry["state"] == "retry_wait" and entry["request_id"] == key
    assert entry["next_retry_at"] >= before + 900 > before + lm.publish_retry_delay(2)
    asyncio.run(mon._publish_one(entry))

    assert [p["_id"] for p in zernio.posts] == ["post1"]
    assert mon._pending_publish == [] and mon._failed_publish == []


def test_ambiguous_outcome_then_restart_recovers_the_same_publication(tmp_path, zernio):
    """Scenario B: the provider created the post but the answer was lost and
    the process restarted (hours later, past any short window). Recovery keeps
    the publication identity and key, and replays instead of posting again."""
    mon = _monitor(tmp_path)
    persisted = []
    mon._on_state_change = lambda: persisted.append(json.loads(json.dumps(mon.snapshot())))
    composed = tmp_path / "consolidated.mp4"
    composed.write_bytes(b"COMPOSED")
    queued = LiveMonitor._as_publication({"job_id": JOB, "clip": _clip(),
                                          "composed_path": str(composed)})
    mon._pending_publish = [queued]
    pid, key = queued["publication_id"], queued["request_id"]

    zernio.lose_next_create_response = True
    asyncio.run(mon._publish_one(queued))

    fresh = _monitor(tmp_path)
    fresh.restore(persisted[-1])
    restored = fresh._pending_publish[0]
    assert (restored["publication_id"], restored["request_id"]) == (pid, key)
    restored["next_retry_at"] = 0          # due now
    asyncio.run(fresh._drain_pending())

    assert [p["_id"] for p in zernio.posts] == ["post1"]
    assert fresh._pending_publish == [] and fresh._failed_publish == []
    assert len(fresh._published) == 1


def test_publish_clip_sends_a_key_only_idempotency_header(tmp_path, zernio):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    zernio.lose_next_create_response = True
    kwargs = dict(api_key="sk_test", clip_path=str(clip), title="t", caption="c",
                  platform_targets=[{"platform": "tiktok", "accountId": "a"}],
                  request_id="rid-1")
    with pytest.raises(ZernioError):
        sp.publish_clip(**kwargs)
    result = sp.publish_clip(**kwargs)

    assert result["post_id"] == "post1"
    assert len(zernio.posts) == 1


def test_idempotency_conflict_409_is_not_treated_as_accepted(tmp_path, monkeypatch):
    """409 idempotency_conflict = the first request is still being processed:
    no post may exist yet. Marking it accepted would drop the publication
    and delete its artifacts; it must be retried with the SAME key."""
    conflict = ZernioError("Zernio POST /posts → HTTP 409", status_code=409,
                           body='{"error":"Request in progress","code":"idempotency_conflict"}')
    calls = []

    def fake_publish(**kw):
        calls.append(kw["request_id"])
        raise conflict

    monkeypatch.setattr(sp, "publish_clip", fake_publish)
    mon = _monitor(tmp_path)
    mon.cfg["delete_after_publish"] = True
    composed = tmp_path / "consolidated.mp4"
    composed.write_bytes(b"COMPOSED")
    entry = {"job_id": JOB, "clip": _clip(), "composed_path": str(composed)}
    key = lm.LiveMonitor._as_publication(entry)["request_id"]

    asyncio.run(mon._publish_one(entry))

    assert mon._published == set()
    assert entry["state"] == "retry_wait" and mon._pending_publish == [entry]
    assert entry["request_id"] == key == calls[0]
    assert composed.exists()


def test_content_dedup_409_still_counts_as_accepted():
    dup = ZernioError("HTTP 409", status_code=409,
                      body='{"error":"duplicate","details":{"existingPostId":"p9"}}')
    assert lm.classify_publish_error(dup) == "duplicate"
    conflict = ZernioError("HTTP 409", status_code=409,
                           body='{"code":"idempotency_conflict"}')
    assert lm.classify_publish_error(conflict) == "retry"
    assert not lm._definitely_not_created(conflict)


def test_idempotency_conflict_is_recognised_past_the_body_snippet_limit():
    """The client keeps only 500 chars of an error body (for the UI); the
    retry-vs-accepted decision must not depend on where ``code`` lands."""
    client = sp.ZernioClient("sk_test")
    payload = {"error": "Request in progress", "message": "x" * 600,
               "code": "idempotency_conflict"}
    client._session.request = lambda method, url, **kw: _Resp(409, payload)

    with pytest.raises(ZernioError) as caught:
        client.create_post(content="c", media_items=[], platforms=[], request_id="k")

    assert "idempotency_conflict" not in caught.value.body     # truncated away
    assert lm.classify_publish_error(caught.value) == "retry"


@pytest.mark.parametrize("body", ["slow down", "Daily limit reached for tiktok"])
def test_request_id_rotated_after_a_429_is_durable_before_the_next_call(tmp_path, monkeypatch, body):
    """A 429 rotates the key in memory and calls the provider again. If that
    call is accepted and the process dies before the next persist, the
    restart must retry with the key the provider saw — not the old one."""
    monkeypatch.setattr(lm, "PUBLISH_429_BACKOFF_SECONDS", 0)
    mon = _monitor(tmp_path)
    persisted = []
    mon._on_state_change = lambda: persisted.append(json.loads(json.dumps(mon.snapshot())))
    at_call = []
    calls = []

    def fake_publish(**kw):
        calls.append(kw["request_id"])
        at_call.append(persisted[-1])
        if len(calls) == 1:
            raise ZernioError("HTTP 429", status_code=429, body=body)
        return {"post_id": "p1", "status": "scheduled"}

    monkeypatch.setattr(sp, "publish_clip", fake_publish)
    composed = tmp_path / "consolidated.mp4"
    composed.write_bytes(b"C")
    asyncio.run(mon._publish_one({"job_id": JOB, "clip": _clip(), "composed_path": str(composed)}))

    assert calls[0] != calls[1]
    durable = at_call[1]["pending_publish"][0]
    assert durable["state"] == "in_flight"
    assert durable["request_id"] == calls[1]


# ---------------------------------------------------------------------------
# P2 — monitor artifact reads vs a concurrent compose of the same clip
# ---------------------------------------------------------------------------

def test_recompose_on_drain_uploads_its_own_compose(tmp_path, monkeypatch):
    """Restored entry whose consolidated file vanished → the drain recomposes
    in the job dir and uploads that file. A manual compose of the same clip
    must not delete/replace it between the compose and the upload."""
    job_dir = _job(tmp_path)
    mon = _monitor(tmp_path)
    fake = _FakeCompose()
    monitor_composed = asyncio.Event()
    upload_may_read = threading.Event()
    uploads = []

    async def monitor_compose(**kw):
        name = await fake(**kw)
        monitor_composed.set()
        return name

    def fake_publish(**kw):
        assert upload_may_read.wait(5)
        if not os.path.isfile(kw["clip_path"]):
            raise ValueError(f"clip not found: {kw['clip_path']}")
        with open(kw["clip_path"], "rb") as f:
            uploads.append(f.read())
        return {"post_id": "p1", "status": "scheduled"}

    monkeypatch.setattr(compose_mod, "compose_layers", monitor_compose)
    monkeypatch.setattr(sp, "publish_clip", fake_publish)
    entry = {"job_id": JOB, "clip": _clip(), "composed_path": str(tmp_path / "gone.mp4")}

    async def scenario():
        release = asyncio.Event()

        async def manual_compose():
            await monitor_composed.wait()
            if _held(job_dir, 0):
                upload_may_read.set()          # it will have to wait its turn
            await fake(job_dir=str(job_dir), clip_index=0, clip_info=_clip(),
                       tag=b"MANUAL", gate=release, on_deleted=upload_may_read.set)

        manual = asyncio.create_task(manual_compose())
        await mon._publish_one(entry)
        release.set()
        await manual

    asyncio.run(scenario())

    assert mon._failed_publish == []
    assert uploads == [b"MONITOR"]


def test_consolidation_copies_its_own_compose(tmp_path, monkeypatch):
    """Hand-off composes each clip in the job dir, then copies it into the
    monitor folder. A manual compose in between used to make the copy fail and
    silently drop the clip from the publish queue."""
    job_dir = _job(tmp_path)
    mon = _monitor(tmp_path)
    fake = _FakeCompose()
    monitor_composed = asyncio.Event()
    copy_may_read = threading.Event()
    real_copy = shutil.copyfile

    async def monitor_compose(**kw):
        name = await fake(**kw)
        monitor_composed.set()
        return name

    def gated_copy(src, dst, *a, **k):
        assert copy_may_read.wait(5)
        return real_copy(src, dst, *a, **k)

    monkeypatch.setattr(compose_mod, "compose_layers", monitor_compose)
    monkeypatch.setattr(shutil, "copyfile", gated_copy)

    async def scenario():
        release = asyncio.Event()

        async def manual_compose():
            await monitor_composed.wait()
            if _held(job_dir, 0):
                copy_may_read.set()
            await fake(job_dir=str(job_dir), clip_index=0, clip_info=_clip(),
                       tag=b"MANUAL", gate=release, on_deleted=copy_may_read.set)

        manual = asyncio.create_task(manual_compose())
        out = await mon._consolidate_clips(JOB, [_clip()])
        release.set()
        await manual
        return out

    out = asyncio.run(scenario())

    assert len(out) == 1
    with open(out[0]["composed_path"], "rb") as f:
        assert f.read() == b"MONITOR"


# ---------------------------------------------------------------------------
# P1 — manual publish vs the monitor's ownership of the same clip
# ---------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch, tmp_path):
    outputs = tmp_path / "output"
    _job(outputs, titles=("A", "B"))
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))
    monkeypatch.setattr(app_module, "load_zernio_config", lambda: {"api_key": "k"})
    monkeypatch.setattr(app_module.live_monitor, "_monitors", {})
    monkeypatch.setattr(app_module.live_monitor, "_snapshots", {})
    app_module.jobs[JOB] = {"status": "completed"}
    uploads = []
    monkeypatch.setattr(sp, "publish_clip",
                        lambda **kw: uploads.append(kw) or {"post_id": f"m{len(uploads)}"})
    yield outputs, uploads
    app_module.jobs.pop(JOB, None)


def _owning_monitor(outputs, state=None, inflight=False):
    mon = _monitor(outputs)
    if inflight:
        mon._inflight_jobs = {JOB: None}
    if state:
        entry = LiveMonitor._as_publication({"job_id": JOB, "clip": _clip(0, "A")})
        entry["state"] = state
        mon._pending_publish = [entry]
    return mon


@pytest.mark.parametrize("how", ["job_not_handed_off", "queued", "in_flight", "retry_wait",
                                 "stopped_monitor_queue"])
def test_manual_publish_of_a_clip_the_monitor_still_owns_is_refused(api, how):
    outputs, uploads = api
    registry = app_module.live_monitor
    if how == "job_not_handed_off":
        registry._monitors["twitch:foo"] = _owning_monitor(outputs, inflight=True)
    elif how == "stopped_monitor_queue":
        registry._snapshots["twitch:foo"] = _owning_monitor(outputs, state="queued").snapshot()
    else:
        registry._monitors["twitch:foo"] = _owning_monitor(outputs, state=how)

    r = TestClient(app_module.app, headers=ORIGIN).post(f"/api/publish/{JOB}/0", json=PUBLISH)

    assert r.status_code == 409, r.text
    assert uploads == []


def test_manual_publish_stays_open_for_other_clips_and_failed_items(api):
    outputs, uploads = api
    mon = _owning_monitor(outputs, state="queued")
    failed = LiveMonitor._as_publication({"job_id": JOB, "clip": _clip(1, "B")})
    failed["state"] = "failed"
    mon._failed_publish = [failed]
    app_module.live_monitor._monitors["twitch:foo"] = mon
    http = TestClient(app_module.app, headers=ORIGIN)

    assert http.post(f"/api/publish/{JOB}/1", json=PUBLISH).status_code == 200
    assert len(uploads) == 1


def test_monitor_publish_in_flight_blocks_a_concurrent_manual_publish(api, monkeypatch):
    """Scenario A: the monitor is mid-upload of clip 0 when the user publishes
    the same clip by hand. One provider call, and the automatic publication
    is recorded on the clip so a later manual publish is a visible choice."""
    outputs, uploads = api
    mon = _owning_monitor(outputs)
    app_module.live_monitor._monitors["twitch:foo"] = mon
    consolidated = outputs / "monitor_twitch_foo"
    consolidated.mkdir()
    (consolidated / "A.mp4").write_bytes(b"COMPOSED-A")
    entry = {"job_id": JOB, "clip": _clip(0, "A"), "composed_path": str(consolidated / "A.mp4")}
    in_upload, release = threading.Event(), threading.Event()
    calls = []

    def fake_publish(**kw):
        calls.append(kw.get("request_id"))
        if kw.get("request_id"):
            in_upload.set()
            assert release.wait(5)
        return {"post_id": f"p{len(calls)}", "status": "scheduled"}

    monkeypatch.setattr(sp, "publish_clip", fake_publish)

    async def scenario():
        auto = asyncio.create_task(mon._publish_one(entry))
        assert await asyncio.to_thread(in_upload.wait, 5)
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost",
                                     headers=ORIGIN) as client:
            during = await client.post(f"/api/publish/{JOB}/0", json=PUBLISH)
            release.set()
            await auto
            after = await client.post(f"/api/publish/{JOB}/0", json=PUBLISH)
        return during, after

    during, after = asyncio.run(scenario())

    assert during.status_code == 409, during.text
    assert calls[0] and len(calls) == 2             # monitor, then the explicit re-publish
    assert after.status_code == 200
    records = load_job_metadata(JOB, str(outputs))[1]["shorts"][0]["published"]
    assert [r.get("source") for r in records] == ["monitor:twitch:foo", None]
    assert records[0]["post_id"] == "p1"


# ---------------------------------------------------------------------------
# P5 — legacy (pre-_<n>) composed filenames
# ---------------------------------------------------------------------------

def test_legacy_composed_file_is_never_uploaded(api):
    """``<title>.mp4`` predates the per-clip suffix: with duplicate titles it
    may be the other clip's render, so publish never trusts it."""
    outputs, uploads = api
    job_dir = outputs / JOB
    (job_dir / "A.mp4").write_bytes(b"LEGACY-COMPOSED")

    r = TestClient(app_module.app, headers=ORIGIN).post(f"/api/publish/{JOB}/0", json=PUBLISH)

    assert r.status_code == 200, r.text
    assert uploads[0]["clip_path"] == str(job_dir / "vid_clip_1.mp4")


# ---------------------------------------------------------------------------
# G-pub1 — manual publication intent (``intent_id``) end to end
# ---------------------------------------------------------------------------

INTENT = "5f0c1d2e3a4b4c6d8e9f0a1b2c3d4e5f"


@pytest.fixture
def manual(monkeypatch, tmp_path, zernio):
    """The real publish endpoint → publish_clip → HTTP-level fake Zernio."""
    outputs = tmp_path / "output"
    _job(outputs, titles=("A", "B"))
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(outputs))
    monkeypatch.setattr(app_module, "load_zernio_config", lambda: {"api_key": "sk_test"})
    monkeypatch.setattr(app_module.live_monitor, "_monitors", {})
    monkeypatch.setattr(app_module.live_monitor, "_snapshots", {})
    app_module.jobs[JOB] = {"status": "completed"}
    yield outputs
    app_module.jobs.pop(JOB, None)


def _publish(client, clip=0, intent=INTENT):
    body = dict(PUBLISH, **({"intent_id": intent} if intent else {}))
    return client.post(f"/api/publish/{JOB}/{clip}", json=body)


def test_manual_retry_after_a_lost_response_reuses_the_intent_key(manual, zernio):
    """Provider accepted, the answer never came back (the API returns 502):
    the client retries the same intent, re-uploading to a new media URL —
    only a key-only replay keeps it one post."""
    http = TestClient(app_module.app, headers=ORIGIN)
    zernio.lose_next_create_response = True
    first = _publish(http)
    second = _publish(http)

    assert first.status_code == 502, first.text
    assert second.status_code == 200, second.text
    assert [p["_id"] for p in zernio.posts] == ["post1"]
    assert second.json()["post_id"] == "post1"


def test_same_intent_after_a_confirmed_publish_is_answered_from_the_record(manual, zernio):
    """Browser retry after the API DID answer (response lost client-side):
    the server finds the intent on the clip's publish record — no second
    upload, even past the provider's 24 h key window."""
    http = TestClient(app_module.app, headers=ORIGIN)
    first = _publish(http)
    presigns = zernio.presigns
    second = _publish(http)

    assert first.status_code == second.status_code == 200
    assert second.json()["post_id"] == first.json()["post_id"] == "post1"
    assert zernio.presigns == presigns and len(zernio.posts) == 1
    records = load_job_metadata(JOB, str(manual))[1]["shorts"][0]["published"]
    assert [r.get("intent_id") for r in records] == [INTENT]


def test_concurrent_double_submit_of_one_intent_posts_once(manual, zernio):
    async def scenario():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost",
                                     headers=ORIGIN) as client:
            return await asyncio.gather(*(client.post(f"/api/publish/{JOB}/0",
                                                      json=dict(PUBLISH, intent_id=INTENT))
                                          for _ in range(2)))

    responses = asyncio.run(scenario())
    assert [r.status_code for r in responses] == [200, 200]
    assert {r.json()["post_id"] for r in responses} == {"post1"}
    assert len(zernio.posts) == 1


def test_a_new_intent_is_an_explicit_republish(manual, zernio):
    http = TestClient(app_module.app, headers=ORIGIN)
    assert _publish(http).status_code == 200
    again = _publish(http, intent="0e1d2c3b4a594867a5b4c3d2e1f0a9b8")
    assert again.status_code == 200
    assert [p["_id"] for p in zernio.posts] == ["post1", "post2"]


def test_one_intent_id_on_two_clips_never_shares_a_provider_key(manual, zernio):
    http = TestClient(app_module.app, headers=ORIGIN)
    assert _publish(http, clip=0).status_code == 200
    assert _publish(http, clip=1).status_code == 200
    assert len(zernio.posts) == 2 and len(zernio.by_key) == 2
    assert all(INTENT not in key for key in zernio.by_key)       # derived, not echoed


def test_publish_without_an_intent_keeps_the_legacy_behaviour(manual, zernio):
    http = TestClient(app_module.app, headers=ORIGIN)
    assert _publish(http, intent=None).status_code == 200
    assert _publish(http, intent=None).status_code == 200
    assert len(zernio.posts) == 2 and zernio.by_key == {}


@pytest.mark.parametrize("bad", ["short", "has space in it", "x" * 65, "../../etc/passwd"])
def test_malformed_intent_id_is_rejected(manual, zernio, bad):
    r = _publish(TestClient(app_module.app, headers=ORIGIN), intent=bad)
    assert r.status_code == 422
    assert zernio.posts == []


def test_intent_does_not_bypass_monitor_ownership(manual, zernio):
    app_module.live_monitor._monitors["twitch:foo"] = _owning_monitor(manual, state="retry_wait")
    r = _publish(TestClient(app_module.app, headers=ORIGIN))
    assert r.status_code == 409
    assert zernio.posts == []
