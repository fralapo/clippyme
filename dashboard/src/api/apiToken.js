// Optional API token for deliberate LAN deployments (CLIPPYME_API_TOKEN).
// When the backend has a token configured, every /api request must carry it;
// the token itself lives in localStorage (set in Settings) so the static
// frontend needs no build-time secret. Empty token → apiFetch is plain fetch,
// byte-identical request shape.

const API_TOKEN_KEY = 'clippyme_api_token';

function storage() {
  // Node (unit tests) has no localStorage; browsers can throw on access in
  // hardened privacy modes. Either way we degrade to "no token".
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null;
  } catch {
    return null;
  }
}

export function getApiToken() {
  try {
    return storage()?.getItem(API_TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

export function setApiToken(token) {
  try {
    const s = storage();
    if (!s) return;
    const trimmed = (token || '').trim();
    if (trimmed) s.setItem(API_TOKEN_KEY, trimmed);
    else s.removeItem(API_TOKEN_KEY);
  } catch {
    // Persist failure just means the user re-enters the token next session.
  }
}

/** fetch() that attaches X-API-Token when one is configured. */
export function apiFetch(url, init = {}) {
  const token = getApiToken();
  if (!token) return fetch(url, init);
  return fetch(url, { ...init, headers: { ...(init.headers || {}), 'X-API-Token': token } });
}
