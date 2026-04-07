# ClippyMe

<div align="center">
  <img src="dashboard/public/logo.svg" alt="ClippyMe Logo" width="80" />
  <p><strong>Self-hosted AI video platform that turns long-form videos into viral 9:16 shorts — and publishes them.</strong></p>
</div>

## Features

- **Viral Moment Detection** — Google Gemini analyzes transcripts and scenes to score and rank the best moments
- **Smart 9:16 Reframing** — Active-speaker tracking using **mouth-movement detection** (MediaPipe FaceMesh + MAR variance), Y-axis tracking with dynamic vertical zoom, adaptive smoothing for snappy speaker switches, and YOLOv8 person fallback that aims at the head zone
- **Toggle System** — Smart Cut, Hook, and Subtitles as independent toggles per clip; compose only at download time
- **ASS Karaoke Subtitles** — 6 viral presets with live preview, font selection, and vertical offset slider; classic mode with per-clip font/color/position
- **Smart Cut (two-stage)** — Filler-word + transcript-gap detection (5 languages, multi-word phrase matching) rendered via **auto-editor v3 timeline JSON** for frame-accurate single-pass cuts, followed by an audio-loudness polish pass that catches silences the transcript misses
- **Hook Overlay** — Text overlay with emoji support, configurable position and size
- **Pre-selection** — Choose options before processing (including classic subtitle font/color/position); applied automatically to all generated clips
- **Mixed Batch Processing** — Submit up to 20 items mixing URLs and file uploads
- **Social Publishing (Zernio)** — One-click publish/schedule to **TikTok, Instagram, YouTube** with smart auto-scheduling (Italian prime-time slots, anti-collision)
- **Self-updating auto-editor** — The Nim binary refreshes itself daily from GitHub Releases via a background updater

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, Python 3.11, async job queue |
| AI | Google Gemini, faster-whisper, YOLOv8, MediaPipe (FaceDetection + FaceMesh) |
| Video | FFmpeg, yt-dlp (Deno JS runtime), PySceneDetect, **auto-editor (Nim, v30.x)** |
| Publishing | Zernio API (14 social platforms) |
| Frontend | React 18, Vite 5, Tailwind CSS v4, shadcn/ui, Sonner toasts |
| Infra | Docker (NVIDIA CUDA 12.3 + CPU multi-arch fallback) |
| Testing | pytest (32 unit tests, 0.1s) |

## Quick Start

```bash
git clone https://github.com/your-user/clippyme
cd clippyme
docker compose up --build
```

Open **http://localhost:5175**, enter your Gemini API key in **Settings**, and start clipping.

> [!TIP]
> First run or after dependency changes: `docker compose down -v && docker compose up --build` to clear cached volumes and the stale `node_modules` anonymous volume.

## Local Development

```bash
# Backend
pip install -r requirements.txt
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd dashboard && npm install && npm run dev
```

Frontend dev server: http://localhost:5173 | Backend: http://localhost:8000

## Tests

```bash
python -m pytest tests/test_smartcut.py tests/test_social_publisher.py -v
```

32 unit tests covering filler-word matching (n-gram lookahead, multilingual punctuation), Smart Cut concurrency primitives, hash-based output cache invalidation, the SmartScheduler slot-picking logic, and the Zernio REST client (network mocked). Runs in ~0.1s.

## Configuration

All settings are managed through the dashboard UI (**Settings** tab):

| Setting | Required | Description |
|---------|----------|-------------|
| Gemini API Key | Yes | Powers viral detection and clip analysis |
| HuggingFace Token | No | Faster Whisper model downloads |
| YouTube/Twitch Cookies | No | Netscape `.txt` file for bypassing download restrictions |
| Gemini Model | No | Model selection (default: gemini-2.5-flash) |
| **Zernio API Key** | No (only for publishing) | Powers one-click multi-platform publishing |
| **Zernio Account IDs** | No (only for publishing) | Per-platform account IDs (TikTok / IG / YT). Auto-discoverable via "Discover from Zernio" button |

> [!NOTE]
> No `.env` file needed. Config persists in `data/config.json` (git-ignored). Cookies are stored in `data/cookies.txt`. Zernio settings live in a dedicated `"zernio"` namespace inside `data/config.json` and the API key is only ever returned to the UI in masked form.

### Tunable env vars

| Var | Default | Purpose |
|---|---|---|
| `AE_SILENCE_THRESHOLD` | `0.8` | Smart Cut: gap (sec) between words → silence |
| `AE_SILENCE_KEEP` | `0.3` | Smart Cut: padding kept around each cut |
| `AE_AUDIO_THRESHOLD` | `0.04` | Audio polish: amplitude under which audio is considered silent |
| `AE_MARGIN` | `0.2sec` | Audio polish: padding around detected silence |
| `AE_MAX_POLISH_CUT_RATIO` | `0.5` | Revert audio polish if it removes more than this fraction (music safety) |
| `AE_TIMEOUT_SECONDS` | `300` | Hard cap on any auto-editor invocation |
| `AE_SKIP_POLISH_THRESHOLD` | `8.0` | Skip audio polish if stage 1 already saved this much |
| `AE_MAX_PARALLEL` | `2` | Cap on concurrent auto-editor processes (0 = unlimited) |
| `AE_FILLER_CONFIG` | `data/filler_words.json` | Optional external filler word list (JSON: `{lang: [words...]}`) |
| `ZERNIO_DEFAULT_TZ` | `Europe/Rome` | Default timezone passed to Zernio |
| `ZERNIO_MIN_GAP_SECONDS` | `5400` | Smart scheduler: min gap (sec) between scheduled posts |

## How It Works

```
Input (URL or file)
  → Download (yt-dlp)
  → Transcribe (faster-whisper, cached by URL hash)
  → Detect scenes (PySceneDetect, 7 sample frames per scene)
  → Rank viral moments (Gemini)
  → Reframe to 9:16
       ├─ TRACK / WIDE: SpeakerTracker (MAR variance + face size, hysteresis,
       │                 cooldown 1.5s) → SmoothedCameraman (X+Y tracking,
       │                 dynamic 1.0–1.6× zoom, adaptive smoothing)
       └─ GENERAL:      letterbox with blurred background
  → Post-process (zoom, audio normalization -14 LUFS, cover frame)
  → User toggles: Smart Cut / Hook / Subtitles
  → Compose & Download (or Publish)
```

## Architecture

```
app.py              FastAPI server, job queue, endpoints (~680 lines)
main.py             Pipeline: download → transcribe → detect → reframe → normalize
compose.py          Smart Cut → Hook → Subtitles compose pipeline
subtitle_pipeline.py Subtitle generation + burn helper
clip_endpoints.py   Smart Cut + history restore endpoint helpers
job_results.py      Worker loop result loaders + main.py command builder
smartcut.py         Two-stage cut: filler-word + audio polish (auto-editor v3 timeline)
auto_editor_updater.py  Background daily updater for the auto-editor binary
social_publisher.py Zernio REST client + SmartScheduler + publish_clip orchestrator
config_store.py     Persistent config (core keys + Zernio namespace)
schemas.py          Pydantic request models
security.py         Trusted-origin checks, job ID validation
subtitles.py        ASS karaoke (6 presets) + SRT
hooks.py            Text overlay with Pillow + NotoColorEmoji

dashboard/src/
  App.jsx                       Top-level orchestrator (~270 lines)
  hooks/                        useJobSubmission, useJobPolling, useHistory,
                                useSessionPersistence, useBackendStatus
  components/
    MediaInput.jsx              Single + Batch tabs (URL/file mix)
    ResultCard.jsx              9:16 player + toggles + Download/Publish
    PublishModal.jsx            Multi-platform publish modal (Zernio)
    ZernioSettings.jsx          API key + account discovery + per-platform IDs
    SubtitleModal.jsx           Karaoke/Classic editor with live preview
    HookModal.jsx               Hook text overlay editor
    ProcessingView.jsx          Processing/error/partial-results merged view
    [...20+ other components]

fonts/                          Bundled TTF fonts (served via /fonts mount)
data/                           Config, cookies, transcription cache (git-ignored)
tests/                          pytest suite (32 unit tests)
```

## API

### Processing

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/process` | Process single video (URL or file upload) |
| POST | `/api/batch` | Submit up to 20 URLs for batch processing |
| GET | `/api/status/{job_id}` | Poll job progress |
| GET | `/api/batch/{batch_id}` | Aggregated batch status |
| POST | `/api/cancel/{job_id}` | Cancel a running job |

### Editing

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/compose/{job_id}/{clip_index}` | Compose final video from active toggles |
| POST | `/api/smartcut/{job_id}/{clip_index}` | Generate smart-cut version |
| POST | `/api/subtitle` | Generate and burn subtitles |
| POST | `/api/hook` | Add hook text overlay |
| GET | `/api/subtitle/presets` | List available subtitle preset names |

### Publishing (Zernio)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/publish/{job_id}/{clip_index}` | Upload + publish/schedule on TikTok/IG/YT |
| GET | `/api/config/zernio` | Read masked Zernio settings |
| POST | `/api/config/zernio` | Save Zernio API key + account IDs + timezone |
| GET | `/api/zernio/accounts` | Discover connected social accounts via Zernio |

### Config

| Method | Path | Purpose |
|--------|------|---------|
| GET / POST | `/api/config` | Read / write core API keys |
| POST | `/api/config/cookies` | Upload persistent cookies file |
| GET | `/api/config/cookies/status` | Check if cookies are configured |
| DELETE | `/api/config/cookies` | Remove cookies file |

### History

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/history` | List past jobs |
| POST | `/api/history/{job_id}/restore` | Restore a past job to memory |
| DELETE | `/api/history/{job_id}` | Delete a job from disk |

## Smart Cut pipeline

Stage 1 (transcript-based): n-gram filler-word matching across 5 languages plus inter-word silence detection. Cuts are emitted as a hand-built **auto-editor v3 JSON timeline** and rendered in a single frame-accurate pass. Falls back to FFmpeg concat demuxer if `auto-editor` is missing.

Stage 2 (audio polish): re-runs `auto-editor --edit audio:threshold=0.04 --margin 0.2sec` on the stage-1 output to catch silences the transcript missed (mumbles below ASR confidence, music gaps). Reverts automatically if the polish would cut more than 50% (music safety net).

Per-clip locking, output caching by `(segments, language)` hash, parallel-invocation cap, probe cache, and a 5-minute timeout per subprocess. Stats include the renderer used (`auto-editor-v3` / `ffmpeg-concat` / `cache`) and the auto-editor version.

## Reframing

`SpeakerTracker` uses **mouth-aspect-ratio (MAR) variance** as the primary signal for active speaker detection. For each detected face the pipeline runs MediaPipe FaceMesh on the face ROI, extracts mouth landmarks (13/14/78/308), and keeps a 1-second sliding window of MAR samples. Combined score = `0.3 × face_size + 1.0 × MAR_variance` so a small but talking face beats a larger silent one.

`SmoothedCameraman` tracks both X and Y axes with adaptive easing (slow `0.08` glide for small moves, fast `0.30` catch-up when the speaker switches sides), animates dynamic vertical zoom between 1.0× and 1.6× based on detected face height, and clamps the crop inside the source frame. YOLO person fallback aims at the upper 15% of the bbox (head zone) instead of the body center.

`analyze_scenes_strategy()` samples 7 frames per scene (was 3) and routes each scene to `TRACK` (single speaker), `WIDE` (multi-speaker, also uses SpeakerTracker with longer cooldown — no more letterbox), or `GENERAL` (no faces, letterbox fallback).

## Subtitle Presets

`classic_white` · `hormozi_bold` · `neon_glow` · `mrbeast_box` · `minimal_clean` · `fire_impact`

The pre-selection panel shows a visual 2×3 grid of preset previews (with the actual font / color / shadow / background style) when in karaoke mode, and a font/color/position picker when in classic mode. Preview fonts are loaded via `FontFace` with the `/fonts` static mount proxied through Vite.

## Publishing

Click **Publish** on any generated clip to open the publish modal:

1. **Title + caption** prefilled from the clip's Gemini-generated metadata
2. **Platforms** — toggle TikTok / Instagram / YouTube (disabled when no account ID is configured)
3. **Schedule mode**:
   - **Now** — immediate publish (`publishNow=true`)
   - **Auto slot** — `SmartScheduler` picks the next optimal slot today/tomorrow, avoiding collisions with already-scheduled posts (Italian prime-time windows tuned for TikTok/Reels/Shorts, 90-min minimum gap)
   - **Pick time** — datetime picker for explicit ISO 8601 scheduling
4. If any toggle is active (Smart Cut / Hook / Subtitles), the backend re-composes the clip before upload so the published version reflects the preview

`auto-editor` is auto-updated daily from GitHub Releases via a background asyncio task in the FastAPI lifespan, with a `fcntl.flock` so two workers can't double-download.

## CLI

```bash
python main.py <url_or_path> [options]
  --instructions "focus on hooks"        # Directive for Gemini
  --no-zoom                              # Disable Ken Burns auto-zoom
  --reframe-mode auto|disabled           # Auto tracking or 4:3 crop
```

## Security

- Pre-commit hook blocks API keys, tokens, and cookie data from being committed
- `.gitignore` covers `data/`, cookies, `.env`, `tmp/`, and all output directories
- Zernio API key is only ever returned to the UI in masked form (`{prefix}...{suffix}`)
- Job IDs validated with strict regex to prevent path traversal
- Config endpoints require trusted origin / private network client
- Containers run as non-root users
- The Whisper transcription cache is namespaced by URL hash and pruned automatically

> [!IMPORTANT]
> After cloning, activate the pre-commit hook: `git config core.hooksPath .githooks`

## CPU / Apple Silicon

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build
```

## Acknowledgements

- [auto-editor](https://github.com/WyattBlue/auto-editor) — frame-accurate timeline renderer + audio polish
- [Zernio](https://zernio.com) — multi-platform social publishing API
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [YOLOv8](https://github.com/ultralytics/ultralytics), [MediaPipe](https://github.com/google-ai-edge/mediapipe), [PySceneDetect](https://github.com/Breakthrough/PySceneDetect)
- Originally a fork of OpenShorts
