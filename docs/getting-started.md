# Getting started

This guide takes you from a fresh machine to your first clips. It assumes no
programming knowledge beyond running a few commands.

## What you need

- **Docker** with Compose v2 (Docker Desktop on Windows and macOS, Docker
  Engine on Linux). ClippyMe runs on x86_64 and ARM64, including Apple
  Silicon. An NVIDIA GPU is optional.
- **Disk space.** The images are several GB (PyTorch, OpenCV, MediaPipe), and
  every job keeps its source video and clips.
- **API keys** — only for the services you want:

| Service | What it does in ClippyMe | Without it |
|---------|--------------------------|------------|
| [Google Gemini](https://aistudio.google.com/apikey) | Picks the best moments and writes titles | Clips are split by topic instead, not ranked |
| [Deepgram](https://console.deepgram.com) (default) or [ElevenLabs](https://elevenlabs.io) | Fast, accurate transcription | Local Whisper transcribes on your CPU/GPU (slower) |
| [Zernio](https://zernio.com) | Publishes to TikTok, Instagram and YouTube | You download clips and post them yourself |
| [Twitch developer app](https://dev.twitch.tv/console/apps) | Watching Twitch channels with the live monitor | Twitch monitoring is unavailable |

## Install and start

```bash
git clone https://github.com/fralapo/clippyme.git
cd clippyme
docker compose up --build
```

The first build downloads and installs everything and takes a while. When the
logs settle, open **<http://localhost:5175>**. The backend listens on
<http://localhost:8000>.

Both addresses work only on this computer. To use ClippyMe from other devices,
read [Deployment → Network exposure](deployment.md#network-exposure) first.

## Configure

Open **Settings** in the dashboard and enter the keys you have. They are stored
locally in `data/config.json`, readable only by the app's user. You can also:

- upload a `cookies.txt` (Netscape format) for age-restricted or
  region-locked YouTube videos;
- upload a brand logo and custom fonts for captions and hooks;
- choose the transcription provider and the default Gemini model.

Advanced settings are environment variables; see the
[configuration reference](reference/configuration.md). Most installations
never need them.

## Make your first clips

1. In **Create**, paste a YouTube URL or upload a video file.
2. Optionally set clip options: reframe mode, captions style, instructions for
   the AI ("focus on the funny moments"), the model.
3. Start the job. Progress, logs and finished clips appear as the job runs;
   you can pause, stop and keep what is done, or discard.
4. Open a clip to edit it: colour grade, captions, silence removal, manual
   trim, hook text, logo. Nothing re-renders until you apply.
5. Download the clip, or publish or schedule it through Zernio.

Finished jobs stay in **History**, including after a restart.

## Stop and update

- Stop: `Ctrl+C` in the terminal, or `docker compose down`.
- Update:

  ```bash
  git pull
  docker compose down -v
  docker compose up --build
  ```

  `down -v` removes the container-only `node_modules` volume so the dashboard
  picks up new frontend dependencies. Your data lives in the `data/`,
  `output/` and `uploads/` folders of the repository and is not affected.

## Where things are

| Folder | Contents |
|--------|----------|
| `data/` | Settings, keys, cookies, logo, fonts, caches, monitor state |
| `output/` | One folder per job with its clips |
| `uploads/` | Videos you uploaded |

Back up `data/` to keep your configuration; back up `output/` to keep clips.

Next: [deployment options](deployment.md) (GPU, production frontend, LAN
access) · [troubleshooting](deployment.md#troubleshooting).
