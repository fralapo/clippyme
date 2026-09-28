// Pure helpers for the Live Monitor start form (host-tested, no DOM/network).
// Mirrors the backend's per-platform channel validation (domain/live_monitor.py
// _validate_channel) so the form can reject a bad channel before the request
// round-trip.
const SLUG_RE = /^[a-z0-9_-]+$/; // kick / twitch login
const YT_HANDLE_RE = /^@[A-Za-z0-9._-]{1,64}$/;
const YT_UC_RE = /^UC[A-Za-z0-9_-]{20,40}$/;

export function validateSlug(slug, platform = 'kick') {
  const raw = (slug || '').trim();
  if (!raw) return 'Channel is required';
  if (platform === 'youtube') {
    const s = raw;
    if (s.length > 256 || /\s/.test(s)) return 'Invalid channel (use an @handle, UC… id, or channel URL)';
    const lower = s.toLowerCase();
    const looksLikeUrl = lower.startsWith('http://') || lower.startsWith('https://')
      || lower.startsWith('youtube.com') || lower.startsWith('www.youtube.com');
    if (!(YT_HANDLE_RE.test(s) || YT_UC_RE.test(s) || looksLikeUrl)) {
      return 'Use an @handle, UC… channel id, or a youtube.com channel URL';
    }
    return null;
  }
  const s = raw.toLowerCase();
  if (s.length > 64 || !SLUG_RE.test(s)) return 'Use only lowercase letters, numbers, "_" or "-"';
  return null;
}

// Build the {platform, accountId} targets Zernio expects from the toggled
// `plats` map + the accounts saved in Settings. Mirrors publish.jsx's
// platTargets() so both surfaces stay in lockstep with the Zernio schema.
export function buildPlatformTargets(plats, accounts, platMap) {
  return Object.keys(plats || {})
    .filter((k) => plats[k] && accounts?.[platMap[k]?.acct])
    .map((k) => ({ platform: platMap[k].platform, accountId: accounts[platMap[k].acct] }));
}

// Convert the form's minute fields into the seconds payload, clamped to the
// backend schema bounds (segment 60–3600s, prelive 0–7200s, gap 0–86400s).
// A cleared number input is '' (NOT NaN — Number('') === 0): treat it as
// untouched and use the schema default, same as clipSelectionPayload, so a
// blanked field never silently becomes a 60-second segment.
export function clampMonitorTimings(segmentMin, preliveMin, minGapMin) {
  const secs = (v, fallback) => {
    if (v === '' || v === null || v === undefined) return fallback;
    const n = Math.round(Number(v) * 60);
    return Number.isFinite(n) ? n : fallback;
  };
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
  return {
    segment_seconds: clamp(secs(segmentMin, 1800), 60, 3600),
    prelive_skip_seconds: clamp(secs(preliveMin, 1800), 0, 7200),
    min_gap_seconds: clamp(secs(minGapMin, 900), 0, 86400),
  };
}

// Build the clip-selection payload (how many clips a segment publishes).
// "fixed" always takes the top `maxClips` by viral_score; "auto" keeps only
// clips scoring at least `minScore` — a weak segment then publishes fewer
// clips (or none) and `maxClips` is only the ceiling. Bounds mirror the
// backend schema (max_clips 0–1000 where 0 = no cap, min_viral_score 1–100).
export function clipSelectionPayload(selection, maxClips, minScore) {
  const clampInt = (v, lo, hi, fallback) => {
    // Number('') === 0 would clamp a cleared field to the minimum — treat
    // empty/null as untouched and fall back to the schema default instead.
    if (v === '' || v === null || v === undefined) return fallback;
    const n = Math.round(Number(v));
    return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : fallback;
  };
  return {
    clip_selection: selection === 'auto' ? 'auto' : 'fixed',
    max_clips: clampInt(maxClips, 0, 1000, 5),
    min_viral_score: clampInt(minScore, 1, 100, 70),
  };
}

// Letterbox zoom is stored as a FRACTION by the backend (0, or 0.05–0.15) but
// edited as a percentage in the UI. Anything outside the allowed band reads as
// off, so a stale/garbage config never renders a bogus slider value.
export const LETTERBOX_ZOOM_PERCENTS = [0, 5, 10, 15];

export function zoomToPercent(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return 0;
  const pct = Math.round(n > 1 ? n : n * 100);
  return LETTERBOX_ZOOM_PERCENTS.includes(pct) ? pct : 0;
}

// Classify a failed /api/live-monitor/start error message so the UI can show
// a targeted toast instead of a generic failure banner.
export function classifyStartError(message) {
  const m = String(message || '');
  if (/already running/i.test(m)) return 'duplicate';
  if (/twitch/i.test(m) && /credential|client_id|client_secret/i.test(m)) return 'twitch_creds';
  return 'other';
}
