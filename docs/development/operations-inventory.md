# Cost and queue operations inventory

Reviewed locally on 2026-10-14 against the pipeline, runtime journal,
dashboard and Live Monitor persistence.

## Cost visibility

| Work | Metering and display | Finding |
|---|---|---|
| Gemini analysis | Token usage is priced by the selected model, retries/fallback calls are accumulated, preflight reports an upper bound, and job metadata/History retain the result. Unknown model pricing stays unknown and cost limits fail closed. | Covered, with a UI clarity gap now fixed: the preflight calls out its upper-bound scope and History labels the saved amount as Gemini-only. |
| Deepgram or ElevenLabs transcription | Provider response content is normalized into transcript data; no provider charge is captured in job metadata or History. | Actual cost is untracked. No price is inferred because provider plan/rate and billing adjustments are not available locally. |
| Optional ElevenLabs Voice Isolator | Best-effort pre-pass, with no usage/cost record. | Actual cost is untracked and excluded from the Gemini total. |
| Faster-Whisper | Local inference. | No provider charge is applicable; compute/resource telemetry is available separately. |

The History dollar amount is therefore **Gemini usage**, not a total job bill.
The processing screen now states that its Gemini amount is an upper-bound
estimate and excludes paid transcription and optional audio isolation. Adding
a complete monetary total needs provider-specific usage records plus a
user-configurable or billing-authoritative rate source; the current repo has
neither, so this review does not fabricate one.

## Queue and restart behavior

- Dashboard and Live Monitor jobs share a bounded `asyncio.Queue` (capacity
  50) and a configured worker semaphore in one FastAPI process.
- Submission registers the job and enqueues it as one event-loop operation;
  queue-full rollback removes the created output and journal snapshot.
- `data/jobs_journal.json` is replaced atomically, fsync'd and permissioned
  owner-only. It contains active job metadata only, never API keys, full
  environments, logs or results.
- Startup re-enqueues journaled queued jobs. It restores jobs whose final
  result is already durable, resumes checkpoint-capable interrupted jobs and
  safely marks unrecoverable interruptions failed. Runtime checkpoints avoid
  repeating paid work already durably completed.
- Live Monitor separately persists pending publications and retries with a
  stable publication/request identity. Zernio guarantees idempotency for a
  bounded window, so provider acceptance followed by a long outage can still
  produce at-least-once duplicate risk after that window.
- The processing UI exposes `queued`, active stage, ETA, attempt count and
  resource telemetry. It does not predict a queue wait time; workload duration
  and the number of active workers make that estimate unreliable today.

The existing journal and checkpoint design covers the supported local,
single-instance deployment. A distributed broker would only be justified by
multi-process or multi-host workers, which would also require shared storage,
distributed job/clip locks and monitor leader ownership. Those deployment
semantics are not implemented or claimed.
