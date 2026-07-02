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
