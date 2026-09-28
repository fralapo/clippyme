import { test } from 'vitest';
import assert from 'node:assert/strict';
import { sanitizeHandle, bannerText } from './bannerText.js';

// Mirrors clippyme.domain.banner (sanitize_handle / banner_text) — the
// display-text preview shown in the UI must match what the backend burns.

test('bannerText forces the "@" prefix for youtube only', () => {
  assert.equal(bannerText('kick', 'grenbaud'), 'kick.com/grenbaud');
  assert.equal(bannerText('twitch', 'grenbaud'), 'twitch.tv/grenbaud');
  assert.equal(bannerText('youtube', 'GrenBaudLounge'), 'youtube.com/@GrenBaudLounge');
  assert.equal(bannerText('youtube', '@GrenBaudLounge'), 'youtube.com/@GrenBaudLounge');
});

test('bannerText is null for an unknown platform or unusable handle', () => {
  assert.equal(bannerText('twitter', 'x'), null);
  assert.equal(bannerText('kick', ''), null);
  assert.equal(bannerText('kick', null), null);
  assert.equal(bannerText('kick', '###'), null);
});

test('sanitizeHandle strips pasted URLs down to the handle', () => {
  assert.equal(sanitizeHandle('https://kick.com/grenbaud'), 'grenbaud');
  assert.equal(sanitizeHandle('kick.com/grenbaud?x=1'), 'grenbaud');
  assert.equal(sanitizeHandle('https://www.youtube.com/@GrenBaudLounge'), 'GrenBaudLounge');
  assert.equal(sanitizeHandle('twitch.tv/xqc/'), 'xqc');
});

test('sanitizeHandle drops a leading @, disallowed chars, and caps length', () => {
  assert.equal(sanitizeHandle('@GrenBaudLounge'), 'GrenBaudLounge');
  assert.equal(sanitizeHandle('gr en$baud!'), 'grenbaud');
  assert.equal(sanitizeHandle('a'.repeat(60)).length, 40);
});
