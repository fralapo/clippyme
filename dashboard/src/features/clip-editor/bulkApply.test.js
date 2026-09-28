// Pure-logic tests for the bulk "apply to many clips" helpers. Run with the
// built-in Node test runner — `npm test`.
import { test } from 'vitest';
import assert from 'node:assert/strict';
import { clipStateToParams, buildClipParams, buildBulkPlan } from './bulkApply.js';

test('clipStateToParams uses saved state when present', () => {
  const state = {
    reframeMode: 'object',
    toggles: { smartcut: true, hook: false, subtitles: true, logo: false },
    subtitleParams: { mode: 'classic' },
    hookParams: { text: 'A', text_color: '#fff' },
    logoParams: { position: 'center', size: 'L' },
  };
  const p = clipStateToParams(state, {}, { reframe_mode: 'auto' });
  assert.equal(p.reframeMode, 'object');
  assert.deepEqual(p.toggles, state.toggles);
  assert.equal(p.subtitleParams.mode, 'classic');
  assert.equal(p.logoParams.position, 'center');
});

test('clipStateToParams falls back to seeds + clip reframe when state empty', () => {
  const pre = { smartcut: true, subtitles: { mode: 'karaoke', preset: 'hormozi_bold' } };
  const p = clipStateToParams(undefined, pre, { reframe_mode: 'disabled', viral_hook_text: 'Hi' });
  assert.equal(p.reframeMode, 'disabled'); // from the clip, not the missing state
  assert.equal(p.toggles.smartcut, true);
  assert.equal(p.subtitleParams.preset, 'hormozi_bold');
  assert.equal(p.hookParams.text, 'Hi'); // seeded from the clip
});

test('buildClipParams keeps the target clip own hook text + never copies drop ranges', () => {
  const src = {
    reframeMode: 'auto',
    toggles: { smartcut: true, hook: true, subtitles: false, logo: false },
    subtitleParams: { mode: 'karaoke' },
    hookParams: { text: 'SOURCE HOOK', text_color: '#ff0000', outline_width: 4 },
    logoParams: { position: 'top-left', size: 'M' },
  };
  const target = { reframe_mode: 'object', viral_hook_text: 'TARGET HOOK' };
  const targetState = { dropRanges: [[1, 2]] };
  const out = buildClipParams(src, target, targetState);
  // Hook STYLE copied, TEXT preserved from the target.
  assert.equal(out.hookParams.text, 'TARGET HOOK');
  assert.equal(out.hookParams.text_color, '#ff0000');
  assert.equal(out.hookParams.outline_width, 4);
  // Manual trim never propagated.
  assert.deepEqual(out.dropRanges, []);
  // baseMode reflects the target's current on-disk mode (for the reframe diff).
  assert.equal(out.baseMode, 'object');
  assert.equal(out.reframeMode, 'auto');
});

test('buildClipParams hook text falls back through clip then source', () => {
  const src = { reframeMode: 'auto', toggles: {}, subtitleParams: {}, logoParams: {},
    hookParams: { text: 'SRC' } };
  // No target text anywhere → source text is the last resort.
  assert.equal(buildClipParams(src, {}, {}).hookParams.text, 'SRC');
  // Saved per-clip edit wins over the Gemini suggestion.
  assert.equal(
    buildClipParams(src, { viral_hook_text: 'GEMINI' }, { hookParams: { text: 'EDITED' } }).hookParams.text,
    'EDITED',
  );
});

test('buildBulkPlan skips the source clip and plans the rest', () => {
  const src = { reframeMode: 'auto', toggles: { smartcut: true }, subtitleParams: {}, logoParams: {}, hookParams: { text: 'x' } };
  const targets = [
    { i: 0, c: { id: 'a' } },
    { i: 1, c: { id: 'b' } },
    { i: 2, c: { id: 'c' } },
  ];
  const plan = buildBulkPlan(src, targets, {}, 1);
  assert.equal(plan.length, 2);
  assert.deepEqual(plan.map((p) => p.idx), [0, 2]);
  assert.equal(plan[0].clip.id, 'a');
  assert.equal(plan[0].params.toggles.smartcut, true);
});
