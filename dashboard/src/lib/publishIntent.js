// One manual publication intent per clip. It is born on the first Publish of
// the clip and reused by every retry of that Publish — a double click, a
// network error or timeout, a reload of this tab — until the server confirms
// the post; the next Publish after that is a new, deliberate re-publish.
// The backend turns it into Zernio's Idempotency-Key and also answers a
// repeat of an already-recorded intent without posting again.
//
// sessionStorage keeps it across a reload of the tab; if storage is blocked
// the in-memory copy still covers retries within this page.
import { readStoredJson, removeStoredValue, writeStoredJson } from './storage.js';

const memory = new Map();
const keyFor = (jobId, index) => `clippyme.publishIntent.${jobId}.${index}`;
const isIntent = (v) => typeof v === 'string' && /^[A-Za-z0-9-]{8,64}$/.test(v);

function newIntent() {
  // getRandomValues works on plain-http LAN origins; randomUUID does not.
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function publishIntent(jobId, index) {
  const key = keyFor(jobId, index);
  const id = readStoredJson(key, null, { kind: 'session', validate: isIntent })
    || memory.get(key) || newIntent();
  memory.set(key, id);
  writeStoredJson(key, id, { kind: 'session' });
  return id;
}

export function clearPublishIntent(jobId, index) {
  const key = keyFor(jobId, index);
  memory.delete(key);
  removeStoredValue(key, { kind: 'session' });
}
