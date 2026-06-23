// Cross-job taste memory (#8). ClippyMe never learned from which clips a user
// actually kept vs threw away — every job started cold. This records a small
// rolling signal (clip viral_score + duration + whether kept/published or
// discarded) and distils it into a one-line natural-language hint that is
// appended to the Gemini `instructions` on the NEXT job. The hint rides the
// EXISTING instructions channel, so no backend change is needed: it reaches
// `get_viral_clips` exactly like a user-typed directive.
//
// Pure functions (summarizeTaste) are unit-tested via `node --test`; the
// localStorage I/O is thin and guarded.

const KEY = 'clippyme_taste_v1';
const MAX_EVENTS = 120;        // rolling window — old taste decays out
const MIN_EVENTS = 6;          // below this we don't have enough signal to hint

export function loadTasteEvents() {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

// action: 'kept' (published) | 'discarded' (removed/disabled).
export function recordTasteEvent({ viralScore, duration, action }) {
  if (action !== 'kept' && action !== 'discarded') return;
  const ev = {
    s: Number.isFinite(viralScore) ? Math.round(viralScore) : null,
    d: Number.isFinite(duration) ? Math.round(duration) : null,
    a: action,
  };
  try {
    const events = loadTasteEvents();
    events.push(ev);
    const trimmed = events.slice(-MAX_EVENTS);
    localStorage.setItem(KEY, JSON.stringify(trimmed));
  } catch {
    /* localStorage unavailable — taste memory is best-effort */
  }
}

function median(nums) {
  const xs = nums.filter((n) => Number.isFinite(n)).sort((a, b) => a - b);
  if (!xs.length) return null;
  const m = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[m] : Math.round((xs[m - 1] + xs[m]) / 2);
}

// Pure: events → short hint string (or '' when there isn't enough signal).
export function summarizeTaste(events) {
  const evs = (events || []).filter((e) => e && (e.a === 'kept' || e.a === 'discarded'));
  if (evs.length < MIN_EVENTS) return '';

  const kept = evs.filter((e) => e.a === 'kept');
  const discarded = evs.filter((e) => e.a === 'discarded');
  const parts = [];

  // Preferred length from clips the user kept.
  const keptDur = median(kept.map((e) => e.d));
  if (keptDur) {
    const lo = Math.max(5, keptDur - 6);
    const hi = keptDur + 6;
    parts.push(`prefer clips roughly ${lo}-${hi}s long`);
  }

  // Score band the user tends to discard: if discarded clips skew low-score.
  const discMedScore = median(discarded.map((e) => e.s));
  const keptMedScore = median(kept.map((e) => e.s));
  if (discMedScore != null && keptMedScore != null && keptMedScore - discMedScore >= 8) {
    parts.push(`avoid weak moments — the user discards clips scoring below about ${keptMedScore}`);
  }

  if (!parts.length) return '';
  return `Based on the user's past edits, ${parts.join(' and ')}.`;
}

// Convenience: the suffix to append to a job's AI instructions.
export function tasteInstructionSuffix() {
  return summarizeTaste(loadTasteEvents());
}
