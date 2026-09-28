# Publishing

ClippyMe publishes to TikTok, Instagram and YouTube through
[Zernio](https://zernio.com). Clips are published manually from the dashboard,
or automatically by the [live monitor](live-monitor.md).

## Manual publish

`POST /api/publish/{job_id}/{clip_index}` (`domain/publish_service.py`,
`integrations/social_publisher.py`):

1. Optionally re-compose the clip with the current edit layers, so the upload
   matches the preview.
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

The dashboard's publish dialog sends the selected clips concurrently, as `now`
or `auto`; in `auto` mode each clip starts its slot search one day later than
the previous one (today, tomorrow, …) to stay under per-platform daily limits.
`manual` is available through the API only. Zernio error bodies are passed through unchanged, so
the dashboard can show a platform's daily-limit 429 on the clip it affects.

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
