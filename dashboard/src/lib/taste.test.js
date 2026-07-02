import { test } from 'node:test';
import assert from 'node:assert/strict';

// In-memory localStorage shim so the I/O exports are testable without jsdom.
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};

const { summarizeTaste, loadTasteEvents, recordTasteEvent, tasteInstructionSuffix } =
  await import('./taste.js');

test('summarizeTaste returns empty below the signal threshold', () => {
  assert.equal(summarizeTaste([]), '');
  assert.equal(summarizeTaste([{ a: 'kept', d: 20, s: 80 }]), '');
});

test('summarizeTaste suggests a preferred length from kept clips', () => {
  const evs = Array.from({ length: 8 }, () => ({ a: 'kept', d: 20, s: 80 }));
  const out = summarizeTaste(evs);
  assert.match(out, /14-26s/);
  assert.match(out, /past edits/);
});

test('summarizeTaste flags a discard score band when kept >> discarded', () => {
  const kept = Array.from({ length: 5 }, () => ({ a: 'kept', d: 25, s: 85 }));
  const disc = Array.from({ length: 5 }, () => ({ a: 'discarded', d: 25, s: 40 }));
  const out = summarizeTaste([...kept, ...disc]);
  assert.match(out, /scoring below about 85/);
});

test('summarizeTaste ignores invalid actions', () => {
  const evs = Array.from({ length: 10 }, () => ({ a: 'bogus', d: 20, s: 80 }));
  assert.equal(summarizeTaste(evs), '');
});

// --- localStorage-backed exports (shimmed above) ----------------------------

test('recordTasteEvent round-trips through loadTasteEvents', () => {
  store.clear();
  recordTasteEvent({ viralScore: 87.4, duration: 21.6, action: 'kept' });
  assert.deepEqual(loadTasteEvents(), [{ s: 87, d: 22, a: 'kept' }]);
});

test('recordTasteEvent silently drops invalid actions', () => {
  store.clear();
  recordTasteEvent({ viralScore: 80, duration: 20, action: 'published' });
  recordTasteEvent({ viralScore: 80, duration: 20 });
  assert.deepEqual(loadTasteEvents(), []);
});

test('recordTasteEvent trims to the 120-event rolling window', () => {
  store.clear();
  for (let i = 0; i < 130; i++) {
    recordTasteEvent({ viralScore: i, duration: 20, action: 'kept' });
  }
  const events = loadTasteEvents();
  assert.equal(events.length, 120);
  assert.equal(events[0].s, 10, 'oldest events must decay out first');
  assert.equal(events[119].s, 129);
});

test('loadTasteEvents survives garbage in storage', () => {
  store.set('clippyme_taste_v1', 'not json{{{');
  assert.deepEqual(loadTasteEvents(), []);
  store.set('clippyme_taste_v1', '{"an":"object"}');
  assert.deepEqual(loadTasteEvents(), [], 'non-array JSON must not leak through');
});

test('tasteInstructionSuffix distils stored events into a hint', () => {
  store.clear();
  for (let i = 0; i < 8; i++) {
    recordTasteEvent({ viralScore: 85, duration: 20, action: 'kept' });
  }
  assert.match(tasteInstructionSuffix(), /14-26s/);
});
