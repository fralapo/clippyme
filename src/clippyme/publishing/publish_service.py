"""Publish-to-Zernio flow (moved out of app.py — thin-handler rule).

Owns: optional compose-first pass, upload-path resolution (fresh compose →
existing composed file → base clip), the blocking Zernio upload run off the
event loop, and the ZernioError → ClippyMeError mapping (preserving the
response-body snippet the frontend parses for per-platform 429 daily-limit
failures). Receives the request as a plain dict so this module never imports
``api.schemas``.
"""
import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone

from clippyme.clips.clip_locks import clip_lock
from clippyme.clips.clip_resolve import ResolvedClip, composed_clip_basename
from clippyme.editing.compose import compose_layers
from clippyme.core.errors import ClippyMeError, NotFoundError, ValidationError
from clippyme.publishing.intent_journal import read_intent, begin_intent, confirm_intent, reject_intent
from clippyme.jobs.job_artifacts import load_job_metadata, record_clip_publish

logger = logging.getLogger("clippyme")


async def publish_clip_flow(*, job_id: str, clip_index: int,
                            resolved: ResolvedClip, req: dict,
                            zernio_cfg: dict) -> dict:
    """Compose (optionally) and upload one clip to Zernio.

    ``req`` is ``PublishRequest.model_dump()``; ``resolved`` comes from
    ``resolve_clip(..., require_file=False)`` — the base clip may be absent
    when a composed file exists on disk.
    """
    api_key = zernio_cfg.get("api_key")
    if not api_key:
        raise ValidationError("Zernio API key not configured")

    toggles = req.get("toggles")
    logger.info(
        "publish_clip_flow: job=%s clip=%d compose_first=%s toggles=%s has_hook_params=%s has_sub_params=%s",
        job_id, clip_index, req.get("compose_first"),
        list((toggles or {}).keys()),
        bool(req.get("hook_params")),
        bool(req.get("subtitle_params")),
    )

    # Held from choosing the file until the upload has read it: a compose of
    # this clip deletes the composed file up front and rewrites it at the end,
    # so an unlocked publish could upload the raw clip, a half-copied file or
    # the other request's version. compose_layers re-enters the same lock.
    # It also serialises repeats of one intent, so a double submit finds the
    # first one's record below instead of racing it to the provider.
    async with clip_lock(resolved.job_dir, clip_index):
        intent_id = req.get("intent_id")
        if intent_id:
            recorded = await asyncio.to_thread(
                _recorded_intent, job_id, clip_index, os.path.dirname(resolved.job_dir), intent_id)
            if recorded is not None:
                return {"success": True, "replayed": True,
                        "post_id": recorded.get("post_id"),
                        "scheduled_for": recorded.get("scheduled_for")}
            receipt = await asyncio.to_thread(read_intent, resolved.job_dir, clip_index, intent_id)
            if receipt and receipt.get("state") == "confirmed":
                outcome = receipt.get("result") or {}
                # The receipt is authoritative when metadata write failed after
                # Zernio accepted the post. Reconcile it without re-uploading.
                try:
                    await asyncio.to_thread(
                        record_clip_publish, job_id, clip_index,
                        os.path.dirname(resolved.job_dir),
                        _publication_record(req, intent_id, outcome),
                    )
                except Exception:
                    logger.warning("Cannot repair metadata for accepted publication %s/%d", job_id, clip_index)
                # A known remote post ID permits a precise provider GET. Never
                # approximate by title or scheduled time (could match another).
                if outcome.get("post_id"):
                    from clippyme.integrations.social_publisher import ZernioClient, ZernioError
                    try:
                        fresh = await asyncio.to_thread(ZernioClient(api_key).get_post, outcome["post_id"])
                        post = fresh.get("post", fresh) if isinstance(fresh, dict) else {}
                        if isinstance(post, dict):
                            outcome = {**outcome, "status": post.get("status", outcome.get("status"))}
                    except (ZernioError, ValueError):
                        logger.info("Remote verification unavailable for saved post %s", outcome["post_id"])
                return {"success": True, "replayed": True, **outcome}
        return await _compose_and_upload(
            job_id=job_id, clip_index=clip_index, resolved=resolved, req=req,
            api_key=api_key, zernio_cfg=zernio_cfg)


def _publication_record(req: dict, intent_id: str | None, result: dict) -> dict:
    return {
        "platforms": req.get("platforms"),
        "post_id": result.get("post_id"),
        "scheduled_for": result.get("scheduled_for"),
        "at": datetime.now(timezone.utc).isoformat(),
        **({"intent_id": intent_id} if intent_id else {}),
    }


def manual_request_id(job_id: str, clip_index: int, intent_id: str) -> str:
    """Zernio Idempotency-Key for one manual publication intent: stable across
    that intent's retries, distinct per clip even if a client reuses an id."""
    digest = hashlib.sha256(f"{job_id}:{clip_index}:{intent_id}".encode()).hexdigest()
    return f"manual-{digest[:48]}"


def _recorded_intent(job_id: str, clip_index: int, output_dir: str, intent_id: str):
    """The clip's publish record left by this intent, if it already succeeded."""
    try:
        shorts = load_job_metadata(job_id, output_dir)[1].get("shorts") or []
        records = shorts[clip_index].get("published") or []
    except (FileNotFoundError, IndexError, ValueError, AttributeError):
        return None
    return next((r for r in records if isinstance(r, dict) and r.get("intent_id") == intent_id),
                None)


async def _compose_and_upload(*, job_id, clip_index, resolved, req, api_key,
                              zernio_cfg) -> dict:
    job_dir = resolved.job_dir
    base_clip = resolved.clip_path
    upload_path = base_clip
    intent_id = req.get("intent_id")
    composed_path = os.path.join(job_dir, composed_clip_basename(resolved.clip_info, clip_index))
    toggles = req.get("toggles")
    if req.get("compose_first") and toggles:
        try:
            composed_filename = await compose_layers(
                base_clip=base_clip,
                job_dir=job_dir,
                clip_index=clip_index,
                metadata=resolved.metadata,
                clip_info=resolved.clip_info,
                toggles=toggles,
                hook_params=req.get("hook_params") or {},
                subtitle_params=req.get("subtitle_params") or {},
                logo_params=req.get("logo_params") or {},
                grade_params=req.get("grade_params") or {},
                banner_params=req.get("banner_params") or {},
                drop_ranges=req.get("drop_ranges"),
            )
            upload_path = os.path.join(job_dir, composed_filename)
        except ClippyMeError:
            raise
        except Exception as e:
            logger.error("publish: compose_layers failed for %s/%d: %s", job_id, clip_index, e)
            raise ClippyMeError(f"Compose before publish failed: {e}", status_code=500)
    elif toggles is None and os.path.exists(composed_path):
        # Backwards-compatible API behavior: omitted toggles reuse the last
        # composed file. An explicit all-off selection from the dashboard
        # must use the raw clip instead of stale edits still on disk.
        upload_path = composed_path

    if not os.path.exists(upload_path):
        raise NotFoundError(f"Clip file not found: {upload_path}")

    # Write the pending intent BEFORE any possible remote acceptance. Retrying
    # the same intent reuses the provider key. An uncertain intent older than
    # 23h is blocked instead of risking duplicates after Zernio's TTL.
    if intent_id:
        try:
            await asyncio.to_thread(begin_intent, job_dir, clip_index, intent_id)
        except OSError as exc:
            raise ClippyMeError("Could not durably register publication intent", status_code=503) from exc

    # Run the publish in a worker thread (presign + PUT + create are blocking)
    from clippyme.integrations.social_publisher import publish_clip, ZernioError
    try:
        result = await asyncio.to_thread(
            publish_clip,
            api_key=api_key,
            clip_path=upload_path,
            title=req.get("title") or resolved.clip_info.get("title", "")[:100] or f"Clip {clip_index + 1}",
            caption=req.get("caption") or "",
            platform_targets=req.get("platforms"),
            schedule_mode=req.get("schedule_mode"),
            scheduled_for=req.get("scheduled_for"),
            timezone=req.get("timezone") or zernio_cfg.get("timezone") or "Europe/Rome",
            tiktok_settings=req.get("tiktok_settings"),
            start_date=req.get("start_date"),
            request_id=manual_request_id(job_id, clip_index, intent_id) if intent_id else None,
        )
    except ValueError as e:
        if intent_id:
            await asyncio.to_thread(reject_intent, job_dir, clip_index, intent_id)
        raise ValidationError(str(e))
    except ZernioError as e:
        # Known client-side rejections cannot have created a post. An unknown
        # network outcome, 5xx or 409 in-progress MUST retain the ledger.
        if intent_id and e.status_code in {400, 401, 403, 404, 422, 429}:
            await asyncio.to_thread(reject_intent, job_dir, clip_index, intent_id)
        logger.error("publish: Zernio error: %s (status=%s body=%s)",
                     e, e.status_code, (e.body or "")[:200])
        # Include the full response body (truncated) in the error detail so
        # the frontend can parse per-platform failures like the Zernio
        # "Daily limit reached" 429 and skip the exhausted platform for the
        # rest of a batch publish run.
        body_snippet = (e.body or "")[:500]
        detail_msg = f"Zernio API error: {e}"
        if body_snippet:
            detail_msg = f"{detail_msg} | body={body_snippet}"
        raise ClippyMeError(
            detail_msg,
            status_code=502 if e.status_code is None else e.status_code,
        )
    except Exception:
        logger.exception("publish: unexpected error")
        raise ClippyMeError("Publish failed", status_code=500)

    # Dual durability: write the provider receipt and the ordinary metadata
    # independently. A failed metadata save must never erase accepted status.
    # If BOTH writes fail, report an ambiguous result so the client retains
    # its intent key (rather than confidently announcing success).
    receipt_saved = not bool(intent_id)
    metadata_saved = False
    if intent_id:
        try:
            await asyncio.to_thread(confirm_intent, job_dir, clip_index, intent_id, result)
            receipt_saved = True
        except OSError:
            logger.exception("Could not persist provider receipt for %s/%d", job_id, clip_index)
    try:
        await asyncio.to_thread(
            record_clip_publish,
            job_id,
            clip_index,
            os.path.dirname(job_dir),
            _publication_record(req, intent_id, result),
        )
        metadata_saved = True
    except Exception:
        logger.warning("Could not persist accepted publication into metadata %s/%d", job_id, clip_index, exc_info=True)
    if not receipt_saved and not metadata_saved:
        raise ClippyMeError(
            "Zernio may have accepted the post but its receipt could not be saved. "
            "Do not start a new publication; retry with the same intent once storage is repaired.",
            status_code=503,
        )

    return {"success": True, **result}
