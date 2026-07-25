
import { act, render } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { LazyVideo } from './LazyVideo';

afterEach(() => { delete globalThis.IntersectionObserver; });

test('defers the src until the video approaches the viewport', () => {
  let callback;
  globalThis.IntersectionObserver = vi.fn(function IntersectionObserverMock(cb) { callback = cb; return { observe: vi.fn(), disconnect: vi.fn() }; });
  const { container } = render(<LazyVideo src="/clip.mp4" />);
  const video = container.querySelector('video');
  expect(video.getAttribute('src')).toBeNull();
  act(() => callback([{ isIntersecting: true }]));
  expect(video.getAttribute('src')).toBe('/clip.mp4');
});

test('loads immediately when IntersectionObserver is unavailable', () => {
  const { container } = render(<LazyVideo src="/clip.mp4" />);
  expect(container.querySelector('video').getAttribute('src')).toBe('/clip.mp4');
});
