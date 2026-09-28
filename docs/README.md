# ClippyMe documentation

**Using ClippyMe**

- [Getting started](getting-started.md) — install, configure, first clips
- [Deployment](deployment.md) — GPU, production frontend, network exposure, troubleshooting

**How it works**

- [Architecture overview](architecture/overview.md) — components, boundaries, persistence, glossary
- [Jobs and runtime](architecture/jobs.md) · [Video pipeline](architecture/pipeline.md) · [Reframe](architecture/reframe.md) · [Live monitor](architecture/live-monitor.md) · [Publishing](architecture/publishing.md)

**Reference**

- [Configuration](reference/configuration.md) — every setting
- [HTTP API](reference/api.md) — conventions; the full schema is at `/docs` on a running backend

**Contributing**

- [CONTRIBUTING.md](../CONTRIBUTING.md) · [Testing](development/testing.md) · [Dependencies](development/dependencies.md)

**Background** (not current documentation)

- [Research notes](research/README.md) — studies of other projects and techniques
- [Vendored specs](vendor/README.md) — third-party API specifications

## Where each kind of information lives

When two places seem to disagree, this table says which one is right.
Code, configuration and tests outrank any prose.

| Information | Source of truth |
|-------------|-----------------|
| What ClippyMe is, quick start | [README.md](../README.md) |
| Current behaviour and design | `docs/architecture/`, then the code and tests |
| Settings: names, defaults, meaning | [reference/configuration.md](reference/configuration.md); `.env.example` is the fill-in template |
| HTTP routes and schemas | FastAPI OpenAPI (`/docs`, `/openapi.json`) |
| Test tiers and what CI runs | [development/testing.md](development/testing.md), checked against `.github/workflows/ci.yml` |
| Dependency versions | `requirements.txt`, `requirements.lock`, `dashboard/package*.json` |
| Contribution workflow | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Rules and invariants for coding agents | [CLAUDE.md](../CLAUDE.md) (`AGENTS.md` points to it) |
| Security reporting | [SECURITY.md](../SECURITY.md) |
| Why an idea was adopted or rejected | `docs/research/` — rationale only, never a specification |
| History of changes | `git log` |
