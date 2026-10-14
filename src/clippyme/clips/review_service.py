"""Durable per-clip operator review state."""
from datetime import datetime, timezone

from clippyme.core.errors import ConflictError, NotFoundError, ValidationError
from clippyme.jobs.job_artifacts import update_job_metadata

REVIEW_STATES = frozenset({"pending", "approved", "changes_requested", "discarded"})


def set_clip_review(job_id: str, clip_index: int, output_dir: str,
                    status: str, note: str = "") -> dict:
    """Persist a review decision in the job's canonical clip metadata."""
    if status not in REVIEW_STATES:
        raise ValidationError("Invalid clip review status")
    clean_note = (note or "").strip()
    if len(clean_note) > 500:
        raise ValidationError("Review note is too long")
    if status == "changes_requested" and not clean_note:
        raise ValidationError("A note is required when requesting changes")

    updated = {
        "review_status": status,
        "review_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if status == "changes_requested":
        updated["review_note"] = clean_note

    found = False

    def mutate(data):
        nonlocal found
        shorts = data.get("shorts")
        if not isinstance(shorts, list) or not 0 <= clip_index < len(shorts):
            return False
        clip = shorts[clip_index]
        if not isinstance(clip, dict):
            return False
        found = True
        clip.update(updated)
        if status != "changes_requested":
            clip.pop("review_note", None)
        return True

    update_job_metadata(job_id, output_dir, mutate)
    if not found:
        raise NotFoundError("Clip not found")
    return updated


def require_clip_approved(job_id: str, clip_index: int, output_dir: str) -> None:
    """Fail closed for manual publishing until the operator approves a clip."""
    from clippyme.jobs.job_artifacts import load_job_metadata

    try:
        clip = load_job_metadata(job_id, output_dir)[1]["shorts"][clip_index]
    except (FileNotFoundError, IndexError, KeyError, TypeError):
        raise NotFoundError("Clip not found")
    if not isinstance(clip, dict) or clip.get("review_status", "pending") != "approved":
        raise ConflictError("Clip requires operator approval before manual publishing")
