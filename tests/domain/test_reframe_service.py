"""run_reframe must resolve the clip's on-disk filename via clip_resolve
(clip_filename_for) rather than re-deriving the pre-task-4 positional
`<base>_clip_{i+1}.mp4` pattern. A job produced after task 4 renders clips
under a sanitized-title filename persisted as `clip_filename` in metadata —
the old positional guess pointed at a file that doesn't exist for such jobs,
so the 409 "source slice not available" guard fired for every post-hoc
reframe attempt.

asyncio.create_subprocess_exec is monkeypatched (no real subprocess); we
assert the source/target paths the function computes and writes back.
"""
import asyncio
import json
import os

from clippyme.domain import reframe_service


class _FakeProc:
    returncode = 0

    async def communicate(self):
        return (b"", None)


async def _fake_exec(*cmd, **kwargs):
    return _FakeProc()


def _run(**kwargs):
    return asyncio.run(reframe_service.run_reframe(**kwargs))


def test_run_reframe_resolves_title_based_clip_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(reframe_service.asyncio, "create_subprocess_exec", _fake_exec)
    job_id = "55555555-5555-4555-8555-555555555555"
    output_root = str(tmp_path)
    job_dir = os.path.join(output_root, job_id)
    os.makedirs(job_dir)

    clip_filename = "epic_moment_clip_1.mp4"
    meta = {
        "aspect": "9:16",
        "shorts": [{"start": 0.0, "end": 5.0, "clip_filename": clip_filename}],
    }
    with open(os.path.join(job_dir, "vid_metadata.json"), "w") as f:
        json.dump(meta, f)
    # Source slice must live under the TITLE-based name, not the positional one.
    open(os.path.join(job_dir, f"source_{clip_filename}"), "wb").close()

    result = _run(job_id=job_id, clip_index=0, mode="auto", output_root=output_root, jobs={})

    assert result["success"] is True
    assert result["new_video_url"].startswith(f"/videos/{job_id}/{clip_filename}?v=")
    with open(os.path.join(job_dir, "vid_metadata.json")) as f:
        saved = json.load(f)
    assert saved["shorts"][0]["video_url"] == f"/videos/{job_id}/{clip_filename}"


def test_run_reframe_legacy_positional_fallback_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(reframe_service.asyncio, "create_subprocess_exec", _fake_exec)
    job_id = "66666666-6666-4666-8666-666666666666"
    output_root = str(tmp_path)
    job_dir = os.path.join(output_root, job_id)
    os.makedirs(job_dir)

    # Legacy metadata: no clip_filename, no video_url -> positional fallback.
    meta = {"aspect": "9:16", "shorts": [{"start": 0.0, "end": 5.0}]}
    with open(os.path.join(job_dir, "vid_metadata.json"), "w") as f:
        json.dump(meta, f)
    open(os.path.join(job_dir, "source_vid_clip_1.mp4"), "wb").close()

    result = _run(job_id=job_id, clip_index=0, mode="auto", output_root=output_root, jobs={})

    assert result["success"] is True
    assert result["new_video_url"].startswith(f"/videos/{job_id}/vid_clip_1.mp4?v=")
