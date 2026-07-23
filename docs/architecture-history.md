# Architecture history

A short record of the major structural changes, so CLAUDE.md can stay a
current-state guide. The full pre-2026-07 CLAUDE.md (which doubled as a
narrative changelog) is in git history; per-feature rationale lives in the
`docs/*-analysis.md` comparative studies and `docs/fable5-improvement-log.md`.

## 2026-07 — repo-wide risanamento (6 waves)

1. **Dead-code removal**: `reframe_ops.iou/associate_subject/rank_subject/
   split_screen_slots` — ported building blocks that never gained a caller —
   deleted (git history has them).
2. **app.py thin-handler refactor**: the fat handlers (process, batch,
   cancel, stop, compose, publish, and the `run_job` worker) moved into
   `domain/clip_resolve.py`, `domain/job_submission.py`,
   `domain/job_runner.py`, `domain/job_actions.py`,
   `domain/publish_service.py`. The five per-clip endpoints now share one
   `resolve_clip()` instead of five copies of the metadata/filename chain.
   Compose/publish switched from 400 to 404 on an out-of-range clip index.
3. **Job journal** (`domain/job_journal.py`): the in-memory queue is
   journalled to `data/jobs_journal.json` on every transition; startup
   recovery re-enqueues queued jobs and fails/restores interrupted ones.
   Before this, a backend restart silently lost every queued job and orphaned
   running pipeline subprocesses.
4. **reframe split**: `reframe.py` (1817 lines) split into `reframe_track.py`
   (pure tracking classes, host-tested), `reframe_detect.py` (YOLO/MediaPipe),
   and the orchestrator. The `reframe.ASPECT_RATIO` cross-module global —
   written per-job by `main.py` — was replaced by an explicit
   `process_video_to_vertical(..., aspect_ratio=)` parameter.
5. **Frontend testing**: the bare `node --test` runner was replaced by Vitest
   + jsdom + testing-library; component tests cover the EditClipModal payload
   seam and the extracted `lib/applyEdit.js` reprocess orchestration. CI runs
   the frontend suite for the first time.
6. **Docs**: CLAUDE.md rewritten as a compact current-state guide; the env-var
   surface documented in `.env.example`; the `REFRAME_GLOBAL_METHOD=kalman|l2`
   reachability caveat (requires `REFRAME_STATIC_AUTO=0`) documented.

## Earlier milestones (pre-2026-07, summarised)

- **8-round app.py extraction**: the original monolithic `app.py` was
  progressively split into `clippyme.domain.*` (compose, clip_endpoints,
  job_results, job_artifacts, job_worker, history_service, …) and the src-layout
  `clippyme` package was adopted (`pip install -e .`).
- **main.py pipeline extraction**: the 2216-line orchestrator was decomposed
  into `transcribe_cache/download/scene_detection/postprocess/diarization/
  hardware/reframe/reframe_ops/media_probe/texttiling_ops`.
- **Legacy frontend removal**: the original `App.jsx` +
  `dashboard/src/components/*` tree was deleted once the `redesign/` UI became
  the only reachable surface.
- **Transcription providers**: local Whisper → + Deepgram Nova-3 (default) →
  + ElevenLabs Scribe (audio-event tags as a viral signal, opt-in Voice
  Isolator).
- **Comfort mode**: the reframe default moved from "track the face
  continuously, smooth the path" to "within a scene the camera never moves" —
  see `docs/reframe-improvements-research.md` for the research and metrics.
- **video-use-inspired quality passes**: word/sentence/silence clip-edge
  snapping (`cut_ops.py` + `media_probe.detect_silences`), post-render QA
  (`clip_qa.py`), colour grade layer, animated hooks, conversational trim,
  cross-job taste memory.
