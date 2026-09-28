"""Local Zernio contract: the vendored OpenAPI spec vs what the client parses.

No live call. Two halves:

* the spec (``docs/vendor/zernio-openapi.yaml``, re-synced with
  docs.zernio.com) still documents every field/header/code the code relies
  on, read from the exact operation/response block — a re-vendored spec that
  renames one fails here;
* a spec-shaped HTTP answer goes through the real ``ZernioClient._request``
  → ``publish_clip`` / monitor classification, so a parser drift fails too.
"""
import json
from pathlib import Path

import pytest
import requests

from clippyme.domain import live_monitor as lm
from clippyme.integrations import social_publisher as sp

SPEC = Path(__file__).resolve().parents[2] / "docs" / "vendor" / "zernio-openapi.yaml"


def _block(lines, key):
    """Lines nested under the first ``key`` line (stripped match), by indent."""
    for i, line in enumerate(lines):
        if line.strip() == key:
            indent = len(line) - len(line.lstrip())
            out = []
            for child in lines[i + 1:]:
                if child.strip() and len(child) - len(child.lstrip()) <= indent:
                    break
                out.append(child)
            return out
    raise AssertionError(f"{key!r} not found in the vendored spec block")


@pytest.fixture(scope="module")
def spec_lines():
    return SPEC.read_text(encoding="utf-8").splitlines()


def test_presign_answers_upload_and_public_urls(spec_lines):
    ok = _block(_block(_block(_block(spec_lines, "/v1/media/presign:"), "post:"),
                       "responses:"), "'200':")
    text = "\n".join(ok)
    assert "uploadUrl:" in text and "publicUrl:" in text


def test_create_post_contract_the_publisher_relies_on(spec_lines):
    create = _block(_block(spec_lines, "/v1/posts:"), "post:")
    params = "\n".join(_block(create, "parameters:"))
    assert "- name: Idempotency-Key" in params and "- name: x-request-id" in params

    responses = _block(create, "responses:")
    created = "\n".join(_block(responses, "'201':"))
    assert "post:" in created and "_id:" in created  # {post: {_id}}

    conflict = _block(responses, "'409':")
    headers = "\n".join(_block(conflict, "headers:"))
    body = "\n".join(_block(conflict, "content:"))
    assert "Retry-After:" in headers
    assert "enum: [idempotency_conflict]" in body     # in-progress conflict
    assert "existingPostId:" in body                  # duplicate content


class _Resp:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _client_answering(monkeypatch, response):
    client = sp.ZernioClient("sk_test")
    monkeypatch.setattr(client._session, "request", lambda method, url, **kw: response)
    return client


def test_in_progress_conflict_is_retried_after_its_retry_after(monkeypatch):
    client = _client_answering(monkeypatch, _Resp(
        409, {"error": "Request in progress", "code": "idempotency_conflict"},
        {"Retry-After": "7"}))
    with pytest.raises(sp.ZernioError) as info:
        client.create_post(content="c", media_items=[], platforms=[], request_id="k-1")
    exc = info.value
    assert exc.code == "idempotency_conflict" and exc.retry_after == "7"
    assert lm.classify_publish_error(exc) == "retry"
    assert lm.retry_after_seconds(exc) == 7.0
    assert not lm._definitely_not_created(exc)   # same key on the retry


def test_duplicate_content_conflict_counts_as_already_posted(monkeypatch):
    client = _client_answering(monkeypatch, _Resp(
        409, {"error": "This exact content is already scheduled",
              "details": {"existingPostId": "p9", "platform": "tiktok"}}))
    with pytest.raises(sp.ZernioError) as info:
        client.create_post(content="c", media_items=[], platforms=[], request_id="k-1")
    assert info.value.code is None
    assert lm.classify_publish_error(info.value) == "duplicate"


def test_publish_clip_reads_the_documented_201_answer(tmp_path, monkeypatch):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    answers = {"/media/presign": _Resp(200, {"uploadUrl": "https://up.example/1",
                                             "publicUrl": "https://cdn.example/1.mp4"}),
               "/posts": _Resp(201, {"post": {"_id": "65f1c0a9", "status": "scheduled"},
                                     "message": "Post scheduled successfully"})}
    sent = []

    def request(self, method, url, **kwargs):
        sent.append((method, url.split("/api/v1", 1)[-1], kwargs.get("headers") or {}))
        if method == "GET":
            return _Resp(200, {"posts": []})
        return answers[url.split("/api/v1", 1)[-1]]

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setattr(sp.requests, "put", lambda *a, **k: _Resp(200, {}))
    monkeypatch.setattr(sp, "_reject_internal_upload_url", lambda url: None)
    result = sp.publish_clip(api_key="k", clip_path=str(clip), title="t", caption="c",
                             platform_targets=[{"platform": "tiktok", "accountId": "a"}],
                             request_id="r-1")
    assert result["post_id"] == "65f1c0a9"
    create_headers = [h for m, path, h in sent if m == "POST" and path == "/posts"][0]
    assert create_headers["Idempotency-Key"] == "r-1" == create_headers["x-request-id"]
