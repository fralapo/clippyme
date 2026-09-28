import { afterEach, test, vi } from 'vitest';
import assert from 'node:assert/strict';
import { clearPublishIntent, publishIntent } from './publishIntent.js';

afterEach(() => {
  vi.unstubAllGlobals();
  globalThis.sessionStorage?.clear();
});

test('retries of one Publish reuse the same intent', () => {
  const first = publishIntent('job', 0);
  assert.match(first, /^[0-9a-f]{32}$/);
  assert.equal(publishIntent('job', 0), first);
});

test('each clip gets its own intent', () => {
  assert.notEqual(publishIntent('job', 0), publishIntent('job', 1));
  assert.notEqual(publishIntent('job', 0), publishIntent('other', 0));
});

test('a confirmed publish ends the intent: the next one is a new re-publish', () => {
  const first = publishIntent('job', 2);
  clearPublishIntent('job', 2);
  assert.notEqual(publishIntent('job', 2), first);
});

test('the intent is kept in sessionStorage, which survives a reload of the tab', () => {
  const first = publishIntent('job', 3);
  const stored = JSON.parse(globalThis.sessionStorage.getItem('clippyme.publishIntent.job.3'));
  assert.equal(stored, first);
});

test('blocked storage still keeps the intent for retries in this page', () => {
  vi.stubGlobal('sessionStorage', undefined);
  const first = publishIntent('job', 4);
  assert.equal(publishIntent('job', 4), first);
});
