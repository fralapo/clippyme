# Fable 5 improvement log

Running log of the audit-driven improvement waves (2026-07-02 →). One entry per
improvement: what changed, why it mattered, verification evidence. The full
ranked audit lives in the session that produced this plan; each wave below maps
to an approved audit finding.

## Wave 1 — backend correctness (2026-07-02)

**1. `/api/cancel` race vs natural completion (High).**
`app.py:cancel_job` now refuses (HTTP 409) when the job's subprocess has
already exited: `run_job`'s 2s poll loop may not have observed the exit yet, so
the status still reads `processing` — honouring the cancel in that window
`rmtree`'d a fully-rendered job. Queued jobs (no process handle) stay
cancellable via the existing pre-dispatch guard.
Test: `tests/api/test_job_controls.py::test_cancel_refused_when_process_already_exited`
(+ `test_cancel_kills_running_process`, `test_cancel_queued_job_still_allowed`).

**2. Orphaned subprocess on unexpected `run_job` exception (High).**
An exception escaping the poll loop (e.g. a `TypeError` from a result loader)
set status `failed` but left the pipeline subprocess running — unkillable via
the API (`can_cancel('failed')` is False) while its concurrency slot was
already released. The `except` branch now kills any still-alive process.
Test: `tests/api/test_job_controls.py::test_run_job_kills_orphan_on_unexpected_error`.

**3. Missing ffmpeg timeouts on compose layers (High).**
`grade.py` / `hooks.py` / `logo.py` / `subtitles.py` ran ffmpeg with no
`timeout=`; each call executes on asyncio's shared default thread pool, so a
few hung ffmpeg processes would pin its workers and stall job polling
server-wide. All four now pass `encode.ffmpeg_timeout()` (new,
`CLIPPYME_FFMPEG_TIMEOUT`, default 600s). Grade degrades to
keep-ungraded-input on timeout; hook/logo raise with a clear message.
`logo.py`'s ffprobe also gained a 30s timeout and a warning log on its
previously-silent 1080×1920 fallback (wrong for 1:1 / 16:9 jobs).
Tests: `tests/domain/test_encode.py::test_ffmpeg_timeout_default_and_env`,
`tests/domain/test_grade.py::test_apply_grade_timeout_returns_false`.

**4. Log-reader thread died on non-UTF-8 bytes (Med-High).**
`job_worker.enqueue_output` decoded subprocess output with strict UTF-8; one
stray byte (ffmpeg/yt-dlp) raised, the outer except ended the read loop, and
the job's visible log froze for the rest of the run. Now decodes with
`errors="replace"`.
Test: `tests/domain/test_job_worker.py` (new file, 5 cases).

**5. Retention sweep could purge an active job (Med).**
`cleanup_jobs` purged by directory mtime only; a long-paused/slow job whose
dir gained no new entries within `JOB_RETENTION_SECONDS` was purge-eligible
while its subprocess was alive. New pure guard `job_control.can_purge(status)`
skips jobs in `ACTIVE_STATES`. Cleanup-failure logs bumped `debug`→`warning`
(the app's INFO basicConfig made them invisible — a systematically failing
cleanup was a silent disk leak).
Test: `tests/pipeline/test_job_control.py::test_can_purge_blocks_active_jobs`.

**6. Secret-scan hook missed ElevenLabs keys (Med).**
`.githooks/pre-commit`: added `sk_[a-f0-9]{20,}` (ElevenLabs uses `sk_`, which
the OpenAI `sk-` pattern never matched), added `ELEVENLABS` to the name-based
alternation, and allowed optional quotes around name/value so JSON-style
`"X_API_KEY": "…"` lines are caught for every provider.
Verified by piping 4 representative fake-key samples through the exact
patterns (all matched).

**Verification (Wave 1):** `pytest -m "not integration"` → 583 passed,
3 skipped. `ruff check src/clippyme tests --select E9,F63,F7,F82` (CI rule
set) → clean. Commit `6749f0e`.

## Wave 2 — per-clip serialisation locks (2026-07-02)

**7. Concurrent reframe/compose on the same clip raced deterministic files
(Med-High).** New `domain/clip_locks.py`: a refcounted `asyncio.Lock` registry
keyed `(job_dir, clip_index)` (async analogue of `smartcut._CLIP_LOCKS`).
`compose_layers` acquires it around the whole layer pipeline (covers both
`/api/compose` and publish's `compose_first`); `/api/reframe` acquires the
same lock around the `--reframe-only` subprocess + metadata write. Before: a
double-clicked "Apply & reprocess" spawned two subprocesses racing
`os.replace` on the same `<clip>.reframe.tmp.mp4`, both returning success over
a nondeterministic result; an overlapping Download + Publish could delete the
other's in-flight `composed_*_{i}.mp4`. Different clips remain fully parallel.
Tests: `tests/domain/test_clip_locks.py` (mutual exclusion, cross-clip
parallelism via event-handshake, registry cleanup, path normalisation).

**Verification (Wave 2):** `pytest -m "not integration"` → 587 passed,
3 skipped. CI ruff rule set → clean. Commit `a56377b`.

## Wave 3 — reframe: no state bleed across scene cuts (2026-07-02)

**8. Tracker state bled across hard cuts (High, product quality).**
`SpeakerTracker` and `DetectionSmoother` were created once per clip and never
reset at scene boundaries — only the *camera* snapped (`force_snap`). A face in
the new scene landing near a previous scene's track inherited the old
active-speaker 3× sticky bonus + 45-frame switch cooldown and was box-averaged
with stale frames from an unrelated shot; under comfort mode (default) the
polluted early targets skew the whole scene's collapsed-median static crop.
Worst on fast-cut viral-edit content — exactly the product's target. Both
classes gained `reset()`; both scene-advance sites (streaming loop +
global-smooth pass 1) call them. `SpeakerTracker.reset` also rearms the switch
cooldown so the new scene locks its speaker immediately; `next_id` keeps
counting so IDs never collide across scenes.

**9. Short-scene strategy sampling read the neighbour scene (Med).**
`analyze_scenes_strategy` sampled `s_frame+2` / `e_frame-2` unclamped: on a
<5-frame scene those indices land in the adjacent scene, misclassifying
TRACK/WIDE/GENERAL from a neighbour's content. Samples are now clamped to
`[s_frame, e_frame)`.

Tests: `tests/pipeline/test_reframe_scene_reset.py` (host, source-level — the
module imports cv2 so it can't be imported on the host; the wiring is pinned
by AST/text, behaviour by the Docker suite).

**Verification (Wave 3):** host `pytest -m "not integration"` → 590 passed;
Docker `pytest -m integration` → 30 passed, 42.9s; CI ruff rule set → clean.
Commit `10edaa4`.

## Wave 6 — frontend test coverage (2026-07-02)

**10. The frontend's highest-fan-in pure logic had zero tests (4 test files vs
53 on the backend).** Added (all plain `node --test`, no new dependency):
- `lib/seedClipParams.test.js` — pins the single seam that keeps Create panel /
  EditClipModal / export / publish emitting the same `*_params` shape
  compose.py reads: defaults, grade-toggle gating, style-key forwarding, and
  the explicit-only omission contract for `uppercase`/`font_size`/
  `outline_width`/`words_per_group` (each a documented past regression).
- `redesign/realApi.test.js` — `optsToPreselections` (object→subject alias,
  legacy boolean fallback, karaoke vs classic field sets, model/grade/logo
  omission), the `javascript:`/`data:` scheme neutralisation in
  `clipVideoSrc`/`clipPreviewSrc` (a security property previously uncovered),
  cache-buster handling, `fmtDuration`.
- `lib/taste.test.js` extended to the localStorage exports via a 10-line Map
  shim: round-trip, invalid-action no-op, 120-event rolling window,
  garbage-JSON resilience, `tasteInstructionSuffix`.
- `lib/scheduleDates.js` — `localDatePlus` extracted from `publish.jsx` (JSX is
  not `node --test`-parseable) with an injectable `now`;
  `scheduleDates.test.js` covers zero-padding, per-batch-position day spacing
  (the anti-429 contract), month/year rollover.
- `tests/domain/test_frontend_backend_parity.py` — cross-file guard parsing
  `data.js`: grade preset ids ↔ `grade.GRADE_PRESETS`, logo positions/sizes ↔
  `logo._POSITIONS`/`compose._LOGO_SIZE_MAP`, `HOOK_STYLE_DEFAULT` ↔
  `hooks.HOOK_STYLE_DEFAULTS` (the documented hook-default drift incident,
  previously only asserted on the backend side).

Enablers: `config.js` guards `import.meta.env` (Vite still defines it;
plain Node no longer throws) and `realApi.js` uses explicit `.js` import
extensions (strict Node ESM resolution; Vite accepts them unchanged).

**Verification (Wave 6):** `npm test` → 54 passed (was 26); `npm run lint` →
0 warnings; `npm run build` → clean; host pytest → 593 passed.
Commit `92bcad4`.

## Wave 4 — pipeline perf quick wins (2026-07-02)

**11. Loudnorm analysis decoded the whole video stream for an audio-only
measurement.** `postprocess.normalize_audio` pass 1 now passes `-vn`: without
it ffmpeg decoded every 1080×1920 frame into the null muxer while loudnorm
only reads audio — typically >50% of normalize wall-time, on every clip of
every job (and again on every `--reframe-only`). Measured values identical.

**12. Global-smooth pass 1 fully decoded+converted frames it never looks at.**
Detection runs on even frames of TRACK/WIDE scenes only; odd frames and
DISABLED/GENERAL scenes now use `cap.grab()` (decode without the
retrieve+BGR-convert memcpy) instead of `cap.read()`. Comfort mode is default
on, so this trims every AUTO clip's dominant tracking pass.

**13. Source-slice cut used raw `-crf 18 -preset fast` literals.** The one
remaining scattered encode literal (`main.py`) — the exact drift
`encode.x264_video_args()` exists to prevent, and `fast` contradicted the
centralized `medium`. Now routed through the shared helper
(`faststart=False`: internal intermediate).

**14. `smartcut._probe_video` spawned two ffprobe processes per probe.**
Video + audio stream entries now come from ONE `-show_entries
stream=codec_type,…` call, halving probe subprocess spawns on the smart-cut
path (the result was already LRU-cached per path+mtime).

**15. Silent per-clip reframe failure got a log line.** The render loop had
no `else` branch when `process_video_to_vertical` returned False — the clip
was simply absent from the results grid with zero breadcrumb in the job log.

**Verification (Wave 4):** host `pytest -m "not integration"` → 593 passed;
Docker `pytest -m integration` → 30 passed, 37.0s; CI ruff rule set → clean.
Commit `3bc6023`.

## Wave 5 — compose pass fusion (2026-07-02)

**16. Grade + Subtitles fused into one encode.** When both toggles are active,
`grade.build_grade_filter(preset)` rides as `pre_vf` on the subtitle burn
(`burn_subtitles(pre_vf=…)` prepends it to the `ass`/`subtitles` filter).
Inside one filtergraph the colour transform still hits the source pixels
BEFORE the glyphs are composited, so the Grade→Subtitles ordering semantics
are exactly preserved — one generation cheaper. Grade-only keeps its own pass;
an unknown preset falls back to the standalone (no-op) path.

**17. Hook + Logo fused into one encode.** Both are static overlays applied
after Smart Cut. `hooks.build_hook_logo_filter` (pure, host-tested) builds a
single `-filter_complex` compositing hook first, logo topmost — the exact
z-order of the sequential passes (animated hook entrance preserved).
`add_hook_to_video` gains an optional `logo` dict; the shared geometry/clamps
moved to `logo.logo_filter_chain` so the fused and standalone paths can't
drift. Degraded cases (empty hook text, no uploaded logo) fall back to the
respective standalone pass.

Net effect: a fully-toggled compose (grade+subs+smartcut+hook+logo) drops from
5 sequential libx264 encodes to 3 — ~35-40% faster downloads and two fewer
generational quality losses. The load-bearing Grade → Subtitles → Smart Cut →
Hook → Logo order is untouched (fusion changes WHERE a step renders, not when).

Tests: `tests/domain/test_compose_merge.py` (pure filters, `pre_vf` command
assembly, compose wiring incl. fallbacks) + 3 new Docker render tests in
`test_ffmpeg_render_integration.py` (hook+logo static/animated, graded
subtitle burn).

**Verification (Wave 5):** host `pytest -m "not integration"` → 604 passed;
Docker `pytest -m integration` → 33 passed, 44.3s; CI ruff rule set → clean.
Commit `1d56e87`.

## Wave 7 — network exposure default (2026-07-02)

**18. Published ports bound to loopback by default.** `security.py` treats
every RFC1918 peer as a trusted client for config/state endpoints (API-key
overwrite, cookies download/delete, job deletion); docker-compose published
8000 and 5175 on all interfaces, extending that trust to the whole LAN. Both
ports now bind `127.0.0.1` via `${CLIPPYME_BIND:-127.0.0.1}` — LAN exposure
becomes an explicit opt-in (`CLIPPYME_BIND=0.0.0.0`). The dashboard port is
bound too because the Vite proxy reaches the backend from inside the docker
network as a trusted private peer, so a LAN-exposed dashboard would reopen
the hole. Verified with `docker compose config` (host_ip: 127.0.0.1 on both).
(The full API-token alternative for deliberate LAN deployments remains open —
descoped: needs token distribution to the frontend.) Commit `85ddb6a`.

## Wave 8 — smart-cut polish pre-screen (2026-07-02)

**19. Stage-2 polish no longer renders clips it would discard.**
`_audio_polish_pass` always ran a full auto-editor decode+encode, then deleted
the result when it saved <0.5s — a whole wasted encode generation on quiet-
free clips. A seconds-cheap audio-only `media_probe.detect_silences` pass now
predicts the saving first (`cut_ops.predict_polish_saving`: each silence can
contribute at most `len - 2*margin`); the noise floor is biased +4 dB above
auto-editor's threshold so the estimate over-counts, and the render is skipped
only when even that optimistic upper bound can't reach the 0.5s keep-threshold.
Advisory: any pre-screen failure falls through to the real pass. Kill-switch
`AE_POLISH_PRESCREEN=0`. Pure helpers (`parse_margin_seconds`,
`predict_polish_saving`) host-tested in `tests/pipeline/test_cut_ops.py`.

**Verification (Wave 8):** host pytest → 607 passed; Docker integration →
33 passed, 47.4s. Commit `2a51f6d`.

## Wave 9 — Ken Burns zoom folded into the master encode (2026-07-02)

**20. `apply_subtle_zoom` no longer costs its own generation.**
`process_video_to_vertical(zoom_end=…)` appends the 1.0→1.05 `zoompan` to the
master rawvideo encode's `-vf` (frame count from the existing probe cap), so
every clip pays one decode+encode less — in the main clip loop AND on every
`--reframe-only` request. `--no-zoom` passes `zoom_end=None`; an unreadable
container frame count falls back to the legacy `apply_subtle_zoom` post-pass
inside the function, so the caller contract is unchanged (zoom requested →
zoom delivered). The whole-video fallback paths never zoomed and still don't.
Integration test `test_zoom_fold_renders_valid_vertical` asserts a valid 9:16
output with an unchanged frame count.

**Verification (Wave 9):** host pytest → 607 passed; Docker integration →
34 passed, 50.8s; CI ruff rule set → clean. Commit `2d3fd48`.

## Wave 10 — accessibility fixes (2026-07-02)

**21. Keyboard + screen-reader access for the mouse-only controls.**
- Both upload dropzones in `create.jsx` gained `role="button"`, `tabIndex=0`,
  an `aria-label`, and Enter/Space activation — before, keyboard-only users
  could not open the file picker at all (the `<input type=file>` is `hidden`,
  unreachable by Tab).
- The "clear files" chip became a real `<button>`.
- Every credential input in Settings (`views.jsx`: Gemini/Deepgram/ElevenLabs/
  HF via `KeyRow`, the Zernio API key, the 3 per-platform account IDs) gained
  an `aria-label` — they were identified by placeholder only, which disappears
  once a value is typed and is not a reliable accessible name.

NOT done: adding `eslint-plugin-jsx-a11y` as a lint-time guardrail — the
repo's config-protection hook blocks edits to `eslint.config.js`, so the
plugin was uninstalled again and the config left untouched. Enabling it needs
an explicit owner decision (it is a strengthening change, not a weakening
one).

**Verification (Wave 10):** `npm run lint` → 0 warnings; `npm test` →
54 passed; `npm run build` → clean. Commit `e16af76`.

## Wave 11 — reframe handler extracted to the domain layer (2026-07-02)

**22. `reframe_clip` was ~165 lines inside app.py** (the largest violation of
the thin-handler rule). Everything from metadata resolution through the
`--reframe-only` subprocess and metadata persistence moved verbatim to
`domain/reframe_service.run_reframe`; the endpoint keeps only trust/rate-limit
checks + mode validation and delegates. Domain code raises `ClippyMeError`
subclasses (incl. the 409 source-slice case) instead of `HTTPException`,
mapped by the existing app-level exception handler. app.py: 1428 → 1315
lines; behaviour pinned by the untouched `tests/api/test_reframe_aspect_api.py`
(aspect round-trip, legacy-alias normalization, tampered-aspect guard — all
still green). Unused `time` import and `save_job_metadata` re-export dropped
from app.py.

**Verification (Wave 11):** host pytest → 607 passed; CI ruff rule set →
clean. (No pipeline/render change — Docker suite unaffected by this wave.)

## Wave 12 — jsx-a11y lint guardrail: blocked by owner hook (2026-07-02)

**23. eslint-plugin-jsx-a11y as a permanent lint guardrail — NOT SHIPPED.**
The user's config-protection hook blocks every edit to
`dashboard/eslint.config.js`, including this purely additive/strengthening
one ("BLOCKED: Modifying eslint.config.js is not allowed… disable the
config-protection hook temporarily" — reproduced 2026-07-02). The concrete
DOM a11y fixes from Wave 10 are all in; only the *guardrail* is missing. To
ship it: temporarily disable the hook, `npm i -D eslint-plugin-jsx-a11y`,
add the plugin + `jsxA11y.flatConfigs.recommended` rules to eslint.config.js,
fix any new findings, re-enable the hook. No file churn was left behind.

## Wave 13 — additive production frontend stack (2026-07-02)

**24. The dashboard could only be served by the Vite dev server** (HMR
tooling, eval-friendly CSP, source bind mount) — fine on loopback, wrong for
a deliberate deployment. New opt-in prod path, fully additive:
`dashboard/Dockerfile.prod` (multi-stage `npm ci` + `vite build` → nginx),
`dashboard/nginx.conf` (SPA fallback, immutable `/assets/` caching, proxy for
`/api|/videos|/thumbnails|/fonts` → backend:8000 with 600s timeouts matched
to `CLIPPYME_FFMPEG_TIMEOUT` and unbuffered upload/video streaming), and
`docker-compose.prod.yml` (swaps the frontend build, drops the dev mounts via
`!reset`; needs Compose ≥ 2.24). nginx listens on 5175 so the `CLIPPYME_BIND`
loopback default and port mapping carry over unchanged; the build gets the
CSP meta tag (vite cspPlugin is build-only). Default `docker compose up`
dev workflow untouched.

**Verification (Wave 13):** merged `compose config` shows Dockerfile.prod +
no volumes + loopback port; image built clean; live smoke test on the built
image → SPA `GET /` 200 and `GET /api/history` 200 through the nginx proxy.
Commit 59b0240.

## Wave 14 — optional API token for deliberate LAN deploys (2026-07-02)

**25. `CLIPPYME_BIND=0.0.0.0` re-extended RFC1918 trust to the whole LAN**
with no per-client auth. New `CLIPPYME_API_TOKEN` (default unset = no-op,
byte-identical): `security.configured_api_token`/`enforce_api_token`
(constant-time `hmac.compare_digest`; `X-API-Token` or `Authorization:
Bearer`) enforced by an app middleware on every `/api` route (OPTIONS
exempt for CORS preflight; static media mounts stay IP-open since
`<video>`/FontFace can't send custom headers). Frontend:
`lib/apiToken.js` (localStorage-backed `getApiToken`/`setApiToken` +
`apiFetch` wrapper) now carries every API call in `realApi.js`,
`lib/api.js`, `useBackendStatus`, `useJobSubmission`; Settings gains an
"API token" row; CORS `allow_headers` gains `X-API-Token`; compose passes
the env through.

**Verification (Wave 14):** 10 new host tests (`tests/api/test_api_token.py`
— unit no-op/401/Bearer/precedence + TestClient middleware 401/pass/no-op)
→ host suite 617 passed; 4 new node tests (`apiToken.test.js`) → 58 passed;
`npm run lint` + `npm run build` green; CI ruff rule set clean. Commit
4403ba0.

**Final sweep (2026-07-02):** host pytest 617 passed / 3 skipped; Docker
integration 34 passed; frontend 58/58 + lint + build green; zero
TODO/FIXME markers in `src/clippyme` + `dashboard/src`. Open owner item:
#23 (jsx-a11y guardrail, blocked by the config-protection hook).
