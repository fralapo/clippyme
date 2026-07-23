# Task 4 report: Monitor passes `--monitor`, surfaces exhaustion in status

## Status: DONE

## Commit
`9cb07a3` — feat(monitor): pass --monitor; surface gemini_exhausted_at in status

## Changes

- `src/clippyme/domain/job_results.py`: `build_main_cmd` gained `monitor: bool = False`,
  appends `"--monitor"` to argv when true (same pattern as `no_zoom`/`skip_analysis`).
- `src/clippyme/domain/live_monitor.py`:
  - `LiveMonitor.__init__` adds `self._gemini_exhausted_at: str | None = None`.
  - `status()` and `snapshot()` expose/persist `gemini_exhausted_at` /
    `"gemini_exhausted_at"`; `restore()` rehydrates it from the snapshot dict.
  - `_submit_segment_job` and `_submit_url_job` now pass `monitor=True` to
    `build_main_cmd`.
  - `_await_and_publish`: after loading `result = self._jobs.get(job_id, {}).get("result") or {}`,
    checks `result.get("gemini_exhausted")` -> sets `_gemini_exhausted_at` (UTC
    ISO timestamp), persists, logs a warning. A segment that does yield clips
    clears `_gemini_exhausted_at` back to `None`. Existing per-clip publish
    loop is unchanged (already no-ops on empty `clips`).
- Tests: added `test_build_main_cmd_monitor_flag` /
  `test_build_main_cmd_no_monitor_by_default` to `tests/domain/test_job_results.py`;
  added `test_status_exposes_gemini_exhausted_at` to `tests/domain/test_live_monitor.py`
  (direct `LiveMonitor(...)` construction -- no `monitor_factory` fixture exists
  in this file, so I followed the file's existing pattern instead of inventing one).

## Test summary

`docker exec clippyme-backend pytest tests/domain/test_job_results.py tests/domain/test_live_monitor.py -v` -> 121 passed.
Full host suite `pytest -m "not integration"` -> 976 passed, 34 deselected.

## Concerns

None. Scope stayed to the four listed files; no unrelated files touched
(pre-existing untracked `.codex/`, `AGENTS.md`, and a modified `task-3-report.md`
in the working tree were left out of the commit).

## Follow-up fix: load_final_result dropped gemini_exhausted

Coordinator caught an integration gap: `_await_and_publish` reads
`result.get("gemini_exhausted")`, but `result` comes from
`load_final_result` (`src/clippyme/domain/job_results.py`), which only
returned `{'clips', 'cost_analysis', 'source_info'}` -- the pipeline's
top-level `gemini_exhausted` key from the metadata JSON was silently
dropped, so the notice could never fire end-to-end. `load_partial_result`
was intentionally left alone (a segment with zero clips already returns
`None` there, which is correct -- partial polls during a still-running
job shouldn't flag exhaustion prematurely).

Fix: `load_final_result` now also returns `'gemini_exhausted': data.get('gemini_exhausted')`.

Added `test_load_final_result_surfaces_gemini_exhausted` to
`tests/domain/test_job_results.py`: writes a `vid_metadata.json` with
`{"shorts": [], "gemini_exhausted": true}` to `tmp_path`, calls
`load_final_result("job1", str(tmp_path))`, asserts the returned dict's
`gemini_exhausted` is `True`.

### Test output

`docker exec clippyme-backend pytest tests/domain/test_job_results.py tests/domain/test_live_monitor.py -v` -> 122 passed.
Full host suite `pytest -m "not integration"` -> 977 passed, 34 deselected.

### Commit
`a774138` -- fix(monitor): load_final_result carries gemini_exhausted through
