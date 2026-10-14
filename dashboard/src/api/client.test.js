import { test, vi } from 'vitest';
import assert from 'node:assert/strict';

// Vitest runs with a jsdom environment, so window.location.origin is real —
// the old plain-Node `globalThis.window` stub is gone.
import { optsToPreselections, clipVideoSrc, clipPreviewSrc, fmtDuration, exportClip, deleteHistoryJob, listHistoryJobs, getStorageUsage, reviewClip, getTikTokCreatorInfo } from './client.js';

// --- optsToPreselections: the Create-tab → backend translation layer --------

test('reframe mode: legacy object alias normalizes to subject', () => {
  assert.equal(optsToPreselections({ reframeMode: 'object' }).reframe_mode, 'subject');
  assert.equal(optsToPreselections({ reframeMode: 'subject' }).reframe_mode, 'subject');
  assert.equal(optsToPreselections({ reframeMode: 'disabled' }).reframe_mode, 'disabled');
});

test('reframe mode: legacy boolean fallback, default auto', () => {
  assert.equal(optsToPreselections({}).reframe_mode, 'auto');
  assert.equal(optsToPreselections({ reframe: false }).reframe_mode, 'disabled');
});

test('model override: blank is omitted, value passes through trimmed', () => {
  assert.equal(optsToPreselections({}).model, undefined);
  assert.equal(optsToPreselections({ model: '  ' }).model, undefined);
  assert.equal(optsToPreselections({ model: ' gemini-2.5-pro ' }).model, 'gemini-2.5-pro');
});

test('karaoke subtitles carry colours but not classic typography', () => {
  const p = optsToPreselections({
    subtitles: true, subMode: 'karaoke', subPreset: 'hormozi_bold',
    subColor: '#FDE700', subStroke: '#111111', subFontSize: 48,
  });
  assert.equal(p.subtitles.preset, 'hormozi_bold');
  assert.equal(p.subtitles.font_color, '#FDE700');
  assert.equal(p.subtitles.outline_color, '#111111');
  assert.equal(p.subtitles.font_size, 48);
  assert.equal('font' in p.subtitles, false, 'classic-only font key leaked into karaoke');
});

test('karaoke font_size 0 means Auto and is omitted', () => {
  const p = optsToPreselections({ subtitles: true, subMode: 'karaoke', subFontSize: 0 });
  assert.equal('font_size' in p.subtitles, false);
});

test('classic subtitles carry font/border/background', () => {
  const p = optsToPreselections({
    subtitles: true, subMode: 'classic', subFont: 'Anton-Regular',
    subColor: '#581BBA', subOutlineW: 3, subBg: true,
  });
  assert.equal(p.subtitles.font, 'Anton-Regular');
  assert.equal(p.subtitles.font_color, '#581BBA');
  assert.equal(p.subtitles.border_width, 3);
  assert.equal(p.subtitles.bg_opacity, 0.6);
  assert.equal(p.subtitles.bg_color, '#000000');
});

test('subtitles off → false; grade none → false; logo off → false', () => {
  const p = optsToPreselections({ subtitles: false, gradePreset: 'none', logo: false });
  assert.equal(p.subtitles, false);
  assert.equal(p.grade, false);
  assert.equal(p.logo, false);
});

test('grade preset flows through when set', () => {
  assert.deepEqual(optsToPreselections({ gradePreset: 'vivid_pop' }).grade, { preset: 'vivid_pop' });
});

// --- URL safety: a malicious API response must never become an executable src

test('clipVideoSrc neutralizes javascript: and data: schemes', () => {
  for (const evil of ['javascript:alert(1)', 'data:text/html,<script>x</script>']) {
    const src = clipVideoSrc({ video_url: evil });
    assert.equal(src.startsWith('javascript:'), false);
    assert.equal(src.startsWith('data:'), false);
    assert.equal(src.startsWith('/'), true, `expected inert relative path, got ${src}`);
  }
});

test('clipVideoSrc appends the cache-buster correctly', () => {
  assert.equal(clipVideoSrc({ video_url: '/videos/j/clip_1.mp4' }, 99).endsWith('?v=99'), true);
  assert.equal(clipVideoSrc({ video_url: '/videos/j/c.mp4?x=1' }, 99).endsWith('&v=99'), true);
});

test('clipPreviewSrc prefers the composed previewUrl over the raw clip', () => {
  const clip = { video_url: '/videos/j/clip_1.mp4' };
  const raw = clipPreviewSrc(clip, {});
  assert.equal(raw.includes('clip_1.mp4'), true);
  const composed = clipPreviewSrc(clip, { previewUrl: '/videos/j/composed_clip_0.mp4', previewBust: 7 });
  assert.equal(composed.includes('composed_clip_0.mp4'), true);
  assert.equal(composed.endsWith('?v=7'), true);
});

test('fmtDuration renders m:ss with zero-padded seconds', () => {
  assert.equal(fmtDuration(0, 65), '1:05');
  assert.equal(fmtDuration(10, 10), '0:00');
  assert.equal(fmtDuration(0, 599.6), '10:00');
});

// --- I-1 regression: per-clip endpoints must resolve by the backend's
// ABSOLUTE `shorts` position (`original_index`), not the frontend array
// position — they diverge once a manual-publish gap skips a
// deleted_after_publish clip (job_results._build_clips).

test('exportClip composes against clip.original_index, not the array position', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (url) => {
    calls.push(url);
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ composed_url: '/videos/j/composed.mp4' }) });
  };
  try {
    // Clip B sits at array position 1 but is absolute shorts position 2 (a
    // deleted_after_publish clip at position 1 was skipped upstream).
    const clip = { original_index: 2, video_url: '/videos/j/clip_3.mp4' };
    const state = { toggles: { subtitles: true } };
    await exportClip('job-1', 1, clip, state, {});
    assert.equal(calls.length, 1);
    assert.match(String(calls[0]), /\/api\/compose\/job-1\/2$/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

// --- history delete must hit the backend (files off disk), not just the
// localStorage entry — a row dismissal that left the output/ dir behind was
// silently leaking storage.

test('deleteHistoryJob issues a DELETE and resolves on 200', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (url, init = {}) => {
    calls.push({ url, method: init.method });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true }) });
  };
  try {
    const body = await deleteHistoryJob('abc-123');
    assert.equal(body.success, true);
    assert.equal(calls.length, 1);
    assert.match(String(calls[0].url), /\/api\/history\/abc-123$/);
    assert.equal(calls[0].method, 'DELETE');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('deleteHistoryJob surfaces non-OK status so callers can handle 404/409', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => Promise.resolve({ ok: false, status: 409 });
  try {
    let caught = null;
    try { await deleteHistoryJob('abc-123'); } catch (e) { caught = e; }
    assert.ok(caught, 'expected deleteHistoryJob to throw on non-OK');
    assert.equal(caught.status, 409);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test('listHistoryJobs returns canonical backend rows and propagates errors', async () => {
  const originalFetch = globalThis.fetch;
  try {
    const jobs = [{ jobId: 'a', status: 'stopped', clipCount: 1, publishedCount: 2 }];
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ jobs }),
    });
    assert.deepEqual(await listHistoryJobs(), jobs);
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 503 });
    await assert.rejects(listHistoryJobs(), (error) => error.status === 503);
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ unexpected: [] }),
    });
    await assert.rejects(listHistoryJobs(), /Malformed history/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('storage summary requests the backend and rejects invalid responses', async () => {
  const previous = globalThis.fetch;
  const valid = { jobs: [], diskFreeBytes: 100, diskTotalBytes: 200, outputBytes: 0,
    dataBytes: 0, uploadsBytes: 0, lowSpace: false };
  try {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => valid });
    assert.deepEqual(await getStorageUsage(), valid);
    assert.match(globalThis.fetch.mock.calls[0][0], /\/api\/storage$/);
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ jobs: [] }) });
    await assert.rejects(getStorageUsage(), /Malformed/);
  } finally { globalThis.fetch = previous; }
});

test('reviewClip persists one review decision and returns canonical metadata fields', async () => {
  const previous = globalThis.fetch;
  const calls = [];
  try {
    globalThis.fetch = vi.fn((url, init) => {
      calls.push({ url, init });
      return Promise.resolve({ ok: true, json: async () => ({
        success: true, review_status: 'changes_requested',
        review_note: 'Keep the full sentence.', review_updated_at: '2030-01-01T00:00:00Z',
      }) });
    });
    const saved = await reviewClip('job-1', 3, {
      status: 'changes_requested', note: 'Keep the full sentence.',
    });
    assert.deepEqual(saved, {
      review_status: 'changes_requested', review_note: 'Keep the full sentence.',
      review_updated_at: '2030-01-01T00:00:00Z',
    });
    assert.match(String(calls[0].url), /\/api\/review\/job-1\/3$/);
    assert.equal(calls[0].init.method, 'PATCH');
    assert.deepEqual(JSON.parse(calls[0].init.body), {
      status: 'changes_requested', note: 'Keep the full sentence.',
    });
  } finally { globalThis.fetch = previous; }
});

test('TikTok creator info URL encodes the account and returns provider options', async () => {
  const previous = globalThis.fetch;
  try {
    const options = { privacyLevels: [{ value: 'SELF_ONLY', label: 'Only me' }] };
    globalThis.fetch = vi.fn(async (url) => {
      assert.match(String(url), /account_id=creator%2B1/);
      return { ok: true, json: async () => options };
    });
    assert.deepEqual(await getTikTokCreatorInfo('creator+1'), options);
  } finally { globalThis.fetch = previous; }
});
