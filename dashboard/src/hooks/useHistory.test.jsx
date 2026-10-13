import { beforeEach, expect, test, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useHistory } from './useHistory';
import { listHistoryJobs } from '../api/client';
import { HISTORY_KEY } from '../lib/constants';

vi.mock('../api/client', () => ({ listHistoryJobs: vi.fn() }));

beforeEach(() => {
  localStorage.clear();
  vi.resetAllMocks();
});

test('History sync imports server-only jobs on a new browser and persists for offline access', async () => {
  const rows = [{ jobId: 'remote', status: 'complete', clipCount: 2,
    publishedCount: 1, title: 'Remote video', timestamp: 123 }];
  vi.mocked(listHistoryJobs).mockResolvedValue(rows);
  const { result } = renderHook(() => useHistory());
  expect(result.current.history).toEqual([]);
  await act(async () => { await result.current.refreshHistory(); });
  expect(result.current.history).toEqual(rows);
  expect(JSON.parse(localStorage.getItem(HISTORY_KEY))).toEqual(rows);
});

test('successful empty backend response clears stale cache; network failure preserves cache', async () => {
  const stale = { jobId: 'stale', status: 'complete', clipCount: 1 };
  localStorage.setItem(HISTORY_KEY, JSON.stringify([stale]));
  vi.mocked(listHistoryJobs).mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce([]);
  const { result } = renderHook(() => useHistory());
  await act(async () => { await expect(result.current.refreshHistory()).rejects.toThrow('offline'); });
  expect(result.current.history).toEqual([stale]);
  await act(async () => { await result.current.refreshHistory(); });
  expect(result.current.history).toEqual([]);
});

test('refresh updates publishedCount from persistent server records after a publish', async () => {
  const old = { jobId: 'same', status: 'complete', clipCount: 2,
    publishedCount: 0, sourceType: 'file' };
  localStorage.setItem(HISTORY_KEY, JSON.stringify([old]));
  vi.mocked(listHistoryJobs).mockResolvedValue([{ jobId: 'same', status: 'complete',
    clipCount: 2, publishedCount: 1 }]);
  const { result } = renderHook(() => useHistory());
  await act(async () => { await result.current.refreshHistory(); });
  expect(result.current.history[0].publishedCount).toBe(1);
  expect(result.current.history[0].sourceType).toBe('file');
});
