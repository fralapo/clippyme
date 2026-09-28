# Contributing to ClippyMe

Thanks for helping. This page is the short version; the linked documents have
the details.

## Set up

The development environment is Docker Compose — it is the only setup that
has every runtime dependency (ffmpeg, auto-editor, OpenCV, PyTorch,
MediaPipe):

```bash
git clone https://github.com/fralapo/clippyme.git
cd clippyme
git config core.hooksPath .githooks      # secret scan before every commit
docker compose up --build
```

The repository is mounted into both containers:

- **Dashboard** changes reload in the browser immediately.
- **Pipeline** changes apply to the next job (each job is a new process).
- **API / service** changes need `docker compose restart backend`.

For tests and lint without Docker, install the light host environment
described in [docs/development/testing.md](docs/development/testing.md).

## Find your way around

- [Architecture overview](docs/architecture/overview.md) — components,
  boundaries, persistence, glossary; subsystem pages from there.
- [CLAUDE.md](CLAUDE.md) — the repository's rules and invariants in compact
  form (written for coding agents, useful for people too).
- [Configuration reference](docs/reference/configuration.md).

## Rules that matter most

- API handlers stay thin: validate, call a service function (`clippyme.jobs`,
  `clips`, `editing`, `monitoring`, `publishing`), return JSON. Service code
  never imports FastAPI; it raises `ClippyMeError`
  subclasses.
- Logic that can be tested without OpenCV/PyTorch goes in the pure modules
  (`*_ops.py`, `reframe_track.py`, …), never inline in `pipeline/main.py` or
  `reframe.py`.
- Files a crash could corrupt are written atomically. Job metadata is updated
  through `job_artifacts.update_job_metadata`, never from a stale copy.
- Respect the lock order and the other invariants listed in
  [CLAUDE.md](CLAUDE.md#invariants).
- Every libx264 encode uses `media/encode.py`.

## Before opening a pull request

1. Run the checks for what you touched — see
   [testing.md](docs/development/testing.md#before-you-push). CI runs the same
   host suite, Ruff, Bandit, dependency audits, the frontend lint/test/build
   and the Docker integration suite.
2. Add or update tests with the change. Bug fixes come with a test that fails
   without the fix.
3. Update the current documentation in the same change: the relevant page
   under `docs/architecture/`, and for a new setting both
   [configuration.md](docs/reference/configuration.md) and, if operators are
   likely to set it, `.env.example`.
4. Adding or upgrading a dependency: follow
   [dependencies.md](docs/development/dependencies.md). Never hand-edit
   `requirements.lock`.

Commit messages follow the style already in the history
(`fix(monitor): …`, `feat(reframe): …`, `docs(repo): …`): a type, a scope, and
an imperative summary; the body explains why.

## Reporting security issues

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
