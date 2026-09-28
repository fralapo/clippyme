import { test } from 'vitest';
import assert from 'node:assert/strict';
import { localDatePlus } from './scheduleDates.js';

// The one-clip-per-day batch spacing lives or dies on this function: two
// clips landing on the same day trips the per-platform daily cap (429) that
// only surfaces days later as an opaque Zernio error.

test('localDatePlus formats today as zero-padded YYYY-MM-DD', () => {
  const out = localDatePlus(0, new Date(2026, 2, 5)); // 5 Mar 2026
  assert.equal(out, '2026-03-05');
});

test('localDatePlus gives each batch position its own day', () => {
  const base = new Date(2026, 6, 2); // 2 Jul 2026
  const days = [0, 1, 2, 3].map((i) => localDatePlus(i, base));
  assert.deepEqual(days, ['2026-07-02', '2026-07-03', '2026-07-04', '2026-07-05']);
  assert.equal(new Set(days).size, days.length, 'duplicate day in batch spacing');
});

test('localDatePlus rolls over month ends', () => {
  assert.equal(localDatePlus(1, new Date(2026, 0, 31)), '2026-02-01');
  assert.equal(localDatePlus(2, new Date(2026, 1, 27)), '2026-03-01'); // 2026 not a leap year
});

test('localDatePlus rolls over year end', () => {
  assert.equal(localDatePlus(1, new Date(2026, 11, 31)), '2027-01-01');
});

test('localDatePlus does not mutate the injected date', () => {
  const base = new Date(2026, 5, 15);
  localDatePlus(5, base);
  assert.equal(base.getDate(), 15);
});
