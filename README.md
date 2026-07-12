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

> Status: personal/self-hosted project. Both published ports bind to **loopback by default** (`CLIPPYME_BIND=127.0.0.1`); opening them to a LAN (`CLIPPYME_BIND=0.0.0.0`) is a deliberate choice — pair it with `CLIPPYME_API_TOKEN` so every API request needs the shared secret. **Do not expose it to the public internet** without a reverse proxy terminating TLS in front.

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
2. **Transcribe** with one of three providers, chosen in Settings: **Deepgram Nova-3** by default (multi-language, code-switching EN/IT), **ElevenLabs Scribe** (emits `(laughter)`/`(applause)` audio-event tags that feed the viral prompt as a free emotional-payoff signal, with an optional Voice Isolator pre-pass for noisy sources), or local **Faster-Whisper**. Both cloud providers fall back to Faster-Whisper on any failure, so a bad key never breaks a job. The video is stripped to a mono-16 kHz FLAC first, so only audio is uploaded/decoded (a few MB instead of the full mp4). Cached on disk for 7 days keyed by URL hash.
3. **Detect viral moments** with **Google Gemini** (`gemini-3.5-flash` by default). A 5-axis viral_score rubric (HOOK_STRENGTH, EMOTIONAL_PAYOFF, QUOTABILITY, SELF_CONTAINED, DENSITY) plus a 5-level robust JSON parser tolerates malformed model output. **No-AI fallback:** if no Gemini key is set or the call fails, the transcript is topic-segmented into several clips by dependency-light lexical **TextTiling** (ported from [ClipsAI](https://github.com/ClipsAI/clipsai)) instead of dumping the whole video as one clip, heuristic, not viral-ranked, but offline and free. **Clean clip edges:** each selected `[start, end]` is then snapped to transcript boundaries, first to the nearest **word** edge, then extended to the surrounding **sentence** (start back to the sentence onset, end forward to the sentence-final word) so a clip never opens or closes mid-word or mid-sentence. The sentence pass is asymmetric and clamped (≤60 s, no overlap with a neighbouring clip), guards against false sentence-ends (abbreviations, decimals, acronyms), and gracefully no-ops on unpunctuated transcripts, so it is never worse than the word-only snap. A final **waveform** pass then nudges each edge into the nearest actual audio **silence trough** (ffmpeg `silencedetect`) so a cut never clips a word's attack or release, moving only toward quiet, and a no-op when no silence sits near the edge.
4. **Reframe to 9:16** with active-speaker tracking: YOLOv8 person detection + MediaPipe FaceMesh mouth-aspect-ratio (MAR) variance to pick who is speaking, then a smoothed cameraman that adapts speed and zoom per scene. Hardened against messy real-world inputs: variable-frame-rate normalization, audio `start_time` compensation (YouTube A/V desync), and corrupt-frame resilience, all no-ops on clean sources.
5. **Post-process** each clip: Ken Burns auto-zoom (1.0→1.05×), EBU R128 audio normalization to −14 LUFS, automatic cover frame selection. Every rendered mp4 is written with a leading `moov` atom (`+faststart`), so it starts playing in the browser before the full file downloads and uploads cleanly to social. Every render and compose pass shares one near-visually-lossless libx264 setting (CRF 18, `CLIPPYME_X264_CRF`), so the stacked re-encodes don't compound into soft output; the final mux and download copy are stream-copy/lossless.
6. **Optional editing** at download time (compose-on-demand): a **Colour grade** preset (warm_cinematic / cool_crisp / neutral_punch / vivid_pop), **Smart Cut** (filler-word + silence removal via auto-editor v3 timeline + audio polish, plus a separate manual transcript trim and a conversational AI trim), **Hook** text overlay (Pillow + emoji, with Instagram-Stories-style banner / colours / outline / font, defaulting to bannerless white Anton with a thin black outline), **Subtitles** (6 ASS karaoke presets or classic SRT with a live preview), and a **Brand logo** watermark. The per-clip editor is a tabbed modal; settings can be applied to one clip, copied to all clips, or staged across a multi-select. Custom subtitle/hook fonts and the logo are uploaded once in Settings.
7. **Publish or schedule** to TikTok / Instagram / YouTube via **Zernio**, with a SmartScheduler that picks Italian-prime-time slots, avoids same-day collisions, and (when scheduling) spreads one clip per day to stay under per-platform daily caps. Any residual Zernio daily-limit 429 is surfaced verbatim per clip.

While a job runs you stay in control:

- **Edit clips as they finish**: completed clips stream into the full editor (toggles, disable/delete, publish) while later ones are still rendering; no need to wait for the whole job.
- **Pause / Resume / Stop**: suspend and resume the running job, **Stop & keep** to end early but retain the clips finished so far, or **Discard** to kill and delete everything.
- **Pick the AI model per job**: override the Gemini model for a single run from the Clip Options panel (or set the default, with live model discovery, in Settings).

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, asyncio queue |
| Pipeline | yt-dlp · Deepgram REST · ElevenLabs Scribe REST · Faster-Whisper · PySceneDetect · YOLOv8 (Ultralytics) · MediaPipe · ffmpeg · auto-editor (Nim binary) · Pillow |
| AI | Google Gemini (viral detection) · Deepgram Nova-3 / ElevenLabs Scribe (transcription) |
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

### Production frontend (optional)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build
```

Swaps the dashboard from the Vite dev server to a static `vite build` served by **nginx** (same port 5175, same loopback default; the nginx proxy mirrors the dev proxy with 600 s timeouts for long composes and unbuffered upload/video streaming). The default `docker compose up` dev workflow (HMR + bind mount) is untouched. Requires Docker Compose ≥ 2.24.

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
                                                [--reframe-mode auto|subject|disabled] \
                                                [--no-zoom]
```

---

## Configuration

All API keys, model selection, and cookies are managed **from the dashboard Settings tab** and persisted to `data/config.json` (mode `0600`, git-ignored). No `.env` file required.

| Key | Required for | Notes |
|---|---|---|
| `GEMINI_API_KEY` | Viral moment detection | Default model `gemini-3.5-flash`; override per job or set the default in Settings (live model discovery). |
| `DEEPGRAM_API_KEY` | Cloud transcription (default) | Falls back to local Faster-Whisper if missing. |
| `ELEVENLABS_API_KEY` | Alternative cloud transcription (Scribe) | Adds audio-event tags + optional Voice Isolator; also falls back to Faster-Whisper. |
| `HUGGINGFACE_TOKEN` | Optional gated models for Whisper | |
| Zernio | Social publishing | Per-platform account IDs auto-discovered via "Discover from Zernio". |
| Cookies | YouTube age-gated / region-locked content | Upload a Netscape `cookies.txt` from the Settings tab. Stored at `data/cookies.txt`, mode `0600`, max 10 MB. |

Runtime env overrides (rarely needed):

| Variable | Default | Purpose |
|---|---|---|
| `CLIPPYME_BIND` | `127.0.0.1` | Host interface both published ports (8000/5175) bind to. `0.0.0.0` exposes the app to the LAN — deliberate choice only. |
| `CLIPPYME_API_TOKEN` | _(unset)_ | Optional shared-secret auth: when set, every `/api` request must carry it (`X-API-Token` or `Authorization: Bearer`). The dashboard stores it in Settings → API token. Unset = no-op. |
| `TRANSCRIPTION_PROVIDER` | `deepgram` | Or `elevenlabs` (Scribe), or `whisper` to force local. |
| `ELEVENLABS_AUDIO_ISOLATION` | `false` | Run the ElevenLabs Voice Isolator before ASR to strip background noise/music on noisy sources. |
| `CLIPPYME_TRANSCRIBE_AUDIO_ONLY` | `true` | Strip to audio-only FLAC before transcription; `false` sends the full video. |
| `CLIPPYME_SILENCE_SNAP` | `1` | Refine clip edges to the nearest waveform silence trough (ffmpeg `silencedetect`); `0`/`false` keeps the transcript-derived edges. |
| `DEEPGRAM_MODEL` | `nova-3` | |
| `DEEPGRAM_LANGUAGE` | `multi` | |
| `REFRAME_COMFORT` | `1` | Anti-nausea default (global-smooth + per-scene stationary + zoom lock). `0` = original single-pass tracker. |
| `REFRAME_STATIC_AUTO` | on | Lock the camera per scene, zero pan, zero mid-shot zoom. `0` = eased-but-moving smoother. |
| `REFRAME_MOTION_WIDE_THRESH` | `0.12` | How far a single subject may travel (fraction of frame) before TRACK is demoted to a static WIDE crop. |
| `REFRAME_STATIONARY_THRESH` / `REFRAME_ZOOM_LOCK` | `0.30` / on | Comfort tuning: scene-lock threshold / one zoom level per scene. |
| `REFRAME_SALIENT_GENERAL` | _(off)_ | Content-aware crop for faceless scenes instead of letterboxing. |
| `REFRAME_OBJECT_WEIGHTS` | _(off)_ | Faceless scenes follow a weighted-object centroid (product/dog/car) by reusing the existing YOLO pass. `1` = curated defaults, or `dog:3,car:2` for custom weights. |
| `REFRAME_FRAMESHIFT_WEIGHTS` | _(GUI defaults)_ | `object`-mode class weights. Defaults `face:1,person:0.8,default:0.5`; override any of those three or add a COCO class, e.g. `face:1,person:0.8,default:0.5,dog:3`. |
| `CLIPPYME_X264_CRF` | `18` | Shared libx264 quality for every render/compose encode (near-visually-lossless; lower = higher quality + bigger files, 0–51). Stops the stacked re-encodes from compounding into soft output. |
| `CLIPPYME_X264_PRESET` | `medium` | Shared libx264 preset; a faster preset (e.g. `fast`) trades a little quality/size for render speed. |
| `ZERNIO_DEFAULT_TZ` | `Europe/Rome` | |
| `ZERNIO_MIN_GAP_SECONDS` | `5400` | SmartScheduler min spacing between posts. |
| `REFRAME_SMOOTHER` | _(blank)_ | `euro` switches the speaker camera to the 1€ adaptive filter; blank keeps the two-speed EMA. |
| `REFRAME_LOST_HOLD` | `90` | Frames a lost subject is held before the camera drifts back to center (~3 s @ 30 fps). |
| `REFRAME_LOST_DRIFT` | `0.05` | Per-frame ease rate of the drift-to-center recovery. |
| `REFRAME_EURO_MINCUTOFF` / `REFRAME_EURO_BETA` | `0.014` / `0.0008` | 1€ smoother tuning (only when `REFRAME_SMOOTHER=euro`): smoothness floor / speed responsiveness. |
| `REFRAME_SPRING_RESPONSE` / `REFRAME_SPRING_DAMPING` | `0.18` / `0.82` | Damped-spring smoother tuning (only when `REFRAME_SMOOTHER=spring`): acceleration / velocity decay. |
| `REFRAME_GLOBAL_SMOOTH` / `REFRAME_GLOBAL_METHOD` | _(off)_ / `savgol` | Opt-in 2-pass trajectory smoothing. ⚠️ `kalman`/`l2` only take effect with `REFRAME_STATIC_AUTO=0` — under the default static-auto policy each scene collapses to one locked crop and the trajectory smoother never runs. |

---

## Repository layout

Backend uses an **`src/`-layout** Python package; frontend is a separate Vite app. Tests live at the root.

```
src/clippyme/
  netutil.py          Bounded DNS resolution shared by the SSRF guards (no global socket state)
  api/                FastAPI surface (thin: validate → domain helper → JSON)
    app.py            Thin FastAPI layer: job-lifecycle routes, middleware, static mounts, lifespan
    config_routes.py  Config-family APIRouter (keys/cookies/fonts/logo/zernio/models), include_router'ed by app.py
    schemas.py        Pydantic request models (strict validation)
    security.py       Trusted-origin / rate-limit / API-token gates, job-id validation
  pipeline/           Heavy lifters (main.py imports cv2/torch → pure logic lives in the *_ops modules)
    main.py           CLI orchestrator: download → transcribe → Gemini → reframe → postprocess
    run_ops.py        Pure entrypoint helpers (output-dir resolve, cut-command argv) → host-tested
    gemini_request.py Pure Gemini prompt template + pricing + cost/retry classification → host-tested
    gemini_parser.py  5-level JSON parsing chain + Pydantic validation + dedupe
    gemini_service.py List available Gemini models (bounded timeout)
    texttiling_ops.py Lexical TextTiling topic segmentation (no-AI clip fallback, no cv2/torch → host-tested)
    reframe.py        cv2 render orchestrator: scene strategy, frame strategies, render loops
    reframe_track.py  Pure tracking classes (SpeakerTracker / SmoothedCameraman, no cv2 → host-tested)
    reframe_ops.py    Pure camera/decision math (no cv2 → host-tested): smoothers, zoom, crops
    reframe_detect.py YOLO / MediaPipe detectors
    cut_ops.py        Pure clip-edge snapping + neighbour-bounds / transcript-snap orchestration → host-tested
    media_probe.py    cv2-free ffprobe + A/V-sync helpers (VFR, start_time, fps)
  domain/             Endpoint-facing business logic (never imports FastAPI; raises errors.ClippyMeError)
    errors.py         Domain exceptions (Validation/NotFound/Conflict) mapped to HTTP by one app handler
    clip_resolve.py   Shared resolve_clip(): job dir → metadata → clip entry → path (used by every per-clip route)
    job_submission.py · job_runner.py · job_worker.py   Submit + per-job subprocess loop + queue dispatch/cleanup
    job_journal.py · job_control.py · job_actions.py    Crash-safe journal + recovery, status machine, cancel/stop
    job_results.py · job_artifacts.py   Result loaders + main.py command builder; atomic metadata IO
    compose.py        Grade → Subtitles → Smart Cut → Hook → Logo compose pipeline (pass-fused)
    smartcut.py       Two-stage filler-word + audio polish (auto-editor v3 timeline)
    smartcut_ops.py   Pure silence/filler/timeline math (host-tested), re-exported by smartcut.py
    clip_endpoints.py · clip_edit_ai.py · clip_qa.py   Smart-cut runner + NL→drop_ranges + QA self-eval
    subtitles.py      ASS karaoke (6 presets) + SRT + ffmpeg burn (filtergraph-escape hardened)
    hooks.py          Text overlay (Pillow + NotoColorEmoji) w/ IG-style banner/outline/font
    logo.py · grade.py   Brand-logo / watermark overlay + colour-grade presets
    encode.py         Single source of x264 settings for every render pass
    publish_service.py · history_service.py   Zernio publish flow + disk-backed job history scan
  integrations/       External clients
    social_publisher.py      Zernio REST + SmartScheduler + publish_clip orchestrator
    auto_editor_updater.py   Background daily updater for the auto-editor binary
  storage/
    config_store.py   data/config.json read/write (mode 0600)

dashboard/
  src/
    main.jsx                Mounts redesign/RedesignApp
    redesign/               The live UI. RedesignApp (top-level state wiring),
                            create / results / publish / views (Settings + History) / processing,
                            captions.jsx (EditClipModal shell) + editTabs.jsx (per-tab bodies),
                            subtitleControls.jsx / layerControls.jsx / hookStyle.jsx (controls shared
                            between Create and the edit modal), realApi.js (backend client),
                            data.js (presets/options), primitives.jsx, icon.jsx
    hooks/                  useJobSubmission (resilient batch poller), useJobPolling, useManualTrim,
                            useHistory, useSessionPersistence, useBackendStatus, useClipStates
    lib/                    Pure helpers (host-tested via `npm test`): applyEdit (reprocess orchestration),
                            pipelineStep, bulkApply, seedClipParams, trimSelection, taste

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
| `POST` | `/api/compose/{job_id}/{clip_index}` | Compose Grade + Subtitles + Smart Cut + Hook + Logo on demand. |
| `POST` | `/api/smartcut/{job_id}/{clip_index}` | Smart Cut a single clip (optional `drop_ranges` for manual trim). |
| `GET` | `/api/transcript/{job_id}/{clip_index}` | Per-clip transcript segments for the manual-trim UI. |
| `POST` | `/api/edit-ai/{job_id}/{clip_index}` | Conversational trim: a plain-English instruction → Gemini → spans to cut. |
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

Every finished clip has an **Edit & reprocess** panel, one button on the clip card opens a **tabbed modal** (Reframe · Grade · Captions · Hook · Smart Cut · Trim · Logo) that gathers all the options in one place so you set everything first and apply once, instead of the clip reprocessing on every tweak. The compose layers:

- **Colour grade**: one of four ffmpeg presets (warm_cinematic / cool_crisp / neutral_punch / vivid_pop). Runs first so the overlays below keep their authored colours.
- **Smart Cut**: auto-removes silences and filler words via auto-editor v3 timeline; falls back to ffmpeg concat demuxer if the binary is missing.
- **Trim** (its own tab): shows the clip's transcript as a tap-to-cut checklist for hand-removing specific lines, kept separate from the automatic pass. A plain-English **AI trim** box turns an instruction like "cut the intro" into the same spans. The picked spans (`drop_ranges`) ride through download and publish; dropping a line implies the Smart Cut compose stage.
- **Hook**: text overlay, auto-prefilled from the Gemini hook suggestion. Beyond position/size it offers **Instagram-Stories-style text styling**: a toggleable coloured banner behind the text (colour + opacity), independent text colour, an outline/stroke (None/Thin/Thick + colour), and a font choice. The default look is bannerless white **Anton** with a thin black outline. A live WYSIWYG preview sits above the controls. Supports emoji.
- **Subtitles**: 6 viral karaoke presets (`classic_white`, `hormozi_bold`, `neon_glow`, `mrbeast_box`, `minimal_clean`, `fire_impact`) or classic SRT with font/color/position controls. The Create-tab grid (`dashboard/src/redesign/data.js`) is a cosmetic CSS preview (system fonts; highlight colours match the backend), not pixel-faithful.
- **Brand logo**: burns an uploaded transparent PNG onto the clip (7 anchor positions × S/M/L size × opacity). Upload it once in Settings → Brand assets.

**Apply across clips.** Each card has an **Apply to all** button that copies that clip's settings to every other clip; in multi-select mode (with **Select all / Deselect all**) you can **Edit N** selected clips at once. Both bulk paths copy the shared config (reframe / Smart Cut / subtitles / hook style / logo) but keep each clip's own manual trim and hook text, and reprocess with a bounded concurrency so the box isn't flooded with subprocesses.

**Custom fonts**: upload a `.ttf`/`.otf` (e.g. a licensed Stratos) in Settings → Brand assets and it appears in the classic-subtitle and hook font pickers, resolved at burn time from the writable `data/fonts/` dir alongside the bundled faces.

Editing is staged: nothing runs while you toggle. **Apply & reprocess** re-renders the framing (only when the reframe mode changed) and then composes the active layers in one pass via `/api/compose/{job_id}/{clip_index}`: order is **Grade → Subtitles → Smart Cut → Hook → Logo** (grade first so the overlays keep their authored colour; subtitles burn next so their absolute timing never drifts when Smart Cut removes silences; the logo sits on top of everything). Adjacent layers are fused into shared ffmpeg passes (grade+subtitles in one, hook+logo in one), so a fully-toggled compose is 3 encodes instead of 5 — noticeably faster downloads with zero quality change. Reprocessing runs in the **background**: Apply closes the modal immediately and the clip card shows a *Reprocessing…* overlay, so you can edit other clips meanwhile. The preview updates to the composed result, and downloading runs the same compose, so what you see is what you get. Downloaded clips are named after the AI-suggested title (sanitized for Windows: forbidden characters and reserved device names are stripped, length-capped, falling back to `clip_N`).

**Apply runs in the background.** Hitting Apply closes the modal immediately and the reframe/compose work runs without blocking the page, the clip card shows a *Reprocessing…* overlay while it renders, and you can edit, reprocess, and publish other clips at the same time. Each clip is an independent job, so several can render at once.

---

## Reframing

Pick one of three modes per job (and per clip after the fact, from the **Edit & reprocess** panel or `POST /api/reframe`):

- **Auto**: face tracking. The default; runs the per-scene strategy picker below.
- **Subject** (the CLI value is `subject`; `object` still works as a legacy alias): [FrameShift](https://github.com/fralapo/FrameShift) face-first crop. Computes a weighted-interest centroid over **every** detection in the frame — faces (weight 1.0), persons (0.8) and other on-screen objects (default 0.5, the FrameShift GUI sliders), each scaled by area and confidence — then crops a 9:16 window on it. A face pulls the camera hardest, so a talking head stays framed while relevant objects (a product, a dog, a car) still bias the crop; a shot with no detectable subject falls back to a black-padded letterbox. Tune the weights with `REFRAME_FRAMESHIFT_WEIGHTS`.
- **Off**: no reframe: a 4:3 center crop inside the 9:16 frame with black bars.

Inside **Auto**, three per-scene strategies are decided by sampling 7 frames per scene:

- **TRACK**: a single, near-static speaker → a crop locked on the face. The camera holds still; it does not pan around with the subject. (`SpeakerTracker` MAR-variance selection and `SmoothedCameraman` still run in pass 1 to find the face; the static policy then pins the shot.)
- **WIDE**: two or more faces in the scene, *or* a single subject that moves too far to hold without panning → a locked, zoomed-out crop that keeps everyone in frame with no camera motion. Movement is measured by how far the primary face travels across the sampled frames (`REFRAME_MOTION_WIDE_THRESH`, default 0.12 of the frame); past that, chasing the subject would cause the exact motion we're trying to avoid, so we pull back instead.
- **GENERAL**: no faces → letterbox.

**Static framing (`REFRAME_STATIC_AUTO`, default on):** the rule that ties the strategies together is that the camera never moves *within* a shot. Each scene collapses to a single fixed crop, TRACK locks on the face (zoom capped so it's framed, not shoved in your face), WIDE locks zoomed-out between the faces. Zoom can still change *across* a cut, which reads as a new shot rather than camera motion. This is the deterministic end-state of comfort mode; set `REFRAME_STATIC_AUTO=0` to go back to the eased-but-moving Savitzky-Golay smoother. The decision math (`centroid_span`, `collapse_scene_targets`) is pure and host-tested.

**Lost-subject recovery:** in TRACK/WIDE, if no speaker is detected for `REFRAME_LOST_HOLD` frames (~3 s) the camera eases back to the source center and gently zooms out instead of freezing on empty space. The active-speaker camera can optionally use a 1€ adaptive filter (`REFRAME_SMOOTHER=euro`) or a momentum/damped-spring smoother (`REFRAME_SMOOTHER=spring`) in place of the default two-speed EMA, with an optional hard pan-rate cap (`REFRAME_MAX_STEP_PX`). The pure decision math lives in the cv2-free, host-tested `clippyme.pipeline.reframe_ops` module; ffprobe-backed A/V-sync helpers (VFR detection, stream `start_time`, fps reconcile) live alongside in `media_probe.py`.

**Comfort mode (`REFRAME_COMFORT`, default on):** continuous face-tracking is what makes auto-reframes feel like seasickness, the camera is always gently moving, and the changing velocity (plus a zoom that breathes mid-shot) is the actual nausea trigger, not pixel jitter. So the default render now biases toward a *still* camera the way [AutoFlip](https://research.google/blog/autoflip-an-open-source-framework-for-intelligent-video-reframing/) does: a two-pass global trajectory smoother Savitzky-Golay-smooths the whole camera path per scene (the alternative `REFRAME_GLOBAL_METHOD=kalman`/`l2` pan-path solvers are reachable only with `REFRAME_STATIC_AUTO=0` — the default static-auto policy collapses each scene to a single locked crop before they would run), a per-scene **stationary lock** (`REFRAME_STATIONARY_THRESH`, default `0.30`) pins near-static scenes to a locked tripod (with `REFRAME_SNAP_CENTER`), and **per-scene zoom lock** (`REFRAME_ZOOM_LOCK`) holds one zoom level per shot so the frame never breathes. It costs a second video decode; set `REFRAME_COMFORT=0` to fall back to the original single-pass streaming tracker. See [`docs/reframe-improvements-research.md`](docs/reframe-improvements-research.md) for the measured comparison.

Override per job with `--reframe-mode auto|subject|disabled` (`subject` = the FrameShift face-first crop above, with `object` accepted as a legacy alias; `disabled` = 4:3 center crop with black bars).

After a job completes, every clip can be flipped between all three modes post-hoc via `POST /api/reframe/{job_id}/{clip_index}` (the **Edit & reprocess** panel exposes the three modes and applies the switch on **Apply**). The original 16:9 source slice is preserved as `source_<clip>.mp4` to make this latency-tolerant. Legacy jobs without the preserved slice return HTTP 409.

---

## Publishing (Zernio)

`POST /api/publish/{job_id}/{clip_index}` uploads the clip to Zernio's presigned URL and schedules a post. Three scheduling modes:

- `now`: immediate
- `auto`: `SmartScheduler` picks the next free Italian-prime-time slot per weekday, with a 90-minute minimum gap and anti-collision against already-scheduled posts (3-step algorithm: free prime-time window → 15-min scan 07–23 → fallback)
- `manual`: caller passes an ISO 8601 `scheduled_for`

The dashboard's unified `PublishModal` publishes the selected clips concurrently in one click, each row showing live queued → uploading → live/error status. With `auto` it spreads one clip per day from a chosen start date (mirroring the original `tmp/programma_shorts.py` logic) to stay under per-platform daily caps; any residual Zernio daily-limit 429 is surfaced verbatim per clip instead of failing the whole batch.

---

## Security posture

This project has been audited; the current state is suitable for **trusted LAN deployment**. Notable hardening already in place:

- Strict UUID4 validation on every `{job_id}` path parameter.
- Trusted-origin guard on every config-mutation endpoint (cookies upload, Gemini key probe, Zernio config).
- Pydantic patterns on all subtitle / hook fields (font name, hex colors, file names) to prevent FFmpeg filtergraph injection.
- `_ffmpeg_filter_escape()` covers `\\ : ' , ; [ ]` and is re-applied even on direct internal callers.
- Subprocess calls use list-form argv with whitelisted `reframe_mode` and bounded `instructions` length, no shell interpolation.
- Uploaded media files are saved with a server-generated name (extension whitelisted): the client-supplied filename is discarded.
- `data/config.json` and `data/cookies.txt` are written with mode `0600`.
- Internal exceptions never leak `str(e)` to API clients; full stack traces are logged server-side only.
- `ZERNIO_BASE_URL` env override is allowlisted to `https://*.zernio.com`.
- A secret-scan **pre-commit hook** (`.githooks/pre-commit`) blocks committing API keys, tokens, cookie files, `data/config.json`, and `.env`. Enable per clone: `git config core.hooksPath .githooks`.
- **CSRF protection**: config-mutation endpoints reject any request whose `Sec-Fetch-Site` is `cross-site`/`same-site` (a browser-set forbidden header JS can't forge), then fall back to an `Origin` allowlist, so a cross-site `<form>` POST can't reach them.
- **Per-client rate limiting** (`RATE_LIMIT_ENABLED`, default on): a dependency-free token bucket throttles the compute-heavy endpoints (`process` / `batch` / `publish`) per client IP; the bucket table is bounded against a unique-IP-flood memory DoS.
- **Spoof-resistant client IP**: `X-Forwarded-For` / `X-Real-IP` are honoured only when `TRUST_PROXY=1` **and** the TCP peer is itself a private/loopback proxy, so a direct public client can't forge its address to dodge the rate limiter or the trusted-origin guard. Within `X-Forwarded-For` the backend reads the **last** hop — the address the proxy itself wrote — so it stays spoof-proof whether your proxy appends to the header (nginx's `$proxy_add_x_forwarded_for`, as shipped) or overwrites it. Exactly one trusted proxy is supported; don't enable it behind a proxy chain.
- **SSRF hardening**: download + Zernio upload URLs are re-resolved and rejected when every resolved address is internal/loopback/link-local (DNS-rebinding-aware), with the DNS lookup bounded by a daemon-thread timeout (no process-global socket state).
- **Loopback by default**: both published ports bind to `127.0.0.1` (`CLIPPYME_BIND`). The trust model treats every private-network peer as an authorized client for config/state endpoints, so LAN exposure is opt-in, not the default.
- **Optional API token** (`CLIPPYME_API_TOKEN`): when set, an app middleware requires the shared secret on every `/api` request (`X-API-Token` or `Authorization: Bearer`, constant-time compare) — the auth layer for deliberate LAN deployments. Static media mounts stay IP-open (`<video>`/FontFace can't send custom headers).

**Not yet in place** (required before exposing publicly): a reverse proxy terminating TLS + security headers.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## CPU vs GPU

The CPU image runs everywhere (Linux x86_64, ARM64, Apple Silicon via Docker Desktop). Faster-Whisper falls back to CPU automatically and YOLOv8 uses the CPU path. The NVIDIA profile adds CUDA wheels for `torch`, `nvidia-cublas-cu12`, and the cuDNN runtime, expect a ~500 MB image-size overhead.

---

## Acknowledgements

- [OpenShorts](https://github.com/SamurAIGPT/Open-Source-Shorts-Maker): original starting point.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper), [Deepgram](https://deepgram.com), [Google Gemini](https://ai.google.dev), [Ultralytics YOLO](https://github.com/ultralytics/ultralytics), [MediaPipe](https://github.com/google/mediapipe), [auto-editor](https://github.com/WyattBlue/auto-editor), [Zernio](https://zernio.com).
- [ClipsAI](https://github.com/ClipsAI/clipsai): TextTiling topic-segmentation algorithm (the no-AI clip-finding fallback is a lexical port; see [`docs/clipsai-analysis.md`](docs/clipsai-analysis.md)).
- [React](https://react.dev), [Vite](https://vitejs.dev), [Tailwind CSS](https://tailwindcss.com), [lucide](https://lucide.dev).
- Reframe-algorithm research studied and selectively ported (see `docs/*-analysis.md`): [fralapo/FrameShift](https://github.com/fralapo/FrameShift) (weighted-object interest region → the `object` reframe mode), [gauravzazz/smart-reframe](https://github.com/gauravzazz/smart-reframe), [KazKozDev/auto-vertical-reframe](https://github.com/KazKozDev/auto-vertical-reframe), [obi19999/smart-video-reframe](https://github.com/obi19999/smart-video-reframe), [mfahsold/montage-ai](https://github.com/mfahsold/montage-ai), [kamilstanuch/Autocrop-vertical](https://github.com/kamilstanuch/Autocrop-vertical).
