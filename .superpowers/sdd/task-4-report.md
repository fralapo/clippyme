
## Task 4c fix

Fixed the three consumers the review flagged as duplicating the pre-task-4
positional `<base>_clip_{i+1}.mp4` fallback instead of routing through
`clip_resolve.clip_filename_for`:

- `src/clippyme/domain/reframe_service.py` (`run_reframe`): removed a dead
  `filename = filename_from_video_url(...)` block (computed, never used) and
  replaced the separately-computed `original_clip_filename` (always
  positional) with `clip_filename_for(metadata_path, clip_data, clip_index)`.
  This name drives both `target_path` (overwrite-in-place) and `source_path`
  (`source_{name}`), so both now agree with the file main.py actually wrote.
- `src/clippyme/domain/clip_endpoints.py` (`restore_job_from_disk`): replaced
  the inline `filename_from_video_url` + positional-fallback pair with
  `clip_filename_for(meta_files[0], clip, i)`.
- `src/clippyme/domain/history_service.py` (`scan_history`): same
  replacement; moved the previously function-local `from
  clippyme.domain.url_utils import filename_from_video_url` import to an
  unused top-level `clip_resolve` import instead.

`clip_resolve.py` was not modified — confirmed it only imports
`errors`/`job_artifacts`/`url_utils` (no cycle risk importing it from
`reframe_service`/`clip_endpoints`/`history_service`).

Tests added: `tests/domain/test_reframe_service.py` (new file — `run_reframe`
had no prior test coverage; two cases via `asyncio.run` with
`create_subprocess_exec` monkeypatched: title-based `clip_filename` resolves
source/target to the persisted name, legacy metadata with no `clip_filename`
resolves via the positional fallback unchanged), plus one new case each in
`tests/domain/test_restore_job.py` and `tests/domain/test_history_service.py`
proving the title-based filename resolves; existing legacy-format cases in
both files (no `clip_filename`/`video_url` present) already exercise the
unchanged fallback path and continue to pass byte-identically.

Verification: `pytest -m "not integration" -q` → 952 passed, 34 deselected
(full host suite, run in `clippyme-revert-test`); `ruff check src/clippyme
tests --select E9,F63,F7,F82` → all checks passed.
resources/bin/docker.exe" \
  exec clippyme-revert-test sh -lc "ruff check src/clippyme tests --select E9,F63,F7,F82"
```
Output: `All checks passed!`

(One iteration: my first `test_whitespace_runs_collapsed_but_spaces_kept`
used `\t\t` as the whitespace run — tabs are ASCII control chars 0-31 and
get stripped outright by the forbidden-char pass rather than collapsed,
so `"a   b\t\tc"` sanitizes to `"a bc"`, not `"a b c"`. Fixed the test to
use a literal space run instead; behavior in `run_ops.py` was correct as
written.)

## CRITICAL CONCERN — the resolve chain does NOT keep working as briefed

The brief states: *"metadata `video_url` carries the real filename, so
resolve chain is unaffected"* and asks me to confirm this by reading
`clip_resolve.py:34-41` and `job_results.py:136`. Having read both (plus
the surrounding call graph), **this claim does not hold for freshly
completed jobs**, and the change as scoped will 404 every clip video
immediately after a job finishes, until the clip goes through
smartcut/reframe (which persist `video_url` to disk).

Trace:

1. `main.py` never writes `clip['video_url']` into `clips_data['shorts']`
   before saving `{video_title}_metadata.json` (the only metadata save in
   the pipeline, at main.py:813-817, which happens *before* the per-clip
   cut loop even decides filenames). So a freshly processed job's
   metadata.json has **no `video_url` field on any clip, ever**.
2. `domain/job_results.py:_build_clips` (called by both
   `load_partial_result` and `load_final_result`, i.e. every
   `/api/status` poll and the final result the frontend renders) does
   **not** read `clip_info.get("video_url")` at all — it unconditionally
   recomputes `clip_filename = f"{base_name}_clip_{i+1}.mp4"` (line 136)
   and overwrites `clip['video_url']` with that (line 141), where
   `base_name` is the **source video's** title (`video_title` in
   main.py), never the per-clip Gemini title. This is the path that
   actually serves the dashboard.
3. `domain/clip_resolve.py:clip_filename_for` (used by
   smartcut/transcript/edit-ai/compose/publish endpoints) *does* try
   `clip_info.get("video_url")` first, but since main.py never persists
   it (point 1), that lookup is empty for a fresh job and it falls
   through to the same `f"{base_name}_clip_{clip_index+1}.mp4"` legacy
   convention (line 39-40) — again keyed on the source title, not the
   clip title.
4. `video_url` only gets *persisted to disk* by
   `domain/reframe_service.py` (post-hoc reframe switch) and
   `domain/clip_endpoints.py` (smart cut) — both one-shot user actions
   that happen strictly after the clip already exists under whatever
   name the pipeline gave it. Before either of those runs, nothing in
   the metadata file points at the new Gemini-title filename.

Net effect of this task as implemented: the on-disk file is named
`<sanitized Gemini title>_clip_{i+1}.mp4`, but every consumer that
serves it to the frontend (`_build_clips`, and `clip_resolve`'s
fallback) still looks for `<video_title>_clip_{i+1}.mp4` — a file that
no longer exists. Every clip video 404s until the user triggers a
smartcut or reframe action on it (which recomputes and persists the
*correct* `video_url` from whatever `clip_resolve.clip_filename_for`
resolves at that moment — but by then it's already broken once).

I did **not** touch `domain/job_results.py` or `domain/clip_resolve.py`
per the scope guard (another task owns them), and did not widen scope to
"fix" this myself. This needs one of:
- `job_results._build_clips` reading `clip_info.get("video_url")` first
  (mirroring `clip_resolve.clip_filename_for`'s already-correct pattern)
  and falling back to the legacy convention only when absent, **and**
  `main.py` persisting the real `video_url`/filename per clip into
  `clips_data['shorts'][i]` before or as it names each file, or
- some other reconciliation between the domain layer and this pipeline
  change that the sibling domain/api task is responsible for.

Flagging this explicitly rather than silently shipping a change that
looks complete under the host test suite (which only exercises the pure
function, not the cross-module resolve chain) but breaks video playback
in the running app.

## Status

DONE_WITH_CONCERNS — implementation matches the brief's literal file
list and constraints exactly, tests pass, ruff clean, commit made. The
concern above is a genuine integration break outside my scope (domain/)
that must be resolved by the task owning `job_results.py`/
`clip_resolve.py` before this is safe to ship together.

## Task 4b fix

Addressed the CRITICAL CONCERN above end-to-end.

### Dump-order finding (confirmed)

Traced `main.py`: the metadata dump (`json.dump(clips_data, f, indent=2)` +
`os.replace`) sits at what was line 813-817, **inside** the `else:` branch
but **before** the `for i, clip in enumerate(clips_data['shorts'])` cut loop
that starts a few lines later (~821). `clip_basename` /`clip_filename` are
computed *inside* that loop (~831-832), so at the time of the first dump no
clip has a computed basename yet — writing `clip['clip_filename']` there
alone would never reach disk. Fix: set `clip['clip_filename']` right where
`clip_basename` is computed (in-loop, one line), then added a **second**
dump — same tmp-file + `os.replace` pattern, reusing the existing
`metadata_tmp`/`metadata_file` variables, no new writer — immediately after
the `for` loop closes (still inside the `else:` block, same indentation as
the loop itself) so the final on-disk metadata reflects every clip's real
`clip_filename`. Partial-result polls *during* a still-running job won't see
`clip_filename` until the loop finishes (pre-existing limitation, not
introduced here — the original single pre-loop dump had the same gap for
positional filenames); `load_final_result`/`_build_clips`, the path that
actually 404'd per the concern above, is fully fixed.

### Other decisions

- `clip_resolve.clip_filename_for` preference chain: `clip_filename` (str,
  non-empty, no `/`, `\`, or `..`) → `video_url` → positional
  `{base}_clip_{i+1}.mp4`. Tampered/malformed `clip_filename` (path
  separators, `..`, wrong type, empty) falls through silently to the next
  link, never raises.
- `job_results._build_clips`: no import cycle (`clip_resolve` only imports
  `job_artifacts`/`url_utils`/`errors`, none of which import `job_results`),
  so it now calls `clip_resolve.clip_filename_for` directly instead of
  duplicating the chain. `clip_filename_for` takes a `metadata_path` (used
  only for `os.path.basename(...).replace("_metadata.json", "")` in the
  fallback branch); `_build_clips` only has `base_name` on hand, so it
  builds a synthetic `f"{base_name}_metadata.json"` string to pass through
  — the file need not exist, it's a string op only.
- Added 4 tests to `tests/domain/test_clip_resolve.py`
  (`clip_filename_for` preference + tamper-rejection + positional
  byte-identical fallback, plus one `resolve_clip` end-to-end test with
  new-format metadata) and 3 to `tests/domain/test_job_results.py`
  (`_build_clips` with `clip_filename`, legacy metadata unchanged, tampered
  `clip_filename` ignored).

### Test command + output tail

```
MSYS_NO_PATHCONV=1 "/c/Program Files/Docker/Docker/resources/bin/docker.exe" \
  exec clippyme-revert-test sh -lc "python -m pytest -m 'not integration' -q"
```
```
939 passed, 34 deselected, 1 warning in 19.73s
```
(925 baseline from task 4 + 14 new: 12 already existed for
`clip_output_basename` in `test_run_ops.py`, 2 net-new here bring the
delta to +14 vs the 925 reported by task 4 — 7 in `test_clip_resolve.py`
and 7 in `test_job_results.py` when counting both new test functions and
parametrized cases individually.)

Ruff:
```
MSYS_NO_PATHCONV=1 "/c/Program Files/Docker/Docker/resources/bin/docker.exe" \
  exec clippyme-revert-test sh -lc "ruff check src/clippyme tests --select E9,F63,F7,F82"
```
```
All checks passed!
```

### Status

DONE. Commit `6a415c8` on `codex/revert-manual-publish`, scoped to
`src/clippyme/pipeline/main.py`, `src/clippyme/domain/clip_resolve.py`,
`src/clippyme/domain/job_results.py`, and the two test files. Did not
touch `live_monitor.py` or `api/app.py`.

### Follow-up: per-iteration re-dump (progressive partial results)

The single post-loop dump above fixed `load_final_result` but left a real
UX regression the coordinator caught: during processing, a finished clip
sits on disk under the new sanitized name while metadata still lacks
`clip_filename` until the *whole* cut loop finishes. `/api/status` polls
`_build_clips(..., only_ready=True)`, which — lacking `clip_filename` —
recomputes the stale positional name, finds no file at that path for any
clip, and the dashboard shows **zero clips for the entire job duration**
instead of filling in progressively (the pre-task-4 behavior, where the
positional name matched during processing too).

Fix: moved the atomic tmp+`os.replace` metadata re-dump from after the
`for` loop to **inside** it, right after `clip['clip_filename'] = clip_filename`
is set for that iteration — same write, same variables
(`metadata_tmp`/`metadata_file`), no new writer. Removed the now-redundant
post-loop dump (the last iteration's in-loop dump already leaves the final
state on disk). N clips is small (≤~10 per job), so N small atomic writes
per job is a non-issue.

Added `tests/domain/test_job_results.py::test_build_clips_partial_job_mid_processing_first_clip_ready`:
metadata with clip 1 carrying `clip_filename` (+ file on disk) and clip 2
with no `clip_filename` (not yet cut) → `_build_clips(only_ready=True)`
returns exactly clip 1 (by its real filename) and skips clip 2, proving the
partial-result path now surfaces ready clips progressively instead of
requiring the whole job to finish.

Test command + tail:
```
MSYS_NO_PATHCONV=1 "/c/Program Files/Docker/Docker/resources/bin/docker.exe" \
  exec clippyme-revert-test sh -lc "python -m pytest -m 'not integration' -q"
```
```
940 passed, 34 deselected, 1 warning in 15.52s
```
Ruff (`ruff check src/clippyme tests --select E9,F63,F7,F82`): `All checks passed!`

Commit `b6c246a` on `codex/revert-manual-publish`, scoped to
`src/clippyme/pipeline/main.py` and `tests/domain/test_job_results.py`
only (`clip_resolve.py`/`job_results.py` needed no further change — the
resolution chain from the first commit already reads `clip_filename` when
present).
