# Comparative analysis: `kamilstanuch/Autocrop-vertical` → ClippyMe

Date: 2026-06-17
External repo: <https://github.com/kamilstanuch/Autocrop-vertical> @ `main`
Size: single 710-LOC `main.py` + `requirements.txt` + README (v1.4.1).
Sixth external study, after `gauravzazz/smart-reframe`,
`KazKozDev/auto-vertical-reframe`, `obi19999/smart-video-reframe`,
`mfahsold/montage-ai`, and `aregrid/frame`.

---

## 0. Verdict up front

Unlike the fifth study (`aregrid/frame`, vaporware), this is **real, mature,
single-file code** in the same domain: horizontal → vertical social-media
cropping (PySceneDetect → YOLOv8 person detection → per-scene TRACK/LETTERBOX →
OpenCV frame pipe → FFmpeg encode). Its **reframe algorithm is simpler than
ClippyMe's** (static per-scene center-crop on a person box; no camera smoothing,
no active-speaker selection, no continuous zoom, no global trajectory pass) — so
there is nothing to port on the reframe-*math* axis where ClippyMe already runs
ahead (`reframe_ops.py` + five prior studies).

Its real value is the **production-hardening layer** the changelog was written
around: A/V-sync correctness on messy real-world inputs (YouTube downloads, phone
VFR). That layer maps onto concrete, previously-unhandled gaps in ClippyMe's
clip/reframe render path, and is what this study ports.

---

## 1. Architecture comparison

| Aspect | Autocrop-vertical | ClippyMe | Takeaway |
|---|---|---|---|
| Scene detection | PySceneDetect `ContentDetector`, `--frame-skip`/`--downscale` | PySceneDetect (`scene_detection.py`) | Parity. |
| Subject detect | YOLOv8n person + Haar-cascade face (middle frame only) | YOLOv8n + MediaPipe FaceMesh + MAR active-speaker (per frame) | ClippyMe richer. |
| Crop decision | `decide_cropping_strategy`: 0 people→LETTERBOX, 1→track box, group→TRACK if group-width < crop-width else LETTERBOX | `analyze_scenes_strategy` → TRACK/WIDE/GENERAL/DISABLED | Comparable intent; ClippyMe adds WIDE multi-speaker. |
| Camera | **static** center-crop per scene (no motion) | `SmoothedCameraman`: EMA/1€/spring smoothing, continuous zoom, lost-subject drift | ClippyMe far ahead. |
| **VFR handling** | `is_variable_frame_rate` (ffprobe r vs avg rate) → re-mux `-vsync cfr` | **none** | **Gap. Ported.** |
| **Audio start_time** | `get_stream_start_time` → `-ss` trims audio lead-in | **none** | **Gap. Ported.** |
| **Corrupt-frame** | try/except → duplicate last good frame | loop aborts on exception | **Gap. Ported.** |
| **Output pix_fmt** | explicit `yuv420p` | only on *later* passes; reframe core + cut omit it | **Gap. Ported.** |
| fps source | OpenCV (same backend that reads frames) + `-vsync cfr` | PySceneDetect for `-r`, OpenCV elsewhere (mismatch risk) | Mitigated by CFR + VFR ports. |
| HW encoder | `--encoder hw` (VideoToolbox/NVENC) + fallback | libx264 only | Deferred (see §3). |
| Quality presets | `--quality fast/balanced/high` + CRF/preset overrides | fixed per stage | Deferred (off product axis). |

---

## 2. Prioritised improvement list

| Pri | Improvement | Status | Notes |
|---|---|---|---|
| **High** | Audio `start_time` offset compensation | ✅ implemented | Classic yt-dlp A/V desync; YouTube is ClippyMe's primary input. `audio_sync_seek_args` + `probe_stream_start_time`, wired into reframe Step 5. |
| **High** | VFR → CFR pre-normalization | ✅ implemented | Phone/odd-timebase sources. `probe_is_variable_frame_rate` gate + re-mux in reframe; CFR inputs (the normal clip slices) untouched. |
| **Medium** | `-pix_fmt yuv420p` on the two bare libx264 encoders | ✅ implemented | reframe raw-frame encoder + main.py source-slice cut; guarantees universal decode even when later 420p passes are skipped. |
| **Medium** | Corrupt/failed-frame resilience | ✅ implemented | try/except in the reframe render loop → duplicate last good frame; preserves frame count → no A/V drift. |
| **Medium** | `-vsync cfr` on reframe encoder + cut | ✅ implemented | Locks constant output rate; pairs with the VFR fix. |
| **Medium** | fps cross-check (cv2 ↔ PySceneDetect) | ✅ implemented | `reconcile_fps`: frames are decoded by OpenCV, so the encoder `-r` follows the cv2 reader when it diverges from the detector (>0.1 fps); within tolerance the detector value is kept (byte-identical). Fixes slow A/V drift on CFR files where VFR-normalize never fires. |
| Low | Hardware encoder (NVENC/VideoToolbox) | ⏸ deferred | ClippyMe encodes in a Linux/Docker container where libx264 is the portable choice; HW detect adds surface for marginal CPU savings off the product axis. Documented, not wired. |
| Low | `--quality`/`--ratio`/`--plan-only` CLI knobs | ⏸ deferred | ClippyMe's ratio/quality are driven by the dashboard + per-stage tuning, not CLI flags; not a fit. |

---

## 3. What was implemented

New module **`src/clippyme/pipeline/media_probe.py`** (pure helpers + thin
ffprobe wrappers, **no cv2** → host-importable), following the established
`reframe_ops.py` "pure logic in a testable module, thin glue in the cv2 file"
pattern:

- `parse_frame_rate(str) -> float` — "30000/1001" → 29.97; malformed/zero → 0.0.
- `is_vfr(r_rate, avg_rate, threshold=0.5) -> bool` — nominal vs average gap.
- `parse_start_time(str) -> float` — ffprobe `start_time`; "N/A"/garbage → 0.0.
- `audio_sync_seek_args(start, min_offset=0.05) -> list[str]` — `['-ss', …]` or `[]`.
- `probe_stream_start_time` / `probe_is_variable_frame_rate` — ffprobe wrappers
  that **never raise** (missing ffprobe / odd file → safe default).

Wiring (glue, in the integration-tested cv2 files):

- **`reframe.py`** — (a) VFR detection + `-vsync cfr` re-mux pre-step (gated on
  `probe_is_variable_frame_rate`, so CFR inputs are byte-identical); (b)
  `-pix_fmt yuv420p` + `-vsync cfr` on the raw-frame encoder; (c) try/except
  around per-frame strategy → duplicate last good frame (`dropped_frames`
  reported); (d) audio extracted with `audio_sync_seek_args(start_time)`;
  (e) `-shortest` on the final mux; (f) `temp_cfr_input` cleanup.
- **`main.py`** — `-pix_fmt yuv420p` + `-vsync cfr` on the persisted source-slice
  cut, so the slice is universally decodable and CFR before reframe ever sees it.

Tests: **`tests/pipeline/test_media_probe.py`** — 31 host (non-integration)
cases covering frame-rate parsing, VFR thresholds, start_time parsing, seek-arg
no-op boundaries, and the never-raise contract.

---

## 4. Conflicts & resolutions

- **"Proven single-pass path must stay byte-identical" (CLAUDE.md).** Every port
  is a *no-op on the common case*: `audio_sync_seek_args` returns `[]` for a
  zero start_time, VFR normalization only fires when detection is confident, and
  the corrupt-frame guard only diverges on an exception that previously aborted
  the run. The normal pipeline feeds already-re-encoded CFR, zero-start clip
  slices, so its bytes are unchanged — confirmed by the integration suite still
  passing (13/13).
- **"Don't rewrite; keep the style" (instruction).** No reframe logic was
  rewritten; the static-crop algorithm was *not* adopted (ClippyMe's is better).
  Only the orthogonal robustness layer was added, in the same inline-ffmpeg +
  pure-helper-module style already used across the pipeline.
- **fps-source mismatch (concern #3).** Closed by `reconcile_fps`: VFR normalize +
  CFR-locked output cover variable-rate sources, and on a *CFR* file where the
  detector and the cv2 reader disagree the encoder now follows the reader (the
  backend that actually decodes the frames being written). Conservative: only a
  divergence beyond 0.1 fps overrides, so the common case stays byte-identical.
- **`_render_global_smooth` opt-in path** shares the same single-write model; the
  corrupt-frame guard was extended to its pass-2 render loop too (follow-up
  commit), so both render paths now duplicate the last good frame rather than
  aborting.
- **Heavy ports skipped.** HW encoder, quality/ratio CLI flags are real but off
  ClippyMe's product axis (dashboard-driven, containerized libx264) — catalogued
  as deferred, honouring "Non riscrivere tutto."

---

## 5. Learnings & how they were applied

1. **A simpler upstream can still be a net contribution — via its hardening, not
   its core.** Autocrop's *algorithm* is behind ClippyMe's, but its changelog is
   a checklist of real-world A/V-sync bugs (VFR drift, start_time desync,
   dropped-frame drift) that a more sophisticated reframe core never bothered to
   handle. Value lived in the boring layer. *Applied:* ported the robustness,
   ignored the algorithm.
2. **Pure-vs-glue split makes "untestable" ffmpeg logic testable.** The decision
   content (VFR threshold, seek-arg boundaries, rate parsing) was extracted into
   a cv2-free module and host-unit-tested (31 cases), while only the ffmpeg
   string-building stayed in the integration-only file — same discipline as
   `reframe_ops.py`. *Applied:* `media_probe.py`.
3. **Port as no-ops on the happy path.** Each fix is gated so the proven path is
   byte-identical and only pathological inputs take the new branch. This is what
   let a change to the integration render loop ship without re-baselining the
   golden output. *Applied:* every wiring point above.

---

## 6. Verification

- Host pure-helper suite: `pytest tests/pipeline/test_media_probe.py` → **36 passed**.
- Full host (non-integration) suite: `pytest -m "not integration"` → **284 passed,
  2 skipped** (248 prior baseline + 36 new) — no regression.
- Integration suite in Docker:
  `docker compose run --rm -u root backend sh -lc "pip install -q pytest && pytest -m integration"`
  → **13 passed, 290 deselected** — reframe.py imports (cv2/mediapipe) and the
  reframe render path are unaffected by the wiring.
- `py_compile` on `reframe.py`, `main.py`, `media_probe.py` → clean.
