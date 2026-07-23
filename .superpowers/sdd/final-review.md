# Final whole-branch review — codex/revert-manual-publish

Branch: `codex/revert-manual-publish` (base 9092393, worktree `.worktrees/revert-mp`).
Scope reviewed: cross-task integration seams, security regressions, revert
completeness, and I1/I2 closure by ff7a7ed. Per-task reviews assumed for
within-task correctness; test evidence (backend 961 / frontend 152 + lint +
build) accepted, not re-run.

## Verdict: NOT READY (one Important correctness regression)

Everything else is clean and merge-ready. The single blocker is a frontend↔backend
index-resolution seam that the per-task reviews structurally could not see. It is
narrow in trigger but violates an explicit requirement ("siblings' index-based
resolution intact") and ships to production.

---

## Important findings

### I-1 — `deleted_after_publish` skip breaks per-clip index resolution for manual UI actions
- Backend `_build_clips` now `continue`s past `deleted_after_publish` clips
  (`src/clippyme/domain/job_results.py:142`) for BOTH `only_ready` values,
  producing a result array that is contiguous by array-position but has a GAP in
  `shorts` index. It correctly stamps `clip['original_index'] = i` (absolute).
- The frontend, however, resolves every per-clip endpoint by **array position**,
  not `original_index`: `dashboard/src/redesign/results.jsx:170` renders
  `<ClipCard index={i} …>` and ClipCard calls `exportClip/onEdit/onPublish/
  onApplyToAll(index)`; `realApi.js` puts that array index straight into the URL
  (`composeClip`/`reframeClip`/`publishClip`/`exportClip(jobId, index)` →
  `resolve_clip(job_id, index)` reads `shorts[index]`). `original_index` is used
  ONLY as the React `key` (`c.original_index ?? i`), never for the backend call.
  `RedesignApp.jsx:337` passes the raw `results.clips` array straight through — no
  re-alignment.
- Net: for any job with a published-and-deleted **middle** clip, every clip after
  the gap mis-resolves. `require_file=True` endpoints (compose/publish/download)
  hit the deleted index → 404 "Clip file not found"; `require_file=False`
  endpoints (reframe `reframe_service.py:45`, transcript, edit-ai) can operate on
  the WRONG clip's metadata.
- Reachability: a monitor segment job where clip _i_ publishes (→ deleted+marked)
  but a neighbour fails Zernio (`_publish_one` returns without deleting on
  failure) leaves exactly such a gap. Surfaced to the user via History → restore
  (`clip_endpoints.py:restore_job_from_disk`, which ALSO drops missing-file clips
  and never sets `original_index` at all → same array/shorts skew).
- Note: the monitor's OWN auto-publish/delete flow is correct — it uses
  `clip.get("original_index")` throughout (`_publish_one`, `_compose_for_publish`,
  `_mark_clip_deleted`, `_delete_clip_artifacts`). Only MANUAL dashboard actions
  on a gapped job are affected.
- Fix (small, aligns with the backend's stated design): send
  `clip.original_index ?? index` from the per-clip call sites
  (ClipCard export/edit/publish/apply-to-all, `exportMany`/`publishMany`), and set
  `clip['original_index'] = i` in `restore_job_from_disk`. Alternatively, resolve
  server-side via `original_index`.

I1 (ghost entries) is genuinely CLOSED — the skip + the file-existence guards in
`scan_history` (`history_service.py:62`) and `restore_job_from_disk`
(`clip_endpoints.py:87`) mean a deleted clip never resurfaces. But the closure
method is what introduces I-1 above: the "no ghost" half is met, the "sibling
resolution intact" half is not (for the manual path).

## Critical findings
None. No data loss, no security regression, no silent wrong-publish to external
platforms (mis-resolved publish 404s on the missing file rather than uploading the
wrong clip).

---

## Confirmations (passed)

**Revert completeness** — `manual_publish_queue.py` (540 lines), `manualPublish.jsx`,
`manualShare.js`, all `test_manual_publish_*`/`manualShare.test` deleted. Grep of
`src/` and `dashboard/src/` for manual_publish / publisher_mode / manualQueue: only
two BENIGN stale comments in `live_monitor.py:254,275` that still list
`publisher_mode` as a rejected field (see Minors). Zernio-only restored:
`platforms` mandatory again via `LiveMonitorStartRequest`; `publisher_mode` gone
from `schemas.py`.

**I2 (drain-on-start)** — genuinely CLOSED. `LiveMonitor.start()`
(`live_monitor.py:617`) schedules `_drain_pending()` when a restored snapshot has
`publishing_enabled and _pending_publish`; `_drain_pending` is serialised by the
`_draining` guard (line 1181) and publishes through the shared `_publish_lock`, so
no interleave/double-publish. Pause mid-drain re-queues the popped entry
(`_publish_one` re-appends when `not publishing_enabled`) — no loss.

**Auto-resume × revert cherry-pick** — `resume_on_start` set on loop/vod monitors
(`start()` line 593), persisted in `_SNAPSHOT_CONFIG_FIELDS`/snapshot, `shutdown()`
retires with `disable_resume=False`, explicit stop clears it; `auto_resume()`
reloads creds from `config_store` (never snapshot) and never fails startup. Correct
against the post-revert API.

**Runtime config × catchup exclusion** — `catchup` is NOT in
`_UPDATABLE_CONFIG_FIELDS` (start-time only, as required) but IS in
`_SNAPSHOT_CONFIG_FIELDS` (survives restart). `live_only` is enforced in
`_schedule_backfill` (line 825) with defence-in-depth early-returns in
`_backfill_from_vod` (863) and `_recover_kick_backfill` (883) → zero pre-start
footage. `update_config` swaps `self.cfg` atomically; reads at use-time → applies
to next segment/publish only.

**Publish-delete × clip_filename resolution** — delete happens only AFTER a
confirmed publish (`_publish_one:1155-1159`); `_delete_clip_artifacts` removes
clip/source/`_cover.jpg` (naming matches `select_cover_frame`
`reframe.py:512`)/composed; `_mark_clip_deleted` marks (not removes) the `shorts`
entry so positions stay stable for `resolve_clip`. Metadata mark is race-free (job
already terminal before publish). No secrets in snapshot/pending
(`_SNAPSHOT_CONFIG_FIELDS` allow-list; pending stores `{job_id, clip}` public
metadata only).

**Security** — both new routes (`/api/live-monitor/{id}/config`,
`/publishing`) call `require_trusted_config_request` + rate-limit. Path traversal
via `clip_filename` blocked in `clip_filename_for` (rejects `/`, `\`, `..`,
`clip_resolve.py:42`). `update_config` non-dict body rejected 400 by
`validate_monitor_partial_update`.

**Task-3/4 pipeline** — viral-title sanitizer (`run_ops.clip_output_basename`)
handles Windows-forbidden chars, reserved names, length cap at word boundary,
always-unique `_clip_{i+1}` suffix. `clip_filename` persisted per clip with
per-iteration atomic re-dump (`main.py:837-848`); all four consumers
(`job_results`, `history_service`, `clip_endpoints.restore`, `reframe_service`)
resolve via `clip_filename_for`; legacy jobs fall through to `video_url` /
positional → byte-identical.

**Frontend T5** — `subtitleComposeParams.toComposeSubtitleParams` correctly
translates classic-mode keys (`outline_color`→`border_color`, `bg`→`bg_opacity`);
drawer seeds from `status().config` via `fromComposeSubtitleParams`; `apply()`
sends only allow-listed non-blank fields.

---

## Roll-up Minors — triage

Both roll-up Minors are ACCEPTABLE for merge (do not block):

- **`app.py:830 / 841` malformed-JSON → 500 not 400** (extended from the T1
  roll-up item, now also on `/publishing`). Trusted-origin-gated endpoint,
  cosmetic status code. Fix opportunistically (wrap `await request.json()` in
  try/except → 400), not a blocker.
- **`live_monitor.py:1269` registry double-persist** — harmless idempotent write.
  No action.

New Minors (also non-blocking):
- `live_monitor.py:254,275` — comments still list `publisher_mode` as a rejected
  updatable field though it no longer exists post-revert. Stale comment only.
- Settings drawer `apply()` sends every non-blank field (not strictly "touched")
  and cannot clear a field to empty. Minor UX; merge is a no-op, so harmless.

---

## Recommendation
Fix I-1 (wire the frontend per-clip calls + `restore_job_from_disk` to
`original_index`) before merge, or make an explicit, documented decision that
manual per-clip edits of partially-published monitor jobs may mis-resolve after a
publish-delete gap. Everything else is READY.

---

## Fix wave

**I-1** — every per-clip call site now resolves the backend clip id as
`clip.original_index ?? <array position>` instead of the raw array position:

- `dashboard/src/redesign/realApi.js` — `exportClip` resolves `apiIndex`
  internally (it already receives the `clip` object) before calling
  `composeClip`.
- `dashboard/src/lib/applyEdit.js` — `runApplyEdit` takes a new `apiIdx`
  param (defaults to `idx` for back-compat), used for `reframeClip`/
  `composeClip`; `idx` still keys local `updateClipState`/toast messages.
- `dashboard/src/redesign/RedesignApp.jsx` — `reprocessClip` (the single
  funnel for direct edit, "Apply to all", and bulk edit) now passes
  `apiIdx: clip.original_index ?? idx`.
- `dashboard/src/redesign/results.jsx` — the publish button and
  `publishMany` attach `_apiIdx: clip.original_index ?? index` alongside the
  existing `_idx` (array position, still used to key `clipStates`/progress).
- `dashboard/src/redesign/publish.jsx` — `PublishModal.run()` calls
  `publishClip(jobId, clip._apiIdx ?? clip._idx, ...)`; `clipStates`/progress
  lookups keep using `clip._idx` (array position) unchanged.
- `dashboard/src/redesign/captions.jsx` — `useManualTrim` (transcript +
  edit-ai) is seeded with `clip.original_index ?? idx`.
- `src/clippyme/domain/clip_endpoints.py` — `restore_job_from_disk` now
  mirrors `job_results._build_clips` exactly: skips `deleted_after_publish`
  entries and stamps `clip['original_index'] = i` (absolute `shorts`
  position) on every restored clip.

**Minor — app.py malformed JSON** — `/api/live-monitor/{id}/config` and
`/publishing` now wrap `await request.json()` in try/except → `HTTPException(400,
"Malformed JSON body")`, matching the existing `HTTPException(status_code=400,
...)` idiom used throughout `app.py`.

**Minor — stale comments** — `live_monitor.py:254` and the
`validate_monitor_partial_update` docstring (`:274`) no longer mention
`publisher_mode` (removed by the revert).

**Tests added**
- `tests/domain/test_restore_job.py` — `original_index` matches the array
  position in the no-gap case, and stays the ABSOLUTE `shorts` position (with
  the correct entries skipped) when a `deleted_after_publish` clip creates a
  gap.
- `tests/api/test_live_monitor_config_api.py` — malformed JSON on `/config`
  and `/publishing` → 400.
- `dashboard/src/redesign/realApi.test.js` — `exportClip` composes against
  `clip.original_index`, not the array position, given a fetch stub.
- `dashboard/src/lib/applyEdit.test.js` — `runApplyEdit` calls
  `reframeClip`/`composeClip` with `apiIdx`, independent of the local `idx`
  used for state/toasts.

**Verification**: backend `965 passed` (`pytest -m "not integration"`, up
from 961 — the 4 new tests) + `ruff check --select E9,F63,F7,F82` clean.
Frontend `154 passed` (up from 152) + `npm run lint` clean + `npm run build`
clean.

**Concerns**: none outstanding. `clip._idx` (array position, local state key)
and `clip._apiIdx`/`clip.original_index` (absolute `shorts` position, backend
call id) are now two distinct fields flowing through `PublishModal` —
intentional, since `clipStates` is still keyed by array position everywhere
else in the app; conflating the two would have just moved the bug from the
backend call to the local-state lookup.
