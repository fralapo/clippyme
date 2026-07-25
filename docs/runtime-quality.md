# Runtime resilience and media quality

ClippyMe's queued backend jobs run through `clippyme.pipeline.orchestrator`. The
legacy `clippyme.pipeline.main` module still owns transcription, Gemini analysis,
cutting and reframe algorithms; the orchestrator adds durability and verification
around those proven stages.

## Durable job lifecycle

Each job output directory contains two hidden internal resources:

- `.clippyme_runtime.json`: owner-only operational state, phase, progress,
  attempts, timings, preflight and QA summaries;
- `.clippyme_checkpoint/`: reusable transcript and phase artefacts while a job is
  incomplete.

Writes are atomic and fsync'd. The static `/videos` mount rejects hidden JSON and
checkpoint paths. If the worker fails transiently, the next attempt reuses valid
source downloads, transcripts, analysis metadata, source slices and completed
clips. After a backend restart, interrupted jobs resume only when the runtime
state and original source are still safe; progressive metadata alone is never
considered a completion marker.

`source_<clip>.mp4` slices are intentionally retained after success because the
post-hoc reframe endpoint needs them to change crop mode without downloading,
transcribing or analysing the source again.

## Retry controls

| Variable | Default | Meaning |
| --- | ---: | --- |
| `CLIPPYME_JOB_MAX_ATTEMPTS` | `3` | Total worker attempts, bounded to 1–10 |
| `CLIPPYME_RENDER_QA_RETRIES` | `1` | Extra render attempts after critical QA failure |
| `CLIPPYME_KEEP_CHECKPOINTS` | `0` | Keep hidden duplicate transcript checkpoints after full success |

Exit code `2` is reserved for deterministic validation or preflight rejection and
is never retried. Other non-zero exits retry with bounded exponential backoff.
Stopping/cancelling a job preserves the established user semantics.

## Preflight and quotas

Before transcription or AI analysis, ClippyMe probes the source and estimates:

- duration and input size;
- likely clip count;
- runtime and peak disk requirement;
- Gemini input/output tokens and estimated USD cost when pricing is known;
- available disk headroom.

The estimate is deliberately conservative and is not a billing promise. Operators
can reject jobs before expensive work with:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `CLIPPYME_MAX_DURATION_SECONDS` | disabled | Maximum source duration |
| `CLIPPYME_MAX_INPUT_GB` | disabled | Maximum input size in GiB |
| `CLIPPYME_MAX_ESTIMATED_COST_USD` | disabled | Maximum estimated Gemini cost |
| `CLIPPYME_MIN_FREE_DISK_GB` | `1` | Free space that must remain after estimated peak use |
| `CLIPPYME_MAX_CLIPS` | disabled | Maximum number of ranked candidates actually rendered |

`--skip-analysis` is modelled separately: it creates one whole-video output and
estimates zero Gemini usage.

## Operational telemetry

The existing status response remains backward compatible and may additionally
contain `result.operations`. The processing view shows:

- durable phase and real progress;
- attempt number and ETA;
- verified/failed clip counts;
- host CPU, process-tree RAM and free disk;
- preflight time, disk, clip and Gemini estimates;
- per-stage durations and QA summaries.

A single replaceable `[runtime]` line is kept in the bounded job log, preventing
telemetry polling from growing logs indefinitely.

## Production output QA

Every temporary render is checked before it atomically replaces the public clip:

- file size and readable duration;
- audio and video stream presence;
- expected duration and aspect ratio;
- full-frame black and frozen-frame ratios;
- mean and peak audio level.

Structural defects are critical and trigger a bounded re-render. Signal findings
are warnings and remain visible in metadata without deleting a usable clip.

Set `CLIPPYME_QA_SIGNAL=0` to run structural probes only. This is useful on very
constrained systems, but the default full signal pass is recommended.

## Regression quality suites

Version a JSON manifest beside representative or synthetic clips:

```json
{
  "cases": [
    {
      "name": "vertical-talking-head",
      "path": "fixtures/talking-head.mp4",
      "expected_duration": 24.0,
      "duration_tolerance": 1.0,
      "expected_aspect": "9:16",
      "max_black_ratio": 0.1,
      "max_freeze_ratio": 0.2,
      "min_mean_volume_db": -30,
      "max_peak_volume_db": -0.2,
      "allow_warnings": false
    }
  ]
}
```

Run the same policy used by production:

```bash
python -m clippyme.pipeline.quality_suite quality-manifest.json \
  --output quality-report.json
```

The command exits `0` when every case passes, `1` for a quality regression and
`2` for an invalid/unsafe manifest. Case paths must remain inside the manifest
directory, which makes manifests safe to use in CI workspaces.

## Intelligent reframe controls

Active-speaker tracking now associates identities using two-dimensional distance
and box overlap rather than horizontal position alone. It combines face size and
mouth motion, applies relative switch hysteresis, prunes stale identities and can
frame two similarly active, separated participants together.

| Variable | Default | Meaning |
| --- | ---: | --- |
| `REFRAME_SPEAKER_SWITCH_MARGIN` | `1.25` | Challenger/current score ratio required to switch |
| `REFRAME_MIN_FACE_RATIO` | `0.10` | Ignore faces smaller than this share of the largest candidate |
| `REFRAME_DIALOGUE_GROUP` | `1` | Keep two ambiguous dialogue participants in frame |
| `REFRAME_DIALOGUE_SCORE_RATIO` | `0.88` | Minimum second/first score ratio for group framing |
| `REFRAME_DIALOGUE_SEPARATION` | `0.28` | Minimum horizontal frame separation for group framing |

These controls preserve the existing scene-level comfort/static policies and can
be tuned independently for podcast, gameplay and talking-head workloads.
