# Clipping setup

Personal notes for running this fork as a hands-off stream clipper: watch a
channel, cut the best moments into 9:16 shorts, and post them to TikTok,
Instagram and YouTube. The general install guide is
[docs/getting-started.md](docs/getting-started.md). This page covers only the
choices specific to clipping streamers.

## 1. Where to run it

The live monitor has to run around the clock, so run it on a machine that
stays on.

- **Your own PC.** Fine for testing. Clips stop when the PC sleeps.
- **A small cloud server.** 4 vCPU and 8 GB RAM is enough if transcription
  goes to Deepgram instead of local Whisper. Install Docker, clone this repo,
  and run it there. Keep port 5175 closed to the internet and reach it with an
  SSH tunnel (`ssh -L 5175:localhost:5175 you@server`).
  [docs/deployment.md](docs/deployment.md#network-exposure) explains why it
  must not be exposed.

```bash
git clone https://github.com/flawnull/clippyme.git
cd clippyme
docker compose up --build -d
```

Open <http://localhost:5175>.

## 2. Keys to get

Enter them in the dashboard under **Settings**. They are stored in `data/`,
which git ignores. Never put them in a committed file.

| Key | Where | Why you need it here |
|-----|-------|----------------------|
| Gemini | <https://aistudio.google.com/apikey> | Picks and ranks the moments. Without it the monitor publishes nothing useful. |
| Deepgram | <https://console.deepgram.com> | Fast transcription. Makes a CPU-only server workable. |
| Twitch app (client ID and secret) | <https://dev.twitch.tv/console/apps> | Required to monitor Twitch. Kick and YouTube need no key. |
| Zernio | <https://zernio.com> | Posts to TikTok, Instagram and YouTube. Connect your accounts inside Zernio. It saves you TikTok's app audit: a TikTok app you register yourself can only post privately until it passes. Check that test posts show as public. |

Also set your timezone in `.env` (copy `.env.example` first). The scheduler
defaults to Italy:

```
ZERNIO_DEFAULT_TZ=America/New_York
```

## 3. Start a monitor

In the dashboard, open **Live monitor** and add one per channel. Defaults
worth knowing (full list: [docs/architecture/live-monitor.md](docs/architecture/live-monitor.md)):

- **Mode `live`** cuts the running stream into 30 minute segments and
  processes each one. **Mode `vod`** waits for the finished VOD.
- **Clip selection `auto`** drops clips with a viral score under 70, so a dull
  segment posts nothing. Prefer it over `fixed`, which always posts the top 5.
- **Spacing** between posts is 15 minutes across all monitors. There is no
  daily cap, so set one yourself by limiting `max_clips`.
- **Publishing can be paused** per monitor. Start paused, review what it
  picks for a few days, then turn auto-publish on.

## 4. Before you post anything

- Only clip streamers who allow it. Join their clipping program (Discord,
  Whop Content Rewards, or a clipping agency) and follow its rules on format,
  credit and platforms. Reposting without permission gets strikes and bans.
- Check each campaign's view-count rules. Some only pay for views on specific
  platforms, or require a tag or link in the caption. Put those in the
  monitor's caption template.
- TikTok and Instagram cut reach for raw reposts. Keep the hook, subtitles and
  banner on, which the monitor does by default.

## Known gap

Moment picking reads the transcript only. It does not look at chat, so a
gameplay moment where chat explodes but nobody says much can be missed. A
chat-spike trigger (messages per second, emote bursts) is the obvious first
improvement. [hamzaskewl/clippy](https://github.com/hamzaskewl/clippy) (MIT)
has a working Twitch version to borrow from.
