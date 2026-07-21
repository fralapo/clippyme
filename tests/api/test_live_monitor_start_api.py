from fastapi.testclient import TestClient

from clippyme.api import app as app_module


ORIGIN = {"Origin": "http://localhost:5175"}


class _Registry:
    def __init__(self):
        self.configs = []

    def start(self, config):
        self.configs.append(config)
        return config


def test_live_monitor_start_manual_queue_accepts_no_zernio_platforms(monkeypatch):
    registry = _Registry()
    monkeypatch.setattr(app_module, "live_monitor", registry)
    client = TestClient(app_module.app, headers=ORIGIN)

    response = client.post("/api/live-monitor/start", json={"slug": "grenbaud"})

    assert response.status_code == 200
    assert registry.configs == [{
        "slug": "grenbaud", "platform": "kick", "mode": "live", "platforms": None,
        "segment_seconds": 1800, "prelive_skip_seconds": 1800, "min_gap_seconds": 900,
        "poll_interval": None, "loop": False, "caption_template": "", "title_template": "",
        "instructions": None, "timezone": None, "banner": None, "compose": None,
        "publisher_mode": "manual_queue",
    }]


def test_live_monitor_start_zernio_requires_platforms_and_rejects_unknown_mode(monkeypatch):
    registry = _Registry()
    monkeypatch.setattr(app_module, "live_monitor", registry)
    client = TestClient(app_module.app, headers=ORIGIN)

    assert client.post("/api/live-monitor/start", json={
        "slug": "grenbaud", "publisher_mode": "zernio",
    }).status_code == 422
    assert client.post("/api/live-monitor/start", json={
        "slug": "grenbaud", "publisher_mode": "webhook",
    }).status_code == 422
    assert registry.configs == []
