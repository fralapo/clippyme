
import { expect, test } from 'vitest';
import { validateCreateOptions } from './createValidation';

test('accepts official HTTPS video sources', () => {
  for (const url of ['https://youtu.be/abc', 'https://www.youtube.com/watch?v=abc', 'https://twitch.tv/user', 'https://kick.com/user']) {
    expect(validateCreateOptions({ mode: 'single', source: 'url', url }).valid).toBe(true);
  }
});

test('rejects unsupported hosts, credentials and non-HTTPS URLs', () => {
  expect(validateCreateOptions({ mode: 'single', source: 'url', url: 'https://vimeo.com/1' }).valid).toBe(false);
  expect(validateCreateOptions({ mode: 'single', source: 'url', url: 'http://youtube.com/watch?v=1' }).valid).toBe(false);
  expect(validateCreateOptions({ mode: 'single', source: 'url', url: 'https://u:p@youtube.com/watch?v=1' }).valid).toBe(false);
});

test('deduplicates batch URLs and enforces the 20 source limit', () => {
  const duplicate = validateCreateOptions({ mode: 'batch', batch: 'https://youtu.be/a\nhttps://youtu.be/a', batchFiles: [] });
  expect(duplicate.valid).toBe(true);
  expect(duplicate.sourceCount).toBe(1);
  const tooMany = validateCreateOptions({ mode: 'batch', batch: Array.from({ length: 21 }, (_, i) => `https://youtu.be/${i}`).join('\n'), batchFiles: [] });
  expect(tooMany.firstError).toMatch(/at most 20/);
});

test('validates uploaded file size', () => {
  expect(validateCreateOptions({ mode: 'single', source: 'file', file: { name: 'x.mp4', type: 'video/mp4', size: 10 } }).valid).toBe(true);
  expect(validateCreateOptions({ mode: 'single', source: 'file', file: { name: 'x.mp4', type: 'video/mp4', size: 17 * 1024 ** 3 } }).valid).toBe(false);
});
