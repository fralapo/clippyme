import { test } from 'node:test';
import assert from 'node:assert/strict';
import { summarizeTaste } from './taste.js';

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
