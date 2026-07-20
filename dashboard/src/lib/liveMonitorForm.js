// Pure helpers for the Live Monitor start form (host-tested, no DOM/network).
// Mirrors the backend's slug pattern (domain/live_monitor.py _SLUG_RE) so the
// form can reject a bad slug before the request round-trip.
const SLUG_RE = /^[a-z0-9_-]+$/;

export function validateSlug(slug) {
  const s = (slug || '').trim().toLowerCase();
  if (!s) return 'Channel slug is required';
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
