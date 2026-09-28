# CLAUDE.md

Operating rules for coding agents in this repository. It lists what you must
not break and where to look; it does not explain the product. `AGENTS.md`
points here.

## Context

ClippyMe is a self-hosted app that turns long videos into 9:16 shorts:
FastAPI backend, one pipeline subprocess per job, React 18 + Vite 6 +
Tailwind v4 dashboard, files on disk instead of a database. Start with
[docs/architecture/overview.md](docs/architecture/overview.md).

## Where to look, in order

1. `docs/architecture/` — current design of the subsystem you are changing.
2. The production code and its tests.
3. [docs/reference/configuration.md](docs/reference/configuration.md) and
   `.github/workflows/ci.yml`.
4. Only then `docs/research/`, for rationale. **Research and history are not
   implementation authority**: they describe other projects and past states.
   If they disagree with code, tests or architecture docs, those win.

The source-of-truth table is in [docs/README.md](docs/README.md).

## Repo map

- `src/clippyme/api/` — FastAPI routes (`app.py`: jobs, clips, monitor;
  `config_routes.py`: settings), `schemas.py`, `security.py`.
- Service packages (endpoint logic; never import FastAPI):
  `src/clippyme/jobs/` job lifecycle (submission, queue, runner with the
  retry loop, control, journal, runtime state, results, history, uploads); `clips/` per-clip
  operations (resolution, locks, smart cut and restore endpoints, reframe
  requests); `editing/` compose layers (grade, subtitles, smart cut, hook,
  logo, banner, AI trim); `monitoring/` live monitor; `publishing/` manual
  publish.
- `src/clippyme/core/` — errors, SSRF-safe DNS (`netutil`), Gemini clip
  schema. `media/` — ffmpeg/ffprobe primitives shared by the pipeline and
  the compose layers: `encode`, `media_probe`, `ffmpeg_exec`.
- `src/clippyme/pipeline/` — the per-job subprocess. Entrypoint is
  `orchestrator.py` (preflight, checkpoints, retries, output QA) wrapping
  `main.py` (download, transcription, Gemini, cut, reframe); both module
  paths are fixed (`python -m`, persisted argv). Stages live in
  `transcription/` (Deepgram, ElevenLabs, cache, diarization; local Whisper
  stays in `main.py`, device/model choice in `hardware.py`), `analysis/`
  (Gemini request/parser/service, TextTiling), `reframe/` (engine, detectors,
  tracking, decision math, scene detection) and `quality/` (clip QA, media
  QA, quality suite).
- `src/clippyme/integrations/` — Zernio, Kick, Twitch, YouTube RSS,
  auto-editor updater. `storage/` — `data/config.json`.
- `dashboard/src/` — the UI: `app/App.jsx` (state wiring only), `features/`
  (one folder per screen: create, processing, results, clip-editor,
  publishing, live-monitor, history-settings), `components/` (cross-feature
  UI; `controls/` = shared subtitle/logo/grade/banner/hook controls), `api/`
  (backend client), `hooks/` side effects, `lib/` pure logic, `styles/`.
- `tests/` mirrors `src/clippyme/`; frontend tests sit next to the code.

## Commands

```bash
pytest -m "not integration" -q                                   # host suite
ruff check src/clippyme tests --select E9,F63,F7,F82              # CI lint rules
cd dashboard && npm run lint && npm test && npm run build         # frontend
docker compose run --rm -u root backend sh -lc "pip install -q pytest && pytest -m integration -q"
```

Setup, skips and the full CI list: [docs/development/testing.md](docs/development/testing.md).
Dependency changes: [docs/development/dependencies.md](docs/development/dependencies.md)
(`requirements.lock` is generated with uv, never hand-edited).

Minimum before committing: host suite + Ruff for backend changes; lint, test
and build for dashboard changes; the integration suite when you touch
CV-dependent pipeline code, the Dockerfile or dependency files.

## Code rules

- **Thin handlers**: validate → call a service helper → return JSON.
  More than ~25 lines of logic in a handler gets extracted. Service code raises
  `core.errors.ValidationError` (400), `NotFoundError` (404), `ConflictError`
  (409), mapped by one app-level handler.
- **Per-clip endpoints resolve through `clip_resolve.resolve_clip()`**; do not
  re-implement the metadata/filename fallback chain. Clip files resolve via
  `clip_resolve.clip_filename_for`.
- **Host-testable logic**: `pipeline/main.py`, `reframe.py`,
  `reframe_detect.py` import cv2/torch at module level and cannot be imported
  on the host. Put new logic in the pure modules (`reframe_ops.py`,
  `reframe_track.py`, `cut_ops.py`, `run_ops.py`, `gemini_request.py`,
  `smartcut_ops.py`, `media_probe.py`, …).
- **Back-compat re-exports**: `reframe.py` re-exports the moved track/detect
  names, `main.py` the reframe API, `smartcut.py` the `smartcut_ops` names.
  Keep them when moving code.
- **Atomic writes** for anything a crash could corrupt: temp file +
  `os.replace`, mode `0o600` (`job_artifacts.save_job_metadata` pattern); add
  fsync where the state must survive power loss (`runtime_state`,
  `job_journal`).
- **One encode setting**: every libx264 pass uses `media/encode.x264_video_args()`;
  no raw `-crf` literals.
- **Shared frontend controls**: subtitle/logo/grade controls are shared between
  Create and the edit modal via `subtitleControls.jsx` / `layerControls.jsx`
  (`value` + `onChange(partial)`); never clone them per surface. Edit-modal
  state lives in the `editClipModal.jsx` shell: tab bodies in `editTabs.jsx` are
  conditionally rendered and lose state on unmount. UI primitives are
  hand-rolled in `primitives.jsx` (no shadcn CLI).
- **Defaults duplicated across stacks** (hook style in `dashboard/src/lib/data.js` and
  `editing/hooks.py`, grade/logo presets) are pinned by
  `tests/editing/test_frontend_backend_parity.py`; change both sides and the test.
- **Lint config**: extend rules in `dashboard/eslint.a11y.config.js`, which
  composes the base `eslint.config.js`.
- **New setting**: document it in `docs/reference/configuration.md` (and
  `.env.example` if operators will set it). `tests/repository/test_docs.py` fails when a
  setting read by the code is missing from the reference.

## Invariants

Breaking one of these is a bug even if tests pass.

- **Lock order**, never reversed: `clip_locks.clip_lock` (asyncio, per
  `(job_dir, clip_index)`, re-entrant per task) first; then either
  `smartcut._clip_lock` (threading, only inside a worker thread) or the live
  monitor's global `_publish_lock` (asyncio; serialises monitor publishes and
  guards `picked_slots`; manual publish never takes it);
  `job_artifacts._METADATA_LOCK` innermost, only in sync/worker-thread code.
  No threading lock is held across an `await`.
- **Job metadata is one shared document**: API-side writers use
  `job_artifacts.update_job_metadata` (reload + mutate + save under the lock),
  never a copy loaded before a long render. Reframe, publish and history
  restore answer 409 while the job is queued/processing/paused.
- **Monitor hand-off**: the monitor holds the clip lock over compose → copy at
  hand-off and over recompose → upload → accept, including the post-accept
  history record and artifact cleanup (run in a worker thread).
- **Publish identities** stay separate: logical clip `(job_id,
  original_index)`; monitor `publication_id`; `request_id` = Zernio
  `Idempotency-Key`, reused after an ambiguous outcome, rotated (and persisted
  before the next call) only after a certain rejection. `409
  idempotency_conflict` is retried with the same key after `Retry-After` and
  never counted as accepted; `409` with `existingPostId` is accepted. Manual
  publish derives its key from `(job_id, clip_index, intent_id)`; no
  `intent_id` = no key. Delivery is at least once. Details:
  [docs/architecture/publishing.md](docs/architecture/publishing.md).
- **Manual publish vs monitor**: 409 while `LiveMonitorRegistry.publication_owner`
  says the monitor owns the clip.
- **Published clips**: after a confirmed monitor publish, artifacts are deleted
  and the entry marked `deleted_after_publish`; `shorts` positions never
  shift, consumers pass `original_index`.
- **Job journal** (`data/jobs_journal.json`) holds active jobs only and never
  secrets, `Popen` handles or logs. Recovery reuses status `failed` on purpose:
  the frontend stops polling only on `completed|stopped|cancelled|failed`.
- **Exit code 2** from the orchestrator = deterministic rejection, never
  retried. Progressive metadata is never a completion marker.
- **Compose order**: Grade → Subtitles → Smart Cut → Hook → Logo → Banner.
  Fusion may merge passes, never reorder them. An animated hook needs
  `-loop 1` + `-shortest`.
- **Reframe `disabled`** = whole frame letterboxed, Ken Burns forced off.
  `REFRAME_GLOBAL_METHOD=kalman|l2` only runs with `REFRAME_STATIC_AUTO=0`.
- **Gemini cost**: one price table (`gemini_request.MODEL_PRICING`); thinking
  tokens bill at the output rate; cost is priced per usage category, never from
  `total_token_count`; an unpriced model's cost is `None`, never 0; the
  preflight cost gate fails closed on unknown pricing.
- **Gemini prompt**: titles are engagement-first by design; never reintroduce a
  mechanical CTA. `CLIPPYME_CREATOR_NAME` names the clip's subject but never
  overrides speaker attribution. Rationale:
  [docs/research/title-hook-copy.md](docs/research/title-hook-copy.md).
- **Clip edges**: word → sentence → silence snapping in `cut_ops.py`; the
  10–75 s clip-schema cushion is intentional.
- **ffmpeg in the pipeline** goes through `ffmpeg_exec.py` (stderr to a temp
  file, no-progress watchdog, `.partial-` then validate then rename).
- **DNS** for SSRF checks goes through `netutil.py`; never touch
  `socket.setdefaulttimeout`.

## Security rules

- `job_id` is regex-validated everywhere; the per-job `model` name is
  regex-validated against argv injection; config/state endpoints require a
  trusted origin or private-network client (`security.py`). Subprocess argv is
  always a list, never a shell string.
- `SafeStaticFiles` blocks `*_metadata.json`, `source_*` and runtime files on
  `/videos`.
- With `TRUST_PROXY=1`, `client_ip` reads the **last** `X-Forwarded-For` hop,
  matching nginx's appending `$proxy_add_x_forwarded_for`; keep both in sync.
- Never commit secrets, `data/`, `.env` or `tmp/`. The pre-commit hook
  (`git config core.hooksPath .githooks`) enforces it; never bypass it.
- Tests build fake secrets at runtime; no token-shaped literals in the repo.

## Do not

- Commit with `--no-verify`, force-push, or rewrite published history.
- Hand-edit `requirements.lock` or anything in `docs/vendor/`.
- Treat `docs/research/` as a specification.
- Add a new document when an existing canonical page can be made clearer;
  link instead of copying facts between pages.
