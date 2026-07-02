import { test } from 'node:test';
import assert from 'node:assert/strict';

// safeResolveUrl reads window.location.origin at call time; stub it before the
// dynamic import so the module loads under plain Node (no jsdom needed).
globalThis.window = { location: { origin: 'http://localhost:5175' } };
const { optsToPreselections, clipVideoSrc, clipPreviewSrc, fmtDuration } =
  await import('./realApi.js');

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
