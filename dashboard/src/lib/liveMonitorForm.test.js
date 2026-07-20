import { test } from 'vitest';
import assert from 'node:assert/strict';

import { validateSlug, buildPlatformTargets } from './liveMonitorForm.js';

test('validateSlug: required, charset, length', () => {
  assert.equal(validateSlug(''), 'Channel slug is required');
  assert.equal(validateSlug('   '), 'Channel slug is required');
  assert.equal(validateSlug('xQc'), null); // case-insensitive input, lowercased before checking
  assert.equal(validateSlug('has space'), 'Use only lowercase letters, numbers, "_" or "-"');
  assert.equal(validateSlug('a'.repeat(65)), 'Use only lowercase letters, numbers, "_" or "-"');
  assert.equal(validateSlug('valid_slug-123'), null);
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
