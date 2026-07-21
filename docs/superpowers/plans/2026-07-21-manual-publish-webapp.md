# Manual Publishing Webapp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent mobile manual-publishing queue selectable instead of Zernio, with native sharing, reversible completion, and clip-level History deletion.

**Architecture:** A focused `manual_publish_queue.py` domain owns atomic queue state and immutable per-entry artifacts. API handlers remain thin; Live Monitor dispatches completed clips to either Zernio or this queue. The React redesign adds a mobile queue surface while reusing the existing History and Monitor data flows.

**Tech Stack:** Python 3.11, FastAPI, pathlib/atomic JSON, React 18, Vite 5, Vitest/jsdom, Web Share API Level 2.

## Global Constraints

- `publisher_mode` is exactly `manual_queue` or `zernio`; manual queue is the UI default.
- Marking completed never deletes History files; completion is reversible.
- Deleting a clip removes its queue entries and artifacts; deleting the last clip removes the whole project directory.
- Queue video paths are resolved under `output/<uuid>` and never accepted directly from clients.
- Queue state uses atomic tmp + `os.replace` writes with mode `0600`.
- Manual queue clips use the same final compose recipe as Zernio clips.
- Mobile share requires secure context + `navigator.share` + `navigator.canShare({files})`; copy/download always remain available.
- Existing Zernio behavior remains unchanged when explicitly selected.
- No restart or mutation of the currently running monitor occurs until all code and tests are complete.

---

### Task 1: Persistent manual queue domain and API

**Files:**
- Create: `src/clippyme/domain/manual_publish_queue.py`
- Create: `tests/domain/test_manual_publish_queue.py`
- Modify: `src/clippyme/api/schemas.py`
- Modify: `src/clippyme/api/app.py`

**Interfaces:**
- Produces `ManualPublishQueue(output_dir: Path, state_path: Path)`.
- Produces `enqueue(*, job_id, clip_index, source_path, title, caption, source_platform, source_channel, source_kind, project_title, monitor_id=None) -> dict`.
- Produces `list_entries(status="pending")`, `complete(entry_id)`, `restore(entry_id)`, `remove_job(job_id)`, `remove_clip(job_id, clip_index)`, `resolve_video(entry_id) -> Path`, and race-safe `open_video(entry_id) -> BinaryIO` for API streaming.
- Produces API routes under `/api/manual-publish`.

- [ ] **Step 1: Write failing domain tests** for atomic reload, pending/completed transitions, restore, deterministic grouping fields, path confinement, missing artifact pruning, hardlink freeze with copy fallback, and job/clip cleanup.

- [ ] **Step 2: Run RED tests** with `pytest tests/domain/test_manual_publish_queue.py -q`; expect import/attribute failures.

- [ ] **Step 3: Implement the queue domain** with a private `threading.RLock`, UUID entry IDs, UTC timestamps, state validation, `save_job_metadata`-style atomic writes, hardlink then `shutil.copy2`, and strict resolved-path checks.

- [ ] **Step 4: Run GREEN domain tests** and expect all queue tests to pass.

- [ ] **Step 5: Write failing API tests** covering list, complete, restore, authenticated video response, bad entry IDs, and trusted-request mutation guards.

- [ ] **Step 6: Add thin API handlers** and one app-lifespan queue instance; use `FileResponse(media_type="video/mp4")` for resolved artifacts only.

- [ ] **Step 7: Run API/domain tests and ruff**, then commit `feat: add persistent manual publish queue`.

### Task 2: Clip-level History deletion and queue cleanup

**Files:**
- Modify: `src/clippyme/domain/history_service.py`
- Modify: `src/clippyme/domain/clip_endpoints.py`
- Modify: `src/clippyme/api/app.py`
- Modify: `tests/domain/test_history_service.py`
- Modify: `tests/domain/test_manual_publish_queue.py`

**Interfaces:**
- Produces `delete_history_clip(job_id, clip_index, output_dir, queue) -> dict` returning `{"project_deleted": bool, "remaining": int}`.
- Whole-project deletion calls `queue.remove_job(job_id)` before deleting the directory.

- [ ] **Step 1: Write failing tests** proving one clip deletion removes base/source/composed/cover/manual artifacts and metadata entry, reindexes surviving metadata safely, removes queue records, and deletes the project directory when the last clip is removed.

- [ ] **Step 2: Run RED tests** and verify failure because clip deletion does not exist.

- [ ] **Step 3: Implement one domain operation** using `resolve_clip`/metadata helpers and explicit project-root confinement; do not duplicate endpoint resolution logic.

- [ ] **Step 4: Add `DELETE /api/history/{job_id}/clips/{clip_index}`** with the same validation/security as project deletion and make whole-project deletion queue-aware.

- [ ] **Step 5: Run GREEN tests and ruff**, then commit `feat: add clip-level history cleanup`.

### Task 3: Destination selection and Live Monitor dispatch

**Files:**
- Modify: `src/clippyme/api/schemas.py`
- Modify: `src/clippyme/domain/live_monitor.py`
- Modify: `src/clippyme/domain/job_submission.py` or the existing Create request flow selected during implementation
- Modify: `tests/domain/test_live_monitor.py`
- Add/modify the relevant API schema tests.

**Interfaces:**
- `LiveMonitorStartRequest.publisher_mode: Literal["manual_queue", "zernio"] = "manual_queue"`.
- Zernio `platforms` validation is conditional on `publisher_mode == "zernio"`.
- `LiveMonitor` receives the shared `ManualPublishQueue` and routes each composed clip through `_deliver_one`.
- Snapshot persists `publisher_mode` and sufficient start config for controlled resume.

- [ ] **Step 1: Write failing schema tests** for manual mode without Zernio targets, Zernio mode requiring targets, and invalid modes.

- [ ] **Step 2: Write failing monitor tests** proving manual delivery composes then enqueues, never calls Zernio, records a separate queued guard, retries failed enqueue, and preserves existing Zernio behavior.

- [ ] **Step 3: Run RED tests** and verify expected validation/dispatch failures.

- [ ] **Step 4: Implement conditional schemas and `_deliver_one` dispatch**, preserving the global Zernio scheduler only for Zernio mode and persisting manual queue IDs separately from `_published`.

- [ ] **Step 5: Persist complete resumable monitor config** without secrets; secrets are reloaded from Settings at resume time and never written to monitor state.

- [ ] **Step 6: Add a one-shot importer** that queues existing un-published `kick:grenbaud` clips and skips metadata entries with successful Zernio publish records.

- [ ] **Step 7: Run monitor/schema tests and ruff**, then commit `feat: route jobs and monitors to manual queue`.

### Task 4: Mobile queue webapp and destination controls

**Files:**
- Create: `dashboard/src/redesign/manualPublish.jsx`
- Create: `dashboard/src/redesign/manualPublish.test.jsx`
- Create: `dashboard/src/lib/manualShare.js`
- Create: `dashboard/src/lib/manualShare.test.js`
- Modify: `dashboard/src/redesign/realApi.js`
- Modify: `dashboard/src/redesign/RedesignApp.jsx`
- Modify: `dashboard/src/redesign/chrome.jsx`
- Modify: `dashboard/src/redesign/create.jsx`
- Modify: `dashboard/src/redesign/live.jsx`
- Modify: `dashboard/src/redesign/views.jsx`

**Interfaces:**
- `shareClip({videoUrl, filename, caption}) -> Promise<{shared?, cancelled?, fallback?, error?}>`.
- New API functions `getManualQueue`, `completeManualEntry`, `restoreManualEntry`, `deleteHistoryClip`.
- Queue UI exposes `pending`, `completed`, `history`, and `monitor` touch-friendly tabs.

- [ ] **Step 1: Write failing pure tests** for secure-context/capability detection, MP4 `File` creation, cancellation, copy fallback, and download fallback.

- [ ] **Step 2: Run RED frontend tests** and verify missing module/component failures.

- [ ] **Step 3: Implement `manualShare.js` minimally**, keeping caption copy independent because share targets may ignore text.

- [ ] **Step 4: Write failing component tests** for grouped ordering (platform/channel/project/clip), pending/completed tabs, complete/restore, History single-clip delete, responsive card controls, and empty/error states.

- [ ] **Step 5: Implement the mobile queue view and API wiring** using existing primitives, 44px minimum touch targets, sticky tab bar, lazy video preload, and no new component library.

- [ ] **Step 6: Add `Publish destination` controls** to Create and Live Monitor; hide/disable Zernio account targets in manual mode and send `publisher_mode` in requests.

- [ ] **Step 7: Run `npm test`, `npm run lint`, and `npm run build`**, then commit `feat: add mobile manual publishing webapp`.

### Task 5: Migration, documentation, and deployment verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example` only if a new runtime setting is truly required
- Modify: `docs/architecture-history.md`
- Test: existing backend/frontend suites and Docker smoke checks

**Interfaces:**
- Tailscale Serve documentation points HTTPS at `http://127.0.0.1:5175` and explains Web Share secure-context requirements.
- Migration script/command is kept under ignored `tmp/`, never committed.

- [ ] **Step 1: Run full backend host tests** with `pytest -m "not integration" -q`; only the documented Windows path assertion may remain failing.

- [ ] **Step 2: Run ruff and complete frontend verification**; expect clean lint and successful build.

- [ ] **Step 3: Run final code review** over the entire branch and fix all Critical/Important findings with covering tests.

- [ ] **Step 4: Update README and architecture history** with queue semantics, mobile HTTPS/Tailscale Serve setup, History deletion behavior, and destination selection.

- [ ] **Step 5: Capture the current monitor config/instructions and wait for a safe capture boundary**, then stop only `kick:grenbaud` after preserving any usable partial segment.

- [ ] **Step 6: Merge/deploy backend and frontend, rebuild the backend image, and restart the stack once**; verify health before restarting the monitor.

- [ ] **Step 7: Import existing unpublished Kick clips, restart `kick:grenbaud` in `manual_queue` mode**, and verify `capturing`, queue growth, no Zernio POSTs, share/download response, and persistence across one controlled restart.

- [ ] **Step 8: Commit documentation/migration changes and push the completed branch**.
