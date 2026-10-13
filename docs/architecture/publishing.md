# Publishing

ClippyMe publishes to TikTok, Instagram and YouTube through
[Zernio](https://zernio.com). Clips are published manually from the dashboard,
or automatically by the [live monitor](live-monitor.md).

## Manual publish

`POST /api/publish/{job_id}/{clip_index}` (`publishing/publish_service.py`,
`integrations/social_publisher.py`):

1. Optionally re-compose the clip with the current edit layers, so the upload
   matches the preview. The dashboard always sends its current `toggles`:
   if all layers are off, publish the **raw clip**, even if an earlier composed
   export remains on disk. For backwards compatibility, API callers that
   omit `toggles` (and do not request composition) still reuse an existing
   composed clip if available.
2. Request a presigned upload URL from Zernio and upload the file. The upload
   URL must be HTTPS and every address it resolves to must be public;
   otherwise the upload is refused.
3. Create the post for the selected accounts.

Scheduling modes:

| Mode | Behaviour |
|------|-----------|
| `now` | Publish immediately |
| `manual` | At the ISO 8601 `scheduled_for` time |
| `auto` | `SmartScheduler` picks a slot: a free prime-time window for that weekday (Italian time by default, `ZERNIO_DEFAULT_TZ`), else a 15-minute scan between 07:00 and 23:00, else a fallback; posts keep `ZERNIO_MIN_GAP_SECONDS` (90 min) apart |

The dashboard's publish dialog supports `now`, `auto`, and (for a single clip)
`manual`. For an exact manual time, the browser converts the local date/time
selected by the user to an explicit UTC ISO 8601 instant before submission;
past dates, nonexistent DST-gap times and repeated DST-fallback times are
rejected instead of silently selecting one of two possible instants. The
exact-time input uses the operator's **device-local** timezone, not the
configured SmartScheduler/Zernio timezone; the API receives an explicit
UTC timestamp. Batch publishing supports `now` and `auto` only: in `auto`
mode each clip starts its slot search one day later than the previous one
to reduce daily-limit collisions. Zernio error bodies are passed through
so the dashboard can show a platform's daily-limit 429.

Manual publish answers 409 while the job is still running, or while a live
monitor owns the clip.

## Publish identities

Three identities, kept separate:

| Identity | Scope |
|----------|-------|
| `(job_id, original_index)` | The logical clip |
| `publication_id` | One live-monitor publication; stable across retries |
| `request_id` | Sent to Zernio as `Idempotency-Key` |

Rules:

- Zernio replays a request with the same `Idempotency-Key` for 24 hours
  (key-only; `x-request-id` would also require the same media URL, which every
  retry's fresh presign changes).
- The monitor reuses a `request_id` after an ambiguous outcome (timeout,
  connection drop, 5xx) and rotates it — persisting the new one before the next
  call — only after a certain rejection.
- `409 idempotency_conflict` means the same key is still in progress: retry
  with the same key, no sooner than `Retry-After`; never count it as accepted.
- `409` with `existingPostId` counts as accepted.
- A manual publish carries the client's `intent_id` (one per Publish action on
  a clip, reused by its retries, replaced after a confirmed post;
  `dashboard/src/lib/publishIntent.js`). The server derives the key from
  `(job_id, clip_index, intent_id)` and answers a repeat of an intent already on
  the clip's publish record without posting again. No `intent_id` means no key:
  every request is a new post.

## Manual uncertain-outcome reconciliation

Before making a provider call, the server atomically records a pending manual
intent in `.clippyme_publish_intents.json` (owner-only, not served through
`/videos`). The same intent resumes with the same Zernio Idempotency-Key.
Once accepted, a durable receipt is written independently of the clip metadata;
a retry repairs missing metadata and verifies a known post ID with
`GET /v1/posts/{postId}` without uploading again. Unknown outcomes older than
23 hours are *blocked*, not blindly resubmitted outside Zernio's 24-hour
replay guarantee. When no post ID exists, an exact remote match is impossible:
the operator must inspect Zernio before deliberately creating a new intent.
Definitive client-side rejections drop the pending marker. A 5xx, timeout or
in-progress 409 retains it.

## Delivery guarantee

Delivery is **at least once**. Duplicates are prevented inside the provider's
24-hour idempotency window and, for manual publishes, by the clip's publish
record. Past that, a crash between Zernio accepting a post and ClippyMe
recording it can lead to the clip being posted again. Losing a post is treated
as worse than a rare duplicate.

## Contract checks

The fields, headers and status codes above are pinned against the vendored
Zernio OpenAPI spec ([docs/vendor/](../vendor/README.md)) by
`tests/integrations/test_zernio_contract.py`. `ZERNIO_BASE_URL` is restricted
to `https://*.zernio.com`.
