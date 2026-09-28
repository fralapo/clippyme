# Testing

## Test tiers

| Tier | Where | Runs | Covers |
|------|-------|------|--------|
| Host (backend) | any machine, Python 3.11+ | `pytest -m "not integration"` | API, services, storage, parsers, pure pipeline logic (`*_ops.py`, `reframe_track.py`, preflight, QA verdicts), integrations against fakes |
| Integration (backend) | Docker backend image | `pytest -m integration` | Code that needs OpenCV, MediaPipe, PyTorch, ffmpeg renders: reframe, scene detection, `pipeline.main` |
| Frontend | Node 24 | `npm test` (Vitest + jsdom) | `dashboard/src/lib/`, hooks, components (`*.test.js[x]` next to the code) |

The heavy CV/ML stack is not installed on the host tier.
`tests/conftest.py` skips collecting the integration modules when it is
absent, so the host command stays green on a plain checkout. Code that must
run on the host therefore cannot import `pipeline/main.py`, `reframe.py` or
`reframe_detect.py`; put testable logic in the pure modules.

`tests/` mirrors the package: `tests/api`, `tests/jobs`, `tests/clips`,
`tests/editing`, `tests/monitoring`, `tests/publishing`, `tests/core`,
`tests/media`, `tests/pipeline` (with `transcription/`, `analysis/`,
`reframe/`, `quality/`), `tests/integrations`, `tests/storage`.
Repository-level checks (secret hook, Docker build context, docs links) are in
`tests/repository`.

## Commands

Backend host suite and lint:

```bash
pip install -e ".[host-tests]"
pip install pytest ruff
pytest -m "not integration" -q
ruff check src/clippyme tests --select E9,F63,F7,F82
```

Integration suite (builds the backend image on first run):

```bash
docker compose run --rm -u root backend sh -lc "pip install -q pytest && pytest -m integration -q"
```

Frontend:

```bash
cd dashboard
npm ci
npm run lint
npm test
npm run build
```

`npm run lint` uses `eslint.a11y.config.js`, the lint entrypoint, which
re-exports the base `eslint.config.js`. Accessibility is tested on rendered
DOM with Axe in `src/app/accessibility.test.jsx`.

## Expected skips

| Skip | When |
|------|------|
| `tests/repository/test_dockerignore.py` | No running Docker daemon |
| `tests/repository/test_precommit_hook.py` | No `git` + `bash` on the machine |
| POSIX-only checks (file permissions, PATH shims) | On Windows |
| Integration modules | Heavy runtime absent (host tier) |

Any other skip or failure is a real result.

## What CI runs

`.github/workflows/ci.yml`, on every push and pull request:

| Job | Steps |
|-----|-------|
| Backend | Ruff (bug-class rules above) → Bandit (`bandit -q -r src/clippyme -ll -ii`) → host suite with coverage (report only) and a 120 s per-test timeout → `pip-audit` on `requirements.lock` and on `requirements-runtime-tools.txt`. The test result is enforced after the audits, so one run reports everything. |
| Frontend | `npm ci` → lint → `npm test -- --coverage` → build |
| Frontend audit | `npm audit --package-lock-only --audit-level=high`; any high or critical advisory fails |
| Integration | Builds the backend image (CPU) and runs `pytest -m integration`; on pull requests, pushes to `main`, and manual dispatch |

The `pip-audit` ignore list lives only in `ci.yml`; each entry is an advisory
without a usable fix. See [dependencies.md](dependencies.md).

## Before you push

Run the host suite, Ruff and, if you touched `dashboard/`, the frontend
commands. Run the integration suite when you change `src/clippyme/pipeline/`
code that needs the CV stack, the Dockerfile or the dependency files.

Enable the secret scan once per clone:

```bash
git config core.hooksPath .githooks
```

The hook blocks staged API keys, tokens, cookie files, `.env`,
`data/config.json` and anything under `tmp/`.

## Media quality regression suite

`clippyme.pipeline.quality.quality_suite` replays the production output-QA policy over
a set of clips described by a JSON manifest:

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

```bash
python -m clippyme.pipeline.quality.quality_suite quality-manifest.json --output quality-report.json
```

Exit code `0` = all cases pass, `1` = quality regression, `2` = invalid or
unsafe manifest. Case paths must stay inside the manifest's directory. It
needs `ffprobe`/`ffmpeg`, so run it in the backend container.
