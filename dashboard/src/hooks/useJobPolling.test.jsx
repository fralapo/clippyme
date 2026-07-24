
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../lib/api', () => ({ pollJob: vi.fn() }));
import { pollJob } from '../lib/api';
import { useJobPolling } from './useJobPolling';

beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); });
afterEach(() => vi.useRealTimers());

function mount(overrides = {}) {
  const callbacks = {
    onResult: vi.fn(), onCompleted: vi.fn(), onStopped: vi.fn(), onCancelled: vi.fn(),
    onFailed: vi.fn(), onProgress: vi.fn(), onConnectionChange: vi.fn(), ...overrides,
  };
  const hook = renderHook(() => useJobPolling({ jobId: 'j', isActive: true, ...callbacks }));
  return { ...hook, callbacks };
}

test('polls immediately and completes once', async () => {
  pollJob.mockResolvedValue({ status: 'completed', result: { clips: [] } });
  const { callbacks } = mount();
  await act(async () => {});
  expect(pollJob).toHaveBeenCalledTimes(1);
  expect(callbacks.onCompleted).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

test('network errors do not falsely mark a durable job as failed', async () => {
  pollJob.mockRejectedValue(new Error('offline'));
  const { callbacks, unmount } = mount();
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(callbacks.onFailed).not.toHaveBeenCalled();
  expect(callbacks.onConnectionChange).toHaveBeenCalledWith(false, expect.any(Error));
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

test('aborts an in-flight request on unmount', async () => {
  let signal;
  pollJob.mockImplementation((_id, options) => { signal = options.signal; return new Promise(() => {}); });
  const { unmount } = mount();
  await act(async () => {});
  expect(signal.aborted).toBe(false);
  unmount();
  expect(signal.aborted).toBe(true);
});
