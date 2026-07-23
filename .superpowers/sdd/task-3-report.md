# Task 3 report — Zernio publishing pause/resume + delete-after-publish

## Status: complete

## Files changed
- `src/clippyme/domain/live_monitor.py` — toggle, pending queue, drain, delete-after-publish, registry method.
- `src/clippyme/api/app.py` — one new route `POST /api/live-monitor/{monitor_id}/publishing`.
- `tests/domain/test_live_monitor.py` — 6 new tests.

`api/schemas.py` NOT touched — the neighbouring live-monitor `/config` route reads the raw
`request.json()` body (no Pydantic model), so the publishing route matches that thin style.

## Requirement 5 metadata decision: MARK, not remove
`resolve_clip` (clip_resolve.py) and `_build_clips` (job_results.py) both index clips by
**list position** in `data["shorts"]` — `original_index == i` is the enumerate index, and
`resolve_clip(job_id, clip_index)` slices `clips[clip_index]`. Removing a `shorts` entry would
shift every later clip's position, so a still-present clip at old index N would resolve to the
wrong metadata (or 404) via compose/publish/smartcut/reframe endpoints.

Therefore the clip entry is **marked** `"deleted_after_publish": true` and only its files are
deleted. Positions stay stable; sibling clips' endpoints are untouched. I used a dedicated key
rather than `"published"` because `job_artifacts.record_clip_publish` already uses
`shorts[i]["published"]` as a **list** of publish records — reusing that key as a bool would
collide.

Artifacts deleted per clip (all via `_safe_remove`, idempotent): the raw clip, the composed/
uploaded file (`upload_path`, may equal the raw path — dedup by isfile), `source_<clipname>.mp4`,
`<stem>_cover.jpg` (reframe.py `select_cover_frame` naming), and `composed_clip_<original_index>.mp4`.
Filenames are resolved from `clip_path`'s basename (which itself flows from the
metadata/`clip_resolve` filename chain via `video_url`), not regex-guessed.

Empty-dir cleanup: after deletion, if no `*.mp4` remain in the job dir AND job status is
`completed`/`stopped`, `shutil.rmtree(..., ignore_errors=True)`. Guarded against a still-processing
job as required (the publish path only runs post-completion, but the guard is explicit).

All deletion is wrapped in one best-effort `try/except Exception` → logged, never raised
(requirement 6). The publish has already succeeded and `self._published`/`clips_published` are
committed before cleanup runs.

## Drain concurrency reasoning
- `set_publishing(True)` schedules `_drain_pending()` as a task on the monitor's loop (via
  `_track_task`, so `_run`'s finally awaits it before teardown). `RuntimeError` (no running loop)
  is caught and logged.
- Two drains can't interleave: a plain `self._draining` bool guard makes a second concurrent
  `_drain_pending()` return immediately. I did NOT hold `_publish_lock` across the whole drain —
  `_publish_one` acquires that same (non-reentrant) `asyncio.Lock` internally, so holding it around
  the loop would deadlock. Instead each publish inside the drain is serialised globally by
  `_publish_one`'s existing `_publish_lock`, which is exactly what preserves the shared
  `picked_slots` spacing across monitors.
- Spacing between drained clips: `await asyncio.sleep(PUBLISH_SPACING_SECONDS)` between entries
  (skipped before the first), mirroring `_await_and_publish`.
- Toggling back to paused mid-drain is safe: the while-loop checks `self.publishing_enabled` each
  iteration, and if a popped entry hits `_publish_one` while paused it re-appends itself to pending.

## Snapshot / restore
`publishing_enabled` (bool) and `pending_publish` (list of `{job_id, clip}`) round-trip through
`snapshot()`/`restore()` and are surfaced in `status()` (`pending_publish` as a count there). The
pending `clip` dicts hold only public clip metadata (title/hook/video_url path) — no secrets.

## Test evidence
Command (in container `clippyme-revert-test`, /workspace):
`python -m pytest -m 'not integration' -q` → **958 passed, 34 deselected**.
`ruff check src/clippyme tests --select E9,F63,F7,F82` → **All checks passed!**

New tests:
- `test_paused_publish_queues_instead_of_publishing` — paused → pending, publish_clip not called, snapshot/restore round-trip.
- `test_resume_drains_pending_in_order_with_spacing` — drain order + spacing sleep called.
- `test_successful_publish_deletes_clip_files_and_empty_dir` — files gone, last clip → dir rmtree'd.
- `test_successful_publish_keeps_dir_and_marks_metadata_when_clips_remain` — sibling kept, metadata marked.
- `test_deletion_failure_does_not_raise_and_clip_stays_published` — `os.remove` raising does not surface.
- `test_registry_set_publishing_unknown_id_raises_not_found` — route-level NotFoundError.

## Concerns / notes
- `_await_and_publish` still sleeps `PUBLISH_SPACING_SECONDS` between clips even while paused (each
  `_publish_one` just appends). Harmless (delays queueing only); left as-is to avoid complicating the
  loop.

## Fix wave

Addressed the two Important findings from `task-3-review.md`.

- **I1** — `job_results._build_clips`: added `if clip.get("deleted_after_publish"): continue`
  before filename resolution, so a deleted-after-publish entry is skipped unconditionally —
  including the `only_ready=False` final-result path that previously returned it with a dead
  `video_url`. The skip happens before `original_index` is assigned, so surviving clips keep
  their absolute position in `shorts` (no renumbering).
- **I2** — `live_monitor.LiveMonitor.start()`: after the run-loop task is created, if
  `publishing_enabled and self._pending_publish` it now schedules `_drain_pending()` via the
  existing `_track_task` helper. Reuses the existing drain path (no second interleave path);
  `_draining` guard still applies, so a concurrent `set_publishing(True)` toggle can't
  double-drain. `auto_resume()` and the registry's `start()` both call `mon.restore(snap)` then
  `mon.start(cfg)`, so a snapshot taken mid-drain now resumes draining automatically instead of
  sitting stuck until a manual pause→resume.

Files touched: `src/clippyme/domain/job_results.py`, `src/clippyme/domain/live_monitor.py`,
`tests/domain/test_job_results.py`, `tests/domain/test_live_monitor.py`.

New tests:
- `test_build_clips_skips_deleted_after_publish_even_in_final_result` — `only_ready=False` skips
  the deleted entry; siblings keep `original_index` 0 and 2 (no renumbering).
- `test_restored_monitor_with_pending_and_enabled_drains_on_start` — a monitor with
  `publishing_enabled=True` and a restored non-empty `_pending_publish` drains its one queued
  clip when `start()` runs (loop stubbed out), and `_draining` is released afterward.

### Test evidence
Command (in container `clippyme-revert-test`, `/workspace`):
`python -m pytest -m 'not integration' -q` → **960 passed, 34 deselected** (958 baseline + 2 new).
`ruff check src/clippyme tests --select E9,F63,F7,F82` → **All checks passed!**

### Concerns
- None new. M1–M4 from the review remain unaddressed (out of scope — Minor, not requested).
- Frontend wiring for the new toggle is out of scope (backend + route only).
