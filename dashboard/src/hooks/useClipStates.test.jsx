// useClipStates — per-clip state persisted in localStorage per job.
// Pins the transient-`processing` reset on load (a reload mid-render must not
// leave a card wedged on the "Reprocessing…" overlay).
import { test, expect } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useClipStates } from './useClipStates.js';

const JOB = 'job-abc';
const KEY = `clippyme_clip_states_${JOB}`;

test('processing flag is cleared when state loads from storage', async () => {
  localStorage.setItem(KEY, JSON.stringify({
    0: { processing: true, reframeMode: 'subject' },
    1: { publishedAt: 42 },
  }));
  const { result } = renderHook(() => useClipStates(JOB));
  await waitFor(() => expect(result.current.getClipState(0).reframeMode).toBe('subject'));
  expect(result.current.getClipState(0).processing).toBe(false);
  expect(result.current.getClipState(1).publishedAt).toBe(42);
});

test('a stored karaoke font override is dropped on load, a classic font is kept', async () => {
  // Older builds saved `font: 'Montserrat-Black'` with every karaoke edit;
  // karaoke never had a font picker, so the preset font must win.
  localStorage.setItem(KEY, JSON.stringify({
    0: { subtitleParams: { mode: 'karaoke', preset: 'hormozi_bold', font: 'Montserrat-Black' } },
    1: { subtitleParams: { mode: 'classic', font: 'Bangers-Regular' } },
  }));
  const { result } = renderHook(() => useClipStates(JOB));
  await waitFor(() => expect(result.current.getClipState(0).subtitleParams?.preset).toBe('hormozi_bold'));
  expect('font' in result.current.getClipState(0).subtitleParams).toBe(false);
  expect(result.current.getClipState(1).subtitleParams.font).toBe('Bangers-Regular');
});

test('updateClip merges a patch and persists it', async () => {
  const { result } = renderHook(() => useClipStates(JOB));
  act(() => result.current.updateClip(3, { publishedAt: 99 }));
  act(() => result.current.updateClip(3, { reframeMode: 'disabled' }));
  expect(result.current.getClipState(3)).toMatchObject({ publishedAt: 99, reframeMode: 'disabled' });
  expect(JSON.parse(localStorage.getItem(KEY))['3']).toMatchObject({ publishedAt: 99, reframeMode: 'disabled' });
});

test('garbage in storage falls back to empty state', async () => {
  localStorage.setItem(KEY, '{not json');
  const { result } = renderHook(() => useClipStates(JOB));
  expect(result.current.getClipState(0)).toEqual({});
});

test('no job id → empty state and nothing persisted', () => {
  const { result } = renderHook(() => useClipStates(null));
  expect(result.current.states).toEqual({});
});
