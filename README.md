<a id="readme-top"></a>

<div align="center">
  <img src="dashboard/public/logo.svg" alt="ClippyMe logo" width="90" />

  <h1>ClippyMe</h1>

  <p><b>Self-hosted AI pipeline that turns long videos (YouTube or upload) into viral 9:16 vertical shorts.</b></p>

  <p>
    <img src="https://img.shields.io/github/license/fralapo/clippyme?style=flat-square&color=3b82f6" alt="MIT license" />
    <img src="https://img.shields.io/badge/python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11" />
    <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
    <img src="https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React 18" />
    <img src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker ready" />
    <img src="https://img.shields.io/github/stars/fralapo/clippyme?style=flat-square&color=eab308" alt="GitHub stars" />
  </p>

  <p>
    <a href="#quick-start-docker">Quick start</a> ·
    <a href="#configuration">Configuration</a> ·
    <a href="#api">API</a> ·
    <a href="#security-posture">Security</a> ·
    <a href="https://github.com/fralapo/clippyme/issues">Report a bug</a>
  </p>
</div>

Fork of OpenShorts, hardened and extended: cloud-or-local transcription, Gemini viral-moment detection, active-speaker 9:16 reframing, compose-on-download editing, and one-click multi-platform scheduling.

> Status: personal/self-hosted project. Safe to run on a trusted LAN. **Do not expose port 8000 to the public internet** without adding an authentication layer in front of it.

<details>
<summary><b>Table of contents</b></summary>

- [What it does](#what-it-does)
- [Stack](#stack)
- [Quick start (Docker)](#quick-start-docker)
- [Local development (no Docker)](#local-development-no-docker)
- [Configuration](#configuration)
- [Repository layout](#repository-layout)
- [API](#api)
- [Editing toggles (compose-on-download)](#editing-toggles-compose-on-download)
- [Reframing](#reframing)
- [Publishing (Zernio)](#publishing-zernio)
- [Security posture](#security-posture)
- [CPU vs GPU](#cpu-vs-gpu)
- [Acknowledgements](#acknowledgements)

</details>

---

## What it does

Given a video URL or upload, ClippyMe runs the following pipeline end-to-end:

1. **Download** with `yt-dlp` (Deno-based JS runtime to bypass YouTube bot detection, optional cookies for age-gated content).
2. **Transcribe** with **Deepgram Nova-3** by default (multi-language, code-switching EN/IT) — automatic fallback to local **Faster-Whisper** if no key or network failure. The video is stripped to a mono-16 kHz FLAC first, so only audio is uploaded/decoded (a few MB instead of the full mp4). Cached on disk for 7 days keyed by URL hash.
3. **Detect viral moments** with **Google Gemini** (`gemini-3.5-flash` by default). A 5-axis viral_score rubric (HOOK_STRENGTH, EMOTIONAL_PAYOFF, QUOTABILITY, SELF_CONTAINED, DENSITY) plus a 5-level robust JSON parser tolerates malformed model output.
4. **Reframe to 9:16** with active-speaker tracking: YOLOv8 person detection + MediaPipe FaceMesh mouth-aspect-ratio (MAR) variance to pick who is speaking, then a smoothed cameraman that adapts speed and zoom per scene. Hardened against messy real-world inputs: variable-frame-rate normalization, audio `start_time` compensation (YouTube A/V desync), and corrupt-frame resilience — all no-ops on clean sources.
5. **Post-process** each clip: Ken Burns auto-zoom (1.0→1.05×), EBU R128 audio normalization to −14 LUFS, automatic cover frame selection.
6. **Optional editing** at download time (compose-on-demand): **Smart Cut** (filler-word + silence removal via auto-editor v3 timeline + audio polish), **Hook** text overlay (Pillow + emoji, with Instagram-Stories-style banner / colours / outline / font), **Subtitles** (6 ASS karaoke presets or classic SRT, pixel-faithful frontend preview), and a **Brand logo** watermark. Custom subtitle/hook fonts and the logo are uploaded once in Settings.
7. **Publish or schedule** to TikTok / Instagram / YouTube via **Zernio**, with a SmartScheduler that picks Italian-prime-time slots, avoids same-day collisions, and handles per-platform daily-limit 429s by skipping exhausted platforms across a batch.

While a job runs you stay in control:

- **Edit clips as they finish** — completed clips stream into the full editor (toggles, disable/delete, publish) while later ones are still rendering; no need to wait for the whole job.
- **Pause / Resume / Stop** — suspend and resume the running job, **Stop & keep** to end early but retain the clips finished so far, or **Discard** to kill and delete everything.
- **Pick the AI model per job** — override the Gemini model for a single run from the Clip Options panel (or set the default, with live model discovery, in Settings).

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, asyncio queue |
| Pipeline | yt-dlp · Deepgram REST · Faster-Whisper · PySceneDetect · YOLOv8 (Ultralytics) · MediaPipe · ffmpeg · auto-editor (Nim binary) · Pillow |
| AI | Google Gemini (viral detection) · Deepgram Nova-3 (transcription) |
| Frontend | React 18 · Vite 5 · Tailwind CSS v4 · lucide-react · custom toasts/primitives |
| Publishing | Zernio multi-platform API |
| Deploy | Docker Compose (CPU multi-arch + optional NVIDIA GPU profile) |

---

## Quick start (Docker)

```bash
git clone https://github.com/fralapo/clippyme.git
cd clippyme
docker compose up --build
```

- Backend: http://localhost:8000
- Frontend: http://localhost:5175

Open the dashboard, drop in a YouTube URL or upload a file, and watch the pipeline run live.

> **First run after a pull** that touches `requirements.txt` or `package.json`: `docker compose down -v && docker compose up --build` to clear the stale anonymous volume on `/app/node_modules`.

### NVIDIA GPU profile

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

---

## Local development (no Docker)

```bash
# Backend
pip install -r requirements.txt
pip install -e .                                       # registers the clippyme src-layout package
python -m uvicorn clippyme.api.app:app --reload --port 8000

# Frontend (separate terminal)
cd dashboard && npm install && npm run dev

# Pipeline CLI (one-shot, no API)
python -m clippyme.pipeline.main <url_or_path> [--instructions "focus on hooks"] \
                                                [--reframe-mode auto|object|disabled] \
                                                [--no-zoom]
```

---

## Configuration

All API keys, model selection, and cookies are managed **from the dashboard Settings tab** and persisted to `data/config.json` (mode `0600`, git-ignored). No `.env` file required.

| Key | Required for | Notes |
|---|---|---|
| `GEMINI_API_KEY` | Viral moment detection | Default model `gemini-3.5-flash`; override per job or set the default in Settings (live model discovery). |
| `DEEPGRAM_API_KEY` | Cloud transcription (default) | Falls back to local Faster-Whisper if missing. |
| `HUGGINGFACE_TOKEN` | Optional gated models for Whisper | |
| Zernio | Social publishing | Per-platform account IDs auto-discovered via "Discover from Zernio". |
| Cookies | YouTube age-gated / region-locked content | Upload a Netscape `cookies.txt` from the Settings tab. Stored at `data/cookies.txt`, mode `0600`, max 10 MB. |

Runtime env overrides (rarely needed):

| Variable | Default | Purpose |
|---|---|---|
| `TRANSCRIPTION_PROVIDER` | `deepgram` | Or `whisper` to force local. |
| `CLIPPYME_TRANSCRIBE_AUDIO_ONLY` | `true` | Strip to audio-only FLAC before transcription; `false` sends the full video. |
| `DEEPGRAM_MODEL` | `nova-3` | |
| `DEEPGRAM_LANGUAGE` | `multi` | |
| `REFRAME_COMFORT` | `1` | Anti-nausea default (global-smooth + per-scene stationary + zoom lock). `0` = original single-pass tracker. |
| `REFRAME_STATIC_AUTO` | on | Lock the camera per scene — zero pan, zero mid-shot zoom. `0` = eased-but-moving smoother. |
| `REFRAME_MOTION_WIDE_THRESH` | `0.12` | How far a single subject may travel (fraction of frame) before TRACK is demoted to a static WIDE crop. |
| `REFRAME_STATIONARY_THRESH` / `REFRAME_ZOOM_LOCK` | `0.30` / on | Comfort tuning: scene-lock threshold / one zoom level per scene. |
| `REFRAME_SALIENT_GENERAL` | _(off)_ | Content-aware crop for faceless scenes instead of letterboxing. |
| `REFRAME_OBJECT_WEIGHTS` | _(off)_ | Faceless scenes follow a weighted-object centroid (product/dog/car) by reusing the existing YOLO pass. `1` = curated defaults, or `dog:3,car:2` for custom weights. |
| `ZERNIO_DEFAULT_TZ` | `Europe/Rome` | |
| `ZERNIO_MIN_GAP_SECONDS` | `5400` | SmartScheduler min spacing between posts. |
| `REFRAME_SMOOTHER` | _(blank)_ | `euro` switches the speaker camera to the 1€ adaptive filter; blank keeps the two-speed EMA. |
| `REFRAME_LOST_HOLD` | `90` | Frames a lost subject is held before the camera drifts back to center (~3 s @ 30 fps). |
| `REFRAME_LOST_DRIFT` | `0.05` | Per-frame ease rate of the drift-to-center recovery. |
| `REFRAME_EURO_MINCUTOFF` / `REFRAME_EURO_BETA` | `0.014` / `0.0008` | 1€ smoother tuning (only when `REFRAME_SMOOTHER=euro`): smoothness floor / speed responsiveness. |

---

## Repository layout

Backend uses an **`src/`-layout** Python package; frontend is a separate Vite app. Tests live at the root.

```
src/clippyme/
  api/                FastAPI surface
    app.py            App factory, lifespan, all HTTP endpoints
    schemas.py        Pydantic request models (strict validation)
    security.py       Trusted-origin checks, job-id UUID4 validation
  pipeline/           Heavy lifters
    main.py           CLI orchestrator: download → transcribe → Gemini → reframe → postprocess
    deepgram_transcribe.py   Deepgram Nova-3 REST client (retry/backoff, keyterms)
    gemini_parser.py  5-level JSON parsing chain + Pydantic validation + dedupe
    gemini_service.py List available Gemini models
    reframe.py        cv2/YOLO/MediaPipe glue: SpeakerTracker + SmoothedCameraman
    reframe_ops.py    Pure decision math (no cv2 → host-tested): smoothers, zoom
    media_probe.py    cv2-free ffprobe + A/V-sync helpers (VFR, start_time, fps)
  domain/             Endpoint-facing business logic
    compose.py        Subtitles → Smart Cut → Hook → Logo compose pipeline
    clip_endpoints.py        Smart Cut + history restore helpers
    job_results.py    Worker loop result loaders + main.py command builder (whitelisted)
    job_artifacts.py  Filesystem helpers for job outputs
    job_worker.py     Async queue workers + log enqueue
    history_service.py       Disk-backed job history scan
    smartcut.py       Two-stage filler-word + audio polish (auto-editor v3 timeline)
    subtitles.py      ASS karaoke (6 presets) + SRT + ffmpeg burn (filtergraph-escape hardened)
    hooks.py          Text overlay (Pillow + NotoColorEmoji) w/ IG-style banner/outline/font
    logo.py           Brand-logo / watermark overlay (ffmpeg overlay, positioned)
  integrations/       External clients
    social_publisher.py      Zernio REST + SmartScheduler + publish_clip orchestrator
    auto_editor_updater.py   Background daily updater for the auto-editor binary
  storage/
    config_store.py   data/config.json read/write (mode 0600)

dashboard/
  src/
    main.jsx                Mounts redesign/RedesignApp
    redesign/               The live UI. RedesignApp (state + tab orchestration),
                            create / results / publish / captions / views (Settings +
                            History) / chrome / processing, realApi.js (backend client),
                            data.js (presets/options), primitives.jsx, icon.jsx
    hooks/                  useJobSubmission, useJobPolling, useHistory,
                            useSessionPersistence, useBackendStatus, useClipStates
    lib/subtitlePresets.js  1:1 mirror of subtitles.py SUBTITLE_PRESETS for the live
                            preview (kept in sync by a CI parity test)

fonts/                Bundled TTF fonts served via /fonts (subtitle + hook rendering)
data/                 Persisted config, cookies, transcript cache (git-ignored)
```

---

## API

All routes are JSON in / JSON out. Job IDs are strict UUID4. Config endpoints require a trusted-origin client (loopback or RFC1918).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/process` | Single video (URL or upload). Accepts `reframe_mode`, per-job `model`. |
| `POST` | `/api/batch` | Up to 20 URLs in one shot. |
| `GET` | `/api/status/{job_id}` | Live status + logs + result (clips stream in as they finish). |
| `POST` | `/api/pause/{job_id}` | Suspend the running job (resume-able). |
| `POST` | `/api/resume/{job_id}` | Resume a paused job. |
| `POST` | `/api/stop/{job_id}` | Stop early but **keep the clips finished so far**. |
| `POST` | `/api/cancel/{job_id}` | Kill the subprocess **and discard all output**. |
| `POST` | `/api/compose/{job_id}/{clip_index}` | Compose Subtitles + Smart Cut + Hook + Logo on demand. |
| `POST` | `/api/smartcut/{job_id}/{clip_index}` | Smart Cut a single clip (optional `drop_ranges` for manual trim). |
| `GET` | `/api/transcript/{job_id}/{clip_index}` | Per-clip transcript segments for the manual-trim UI. |
| `POST` | `/api/reframe/{job_id}/{clip_index}` | Switch a clip's reframe mode. |
| `GET` | `/api/history` | Past jobs from disk. |
| `POST` | `/api/history/{job_id}/restore` | Reload a past job into memory. |
| `DELETE` | `/api/history/{job_id}` | Delete from disk. |
| `GET` | `/api/config/models` | List Gemini models (trusted origin). |
| `POST` | `/api/config` | Persist API keys (trusted origin). |
| `POST` | `/api/config/cookies` | Upload Netscape cookies file (trusted origin, 10 MB cap). |
| `GET` | `/api/config/cookies/status` | Is a cookie file present? |
| `DELETE` | `/api/config/cookies` | Remove the cookies file. |
| `POST`/`GET`/`DELETE` | `/api/config/logo` | Upload / status / remove the brand logo PNG. |
| `GET`/`POST`/`DELETE` | `/api/config/fonts` | List / upload / remove custom subtitle+hook fonts. |
| `GET` | `/api/config/zernio` | Masked Zernio config. |
| `POST` | `/api/config/zernio` | Save/update Zernio credentials. |
| `GET` | `/api/zernio/accounts` | Discover accounts via Zernio. |
| `POST` | `/api/publish/{job_id}/{clip_index}` | Upload + schedule a clip on TikTok/IG/YouTube. |

Static mounts: `/videos`, `/thumbnails`, `/fonts` (read-only).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Editing toggles (compose-on-download)

Every finished clip has an **Edit & reprocess** panel — one button on the clip card opens a modal that gathers all the options in one place (reframe mode, Smart Cut, Hook, Subtitles, Brand logo) so you set everything first and apply once, instead of the clip reprocessing on every tweak. The compose layers:

- **Smart Cut** — removes silences and filler words via auto-editor v3 timeline; falls back to ffmpeg concat demuxer if the binary is missing. **Manual trim:** the Edit modal also shows the clip's transcript as a tap-to-cut checklist — auto-removal handles silence and fillers, and you hand-cut any extra line; the picked spans (`drop_ranges`) carry through download and publish.
- **Hook** — text overlay, auto-prefilled from the Gemini hook suggestion. Beyond position/size it offers **Instagram-Stories-style text styling**: a toggleable coloured banner behind the text (colour + opacity), independent text colour, an outline/stroke (None/Thin/Thick + colour), and a font choice. A live WYSIWYG preview sits above the controls. Supports emoji.
- **Subtitles** — 6 viral karaoke presets (`classic_white`, `hormozi_bold`, `neon_glow`, `mrbeast_box`, `minimal_clean`, `fire_impact`) or classic SRT with font/color/position controls. The frontend preview is **pixel-faithful** with the burned-in output (`dashboard/src/lib/subtitlePresets.js` mirrors the Python preset table 1:1 — keep them in sync).
- **Brand logo** — burns an uploaded transparent PNG onto the clip (7 anchor positions × S/M/L size × opacity). Upload it once in Settings → Brand assets.

**Custom fonts**: upload a `.ttf`/`.otf` (e.g. a licensed Stratos) in Settings → Brand assets and it appears in the classic-subtitle and hook font pickers — resolved at burn time from the writable `data/fonts/` dir alongside the bundled faces.

Editing is staged: nothing runs while you toggle. **Apply & reprocess** re-renders the framing (only when the reframe mode changed) and then composes the active layers in one pass via `/api/compose/{job_id}/{clip_index}` — order is **Subtitles → Smart Cut → Hook → Logo** (subtitles burn first so their absolute timing never drifts when Smart Cut removes silences; the logo sits on top of everything). Reprocessing runs in the **background** — Apply closes the modal immediately and the clip card shows a *Reprocessing…* overlay, so you can edit other clips meanwhile. The preview updates to the composed result, and downloading runs the same compose, so what you see is what you get.

**Apply runs in the background.** Hitting Apply closes the modal immediately and the reframe/compose work runs without blocking the page — the clip card shows a *Reprocessing…* overlay while it renders, and you can edit, reprocess, and publish other clips at the same time. Each clip is an independent job, so several can render at once.

---

## Reframing

Pick one of three modes per job (and per clip after the fact, from the **Edit & reprocess** panel or `POST /api/reframe`):

- **Auto** — face tracking. The default; runs the per-scene strategy picker below.
- **Object** — element-aware crop, [FrameShift](https://github.com/fralapo/FrameShift)-style. Skips faces entirely and frames the most salient on-screen elements: it crops on a weighted-object centroid (animals, vehicles, held products), falls back to Sobel saliency, and finally to blurred letterbox bands when there's nothing to lock onto. Good for B-roll, product shots, and anything that isn't a talking head.
- **Off** — no reframe: a 4:3 center crop inside the 9:16 frame with black bars.

Inside **Auto**, three per-scene strategies are decided by sampling 7 frames per scene:

- **TRACK** — a single, near-static speaker → a crop locked on the face. The camera holds still; it does not pan around with the subject. (`SpeakerTracker` MAR-variance selection and `SmoothedCameraman` still run in pass 1 to find the face; the static policy then pins the shot.)
- **WIDE** — two or more faces in the scene, *or* a single subject that moves too far to hold without panning → a locked, zoomed-out crop that keeps everyone in frame with no camera motion. Movement is measured by how far the primary face travels across the sampled frames (`REFRAME_MOTION_WIDE_THRESH`, default 0.12 of the frame); past that, chasing the subject would cause the exact motion we're trying to avoid, so we pull back instead.
- **GENERAL** — no faces → letterbox.

**Static framing (`REFRAME_STATIC_AUTO`, default on):** the rule that ties the strategies together is that the camera never moves *within* a shot. Each scene collapses to a single fixed crop — TRACK locks on the face (zoom capped so it's framed, not shoved in your face), WIDE locks zoomed-out between the faces. Zoom can still change *across* a cut, which reads as a new shot rather than camera motion. This is the deterministic end-state of comfort mode; set `REFRAME_STATIC_AUTO=0` to go back to the eased-but-moving Savitzky-Golay smoother. The decision math (`centroid_span`, `collapse_scene_targets`) is pure and host-tested.

**Lost-subject recovery:** in TRACK/WIDE, if no speaker is detected for `REFRAME_LOST_HOLD` frames (~3 s) the camera eases back to the source center and gently zooms out instead of freezing on empty space. The active-speaker camera can optionally use a 1€ adaptive filter (`REFRAME_SMOOTHER=euro`) or a momentum/damped-spring smoother (`REFRAME_SMOOTHER=spring`) in place of the default two-speed EMA, with an optional hard pan-rate cap (`REFRAME_MAX_STEP_PX`). The pure decision math lives in the cv2-free, host-tested `clippyme.pipeline.reframe_ops` module; ffprobe-backed A/V-sync helpers (VFR detection, stream `start_time`, fps reconcile) live alongside in `media_probe.py`.

**Comfort mode (`REFRAME_COMFORT`, default on):** continuous face-tracking is what makes auto-reframes feel like seasickness — the camera is always gently moving, and the changing velocity (plus a zoom that breathes mid-shot) is the actual nausea trigger, not pixel jitter. So the default render now biases toward a *still* camera the way [AutoFlip](https://research.google/blog/autoflip-an-open-source-framework-for-intelligent-video-reframing/) does: a two-pass global trajectory smoother (method `savgol`/`kalman`/`l2`) Savitzky-Golay-smooths the whole camera path per scene, a per-scene **stationary lock** (`REFRAME_STATIONARY_THRESH`, default `0.30`) pins near-static scenes to a locked tripod (with `REFRAME_SNAP_CENTER`), and **per-scene zoom lock** (`REFRAME_ZOOM_LOCK`) holds one zoom level per shot so the frame never breathes. It costs a second video decode; set `REFRAME_COMFORT=0` to fall back to the original single-pass streaming tracker. See [`docs/reframe-improvements-research.md`](docs/reframe-improvements-research.md) for the measured comparison.

Override per job with `--reframe-mode auto|object|disabled` (`object` = the element-aware crop above; `disabled` = 4:3 center crop with black bars).

After a job completes, every clip can be flipped between all three modes post-hoc via `POST /api/reframe/{job_id}/{clip_index}` (the **Edit & reprocess** panel exposes the three modes and applies the switch on **Apply**). The original 16:9 source slice is preserved as `source_<clip>.mp4` to make this latency-tolerant. Legacy jobs without the preserved slice return HTTP 409.

---

## Publishing (Zernio)

`POST /api/publish/{job_id}/{clip_index}` uploads the clip to Zernio's presigned URL and schedules a post. Three scheduling modes:

- `now` — immediate
- `auto` — `SmartScheduler` picks the next free Italian-prime-time slot per weekday, with a 90-minute minimum gap and anti-collision against already-scheduled posts (3-step algorithm: free prime-time window → 15-min scan 07–23 → fallback)
- `manual` — caller passes an ISO 8601 `scheduled_for`

The dashboard `BatchPublishModal` publishes every eligible clip in one click. With `auto` it can spread one clip per day from a chosen start date (mirroring the original `tmp/programma_shorts.py` logic), and gracefully skips platforms that hit Zernio's daily limit (HTTP 429) without failing the whole batch.

---

## Security posture

This project has been audited; the current state is suitable for **trusted LAN deployment**. Notable hardening already in place:

- Strict UUID4 validation on every `{job_id}` path parameter.
- Trusted-origin guard on every config-mutation endpoint (cookies upload, Gemini key probe, Zernio config).
- Pydantic patterns on all subtitle / hook fields (font name, hex colors, file names) to prevent FFmpeg filtergraph injection.
- `_ffmpeg_filter_escape()` covers `\\ : ' , ; [ ]` and is re-applied even on direct internal callers.
- Subprocess calls use list-form argv with whitelisted `reframe_mode` and bounded `instructions` length — no shell interpolation.
- Uploaded media files are saved with a server-generated name (extension whitelisted) — the client-supplied filename is discarded.
- `data/config.json` and `data/cookies.txt` are written with mode `0600`.
- Internal exceptions never leak `str(e)` to API clients; full stack traces are logged server-side only.
- `ZERNIO_BASE_URL` env override is allowlisted to `https://*.zernio.com`.
- A secret-scan **pre-commit hook** (`.githooks/pre-commit`) blocks committing API keys, tokens, cookie files, `data/config.json`, and `.env`. Enable per clone: `git config core.hooksPath .githooks`.
- **CSRF protection**: config-mutation endpoints reject any request whose `Sec-Fetch-Site` is `cross-site`/`same-site` (a browser-set forbidden header JS can't forge), then fall back to an `Origin` allowlist — so a cross-site `<form>` POST can't reach them.
- **Per-client rate limiting** (`RATE_LIMIT_ENABLED`, default on): a dependency-free token bucket throttles the compute-heavy endpoints (`process` / `batch` / `publish`) per client IP; the bucket table is bounded against a unique-IP-flood memory DoS.
- **Spoof-resistant client IP**: `X-Forwarded-For` / `X-Real-IP` are honoured only when `TRUST_PROXY=1` **and** the TCP peer is itself a private/loopback proxy, so a direct public client can't forge its address to dodge the rate limiter or the trusted-origin guard.
- **SSRF hardening**: download + Zernio upload URLs are re-resolved and rejected when every resolved address is internal/loopback/link-local (DNS-rebinding-aware), with a bounded `getaddrinfo` timeout.

**Not yet in place** (required before exposing publicly): an authentication layer and a reverse proxy terminating TLS + security headers.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## CPU vs GPU

The CPU image runs everywhere (Linux x86_64, ARM64, Apple Silicon via Docker Desktop). Faster-Whisper falls back to CPU automatically and YOLOv8 uses the CPU path. The NVIDIA profile adds CUDA wheels for `torch`, `nvidia-cublas-cu12`, and the cuDNN runtime — expect a ~500 MB image-size overhead.

---

## Acknowledgements

- [OpenShorts](https://github.com/SamurAIGPT/Open-Source-Shorts-Maker) — original starting point.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper), [Deepgram](https://deepgram.com), [Google Gemini](https://ai.google.dev), [Ultralytics YOLO](https://github.com/ultralytics/ultralytics), [MediaPipe](https://github.com/google/mediapipe), [auto-editor](https://github.com/WyattBlue/auto-editor), [Zernio](https://zernio.com).
- [React](https://react.dev), [Vite](https://vitejs.dev), [Tailwind CSS](https://tailwindcss.com), [lucide](https://lucide.dev).
- Reframe-algorithm research studied and selectively ported (see `docs/*-analysis.md`): [fralapo/FrameShift](https://github.com/fralapo/FrameShift) (weighted-object interest region → the `object` reframe mode), [gauravzazz/smart-reframe](https://github.com/gauravzazz/smart-reframe), [KazKozDev/auto-vertical-reframe](https://github.com/KazKozDev/auto-vertical-reframe), [obi19999/smart-video-reframe](https://github.com/obi19999/smart-video-reframe), [mfahsold/montage-ai](https://github.com/mfahsold/montage-ai), [kamilstanuch/Autocrop-vertical](https://github.com/kamilstanuch/Autocrop-vertical).
