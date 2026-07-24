
import { beforeEach, expect, test, vi } from 'vitest';
import { readStoredJson, removeStoredValue, writeStoredJson } from './storage';

beforeEach(() => localStorage.clear());

test('round-trips JSON and validates the shape', () => {
  expect(writeStoredJson('x', { ok: true })).toBe(true);
  expect(readStoredJson('x', null, { validate: (value) => value.ok === true })).toEqual({ ok: true });
  expect(readStoredJson('x', 'fallback', { validate: () => false })).toBe('fallback');
});

test('corrupt JSON and storage failures degrade to fallback', () => {
  localStorage.setItem('x', '{bad');
  expect(readStoredJson('x', [])).toEqual([]);
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
  expect(writeStoredJson('y', {})).toBe(false);
  spy.mockRestore();
});

test('removes a stored value', () => {
  localStorage.setItem('x', '1');
  expect(removeStoredValue('x')).toBe(true);
  expect(localStorage.getItem('x')).toBeNull();
});
