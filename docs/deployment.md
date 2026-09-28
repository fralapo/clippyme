# Deployment

ClippyMe is designed for one trusted operator on one machine. This page covers
the supported ways to run it, how far it can safely be exposed, and common
problems.

## Compose variants

| Command | Use |
|---------|-----|
| `docker compose up --build` | Default. CPU image; dashboard served by the Vite dev server with live reload and the source mounted. |
| `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build` | NVIDIA GPU (x86_64). Adds CUDA wheels (~500 MB); Whisper and pyannote diarization get much faster. Needs the NVIDIA container toolkit. |
| `docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build` | Serves a static production build of the dashboard through nginx on the same port, instead of the dev server. Needs Docker Compose 2.24 or newer. |

The GPU and production overlays can be combined by listing all three files.

Build options: `ENABLE_WHISPER_DIARIZE=1` bakes pyannote.audio into the image
for speaker labels on the local Whisper path (needs a Hugging Face token).

In every variant the backend mounts the repository at `/app`, and `data/` is a
bind mount, so configuration and output survive rebuilds. The container
starts as root only to fix ownership of `data/`, `output/` and `uploads/`, then
runs the server as an unprivileged user.

## Network exposure

The backend treats **every loopback or private-network client as trusted** for
settings and state-changing endpoints (keys, cookies, job deletion). The
defaults are built around that:

| Level | How |
|-------|-----|
| This computer only (default) | Nothing to do: both ports bind to `127.0.0.1`. |
| Trusted LAN | Set `CLIPPYME_BIND=0.0.0.0` and `CLIPPYME_API_TOKEN` in `.env`, and enter the token in Settings → API token. Add the address you open the dashboard at (for example `http://192.168.1.20:5175`) to `ALLOWED_ORIGINS` in `.env`; the browser sends it as `Origin` and the backend rejects unknown origins. Apply `.env` changes with `docker compose down` then `docker compose up -d`. |
| Internet | Not supported. |

Why the API token matters: the dashboard (Vite dev server or the production
nginx) forwards every API call from inside the Docker network, so the backend
sees every browser as the frontend container — a private address, trusted for
settings, and one shared rate-limit bucket. Once other devices can reach the
dashboard, the token is the only per-client access control. This is also why
the dashboard port binds to loopback by default.

`TRUST_PROXY=1` makes the backend read the **last** `X-Forwarded-For` hop,
which is correct when exactly one proxy that appends to the header (the shipped
`dashboard/nginx.conf`) or overwrites it sits in front of the backend. Placing
another proxy, such as a TLS terminator, in front of the production nginx makes
a chain of two, which this does not support; that is one reason internet
exposure is out of scope.

Other protections that are always on: UUID4 validation of job IDs, Pydantic
validation of every caption and hook field (prevents ffmpeg filter
injection), server-generated upload filenames, owner-only config and cookie
files, SSRF checks on download and upload URLs, per-client rate limits on
expensive endpoints, and generic error messages to clients. See also
[SECURITY.md](../SECURITY.md).

## Resources

Each job runs its own pipeline process, and video work is CPU- and
memory-heavy. `MAX_CONCURRENT_JOBS` (default 5) bounds parallel jobs; lower it
on small machines. Preflight limits (`CLIPPYME_MAX_DURATION_SECONDS`,
`CLIPPYME_MAX_INPUT_GB`, `CLIPPYME_MAX_ESTIMATED_COST_USD`,
`CLIPPYME_MIN_FREE_DISK_GB`) reject jobs before they spend money or disk. See
the [configuration reference](reference/configuration.md).

## Troubleshooting

| Symptom | Likely cause and fix |
|---------|---------------------|
| YouTube download fails with a bot check or "sign in to confirm" | Upload a fresh `cookies.txt` in Settings. If a specific player client broke, adjust `YTDLP_PLAYER_CLIENTS`. |
| Dashboard shows old code after a `git pull` | Run `docker compose down -v`, then `docker compose up --build`. |
| Transcription is slow | No cloud key is set, so local Whisper runs on the CPU. Add a Deepgram or ElevenLabs key, or use the GPU overlay. |
| Clips are split by topic, not ranked, and titles are generic | No Gemini key, or Gemini quota exhausted across the fallback chain. Check the job log. |
| A job is rejected immediately with a preflight message | A configured limit was hit (duration, size, disk, estimated cost). The message names the variable. |
| API calls return 401 | `CLIPPYME_API_TOKEN` is set; enter the same value in Settings → API token. |
| API calls return 403 when the dashboard is opened from another device | Its address is not in `ALLOWED_ORIGINS`, or the containers were not recreated (`docker compose down`, then `up -d`) after editing `.env`; see [Network exposure](#network-exposure). |
| Smart Cut result looks like a plain cut | The auto-editor binary is missing or failed; ClippyMe fell back to ffmpeg. Rebuild the image. |
| Permission denied on `data/` | Restart the backend container; the entrypoint repairs ownership on start. |
