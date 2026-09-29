# Research notes

> **Not current documentation.** These notes are exploratory: studies of
> external projects, papers and techniques, written when a decision was being
> made. They can be out of date, they describe other people's code, and the
> "what ClippyMe does" parts reflect the moment they were written. Do not treat
> them as a specification. The current behaviour is in
> [`docs/architecture/`](../architecture/), the code and the tests.

They are kept because they record *why* an idea was adopted or rejected, which
saves re-running the same evaluation later.

| Note | Subject | Outcome |
|------|---------|---------|
| [title-hook-copy.md](title-hook-copy.md) | How the Gemini prompt writes titles and hooks | Rationale for the current `TITLE & CAPTION COPY` prompt section |
| [clipsai.md](clipsai.md) | ClipsAI | TextTiling topic segmentation ported as the no-AI clip fallback (`texttiling_ops.py`) |
| [videolingo.md](videolingo.md) | VideoLingo | Semantic subtitle line-splitting ported (`subtitles.py`) |
| [flycut-caption.md](flycut-caption.md) | flycut-caption | Transcript-driven manual trim ported (`drop_ranges`, `smartcut_ops.py`) |
| [reframe-autoflip.md](reframe-autoflip.md) | Google AutoFlip, framing conventions | Stationary lock / centre snap (`reframe_ops.stationary_lock`); superseded as a default by comfort mode |
| [autocrop-vertical.md](autocrop-vertical.md) | kamilstanuch/Autocrop-vertical | VFR normalisation, audio start-time compensation, corrupt-frame resilience (`media_probe.py`, `reframe.py`) |
| [auto-vertical-reframe.md](auto-vertical-reframe.md) | KazKozDev/auto-vertical-reframe | Damped-spring smoother ported (`REFRAME_SMOOTHER=spring`); the subject-ranking port was later removed as unused |
| [smart-reframe.md](smart-reframe.md) | gauravzazz/smart-reframe | Asymmetric zoom easing ported (fast pull-back, slow push-in) |
| [montage-ai.md](montage-ai.md) | mfahsold/montage-ai | Kalman / L2 camera-path smoothers ported (`REFRAME_GLOBAL_METHOD`) |
| [reframe-prior-art.md](reframe-prior-art.md) | Nine other reframing / shorts projects, including obi19999/smart-video-reframe | Survey; the split-screen idea from smart-video-reframe was ported, then removed as unused |
| [browser-editors.md](browser-editors.md) | FreeCut, OpenReel, WebCut | Rejected: different product and execution model |
