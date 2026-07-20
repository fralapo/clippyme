import { test } from 'vitest';
import assert from 'node:assert/strict';

import { validateSlug, buildPlatformTargets, classifyStartError, clampMonitorTimings } from './liveMonitorForm.js';

test('validateSlug: kick/twitch required, charset, length', () => {
  assert.equal(validateSlug(''), 'Channel is required');
  assert.equal(validateSlug('   '), 'Channel is required');
  assert.equal(validateSlug('xQc'), null); // case-insensitive input, lowercased before checking
  assert.equal(validateSlug('has space'), 'Use only lowercase letters, numbers, "_" or "-"');
  assert.equal(validateSlug('a'.repeat(65)), 'Use only lowercase letters, numbers, "_" or "-"');
  assert.equal(validateSlug('valid_slug-123'), null);
  assert.equal(validateSlug('xqc', 'twitch'), null);
  assert.equal(validateSlug('has space', 'twitch'), 'Use only lowercase letters, numbers, "_" or "-"');
});

test('validateSlug: youtube accepts @handle / UC id / channel URL', () => {
  assert.equal(validateSlug('', 'youtube'), 'Channel is required');
  assert.equal(validateSlug('@MrBeast', 'youtube'), null);
  assert.equal(validateSlug('UC' + 'x'.repeat(22), 'youtube'), null);
  assert.equal(validateSlug('https://youtube.com/@MrBeast', 'youtube'), null);
  assert.equal(validateSlug('www.youtube.com/channel/UCabc', 'youtube'), null);
  assert.equal(validateSlug('justsometext', 'youtube'), 'Use an @handle, UC… channel id, or a youtube.com channel URL');
  assert.equal(validateSlug('has space', 'youtube'), 'Invalid channel (use an @handle, UC… id, or channel URL)');
});

const PLAT_MAP = {
  tiktok: { platform: 'tiktok', acct: 'tiktok' },
  ig: { platform: 'instagram', acct: 'instagram' },
  yt: { platform: 'youtube', acct: 'youtube' },
};

test('buildPlatformTargets: only toggled AND configured accounts pass through', () => {
  const targets = buildPlatformTargets(
    { tiktok: true, ig: true, yt: false },
    { tiktok: 'tt-id', instagram: '' },
    PLAT_MAP,
  );
  assert.deepEqual(targets, [{ platform: 'tiktok', accountId: 'tt-id' }]);
});

test('buildPlatformTargets: empty when nothing toggled or nothing configured', () => {
  assert.deepEqual(buildPlatformTargets({}, {}, PLAT_MAP), []);
  assert.deepEqual(buildPlatformTargets({ tiktok: true }, {}, PLAT_MAP), []);
});

test('classifyStartError: duplicate / twitch creds / other', () => {
  assert.equal(classifyStartError('monitor already running: kick:xqc'), 'duplicate');
  assert.equal(
    classifyStartError('Twitch monitoring requires TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET (set them in Settings or the environment)'),
    'twitch_creds',
  );
  assert.equal(classifyStartError('Gemini API key not configured'), 'other');
  assert.equal(classifyStartError(''), 'other');
});

test('clampMonitorTimings: defaults pass through in seconds', () => {
  assert.deepEqual(clampMonitorTimings(30, 30, 15), {
    segment_seconds: 1800, prelive_skip_seconds: 1800, min_gap_seconds: 900,
  });
});

test('clampMonitorTimings: cleared input (0/NaN) never 422s', () => {
  // Number('') === 0 → segment would be 0 (< schema min 60) without clamping.
  const zeroed = clampMonitorTimings(0, 0, 0);
  assert.equal(zeroed.segment_seconds, 60);
  assert.equal(zeroed.prelive_skip_seconds, 0);
  assert.equal(zeroed.min_gap_seconds, 0);
  // NaN (garbage input) falls back to the schema defaults.
  assert.deepEqual(clampMonitorTimings(NaN, NaN, NaN), {
    segment_seconds: 1800, prelive_skip_seconds: 1800, min_gap_seconds: 900,
  });
});

test('clampMonitorTimings: values above schema caps are clamped', () => {
  const big = clampMonitorTimings(90, 999, 99999);
  assert.equal(big.segment_seconds, 3600);       // 90min → cap 60min
  assert.equal(big.prelive_skip_seconds, 7200);  // cap 120min
  assert.equal(big.min_gap_seconds, 86400);      // cap 24h
});
