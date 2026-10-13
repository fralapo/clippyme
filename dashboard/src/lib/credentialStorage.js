// Browser credential retention policy. Existing installations default to
// persistent localStorage; operators can opt into session-only storage.
// This does not change backend-stored provider keys (configured separately).
const MODE_KEY = 'clippyme_credential_retention';
const GEMINI_KEY = 'gemini_key';
const TOKEN_KEY = 'clippyme_api_token';
const KEYS = [GEMINI_KEY, TOKEN_KEY];

function safeStore(kind) {
  try { return kind === 'session' ? globalThis.sessionStorage : globalThis.localStorage; }
  catch { return null; }
}

export function getCredentialMode() {
  return safeStore('local')?.getItem(MODE_KEY) === 'session' ? 'session' : 'local';
}

export function readBrowserCredential(key) {
  if (!KEYS.includes(key)) return '';
  try { return safeStore(getCredentialMode())?.getItem(key) || ''; }
  catch { return ''; }
}

export function writeBrowserCredential(key, value) {
  if (!KEYS.includes(key)) return;
  const active = getCredentialMode();
  const other = active === 'session' ? 'local' : 'session';
  const normalized = String(value || '').trim();
  for (const mode of [active, other]) {
    try {
      const store = safeStore(mode);
      if (mode !== active || !normalized) store?.removeItem(key);
      else store?.setItem(key, normalized);
    } catch { /* disabled storage: credentials are never written elsewhere */ }
  }
}

export function setCredentialMode(mode) {
  if (mode !== 'session' && mode !== 'local') throw new Error('Invalid credential retention mode');
  const credentials = Object.fromEntries(KEYS.map((key) => [key, readBrowserCredential(key)]));
  // Move out of persistent storage before enabling session mode.
  for (const key of KEYS) for (const kind of ['local', 'session']) {
    try { safeStore(kind)?.removeItem(key); } catch { /* best effort */ }
  }
  try {
    if (mode === 'session') safeStore('local')?.setItem(MODE_KEY, 'session');
    else safeStore('local')?.removeItem(MODE_KEY);
  } catch { /* browser storage may be blocked */ }
  for (const [key, value] of Object.entries(credentials)) writeBrowserCredential(key, value);
  return getCredentialMode();
}
