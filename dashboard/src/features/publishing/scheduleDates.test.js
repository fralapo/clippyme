import process from 'node:process';
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

import { manualScheduleIso, manualScheduleProblem } from './scheduleDates.js';

test('manualScheduleIso converts the browser-local selection to an explicit UTC instant', () => {
  const local = '2030-06-12T17:45';
  assert.equal(manualScheduleIso(local, new Date('2026-10-01T00:00:00Z')), new Date(local).toISOString());
});

test('manualScheduleIso blocks past, invalid and normalization-prone inputs', () => {
  const now = new Date('2030-06-12T17:46');
  for (const local of ['', 'yesterday', '2030-06-12T17:45', '2030-06-12T17:46', '2030-02-31T08:00']) {
    assert.equal(manualScheduleIso(local, now), null, local);
  }
});

test('manual scheduling rejects autumn DST fold in Europe/Rome, not a silent hour choice', () => {
  const original = process.env.TZ;
  try {
    process.env.TZ = 'Europe/Rome';
    const now = new Date('2026-10-12T00:00:00Z');
    // 02:30 exists twice on Sunday 27 October 2030 (CEST and CET).
    assert.equal(manualScheduleIso('2030-10-27T02:30', now), null);
    assert.match(manualScheduleProblem('2030-10-27T02:30', now), /occurs twice/i);
    assert.equal(manualScheduleIso('2030-10-27T03:30', now), '2030-10-27T02:30:00.000Z');
    // Spring-forward gap must still be rejected.
    assert.equal(manualScheduleIso('2030-03-31T02:30', now), null);
    assert.equal(manualScheduleIso('2030-03-31T03:30', now), '2030-03-31T01:30:00.000Z');
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }
});

test('manual scheduling rejects non-European DST ambiguity without rejecting normal times', () => {
  const original = process.env.TZ;
  try {
    process.env.TZ = 'America/New_York';
    const now = new Date('2026-10-12T00:00:00Z');
    // 01:30 repeats on Sunday 3 November 2030 in New York.
    assert.equal(manualScheduleIso('2030-11-03T01:30', now), null);
    assert.match(manualScheduleProblem('2030-11-03T01:30', now), /occurs twice/i);
    assert.equal(manualScheduleIso('2030-11-03T02:30', now), '2030-11-03T07:30:00.000Z');
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }
});
