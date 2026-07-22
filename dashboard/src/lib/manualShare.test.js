// shareClip — capability-gated Web Share, never a silent fallback pretending
// to be success. Pins: secure-context + navigator.share + canShare({files})
// gate, File(type=video/mp4) construction from a same-origin fetch, the
// AbortError→cancelled contract (no download/complete side effect), and
// fallback on any incompatibility/failure.
import { test, expect, vi, beforeEach, afterEach } from 'vitest';
import { shareClip } from './manualShare.js';

function setSecureContext(value) {
  Object.defineProperty(window, 'isSecureContext', { value, configurable: true });
}

function setNavigatorShare(share, canShare) {
  Object.defineProperty(navigator, 'share', { value: share, configurable: true });
  Object.defineProperty(navigator, 'canShare', { value: canShare, configurable: true });
}

const ORIGINAL_FETCH = globalThis.fetch;

beforeEach(() => {
  setSecureContext(true);
  setNavigatorShare(vi.fn(async () => {}), vi.fn(() => true));
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
  delete navigator.share;
  delete navigator.canShare;
});

test('insecure context returns fallback without fetching or sharing', async () => {
  setSecureContext(false);
  const fetchSpy = vi.fn();
  globalThis.fetch = fetchSpy;
  const result = await shareClip({ videoUrl: '/api/x/video', filename: 'clip.mp4', caption: 'hi' });
  expect(result).toEqual({ fallback: true });
  expect(fetchSpy).not.toHaveBeenCalled();
});

test('missing navigator.share returns fallback', async () => {
  delete navigator.share;
  delete navigator.canShare;
  const result = await shareClip({ videoUrl: '/api/x/video', filename: 'clip.mp4', caption: 'hi' });
  expect(result).toEqual({ fallback: true });
});

test('canShare({files}) returning false returns fallback', async () => {
  setNavigatorShare(vi.fn(async () => {}), vi.fn(() => false));
  globalThis.fetch = vi.fn(async () => new Response(new Blob(['data']), { status: 200 }));
  const result = await shareClip({ videoUrl: '/api/x/video', filename: 'clip.mp4', caption: 'hi' });
  expect(result).toEqual({ fallback: true });
});

test('builds a video/mp4 File from the fetched same-origin blob and shares it', async () => {
  const shareMock = vi.fn(async () => {});
  const canShareMock = vi.fn(() => true);
  setNavigatorShare(shareMock, canShareMock);
  globalThis.fetch = vi.fn(async () => new Response(new Blob(['bytes']), { status: 200 }));
  const result = await shareClip({ videoUrl: '/api/manual-publish/abc/video', filename: 'my-clip.mp4', caption: 'Check this out' });
  expect(result).toEqual({ shared: true });
  expect(globalThis.fetch).toHaveBeenCalledWith('/api/manual-publish/abc/video');
  const sharedFile = canShareMock.mock.calls[0][0].files[0];
  expect(sharedFile).toBeInstanceOf(File);
  expect(sharedFile.type).toBe('video/mp4');
  expect(sharedFile.name).toBe('my-clip.mp4');
  expect(shareMock).toHaveBeenCalledWith(expect.objectContaining({ files: [sharedFile] }));
});

test('AbortError from navigator.share returns cancelled and never falls back or downloads', async () => {
  const abortErr = Object.assign(new Error('The user aborted a request.'), { name: 'AbortError' });
  setNavigatorShare(vi.fn(async () => { throw abortErr; }), vi.fn(() => true));
  globalThis.fetch = vi.fn(async () => new Response(new Blob(['bytes']), { status: 200 }));
  const result = await shareClip({ videoUrl: '/api/x/video', filename: 'clip.mp4', caption: 'hi' });
  expect(result).toEqual({ cancelled: true });
});

test('a non-abort share failure returns fallback', async () => {
  setNavigatorShare(vi.fn(async () => { throw new Error('boom'); }), vi.fn(() => true));
  globalThis.fetch = vi.fn(async () => new Response(new Blob(['bytes']), { status: 200 }));
  const result = await shareClip({ videoUrl: '/api/x/video', filename: 'clip.mp4', caption: 'hi' });
  expect(result).toEqual({ fallback: true });
});

test('a failed fetch (non-ok response) returns fallback without calling share', async () => {
  const shareMock = vi.fn(async () => {});
  setNavigatorShare(shareMock, vi.fn(() => true));
  globalThis.fetch = vi.fn(async () => new Response(null, { status: 404 }));
  const result = await shareClip({ videoUrl: '/api/x/video', filename: 'clip.mp4', caption: 'hi' });
  expect(result).toEqual({ fallback: true });
  expect(shareMock).not.toHaveBeenCalled();
});

test('a network error during fetch returns fallback without calling share', async () => {
  const shareMock = vi.fn(async () => {});
  setNavigatorShare(shareMock, vi.fn(() => true));
  globalThis.fetch = vi.fn(async () => { throw new Error('network down'); });
  const result = await shareClip({ videoUrl: '/api/x/video', filename: 'clip.mp4', caption: 'hi' });
  expect(result).toEqual({ fallback: true });
  expect(shareMock).not.toHaveBeenCalled();
});
