# Configuration reference

ClippyMe is configured in two places:

- **Settings tab** in the dashboard — API keys, default Gemini model,
  transcription provider, cookies, logo, fonts, Zernio and Twitch credentials.
  Stored in `data/config.json` (owner-only, git-ignored). This is the normal
  way to configure an installation.
- **Environment variables** — everything below. Put them in a `.env` file in
  the repository root; [`.env.example`](../../.env.example) is the template
  for the commonly changed ones. Docker Compose reads `.env` for the values it
  passes to the containers, and the backend loads the repository's `.env`
  itself at startup (python-dotenv), before any other module reads its
  settings. A variable already set in the process environment wins over
  `.env`.

This page is the complete list. Defaults are the values the code uses when a
variable is unset; a few differ in `docker-compose.yml`, noted as *compose*.

## Server and network

| Name | Default | Purpose | When to change |
|------|---------|---------|----------------|
| `CLIPPYME_BIND` | `127.0.0.1` | Host interface both published ports (8000, 5175) bind to. Read by `docker-compose.yml` only. | `0.0.0.0` to reach the app from other devices on a trusted LAN; set `CLIPPYME_API_TOKEN` too. |
| `CLIPPYME_API_TOKEN` | unset | When set, every `/api` request must send it (`X-API-Token` or `Authorization: Bearer`). Enter the same value in Settings → API token. | Any deployment reachable by more than your own machine. |
| `ALLOWED_ORIGINS` | `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:5175`, `http://127.0.0.1:5175` | CORS and trusted-origin allowlist (comma-separated). | Serving the dashboard from another host name. |
| `TRUST_PROXY` | `0` | `1` = read the client IP from the **last** `X-Forwarded-For` hop, only when the TCP peer is a private or loopback address. | Behind exactly one reverse proxy. Never with a proxy chain. |
| `RATE_LIMIT_ENABLED` | `1` | Per-client token buckets on the expensive endpoints (process, batch, compose, smart cut, reframe, publish, live-monitor actions). | Rarely; `0` disables it. |
| `RATE_LIMIT_MAX_BUCKETS` | `10000` | Upper bound on tracked client IPs. | Rarely. |
| `MAX_CONCURRENT_JOBS` | `5` | Jobs processed in parallel. | Lower on small machines; each job is CPU- and memory-heavy. |
| `MAX_FILE_SIZE_MB` | `16384` | Largest local upload, in MB. | Above 16 GB behind the production frontend also raise `client_max_body_size` in `dashboard/nginx.conf`. |
| `MAX_LOG_LINES` | `2000` | Lines kept in a job's visible log. | Rarely. |
| `JOB_RETENTION_SECONDS` | 30 days (*compose*: `0`) | Auto-purge age for `output/` and `uploads/`; `0` disables purging. | To reclaim disk automatically. |

## AI clip selection (Gemini)

| Name | Default | Purpose | When to change |
|------|---------|---------|----------------|
| `GEMINI_API_KEY` | unset | Gemini key. Usually entered in Settings. | — |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Preferred model; also selectable per job. | To use a different model by default. |
| `GEMINI_FALLBACK_MODELS` | `gemini-3-flash-preview,gemini-2.5-flash,gemini-3.1-flash-lite,gemini-2.5-flash-lite` | Models tried in order after quota or high-demand errors. Each job starts again from `GEMINI_MODEL`. | Paid plans that can use pro models. |
| `GEMINI_MAX_RETRIES` | `3` | Attempts per model call before moving on. | Rarely. |
| `GEMINI_RETRY_MODEL` | `gemini-2.5-flash` | Model used to reformat a malformed response. | Rarely. |

Prices used for cost estimates are in `pipeline/gemini_request.py`
(`MODEL_PRICING`), not configurable.

## Transcription

| Name | Default | Purpose | When to change |
|------|---------|---------|----------------|
| `TRANSCRIPTION_PROVIDER` | `deepgram` | `deepgram`, `elevenlabs` or `whisper` (local). Cloud providers fall back to local Whisper on failure. | Usually from Settings. |
| `CLIPPYME_TRANSCRIBE_AUDIO_ONLY` | `true` | Send a mono 16 kHz FLAC instead of the video. | Rarely. |
| `DEEPGRAM_API_KEY` | unset | Deepgram key. | — |
| `DEEPGRAM_MODEL` | `nova-3` | Deepgram model. | — |
| `DEEPGRAM_LANGUAGE` | `multi` | Language, or `multi` for automatic EN/IT code-switching. Per-job override in the Create tab. | Single-language content. |
| `DEEPGRAM_DIARIZE` | `true` | Speaker labels. | — |
| `DEEPGRAM_KEYTERMS` | empty | Comma-separated names and jargon to bias recognition. | Recurring proper nouns. |
| `DEEPGRAM_HTTP_TIMEOUT` / `DEEPGRAM_MAX_RETRIES` / `DEEPGRAM_MAX_FILE_MB` | `600` / `3` / `1900` | Request limits. | Rarely. |
| `ELEVENLABS_API_KEY` | unset | ElevenLabs key. | — |
| `ELEVENLABS_MODEL` | `scribe_v1` | `scribe_v2` supports `ELEVENLABS_NO_VERBATIM`. | — |
| `ELEVENLABS_LANGUAGE` | empty (*compose*: `multi`); both auto-detect | Language code. | Single-language content. |
| `ELEVENLABS_DIARIZE` / `ELEVENLABS_TAG_AUDIO_EVENTS` | `true` / `true` | Speaker labels / `(laughter)`-style tags passed to the AI prompt. | — |
| `ELEVENLABS_NUM_SPEAKERS` | empty | Speaker-count hint. | Known speaker count. |
| `ELEVENLABS_NO_VERBATIM` | `false` | Strip fillers at the source (v2 only). | — |
| `ELEVENLABS_AUDIO_ISOLATION` | `false` | Run the Voice Isolator before transcription (any provider; needs the ElevenLabs key). | Noisy or music-heavy sources. |
| `ELEVENLABS_HTTP_TIMEOUT` / `ELEVENLABS_MAX_RETRIES` / `ELEVENLABS_MAX_FILE_MB` | `600` / `3` / `2900` | Request limits. | Rarely. |
| `WHISPER_MODEL` | picked from hardware | `tiny` … `large-v3`. | To force a size. |
| `WHISPER_DIARIZE` | `true` | Diarization on the Whisper path; needs the `ENABLE_WHISPER_DIARIZE=1` image and a Hugging Face token. | — |
| `HF_TOKEN` / `HUGGINGFACE_TOKEN` | unset | Hugging Face token (either name). | Whisper diarization; faster model downloads. |
| `CLIPPYME_CACHE_DIR` | `data/cache` | Transcript cache location. | Rarely. |

## Download

| Name | Default | Purpose | When to change |
|------|---------|---------|----------------|
| `YTDLP_PLAYER_CLIENTS` | `default,tv+tv_embedded,web_safari` | yt-dlp player-client fallback chain. | When YouTube changes break a client. |
| `YTDLP_THROTTLED_RATE` | `102400` | Bytes/s below which a throttled segment is re-fetched. | — |
| `YTDLP_NOCHECKCERT` | unset | `1` disables TLS verification. | Only in a sandbox with a broken certificate chain. |
| `YTDLP_VERBOSE` | unset | `1` for verbose yt-dlp logs. | Debugging downloads. |
| `YOUTUBE_COOKIES` | unset | Inline cookies. Prefer uploading `cookies.txt` in Settings. | — |

## Rendering and compose

| Name | Default | Purpose | When to change |
|------|---------|---------|----------------|
| `CLIPPYME_X264_CRF` | `18` | Quality of every libx264 encode (0–51, lower is better and larger). | Smaller files. |
| `CLIPPYME_X264_PRESET` | `medium` | libx264 preset. | `fast` to render quicker. |
| `CLIPPYME_FFMPEG_TIMEOUT` | `600` | Seconds per compose pass; no-progress limit for pipeline cuts and renders. | Very long clips on slow hardware. |
| `CLIPPYME_SILENCE_SNAP` | `1` | Move clip edges into the nearest silence. | `0` to keep transcript-derived edges. |
| `CLIPPYME_FONTS_DIR` | `fonts/` | Bundled fonts. | Rarely. |
| `CLIPPYME_USER_FONTS_DIR` | `data/fonts` | Fonts uploaded in Settings. | Rarely. |
| `CLIPPYME_LOGO_PATH` | `data/logo.png` | Brand logo. | Rarely. |
| `CLIPPYME_RUNTIME_FONT_DOWNLOAD` | `0` | Allow downloading missing fonts at render time. | Rarely. |

### Smart Cut

| Name | Default | Purpose |
|------|---------|---------|
| `AE_SILENCE_THRESHOLD` | `0.8` | Gap (s) between words treated as silence. |
| `AE_SILENCE_KEEP` | `0.3` | Silence (s) kept around each cut. |
| `AE_AUDIO_THRESHOLD` / `AE_MARGIN` | `0.04` / `0.2sec` | Audio polish pass threshold and margin (auto-editor syntax). |
| `AE_SKIP_POLISH_THRESHOLD` | `8.0` | Skip the polish pass when the first pass already saved this many seconds. |
| `AE_MAX_POLISH_CUT_RATIO` | `0.5` | Reject a polish result that removes more than this share. |
| `AE_POLISH_PRESCREEN` | `1` | Skip the polish render when a silence probe predicts no useful saving. |
| `AE_MAX_PARALLEL` | `2` | Concurrent auto-editor processes. |
| `AE_TIMEOUT_SECONDS` | `300` | auto-editor timeout. |
| `AE_FILLER_CONFIG` | `data/filler_words.json` | Optional extra filler words, `{"<lang>": ["word", …]}`. |
| `AUTO_EDITOR_AUTO_UPDATE` | `0` | `1` checks for a new auto-editor binary daily. |

## Reframe

How these interact: [architecture/reframe.md](../architecture/reframe.md).

| Name | Default | Purpose |
|------|---------|---------|
| `REFRAME_COMFORT` | `1` | Two-pass render with per-scene locks. `0` = single-pass streaming tracker. |
| `REFRAME_STATIC_AUTO` | `1` | One fixed crop per scene. `0` = eased but moving camera. |
| `REFRAME_STATIONARY_THRESH` | `0.30` under comfort, else `0` | Scene-lock threshold (fraction of frame). Only with `REFRAME_STATIC_AUTO=0`. |
| `REFRAME_ZOOM_LOCK` | on under comfort | One zoom level per scene. Only with `REFRAME_STATIC_AUTO=0`. |
| `REFRAME_SNAP_CENTER` | `0.10` | Snap a locked crop to centre when this close. |
| `REFRAME_MOTION_WIDE_THRESH` | `0.12` | Subject travel that turns TRACK into WIDE. |
| `REFRAME_SPEAKER_SWITCH_MARGIN` | `1.25` | Score ratio a new speaker needs to take the frame. |
| `REFRAME_MIN_FACE_RATIO` | `0.10` | Ignore faces smaller than this share of the largest. |
| `REFRAME_DIALOGUE_GROUP` | `1` | Keep two similarly active, separated people in frame. |
| `REFRAME_DIALOGUE_SCORE_RATIO` / `REFRAME_DIALOGUE_SEPARATION` | `0.88` / `0.28` | Thresholds for dialogue framing. |
| `REFRAME_FRAMESHIFT_WEIGHTS` | `face:1,person:0.8,default:0.5` | `subject` mode class weights; add COCO classes, e.g. `dog:3`. |
| `REFRAME_SALIENT_GENERAL` | off | Saliency crop instead of letterbox in faceless scenes. |
| `REFRAME_OBJECT_WEIGHTS` | off | Weighted-object crop in faceless scenes (`1` = curated, or `dog:3,car:2`). |
| `REFRAME_LOST_HOLD` / `REFRAME_LOST_DRIFT` | `90` / `0.05` | Frames to hold a lost subject / drift-to-centre rate. |
| `REFRAME_GLOBAL_SMOOTH` | off | Force the two-pass path without comfort mode. |
| `REFRAME_GLOBAL_METHOD` | `savgol` | `kalman` or `l2`; only with `REFRAME_STATIC_AUTO=0`. |
| `REFRAME_SMOOTHER` | EMA | `euro` or `spring`; streaming tracker only. |
| `REFRAME_EURO_MINCUTOFF` / `REFRAME_EURO_BETA` | `0.014` / `0.0008` | 1€ filter tuning. |
| `REFRAME_SPRING_RESPONSE` / `REFRAME_SPRING_DAMPING` | `0.18` / `0.82` | Spring smoother tuning. |
| `REFRAME_DEADZONE_X` / `REFRAME_DEADZONE_Y` | `0.05` / `0.08` | Streaming tracker dead band. |
| `REFRAME_MAX_STEP_PX` | `0` (off) | Hard per-frame pan cap. |
| `REFRAME_DEBUG_EXC` | unset | Log the first dropped-frame exceptions in full. |

## Jobs and runtime

| Name | Default | Purpose | When to change |
|------|---------|---------|----------------|
| `CLIPPYME_JOB_MAX_ATTEMPTS` | `3` | Attempts per job (1–10). Exit code 2 is never retried. | Flaky networks: raise. |
| `CLIPPYME_RENDER_QA_RETRIES` | `1` | Extra renders after a critical output-QA failure. | — |
| `CLIPPYME_QA_SIGNAL` | `1` | `0` = structural QA only (skip black/freeze/loudness probes). | Very constrained hosts. |
| `CLIPPYME_KEEP_CHECKPOINTS` | `0` | Keep checkpoints after a fully successful job. | Debugging. |
| `CLIPPYME_MAX_DURATION_SECONDS` | disabled | Reject longer sources before paid work. | Shared or metered installs. |
| `CLIPPYME_MAX_INPUT_GB` | disabled | Reject larger inputs (GiB). | Same. |
| `CLIPPYME_MAX_ESTIMATED_COST_USD` | disabled | Reject jobs whose upper-bound Gemini cost exceeds this; unpriced reachable models are rejected while set. | Budget control. |
| `CLIPPYME_MIN_FREE_DISK_GB` | `1` | Free disk that must remain after the estimated peak. | — |
| `CLIPPYME_MAX_CLIPS` | disabled (`0`) | Render at most this many ranked clips. | — |
| `CLIPPYME_MIN_VIRAL_SCORE` | disabled | Drop clips scoring below this (1–100). | — |
| `CLIPPYME_CREATOR_NAME` | unset | Channel owner named in titles. Set per job by the live monitor. | — |

## Publishing and live monitor

| Name | Default | Purpose | When to change |
|------|---------|---------|----------------|
| `ZERNIO_BASE_URL` | `https://zernio.com/api/v1` | API base; must be `https://*.zernio.com`. | — |
| `ZERNIO_DEFAULT_TZ` | `Europe/Rome` | Timezone for automatic scheduling. | Audiences outside Italy. |
| `ZERNIO_MIN_GAP_SECONDS` | `5400` | Minimum gap between posts when a manual publish uses `auto` scheduling (SmartScheduler). Live monitors use their own `min_gap_seconds`. | — |
| `ZERNIO_HTTP_TIMEOUT` / `ZERNIO_UPLOAD_TIMEOUT` | `60` / `600` | Request and upload timeouts. | Slow uplinks. |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | unset | Twitch Helix app credentials for Twitch monitors (usually entered in Settings). | — |

Monitor behaviour (segment length, spacing, clip selection, templates) is set
per monitor in the dashboard, not by environment variables; see
[architecture/live-monitor.md](../architecture/live-monitor.md).

## Docker build arguments

| Name | Default | Purpose |
|------|---------|---------|
| `GPU_RUNTIME` | `cpu` | `nvidia` installs CUDA wheels; set by `docker-compose.gpu.yml`. |
| `ENABLE_WHISPER_DIARIZE` | `0` | `1` bakes pyannote.audio into the image (~500 MB). |

## Set internally

`CLIPPYME_JOB_ID`, `CLIPPYME_ATTEMPT` and `CLIPPYME_LANGUAGE` are passed from
the backend to the pipeline subprocess. Do not set them yourself.
