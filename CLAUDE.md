# CLAUDE.md

Guidance for Claude Code when working in this repository. Current-state only —
design history and rationale live in `docs/` (see the pointers at the bottom).

## Project

ClippyMe is a self-hosted AI video platform that turns long-form videos
(YouTube or local uploads) into viral 9:16 vertical shorts. Fork of OpenShorts.
Backend: FastAPI + a subprocess video pipeline. Frontend: React 18 + Vite 5 +
Tailwind v4.

## Repo layout

Python backend is src-layout under `src/clippyme/` (`pip install -e .`):

- `api/` — `app.py` (thin FastAPI layer: job-lifecycle routes, middleware,
  static mounts, lifespan), `config_routes.py` (the config-family `APIRouter`:
  keys/cookies/fonts/logo/zernio/models — routes that touch no job runtime
  state, `include_router`ed by app.py), `schemas.py` (Pydantic request models),
  `security.py` (trusted-origin/rate limit/API-token gates).
- `domain/` — endpoint logic. `clip_resolve.py` (shared `resolve_clip()`: job
  dir → latest metadata → clip entry → path, used by every per-clip endpoint),
  `job_submission.py` (`submit_job()` + queue-full rollback),
  `job_runner.py` (`make_run_job()` — the per-job subprocess loop),
  `job_actions.py` (cancel/stop bodies), `job_journal.py` (crash-safe queue
  journal + startup recovery), `job_worker.py` (queue dispatch + retention
  cleanup), `job_results.py` (`build_main_cmd`, partial/final result loaders),
  `job_artifacts.py` (atomic metadata IO), `job_control.py` (status machine +
  psutil process-tree suspend/resume), `publish_service.py` (Zernio publish
  flow), `compose.py` (layer pipeline), `clip_endpoints.py` (smart-cut runner,
  history restore), `smartcut.py` (impure orchestrator: ffmpeg/auto-editor
  render, ffprobe, per-clip locks, `smart_cut`) + `smartcut_ops.py` (pure,
  host-tested: filler index, drop-range math, `analyze_silences`, v3 timeline
  builder — re-exported by smartcut.py for back-compat), `subtitles.py`,
  `hooks.py`, `logo.py`, `banner.py` (attribution banner: platform logo +
  handle, `suggest_banner` URL parsing, lazy-cairosvg raster, `attach`
  letterbox positioning), `live_monitor.py` (`LiveMonitorRegistry` +
  per-platform strategies: multi-channel Kick/Twitch/YouTube monitor, live +
  vod modes, global `picked_slots` publish spacing, state in
  `data/live_monitor.json`),
  `grade.py`, `clip_qa.py`, `clip_edit_ai.py`, `history_service.py`,
  `encode.py` (single source of x264 settings for every render pass),
  `errors.py` (domain exceptions mapped to HTTP by one app-level handler).
- `pipeline/` — `main.py` (CLI orchestrator), `reframe.py` (orchestrator:
  scene analysis, frame strategies, render loops, `process_video_to_vertical`),
  `reframe_track.py` (pure tracking classes — host-tested, no cv2),
  `reframe_detect.py` (YOLO/MediaPipe detectors), `reframe_ops.py` (pure
  camera math), `cut_ops.py` (clip-edge snapping primitives + the
  `snap_clips_to_transcript`/`compute_neighbor_bounds` batch orchestration),
  `run_ops.py` (pure entrypoint helpers: `resolve_output_dir`,
  `build_cut_command`), `gemini_request.py` (prompt template + pricing +
  prompt/cost/retry-classification — the pure half of `get_viral_clips`; the
  per-word payload is TOON-encoded (`encode_words_toon`, ~50% smaller than
  JSON) while the response contract stays JSON),
  `media_probe.py` (ffprobe + silencedetect wrappers), `texttiling_ops.py`
  (no-AI topic-segmentation fallback), `deepgram_transcribe.py`,
  `elevenlabs_transcribe.py`, `gemini_service.py`, `gemini_parser.py`,
  `scene_detection.py`, `download.py`, `postprocess.py`, `diarization.py`,
  `hardware.py`, `transcribe_cache.py`. `main.py` imports cv2/torch at the
  top → NOT host-importable: pure logic goes in the modules above, never
  inline in `main.py` (it re-imports moved names for back-compat).
- `netutil.py` — bounded DNS resolution (daemon thread + timeout) shared by
  the SSRF guards in `download.py` / `social_publisher.py`; never mutate
  `socket.setdefaulttimeout` (it doesn't even apply to `getaddrinfo`).
- `integrations/` — `social_publisher.py` (Zernio client + SmartScheduler),
  `auto_editor_updater.py` (auto-editor binary self-update),
  `kick_client.py` (Kick channel/VOD JSON via curl_cffi, Cloudflare profile
  rotation), `twitch_client.py` (Helix app-token client: streams/users/videos),
  `youtube_feed.py` (UULF long-form RSS polling — Shorts structurally
  excluded).
- `storage/` — `config_store.py` (persisted config in `data/config.json`).

Frontend lives entirely in `dashboard/src/redesign/` (`main.jsx` renders
`RedesignApp`). Shared hooks in `dashboard/src/hooks/` (incl.
`useManualTrim.js` — the modal's trim state machine), pure logic in
`dashboard/src/lib/` (incl. `applyEdit.js` — the reprocess orchestration,
`seedClipParams.js`, `trimSelection.js`, `bulkApply.js`, `taste.js`).
Subtitle/logo/grade controls are SHARED between the Create recipe and the
EditClipModal via `subtitleControls.jsx` / `layerControls.jsx` (hookStyle.jsx
pattern: fully-controlled `value` + `onChange(partial)`, per-surface `variant`
chrome, defaults resolved by thin adapters) — never re-clone these controls
per surface. `captions.jsx` is the modal shell; tab bodies live in
`editTabs.jsx` with state lifted in the shell (tabs are conditionally
rendered).

## Commands

```bash
docker compose up --build            # primary run (backend :8000, frontend :5175)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build  # prod frontend (nginx)

# Backend host tests (fast, no CV stack) + lint
pip install -e ".[host-tests]" && pip install pytest ruff
pytest -m "not integration" -q
ruff check src/clippyme tests --select E9,F63,F7,F82

# Heavy CV/ML integration tests (Docker only)
docker compose run --rm -u root backend sh -lc "pip install -q pytest && pytest -m integration"

# Frontend (Vitest + jsdom + testing-library)
cd dashboard && npm ci && npm test && npm run lint && npm run build
```

CI (`.github/workflows/ci.yml`): backend host suite (with report-only
coverage) + ruff bug-class rules + blocking `pip-audit`; frontend lint +
**test** (with coverage) + build; the Docker integration job runs on main
pushes or `workflow_dispatch`, pre-building the backend image with GHA layer
caching (tagged `clippyme-backend` so compose reuses it).

## Architecture

**Job lifecycle**: `POST /api/process|/api/batch` → `build_main_cmd` →
`submit_job` (in-memory `jobs` dict + `asyncio.Queue`) → `process_queue`
dispatch (semaphore, `MAX_CONCURRENT_JOBS`) → `run_job` spawns
`python -m clippyme.pipeline.main` as a subprocess and polls partial results
every 2s. Statuses: `queued → processing ⇄ paused → {completed, failed,
cancelled, stopped}` (`job_control.py` owns the guards). `stopped` keeps
finished clips; `cancelled` rmtree's everything.

**Job journal**: every status transition writes `data/jobs_journal.json`
(atomic, ACTIVE jobs only — never env secrets/Popen/logs). On startup,
`lifespan` recovery re-enqueues `queued` jobs, restores interrupted jobs whose
final result reached disk, and marks the rest `failed` (killing orphaned
pipeline trees via psutil with an argv-match guard). **`failed` is reused
deliberately**: the frontend poller terminates only on
`completed|stopped|cancelled|failed` — an unknown status polls forever.

**Pipeline (per job)**: yt-dlp download → transcription → PySceneDetect →
Gemini viral detection (5-level JSON-repair fallback chain in
`gemini_parser.py`; TextTiling topic-split as the no-AI fallback; whole-video
render as the last resort) → per-clip edge snapping (word → sentence →
waveform-silence, `cut_ops.py`) → 9:16 reframe → Ken Burns zoom (folded into
the master encode) → EBU R128 loudnorm → cover frame. The 16:9 source slice
per clip is preserved on disk (`source_*.mp4`) to enable post-hoc reframe
switching.

**Transcription**: `TRANSCRIPTION_PROVIDER` = `deepgram` (default, Nova-3
REST) | `elevenlabs` (Scribe; audio-event tags feed the Gemini prompt) |
`whisper` (local). Both cloud providers silently fall back to Faster-Whisper
on any failure. All paths transcribe an extracted mono-16kHz FLAC, not the
video. Transcripts are cached 7 days under `data/cache/` keyed by URL hash.

**Compose** (`POST /api/compose/{job}/{clip}`): layers render in the order
**Grade → Subtitles → Smart Cut → Hook → Logo → Banner**. Do NOT reorder —
subtitles are burned before Smart Cut so their absolute timing can't drift;
grade runs first so overlays keep authored colour; logo sits on top; the
attribution banner (`banner.py`: platform logo + handle, `attach` mode pins it
under the letterbox band when `reframe_mode == disabled`) renders topmost as a
separate pass. Grade+subtitles and hook+logo are pass-fused (one encode each)
when possible. Toggles are UI-only state; composition happens at
download/publish time. Serialised per clip via `clip_locks.clip_lock`.
Hook overlay shows only the first 4s of the clip, EXCEPT
`reframe_mode == disabled` where it stays for the whole clip.

**Reframe**: three user modes — `auto` (face tracking + per-scene strategy),
`subject` (FrameShift weighted-interest crop; legacy alias `object`),
`disabled` (letterbox). Comfort mode is default-on: within a scene the camera
never moves (`collapse_scene_targets`), zoom locks per scene. The output
aspect is an explicit `process_video_to_vertical(..., aspect_ratio=)`
parameter passed by `main.py` per job — there is no module-global. Post-hoc
mode switching (`POST /api/reframe/{job}/{clip}`) spawns
`main.py --reframe-only` on the preserved source slice. Camera/decision math
lives in `reframe_ops.py`/`reframe_track.py` (pure, host-tested) — add new
reframe logic there, not in the cv2-bound modules.
⚠️ `REFRAME_GLOBAL_METHOD=kalman|l2` only runs with `REFRAME_STATIC_AUTO=0`;
the default static-auto policy never reaches the trajectory smoother.

**Smart Cut**: transcript-driven silence/filler removal rendered via a
hand-built auto-editor v3 JSON timeline (ffmpeg concat fallback if the binary
is missing), plus an audio-threshold polish pass. Manual trims arrive as
`drop_ranges` ([[start,end], …] clip-relative) and ride compose + publish.
The auto-editor binary is NOT a pip dep — Dockerfile downloads it; an opt-in
24h self-update loop refreshes it (`AUTO_EDITOR_AUTO_UPDATE=1`).

**Publish**: Zernio (TikTok/Instagram/YouTube). `publish_service.publish_clip_flow`
optionally re-composes first so uploads match the preview; `SmartScheduler`
picks Italian-prime-time slots with anti-collision. Zernio error bodies pass
through verbatim (the frontend parses per-platform 429 daily limits).

## Code rules

- **Thin handlers**: validate → call a `clippyme.domain.*` helper → return
  JSON. A handler growing past ~25 lines of logic gets extracted. Domain
  modules never import FastAPI — they raise `errors.ClippyMeError` subclasses
  (`ValidationError` 400, `NotFoundError` 404, `ConflictError` 409) mapped by
  one app-level handler.
- **Per-clip endpoints resolve through `clip_resolve.resolve_clip()`** — do
  not re-implement the metadata/filename fallback chain.
- **Pure logic is extracted to host-testable modules** (no cv2/torch imports)
  so it runs in `pytest -m "not integration"`. cv2/ML code is verified only by
  the Docker integration suite.
- **Back-compat re-exports**: `reframe.py` re-exports the moved
  track/detect names; `main.py` re-exports the reframe API. Keep them when
  moving code.
- **Atomic writes** for anything on disk that a crash could corrupt
  (`job_artifacts.save_job_metadata` pattern: tmp + `os.replace`, 0o600).
- **Frontend**: `RedesignApp.jsx` owns only top-level state wiring; side
  effects go in `hooks/`, pure logic in `lib/`, visuals in `redesign/`
  components. UI primitives are hand-rolled in `primitives.jsx` (no shadcn
  CLI). Component tests colocate as `*.test.jsx` (Vitest + jsdom).
- **Security**: `job_id` regex-validated everywhere; config/state endpoints
  require a trusted origin or private-network client; `SafeStaticFiles`
  blocks `*_metadata.json` and `source_*` from the `/videos` mount; secrets
  never enter the job journal; `tmp/` is gitignored and must never be
  committed. Pre-commit secret scan: `git config core.hooksPath .githooks`.
  With `TRUST_PROXY=1`, `client_ip` reads the **last** `X-Forwarded-For`
  hop (the shipped nginx APPENDS via `$proxy_add_x_forwarded_for` — the
  first hop is client-forgeable); keep append+last-hop in sync.

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/process` · `/api/batch` | Submit single video / up to 20 URLs |
| GET | `/api/status/{job_id}` | Poll job progress |
| POST | `/api/pause|resume|stop|cancel/{job_id}` | Job control (stop keeps clips, cancel discards) |
| POST | `/api/compose/{job_id}/{clip_index}` | Compose toggled layers |
| POST | `/api/smartcut/{job_id}/{clip_index}` | Smart Cut (optional `drop_ranges` body) |
| GET | `/api/transcript/{job_id}/{clip_index}` | Clip-relative transcript for manual trim |
| POST | `/api/edit-ai/{job_id}/{clip_index}` | NL instruction → Gemini → `drop_ranges` |
| POST | `/api/reframe/{job_id}/{clip_index}` | Switch reframe mode post-hoc |
| POST | `/api/publish/{job_id}/{clip_index}` | Upload + schedule via Zernio |
| GET/POST/DELETE | `/api/config*` | Keys, cookies, logo, fonts, Zernio (trusted clients) |
| GET | `/api/history` · POST `/api/history/{id}/restore` · DELETE `/api/history/{id}` | Past jobs |

## Configuration

API keys, Gemini model, transcription provider and cookies are managed from
the dashboard Settings tab (persisted in `data/config.json`, git-ignored).
The full operational env-var reference (REFRAME_*, AE_*, CLIPPYME_*,
DEEPGRAM_*, ELEVENLABS_*, ZERNIO_*, server knobs) lives in `.env.example`
(commented, with defaults) and the README table — keep those two in sync when
adding a knob. `GEMINI_MODEL` defaults to `gemini-3.5-flash`; per-job override
via `--model` / `ProcessRequest.model` (regex-validated against argv
injection).

## Docs pointers

- `docs/*-analysis.md` — 14 comparative analyses of the OSS projects ideas
  were ported from (reframe smoothers, ClipsAI TextTiling, flycut manual trim,
  VideoLingo subtitle splitting, …) with adopt/reject rationale.
- `docs/fable5-improvement-log.md` — audit-driven fix log with verification
  evidence per change.
- `docs/reframe-improvements-research.md` — the comfort-mode research and
  measured A/B numbers.
- `docs/architecture-history.md` — summary of major refactors (what moved
  where and why); the pre-rewrite CLAUDE.md is in git history.
