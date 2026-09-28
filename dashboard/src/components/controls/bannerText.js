// Pure mirror of clippyme.domain.banner.sanitize_handle / banner_text, so the
// live "kick.com/grenbaud"-style preview matches what the backend will burn.
// Kept host-testable (no deps) — see bannerText.test.js.

const HANDLE_ALLOWED_RE = /[^A-Za-z0-9_.-]/g;
const HANDLE_MAX = 40;
const HOST_PREFIXES = [
  'https://', 'http://', 'www.',
  'kick.com/', 'twitch.tv/', 'm.twitch.tv/',
  'youtube.com/', 'm.youtube.com/', 'youtu.be/',
];
const PLATFORMS = new Set(['kick', 'twitch', 'youtube']);

export function sanitizeHandle(raw) {
  if (!raw) return null;
  let h = String(raw).trim();
  let low = h.toLowerCase();
  for (const pref of HOST_PREFIXES) {
    if (low.startsWith(pref)) {
      h = h.slice(pref.length);
      low = h.toLowerCase();
    }
  }
  h = h.split('?')[0].split('#')[0].split('/')[0];
  h = h.replace(/^@/, '');
  h = h.replace(HANDLE_ALLOWED_RE, '');
  h = h.slice(0, HANDLE_MAX);
  return h || null;
}

// Display string: 'kick.com/<h>' · 'twitch.tv/<h>' · 'youtube.com/@<h>' (the
// '@' is forced for youtube). null when platform/handle is unusable.
export function bannerText(platform, handle) {
  const h = sanitizeHandle(handle);
  if (!h || !PLATFORMS.has(platform)) return null;
  if (platform === 'kick') return `kick.com/${h}`;
  if (platform === 'twitch') return `twitch.tv/${h}`;
  return `youtube.com/@${h}`;
}
