"""publisher_mode field on ProcessRequest / BatchRequest (Task 4b).

Regular /api/process and /api/batch submissions need a publish-destination
choice mirroring LiveMonitorStartRequest.publisher_mode: "manual_queue"
(default) or "zernio". Anything else is rejected at the Pydantic boundary.
"""
import pytest
from pydantic import ValidationError

from clippyme.api.schemas import BatchRequest, ProcessRequest


def test_process_request_defaults_to_manual_queue():
    req = ProcessRequest(url="https://example.com/video")
    assert req.publisher_mode == "manual_queue"


def test_process_request_accepts_zernio():
    req = ProcessRequest(url="https://example.com/video", publisher_mode="zernio")
    assert req.publisher_mode == "zernio"


def test_process_request_rejects_bad_publisher_mode():
    with pytest.raises(ValidationError):
        ProcessRequest(url="https://example.com/video", publisher_mode="dropbox")


def test_batch_request_defaults_to_manual_queue():
    req = BatchRequest(urls=["https://example.com/video"])
    assert req.publisher_mode == "manual_queue"


def test_batch_request_accepts_zernio():
    req = BatchRequest(urls=["https://example.com/video"], publisher_mode="zernio")
    assert req.publisher_mode == "zernio"


def test_batch_request_rejects_bad_publisher_mode():
    with pytest.raises(ValidationError):
        BatchRequest(urls=["https://example.com/video"], publisher_mode="dropbox")
