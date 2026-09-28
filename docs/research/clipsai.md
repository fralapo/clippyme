# Comparative analysis: `ClipsAI/clipsai` → ClippyMe

> Research note — not current documentation. See [the research index](README.md).

> **Update 2026-07:** `associate_subject`/`iou` (referenced below as ClippyMe's IoU identity) were removed from `reframe_ops.py` as never-wired; `SpeakerTracker`'s center-distance hysteresis remains the live identity mechanism.

Date: 2026-06-18
External repo: <https://github.com/ClipsAI/clipsai> @ `main`
Scope studied: `clipsai/clip/` (texttiler.py, clipfinder.py), `clipsai/resize/`
(resizer.py + segmenter/crops), transcription + diarization front-ends.
Seventh external study, after `gauravzazz/smart-reframe`,
`KazKozDev/auto-vertical-reframe`, `obi19999/smart-video-reframe`,
`mfahsold/montage-ai`, `aregrid/frame`, and `kamilstanuch/Autocrop-vertical`.

---

## 0. Verdict up front

ClipsAI is a **real, mature library** (used in production, ~3k stars) covering the
same pipeline as ClippyMe: transcribe → find clips → reframe to 9:16. Two
subsystems are worth comparing in depth.

1. **Resizer** (`clipsai/resize/`) — speaker-focused reframe via pyannote
   diarization + FaceNet/MTCNN + MediaPipe MAR + K-means face clustering, emitting
   **static per-speaker-segment crops**. This is **behind ClippyMe's reframe core**
   (`SmoothedCameraman` + `reframe_ops.py`: continuous zoom, 1€/spring/savgol
   smoothing, global-trajectory pass, comfort mode, per-frame MAR active-speaker).
   Same conclusion as the Autocrop study — nothing to port on the reframe-math axis.
   The one *idea* ClippyMe doesn't use is diarization-driven crop **segmentation**;
   it's deliberately not adopted (§4).

2. **ClipFinder / TextTiling** (`clipsai/clip/`) — a **non-LLM, deterministic,
   offline** clip finder that segments a transcript at topic boundaries using the
   classic TextTiling algorithm over sentence embeddings. **ClippyMe has no
   equivalent**: its only path is Gemini viral detection, and when Gemini is
   unavailable (no key) or fails it dumps the *entire source* as one vertical clip
   (`main.py` whole-video fallback). This is the one genuinely novel subsystem, and
   it is what this study ports — as a **better whole-video fallback**.

---

## 1. Architecture comparison

| Aspect | ClipsAI | ClippyMe | Takeaway |
|---|---|---|---|
| Transcription | WhisperX (word timings) | Deepgram Nova-3 (default) + faster-whisper fallback | Parity+; ClippyMe richer. |
| Clip finding | **TextTiling** on sentence embeddings (topic boundaries, no LLM) | Gemini viral detection (`viral_score`/`viral_reason`/hook) | Different goals: topic-coherence vs viral judgment. ClippyMe stronger when AI present; **had nothing when absent**. |
| No-AI fallback | TextTiling *is* the finder (always offline) | **whole-video single render** | **Gap. Ported (lexical TextTiling).** |
| Diarization | pyannote (drives crop segments) | pyannote/Deepgram (drives subtitles/speaker labels) | Used for different stages. |
| Reframe subject | FaceNet/MTCNN + MediaPipe MAR + K-means face clustering | YOLOv8 person + MediaPipe FaceMesh + MAR + IoU/center association | Comparable detectors. |
| Reframe camera | **static per-segment crop** (one ROI per speaker turn) | `SmoothedCameraman`: EMA/1€/spring smoothing, continuous zoom, lost-subject drift, global pass | ClippyMe far ahead. |
| Crop segmentation | by **speaker turn** (diarization) merged with scene changes | by **scene** (PySceneDetect) + per-frame active-speaker | Different basis; ClippyMe finer-grained (§4). |
| Identity across frames | K-means clustering of face embeddings | `associate_subject` IoU + `SpeakerTracker` center-distance hysteresis | Parity of intent; ClippyMe's already wired. |

---

## 2. ClipFinder / TextTiling — deep dive

ClipsAI's `text_tile()` chain (faithfully reproduced):

1. **Gap scores** — for each gap between consecutive units, pool a `k`-window of
   embeddings on each side, cosine-compare. Low cosine = topic shift.
2. **Smoothing** — flat moving average (`smoothing_width`, default 3).
3. **Depth scores** — `(left_peak - gap) + (right_peak - gap)`, peaks found by
   walking outward while non-decreasing. Deep valley = strong boundary.
4. **Boundary identification** — gap is a boundary iff `depth > cutoff` AND `>=`
   both neighbours AND not a flat plateau; `cutoff = mean(+std for "high")`.
5. **ClipFinder** runs this in **nested rounds** with growing `k`
   (`[5,7]` <3min, `[11,17]` 3–10min, `[37,53,73,97]` >10min), filters by
   `min/max_clip_duration` (15s / 900s), dedupes within 15s, and combines small
   clips into "super clips" until <8 remain.

### Pros / cons vs ClippyMe's Gemini finder

| | TextTiling (ClipsAI) | Gemini (ClippyMe) |
|---|---|---|
| Cost | **free** | per-call API cost |
| Offline / deterministic | **yes** | no (network, non-deterministic) |
| Needs API key | **no** | yes |
| Viral ranking | **none** (topic boundaries only) | `viral_score` + reason + hook |
| Hook / caption text | none | yes |
| Best content | podcasts/interviews/speeches | any |
| Dep weight | sentence-transformers + torch (~90 MB model) | `requests` only |

**Conclusion:** Gemini is strictly better as the *primary* finder (viral judgment,
hooks, captions). TextTiling's value to ClippyMe is exactly the case Gemini can't
serve: **no key / API down**. There, topic-coherent multi-clip output beats a
whole-video dump.

---

## 3. What was implemented

The neural-embedding front-end is the only heavy part of ClipsAI's finder. The
**boundary math is embedding-source-agnostic**, so the port keeps ClipsAI's exact
math (steps 1–4 above) and swaps the front-end for the **original Hearst (1997)
lexical block comparison** — term-frequency vectors over windows of transcript
segments. That needs **zero new dependencies** (no `sentence-transformers`/`torch`
model download — the very dep ClippyMe avoids elsewhere, cf. the "why not
deepgram-sdk" note), only the transcript text already in hand.

New module **`src/clippyme/pipeline/analysis/texttiling_ops.py`** (pure stdlib + the
existing numpy-class math, **no cv2/torch import** → host-importable), following
the `reframe_ops.py` / `media_probe.py` "pure logic in a testable module, thin
glue in `main.py`" pattern:

- `tokenize` — unicode word tokens, multilingual (EN+IT) stop-word removal.
- `gap_scores(block_tokens, k)` — `k`-window lexical cosine across each gap.
- `smooth_scores`, `depth_scores`, `identify_boundaries` — **verbatim port** of
  ClipsAI's smoothing / depth-valley / four-condition boundary test.
- `segment_indices` — full chain → contiguous block-index spans (with ClipsAI's
  `k > n/5` auto-shrink guard).
- `find_topic_clips(segments, min=15, max=90, max_clips=12)` — maps spans to time
  windows and shapes durations: merge spans `< min` forward, slice spans `> max`
  at segment boundaries, cap clip count. Returns `[]` when un-segmentable.

Wiring (glue, in `main.py`):

- `build_texttiling_fallback(transcript, video_title)` — turns `find_topic_clips`
  output into a `{"shorts": [...]}` dict **shaped exactly like `get_viral_clips`**
  (each clip `viral_score=0` + explicit `viral_reason` so the UI shows it's
  heuristic, not AI-judged), or `None` when un-segmentable.
- The fallback branch now reads:
  `clips_data = get_viral_clips(...)` → if unusable, `build_texttiling_fallback(...)`
  → if *still* empty, the original **whole-video render** (unchanged final
  safety net). Topic clips flow through the **identical proven clip loop**
  (source slice → reframe → zoom/normalize/cover) — no new render path.

Tests: **`tests/pipeline/test_texttiling_ops.py`** — 17 host (non-integration)
cases covering tokenization, cosine, gap/smooth/depth/boundary math, span
contiguity, and the four `find_topic_clips` shaping behaviours (too-few-segments
bail, topic-split, short-merge, long-slice, clip cap).

---

## 4. Conflicts & resolutions

- **"Proven path stays byte-identical."** The port is reached **only when
  `get_viral_clips` returns nothing** (no key / parse failure). The Gemini success
  path is untouched, and the whole-video render remains the final fallback when
  TextTiling also yields nothing → strictly an *upgrade to the failure path*, no
  change to any happy path. Full host suite **459 passed** (442 baseline + 17 new),
  no regression.
- **No heavy dependency.** Adopting ClipsAI's *neural* embeddings would add
  `sentence-transformers` + a model download — exactly the kind of dep CLAUDE.md
  rejects (cf. deepgram-sdk). Resolved by porting the math and using lexical
  embeddings, so the feature ships dependency-free. The neural front-end is noted
  as a **future opt-in upgrade**: the ported boundary math is reusable as-is if
  sentence embeddings are ever added.
- **Diarization-driven crop segmentation (ClipsAI's Resizer) deliberately not
  adopted.** ClippyMe already switches the active speaker **per frame** via MAR
  variance inside scene segments — finer-grained than ClipsAI's per-turn static
  crop — and wiring a second (diarization) segmentation basis into the reframe
  render risks the byte-identical streaming path for no clear gain. Catalogued,
  not wired (honouring "non riscrivere tutto").
- **Reframe core not touched.** ClipsAI's static per-segment crop is behind
  ClippyMe's smoothed/continuous-zoom camera (same finding as five prior reframe
  studies). Nothing ported on that axis.
- **K-means face clustering not adopted.** ClippyMe's existing IoU + center-distance
  identity (`associate_subject` / `SpeakerTracker`) already covers identity; CLAUDE.md
  already flags `associate_subject` as "largely redundant," so adding a heavier
  clustering identity would be negative-value.

---

## 5. Learnings & how they were applied

1. **A mature peer can still be behind on the hard part and ahead on a part you
   skipped.** ClipsAI's reframe is simpler than ClippyMe's, but its *finder* covers
   a case ClippyMe never handled — the no-AI path. *Applied:* ignored the reframe,
   ported the finder, scoped to the fallback.
2. **Separate the algorithm from its front-end.** TextTiling's boundary math is
   independent of whether the vectors are neural embeddings or lexical bags. Porting
   the math and swapping the embedding source kept the idea while dropping the heavy
   dep. *Applied:* lexical front-end in `texttiling_ops.py`.
3. **Port as an upgrade to a failure path, not a change to a success path.** The
   feature only fires where the old code was already degrading (whole-video dump),
   so it can't regress the proven Gemini + clip-render flow. *Applied:* the layered
   `get_viral_clips → texttiling → whole-video` fallback.

---

## 6. Verification

- New pure suite: `pytest tests/pipeline/test_texttiling_ops.py` → **17 passed**.
- Full host (non-integration) suite: `pytest -m "not integration"` → **459 passed,
  3 skipped** (442 prior baseline + 17 new) — no regression.
- `py_compile` on `main.py` + `texttiling_ops.py` → clean.
- Integration path: the fallback reuses the existing clip loop + `process_video_to_vertical`
  (already integration-covered); no new render path was added, so the reframe
  integration suite is unaffected.
