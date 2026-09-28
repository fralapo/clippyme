
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

// Same shape api.throwFromResponse gives an HTTP error.
const httpError = (status, message = `HTTP ${status}`) => Object.assign(new Error(message), {
  status, retryable: status === 408 || status === 429 || status >= 500,
});

test.each([
  [404, 'Job not found'],
  [401, 'Valid API token required.'],
  [400, 'Invalid job ID'],
])('a permanent HTTP %i stops polling instead of retrying forever', async (status, message) => {
  pollJob.mockRejectedValue(httpError(status, message));
  const { callbacks } = mount();
  await act(async () => {});
  expect(callbacks.onFailed).toHaveBeenCalledTimes(1);
  expect(callbacks.onFailed).toHaveBeenCalledWith(message);
  expect(vi.getTimerCount()).toBe(0);
  await act(() => vi.advanceTimersByTimeAsync(120_000));
  expect(pollJob).toHaveBeenCalledTimes(1);
  expect(callbacks.onFailed).toHaveBeenCalledTimes(1);
});

test.each([
  ['a 500', () => httpError(500)],
  ['a 503', () => httpError(503)],
  ['a 429', () => httpError(429)],
  ['a network error', () => new TypeError('Failed to fetch')],
])('%s is retried with backoff and never fails the job', async (_label, makeError) => {
  pollJob.mockRejectedValue(makeError());
  const { callbacks, unmount } = mount();
  await act(async () => {});
  expect(pollJob).toHaveBeenCalledTimes(1);
  await act(() => vi.advanceTimersByTimeAsync(4_000)); // first backoff: 2s * 2
  expect(pollJob).toHaveBeenCalledTimes(2);
  expect(callbacks.onFailed).not.toHaveBeenCalled();
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

test('polling resumes normally after a transient error and ends on completion', async () => {
  pollJob
    .mockRejectedValueOnce(httpError(502))
    .mockResolvedValueOnce({ status: 'processing', logs: [] })
    .mockResolvedValueOnce({ status: 'completed', result: { clips: [] } });
  const { callbacks } = mount();
  await act(() => vi.advanceTimersByTimeAsync(10_000));
  expect(pollJob).toHaveBeenCalledTimes(3);
  expect(callbacks.onCompleted).toHaveBeenCalledTimes(1);
  expect(callbacks.onFailed).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

test('a permanent error arriving after unmount is ignored', async () => {
  let reject;
  pollJob.mockImplementation(() => new Promise((_res, rej) => { reject = rej; }));
  const { callbacks, unmount } = mount();
  await act(async () => {});
  unmount();
  await act(async () => reject(httpError(404)));
  expect(callbacks.onFailed).not.toHaveBeenCalled();
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
