// runApplyEdit — the reprocess orchestration extracted from RedesignApp.
// Pins: call routing (reframe-only / compose-only / both / no-op), the
// toggle-gated compose body, and the partial-failure recovery paths.
import { test, expect, vi } from 'vitest';
import { runApplyEdit } from './applyEdit.js';

const JOB = 'job-1';

function makeCtx({ reframeImpl, composeImpl } = {}) {
  const calls = { states: [], toasts: [] };
  return {
    calls,
    args: {
      jobId: JOB,
      idx: 2,
      api: {
        reframeClip: vi.fn(reframeImpl || (async () => ({}))),
        composeClip: vi.fn(composeImpl || (async () => ({ composed_url: '/videos/job-1/composed_clip_2.mp4' }))),
      },
      updateClipState: (idx, patch) => calls.states.push(patch),
      pushToast: (kind, msg) => calls.toasts.push([kind, msg]),
      now: () => 1234,
    },
  };
}

const baseParams = (over = {}) => ({
  reframeMode: 'auto', baseMode: 'auto',
  toggles: { smartcut: false, subtitles: false, hook: false, logo: false, grade: false },
  subtitleParams: { mode: 'karaoke', preset: 'hormozi_bold' },
  hookParams: { text: 'HOOK' },
  logoParams: { position: 'top-right', size: 'M' },
  gradeParams: { preset: 'warm_cinematic' },
  dropRanges: [],
  ...over,
});

test('no change at all → no API calls, success toast, no processing flag', async () => {
  const { calls, args } = makeCtx();
  await runApplyEdit({ ...args, params: baseParams() });
  expect(args.api.reframeClip).not.toHaveBeenCalled();
  expect(args.api.composeClip).not.toHaveBeenCalled();
  expect(calls.states[0].processing).toBe(false);
  expect(calls.toasts).toEqual([['success', 'Clip 3 updated']]);
});

test('reframe-only: calls reframeClip, busts cache, never composes', async () => {
  const { calls, args } = makeCtx();
  await runApplyEdit({ ...args, params: baseParams({ reframeMode: 'subject' }) });
  expect(args.api.reframeClip).toHaveBeenCalledWith(JOB, 2, 'subject');
  expect(args.api.composeClip).not.toHaveBeenCalled();
  const bust = calls.states.find((p) => p.reframeBust);
  expect(bust).toMatchObject({ reframeBust: 1234, previewUrl: undefined });
  expect(calls.states.at(-1).processing).toBe(false);
});

test('compose-only: gates every param object by its toggle', async () => {
  const { args } = makeCtx();
  await runApplyEdit({
    ...args,
    params: baseParams({
      toggles: { smartcut: false, subtitles: true, hook: false, logo: false, grade: false },
      dropRanges: [[1, 2]],
    }),
  });
  expect(args.api.reframeClip).not.toHaveBeenCalled();
  const body = args.api.composeClip.mock.calls[0][2];
  expect(body.subtitle_params).toMatchObject({ mode: 'karaoke' });
  expect(body.hook_params).toEqual({});
  expect(body.logo_params).toEqual({});
  expect(body.grade_params).toEqual({});
  // smartcut off → the staged dropRanges must NOT ride along
  expect(body.drop_ranges).toEqual([]);
});

test('smartcut on forwards drop_ranges', async () => {
  const { args } = makeCtx();
  await runApplyEdit({
    ...args,
    params: baseParams({
      toggles: { smartcut: true, subtitles: false, hook: false, logo: false, grade: false },
      dropRanges: [[3.5, 4.25]],
    }),
  });
  expect(args.api.composeClip.mock.calls[0][2].drop_ranges).toEqual([[3.5, 4.25]]);
});

test('reframe + compose: both called in order, preview updated', async () => {
  const { calls, args } = makeCtx();
  await runApplyEdit({
    ...args,
    params: baseParams({
      reframeMode: 'disabled',
      toggles: { smartcut: false, subtitles: true, hook: false, logo: false, grade: false },
    }),
  });
  expect(args.api.reframeClip).toHaveBeenCalledTimes(1);
  expect(args.api.composeClip).toHaveBeenCalledTimes(1);
  const done = calls.states.at(-1);
  expect(done).toMatchObject({ previewUrl: '/videos/job-1/composed_clip_2.mp4', processing: false });
});

test('partial failure: reframe ok + compose fail keeps the reframe cache-bust', async () => {
  const { calls, args } = makeCtx({ composeImpl: async () => { throw new Error('boom'); } });
  await runApplyEdit({
    ...args,
    params: baseParams({
      reframeMode: 'subject',
      toggles: { smartcut: true, subtitles: false, hook: false, logo: false, grade: false },
    }),
  });
  const last = calls.states.at(-1);
  expect(last).toMatchObject({ reframeBust: 1234, previewUrl: undefined, processing: false });
  expect(calls.toasts.at(-1)[0]).toBe('error');
  expect(calls.toasts.at(-1)[1]).toMatch(/reframed, but composing/);
});

test('apiIdx resolves the backend call independently of the local idx (I-1 gap)', async () => {
  // idx=2 is the local array position (used to key clipStates); apiIdx=5 is
  // clip.original_index — the backend's ABSOLUTE `shorts` position, which
  // diverges once a manual-publish gap skips a deleted_after_publish clip.
  const { calls, args } = makeCtx();
  await runApplyEdit({
    ...args, apiIdx: 5,
    params: baseParams({
      reframeMode: 'subject',
      toggles: { smartcut: false, subtitles: true, hook: false, logo: false, grade: false },
    }),
  });
  expect(args.api.reframeClip).toHaveBeenCalledWith(JOB, 5, 'subject');
  expect(args.api.composeClip.mock.calls[0][1]).toBe(5);
  // Local state/toast messaging still keys off the array position (idx=2).
  expect(calls.toasts.at(-1)).toEqual(['success', 'Clip 3 updated']);
});

test('409 from reframe → "too old to reframe" toast', async () => {
  const err = Object.assign(new Error('conflict'), { status: 409 });
  const { calls, args } = makeCtx({ reframeImpl: async () => { throw err; } });
  await runApplyEdit({ ...args, params: baseParams({ reframeMode: 'subject' }) });
  expect(calls.toasts.at(-1)[1]).toMatch(/too old to reframe/);
  expect(calls.states.at(-1).processing).toBe(false);
});

test('generic failure → truncated error toast, processing cleared', async () => {
  const { calls, args } = makeCtx({ reframeImpl: async () => { throw new Error('x'.repeat(200)); } });
  await runApplyEdit({ ...args, params: baseParams({ reframeMode: 'subject' }) });
  const [kind, msg] = calls.toasts.at(-1);
  expect(kind).toBe('error');
  expect(msg).toMatch(/reprocess failed/);
  expect(msg.length).toBeLessThan(120);
});
