// Optional LAN authentication token, stored according to the operator's
// browser retention preference (persistent or session-only).
import { readBrowserCredential, writeBrowserCredential } from '../lib/credentialStorage';

export function getApiToken() {
  return readBrowserCredential('clippyme_api_token');
}

export function setApiToken(token) {
  writeBrowserCredential('clippyme_api_token', token);
}

/** fetch() that attaches X-API-Token when configured. */
export function apiFetch(url, init = {}) {
  const token = getApiToken();
  if (!token) return fetch(url, init);
  return fetch(url, { ...init, headers: { ...(init.headers || {}), 'X-API-Token': token } });
}
