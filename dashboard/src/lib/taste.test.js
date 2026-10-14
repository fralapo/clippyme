import { test } from 'vitest';
import assert from 'node:assert/strict';

// In-memory localStorage shim so the I/O exports are testable without jsdom.
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};

const { summarizeTaste, loadTasteEvents, recordTasteEvent, tasteInstructionSuffix, REVIEW_FEEDBACK_REASONS, REVIEW_APPROVAL_REASONS } =
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

test('explicit review reasons store only an allowed category beside coarse clip signals', () => {
  store.clear();
  recordTasteEvent({ viralScore: 81, duration: 22, action: 'changes_requested', reason: 'cut_loses_context' });
  recordTasteEvent({ viralScore: 81, duration: 22, action: 'discarded', reason: 'https://private.example/video' });
  assert.deepEqual(loadTasteEvents(), [
    { s: 81, d: 22, a: 'changes_requested', r: 'cut_loses_context' },
    { s: 81, d: 22, a: 'discarded' },
  ]);
  assert.equal(Object.hasOwn(REVIEW_FEEDBACK_REASONS, 'cut_loses_context'), true);
  recordTasteEvent({ viralScore: 92, duration: 21, action: 'approved', reason: 'strong_payoff' });
  assert.deepEqual(loadTasteEvents()[2], { s: 92, d: 21, a: 'approved', r: 'strong_payoff' });
  assert.equal(Object.hasOwn(REVIEW_APPROVAL_REASONS, 'strong_payoff'), true);
});

test('repeated explicit reasons add a bounded suggestion to future clip instructions', () => {
  const kept = Array.from({ length: 3 }, () => ({ a: 'kept', d: 20, s: 80 }));
  const changes = Array.from({ length: 3 }, () => ({
    a: 'changes_requested', d: 20, s: 80, r: 'cut_loses_context',
  }));
  assert.match(summarizeTaste([...kept, ...changes]), /avoid starting or ending mid-thought/);
  const tooFew = [...kept, ...changes.slice(0, 2)];
  assert.doesNotMatch(summarizeTaste(tooFew), /mid-thought/);
  const accepted = Array.from({ length: 3 }, () => ({ a: 'approved', d: 20, s: 90, r: 'strong_payoff' }));
  assert.match(summarizeTaste([...accepted, ...kept]), /favor hooks that are supported by the clip payoff/);
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
