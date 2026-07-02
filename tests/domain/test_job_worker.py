"""Tests for clippyme.domain.job_worker.enqueue_output.

The log-reader thread feeds the job's user-visible log list. It must survive
non-UTF-8 bytes on the subprocess stream: before the fix, one bad byte raised
UnicodeDecodeError, the outer except ended the read loop, and the job's log
froze for the rest of the run while the subprocess kept working.
"""
import io

from clippyme.domain.job_worker import MAX_LOG_LINES, enqueue_output


def _run(stream_bytes, job_id="j", jobs=None):
    jobs = jobs if jobs is not None else {job_id: {"logs": []}}
    enqueue_output(io.BytesIO(stream_bytes), job_id, jobs)
    return jobs


def test_plain_lines_are_appended():
    jobs = _run(b"line one\nline two\n")
    assert jobs["j"]["logs"] == ["line one", "line two"]


def test_invalid_utf8_does_not_kill_the_reader():
    jobs = _run(b"good\n\xff\xfe mangled\nafter\n")
    logs = jobs["j"]["logs"]
    assert "good" in logs
    assert "after" in logs, "reader died on the invalid-UTF-8 line"
    assert any("mangled" in line for line in logs)


def test_blank_lines_are_skipped():
    jobs = _run(b"\n   \nreal\n")
    assert jobs["j"]["logs"] == ["real"]


def test_log_list_is_trimmed_to_max():
    payload = b"".join(b"l%d\n" % i for i in range(MAX_LOG_LINES + 50))
    jobs = _run(payload)
    logs = jobs["j"]["logs"]
    assert len(logs) == MAX_LOG_LINES
    assert logs[-1] == "l%d" % (MAX_LOG_LINES + 49)


def test_unknown_job_id_is_ignored():
    jobs = _run(b"orphan line\n", job_id="missing", jobs={"other": {"logs": []}})
    assert jobs["other"]["logs"] == []
