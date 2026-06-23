"""Conversational clip editing (video-use "edit by description" + superpowers
ask→execute).

ClippyMe's manual trim made the user tap each transcript line to cut it. This
adds the missing natural-language path: the user types an instruction
("cut the intro, drop the bit where he stumbles") and Gemini returns the
clip-relative spans to remove, which flow through the SAME `drop_ranges`
machinery the tap-to-cut UI already feeds.

Prompt building + response parsing are pure (host-unit-testable). The Gemini
call itself is a thin wrapper using the same `google-genai` client as
gemini_service — no cv2, so this stays importable on the host.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Guardrails — keep an authenticated request from handing the model an
# unbounded transcript or instruction.
MAX_INSTRUCTION_CHARS = 1000
MAX_SEGMENTS = 600


def build_edit_prompt(segments: list[dict], instruction: str, clip_duration: float) -> str:
    """Build the Gemini prompt. Pure.

    `segments` are {index, text, start, end} in CLIP-RELATIVE seconds (exactly
    what /api/transcript returns). The model is asked for spans to REMOVE.
    """
    lines = []
    for s in (segments or [])[:MAX_SEGMENTS]:
        try:
            st = float(s.get("start", 0))
            en = float(s.get("end", 0))
        except (TypeError, ValueError):
            continue
        txt = (s.get("text", "") or "").replace("\n", " ").strip()
        lines.append(f"[{st:.2f}-{en:.2f}] {txt}")
    transcript_block = "\n".join(lines) if lines else "(no transcript available)"
    instruction = (instruction or "").strip()[:MAX_INSTRUCTION_CHARS]

    return (
        "You are a precise video editor. Below is a transcript of a short clip "
        f"that is {clip_duration:.2f} seconds long. Each line is prefixed with "
        "its [start-end] time range in seconds, relative to the clip start "
        "(0 = first frame).\n\n"
        "The user wants this edit:\n"
        f"\"{instruction}\"\n\n"
        "TRANSCRIPT:\n"
        f"{transcript_block}\n\n"
        "Return ONLY the spans to REMOVE from the clip, as strict JSON in this "
        "exact shape and nothing else:\n"
        '{"drops": [[start, end], ...], "explanation": "<one short sentence>"}\n'
        "Rules:\n"
        "- Times are seconds relative to the clip (0 ≤ t ≤ "
        f"{clip_duration:.2f}).\n"
        "- Align each span to the transcript line boundaries.\n"
        "- If nothing should be cut, return an empty drops array.\n"
        "- Never invent spans outside the clip duration.\n"
    )


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_edit_response(text: str, clip_duration: float) -> dict:
    """Parse the model's JSON into {"drops": [[s,e],...], "explanation": str}.

    Pure + tolerant: strips ```json fences / surrounding prose, clamps spans to
    [0, clip_duration], drops malformed/inverted/out-of-range entries. Returns
    empty drops on any failure rather than raising.
    """
    if not text:
        return {"drops": [], "explanation": ""}
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = re.sub(r"^json\s*", "", raw, flags=re.IGNORECASE).strip()
    m = _JSON_OBJ_RE.search(raw)
    if not m:
        return {"drops": [], "explanation": ""}
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return {"drops": [], "explanation": ""}

    explanation = ""
    if isinstance(obj, dict):
        explanation = str(obj.get("explanation", ""))[:300]
        candidates = obj.get("drops", [])
    elif isinstance(obj, list):
        candidates = obj
    else:
        candidates = []

    drops: list[list[float]] = []
    for span in candidates or []:
        try:
            s = float(span[0])
            e = float(span[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        s = max(0.0, min(s, clip_duration))
        e = max(0.0, min(e, clip_duration))
        if e - s > 0.05:  # ignore zero/negative/sub-frame spans
            drops.append([round(s, 3), round(e, 3)])
    return {"drops": drops, "explanation": explanation}


def suggest_drops(
    *,
    api_key: str,
    model: str,
    segments: list[dict],
    instruction: str,
    clip_duration: float,
) -> dict:
    """Ask Gemini which spans to cut. Returns {"drops": [...], "explanation": str}.

    Network/SDK errors are swallowed into an empty result with the error in
    `explanation` — a failed suggestion must not 500 the editor.
    """
    if not api_key:
        return {"drops": [], "explanation": "Gemini API key not configured."}
    prompt = build_edit_prompt(segments, instruction, clip_duration)
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents=prompt)
        text = getattr(resp, "text", "") or ""
        result = parse_edit_response(text, clip_duration)
        logger.info(
            "clip_edit_ai: model=%s instruction_len=%d → %d drops",
            model, len(instruction or ""), len(result["drops"]),
        )
        return result
    except Exception as e:  # pragma: no cover — network path
        from clippyme.pipeline.gemini_service import _redact_key

        logger.warning("clip_edit_ai suggest_drops failed: %s", e)
        return {"drops": [], "explanation": f"AI edit failed: {_redact_key(str(e))}"}
