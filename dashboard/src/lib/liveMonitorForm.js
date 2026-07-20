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

// Classify a failed /api/live-monitor/start error message so the UI can show
// a targeted toast instead of a generic failure banner.
export function classifyStartError(message) {
  const m = String(message || '');
  if (/already running/i.test(m)) return 'duplicate';
  if (/twitch/i.test(m) && /credential|client_id|client_secret/i.test(m)) return 'twitch_creds';
  return 'other';
}
