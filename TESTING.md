# Testing

ClippyMe splits its test suite into two tiers because the video pipeline pulls
in a heavy CV/ML runtime (`cv2`, `mediapipe`, `scenedetect`, `ultralytics`,
`torch`) that isn't practical to install on every contributor's host.

## Tiers

| Tier | Marker | Where it runs | What it covers |
|------|--------|---------------|----------------|
| Fast (host) | *unmarked* | any machine with `pip install -e .` + `pytest` | API schemas, domain logic, config/storage, Gemini parser, reframe math, Deepgram retry logic, social scheduler, history scanner |
| Integration | `@pytest.mark.integration` | Docker image with the full runtime | `clippyme.pipeline.main` orchestration, scene detection, YOLO/MediaPipe tracking |

`tests/conftest.py` automatically skips collecting the pipeline integration
modules when the heavy runtime is absent, so the host command below stays green
on a plain checkout (a bare marker can't prevent a collection-time
`import ultralytics` from erroring).

## Commands

Run the fast host suite (Python 3.11+):

```bash
pip install -e .
pip install pytest
pytest -m "not integration"
```

Run everything, including the CV/ML integration tests, inside Docker:

```bash
docker compose run --rm backend pytest
```

## CI

`.github/workflows/ci.yml` runs the fast host suite + `pip-audit` + the
frontend build/lint on every push and PR. The integration tier is **not** run
in CI yet (it needs the GPU/CV image); run it locally in Docker before merging
changes to `src/clippyme/pipeline/`.

## Frontend

```bash
cd dashboard
npm ci
npm run lint
npm run build
```
