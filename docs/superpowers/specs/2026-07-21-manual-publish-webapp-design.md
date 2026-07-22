# Manual Publishing Webapp — Design

## Goal

Add a mobile-first manual publishing workflow alongside Zernio. Each Create job
and monitor chooses `zernio` or `manual_queue`. Manual clips are composed,
frozen, grouped by source/project, and exposed in a private smartphone webapp
for sharing, caption copying, download, and explicit completion tracking.

## Chosen approach

Use a first-class persistent backend queue, not browser-local state and not
metadata-only flags. This survives browser changes and server restarts, supports
the existing monitor, and keeps pending/completed state consistent across
phones. A queue artifact is frozen under its project directory with a hardlink
when possible and a copy fallback, preventing later re-composition from changing
what the operator shares.

Rejected alternatives:

- Browser `localStorage`: not shared across devices and loses server truth.
- Reusing Zernio `published` metadata: cannot represent pending manual work.
- Pointing directly at mutable `composed_clip_N.mp4`: later edits can silently
  change queued content.

## Mobile information architecture

Add a top-level `Publish Queue` area optimized for narrow touch screens with
four tabs:

1. **Da pubblicare** — pending cards, grouped by source platform/channel,
   stream/video project, then clip order.
2. **Pubblicate** — completed cards in a collapsible/reversible archive.
3. **History** — projects and clips, with per-clip delete and whole-project
   delete.
4. **Monitor** — existing multi-platform monitor controls and status.

Each clip card contains an inline vertical preview, source/channel/project
breadcrumbs, title, editable-looking but read-only caption, `Copia caption`,
`Condividi`, `Scarica MP4`, and `Segna pubblicata`. Completed cards expose
`Ripristina nella coda`.

`Condividi` uses Web Share Level 2 with the MP4 as a `File`. It is enabled only
when `window.isSecureContext`, `navigator.share`, and
`navigator.canShare({files:[file]})` succeed. The permanent fallback is
download plus independent caption copy. Direct platform buttons must not claim
to pre-attach a video because TikTok, Instagram, and YouTube do not provide a
portable browser deep-link contract for that behavior.

Tailscale access should use Tailscale Serve HTTPS (`*.ts.net`) rather than a raw
`http://100.x.x.x` URL, because Web Share and Clipboard require a secure context.

## Persistence model

Store queue state atomically at `data/manual_publish_queue.json` using the
existing tmp + `os.replace` + mode `0600` pattern.

Each entry contains:

```json
{
  "id": "uuid",
  "status": "pending",
  "job_id": "uuid",
  "clip_index": 0,
  "monitor_id": "kick:grenbaud",
  "artifact": "output/<job>/manual_queue/<entry>.mp4",
  "title": "...",
  "caption": "...",
  "source_platform": "kick",
  "source_channel": "grenbaud",
  "source_kind": "live",
  "project_title": "...",
  "created_at": "ISO-8601 UTC",
  "completed_at": null
}
```

Allowed transitions are `pending -> completed` and `completed -> pending`.
Mutations are serialized in-process and every write is atomic. Queue listing
must discard or report entries whose project/artifact no longer exists rather
than returning broken URLs.

## Backend API

- `GET /api/manual-publish?status=pending|completed|all`
- `POST /api/manual-publish/{entry_id}/complete`
- `POST /api/manual-publish/{entry_id}/restore`
- `GET /api/manual-publish/{entry_id}/video`
- `DELETE /api/history/{job_id}/clips/{clip_index}`
- Existing `DELETE /api/history/{job_id}` remains whole-project deletion.

Queue and history mutations require the existing trusted-request guard and rate
limiting. Video delivery validates the entry id and resolved artifact path and
returns `video/mp4` without exposing arbitrary filesystem paths.

Deleting one clip removes its base/source/composed/cover/manual-queue artifacts
and corresponding queue records, then rewrites metadata. If no clips remain,
the complete `output/<job_id>` directory is deleted. Deleting a project also
removes all queue records for that job. Marking a queue entry completed never
deletes History files.

## Generation and monitor selection

Create and Live Monitor gain `Publish destination`:

- `Manual queue` — recommended/default for volume workflows.
- `Zernio automatic` — existing behavior.

The request field is `publisher_mode: "manual_queue" | "zernio"`. Zernio
platform targets are required only in `zernio` mode. Manual mode composes the
same final hook/subtitle/banner recipe, freezes the resulting MP4, renders the
caption/title templates, enqueues it, and records the queue id in clip metadata.

The monitor's deduplication tracks successful enqueue separately from Zernio
publication. A failed enqueue is retryable and must not be marked complete.

## Current Kick monitor migration

All existing, still-present clips from `kick:grenbaud` without a successful
Zernio publication record are imported into the manual queue. Already published
clips are not duplicated.

The deployed code must persist complete monitor start configuration and support
restoring an active `loop=true` monitor after a controlled backend restart. The
cutover sequence is:

1. Let or stop the current capture safely, preserving a segment of at least five
   minutes for processing.
2. Extract the active monitor's instructions/template settings from the current
   job command/state before shutdown.
3. Deploy the queue-capable backend.
4. Restart the monitor as `publisher_mode=manual_queue` with its previous stream
   coverage snapshot, so prior live hours are not backfilled again.
5. Verify state `capturing`, new clips enqueue, and no new Zernio requests occur.

The migration may pause capture briefly during restart, but it must not lose an
already completed segment or duplicate historical coverage.

## Error handling

- Share cancellation is not an error and does not mark a clip completed.
- Share success does not automatically mark completion; the operator checks it
  only after confirming the platform post.
- Missing artifacts produce a readable card/API error and can be removed safely.
- Copy/share/download failures leave queue state unchanged.
- Disk-copy failure leaves the clip retryable and never records a queue entry.
- History deletion and queue cleanup are one domain operation so no stale entry
  remains.

## Testing

Backend host tests cover queue transitions, atomic persistence, hardlink/copy
freeze, traversal rejection, cleanup on clip/project deletion, caption/source
grouping, schema conditional validation, and monitor dispatch/deduplication.

Frontend Vitest covers mobile tab navigation, grouped ordering, copy/share
capability and fallbacks, reversible completion, destination selection, and
History per-clip deletion. Existing backend, frontend lint, build, and Docker
smoke suites remain green.

## Non-goals

- Automatic direct posting through TikTok/Instagram/YouTube APIs.
- Multi-user accounts, assignments, or approval workflows.
- Public internet exposure through Tailscale Funnel.
- Deleting History files when a clip is merely marked published.
