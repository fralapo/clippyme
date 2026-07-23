"""POST /api/live-monitor/{monitor_id}/config — runtime config updates.

TestClient is used WITHOUT its context manager so the FastAPI lifespan never
starts (matches tests/api/test_reframe_aspect_api.py). We inject a fake
monitor directly into the app's live_monitor registry rather than driving a
real asyncio monitor task.
"""
from fastapi.testclient import TestClient

from clippyme.api import app as app_module

ORIGIN = {"Origin": "http://localhost:5175"}


class _FakeMonitor:
    id = "kick:foo"

    def update_config(self, partial):
        self.received = partial
        return {"min_gap_seconds": partial.get("min_gap_seconds", 900)}

    def snapshot(self):
        return {"platform": "kick", "channel": "foo"}


def teardown_function():
    app_module.live_monitor._monitors.pop("kick:foo", None)


def test_update_config_success():
    fake = _FakeMonitor()
    app_module.live_monitor._monitors["kick:foo"] = fake
    client = TestClient(app_module.app, headers=ORIGIN)

    r = client.post("/api/live-monitor/kick:foo/config", json={"min_gap_seconds": 120})

    assert r.status_code == 200, r.text
    assert r.json() == {"monitor": {"min_gap_seconds": 120}}
    assert fake.received == {"min_gap_seconds": 120}


def test_update_config_unknown_monitor_404():
    client = TestClient(app_module.app, headers=ORIGIN)
    r = client.post("/api/live-monitor/kick:nope/config", json={"min_gap_seconds": 120})
    assert r.status_code == 404, r.text


def test_update_config_untrusted_origin_rejected():
    fake = _FakeMonitor()
    app_module.live_monitor._monitors["kick:foo"] = fake
    client = TestClient(app_module.app, headers={"Origin": "https://evil.example"})

    r = client.post("/api/live-monitor/kick:foo/config", json={"min_gap_seconds": 120})

    assert r.status_code in (403, 400)


def test_update_config_malformed_json_400():
    fake = _FakeMonitor()
    app_module.live_monitor._monitors["kick:foo"] = fake
    client = TestClient(app_module.app, headers=ORIGIN)

    r = client.post(
        "/api/live-monitor/kick:foo/config",
        content=b"{not json",
        headers={**ORIGIN, "Content-Type": "application/json"},
    )

    assert r.status_code == 400, r.text


def test_set_publishing_malformed_json_400():
    fake = _FakeMonitor()
    app_module.live_monitor._monitors["kick:foo"] = fake
    client = TestClient(app_module.app, headers=ORIGIN)

    r = client.post(
        "/api/live-monitor/kick:foo/publishing",
        content=b"{not json",
        headers={**ORIGIN, "Content-Type": "application/json"},
    )

    assert r.status_code == 400, r.text



def test_stop_malformed_json_400():
    fake = _FakeMonitor()
    app_module.live_monitor._monitors["kick:foo"] = fake
    client = TestClient(app_module.app, headers=ORIGIN)

    r = client.post(
        "/api/live-monitor/stop",
        content=b"{not json",
        headers={**ORIGIN, "Content-Type": "application/json"},
    )

    assert r.status_code == 400, r.text
    assert app_module.live_monitor._monitors["kick:foo"] is fake
