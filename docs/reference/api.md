# HTTP API

The backend is a FastAPI app. The machine-readable contract — every route,
parameter and schema — is generated from the code:

- interactive docs: <http://localhost:8000/docs>
- OpenAPI JSON: <http://localhost:8000/openapi.json>

This page covers what OpenAPI does not express: the groups of routes, access
rules, and the conventions they share.

## Route groups

| Group | Routes | Notes |
|-------|--------|-------|
| Jobs | `POST /api/process`, `POST /api/batch`, `GET /api/status/{job_id}`, `POST /api/pause\|resume\|stop\|cancel/{job_id}` | `stop` keeps finished clips; `cancel` deletes the job. See [jobs](../architecture/jobs.md). |
| Clip editing | `POST /api/compose/{job_id}/{clip_index}`, `POST /api/smartcut/…`, `GET /api/transcript/…`, `POST /api/edit-ai/…`, `POST /api/reframe/…` | See [pipeline](../architecture/pipeline.md#compose-edit-layers). |
| Publishing | `POST /api/publish/{job_id}/{clip_index}`, `GET /api/zernio/accounts` | See [publishing](../architecture/publishing.md). |
| History | `GET /api/history`, `POST /api/history/{job_id}/restore`, `DELETE /api/history/{job_id}` | Jobs found on disk. |
| Live monitor | `POST /api/live-monitor/start\|stop`, `POST /api/live-monitor/{id}/config`, `POST /api/live-monitor/{id}/publishing`, `GET /api/live-monitor/status` | See [live monitor](../architecture/live-monitor.md). |
| Settings | `/api/config`, `/api/config/models`, `/api/config/cookies…`, `/api/config/fonts…`, `/api/config/logo…`, `/api/config/zernio` | Trusted clients only (below). |
| Health | `GET /api/health` | Liveness. |

Static, read-only mounts: `/videos` (job output; refuses `*_metadata.json`,
`source_*` and runtime files), `/thumbnails`, `/fonts`.

## Access rules

- **Trusted clients.** Settings and state-changing endpoints reject any
  browser request marked `Sec-Fetch-Site: cross-site|same-site` (403). A
  request with an `Origin` must match `ALLOWED_ORIGINS`. A request with
  neither header (curl, scripts) must come from a loopback or private-network
  address. Every private-network peer is therefore trusted, which is why the
  ports bind to loopback by default.
- **API token.** When `CLIPPYME_API_TOKEN` is set, every `/api` request needs
  it in `X-API-Token` or `Authorization: Bearer`. Static mounts stay
  token-free because `<video>` elements cannot send headers.
- **Rate limit.** Expensive endpoints — process, batch, compose, smart cut,
  reframe, publish and the live-monitor actions — are rate-limited per client
  IP (`RATE_LIMIT_ENABLED`).
- **Client IP** comes from the TCP peer, or from the last `X-Forwarded-For`
  hop with `TRUST_PROXY=1` behind one proxy.

## Conventions

- JSON in and out. `job_id` is a UUID4 and is validated on every route.
- Errors: `400` invalid input, `404` unknown job or clip, `409` conflict
  (job still running, clip owned by a live monitor, missing source slice,
  cancel after the process already exited), `401` missing or wrong API token,
  `403` untrusted client, `429` rate limited. Internal errors never include exception text.
- `clip_index` addresses the clip's position in the job metadata (`shorts`).
  Positions stay stable when a published clip is deleted, so clients use each
  clip's `original_index`.
- Per-clip operations on the same clip are serialised; different clips run in
  parallel.
- Zernio error bodies from `publish` are returned unchanged.
