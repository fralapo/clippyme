import { beforeEach, expect, test } from 'vitest';
import { getCredentialMode, readBrowserCredential, writeBrowserCredential, setCredentialMode } from './credentialStorage';

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

test('defaults to existing local persistence and moves both credential types into session storage', () => {
  expect(getCredentialMode()).toBe('local');
  writeBrowserCredential('gemini_key', 'gemini-test');
  writeBrowserCredential('clippyme_api_token', 'shared-token');
  expect(localStorage.getItem('gemini_key')).toBe('gemini-test');
  expect(setCredentialMode('session')).toBe('session');
  expect(localStorage.getItem('gemini_key')).toBeNull();
  expect(localStorage.getItem('clippyme_api_token')).toBeNull();
  expect(sessionStorage.getItem('gemini_key')).toBe('gemini-test');
  expect(readBrowserCredential('clippyme_api_token')).toBe('shared-token');
});

test('clearing a session-only key cannot resurrect a persistent copy', () => {
  setCredentialMode('session');
  writeBrowserCredential('gemini_key', 'secret');
  writeBrowserCredential('gemini_key', '');
  expect(sessionStorage.getItem('gemini_key')).toBeNull();
  expect(localStorage.getItem('gemini_key')).toBeNull();
});

test('switching back restores previous opt-in persistent behavior', () => {
  setCredentialMode('session');
  writeBrowserCredential('clippyme_api_token', 'token');
  setCredentialMode('local');
  expect(sessionStorage.getItem('clippyme_api_token')).toBeNull();
  expect(localStorage.getItem('clippyme_api_token')).toBe('token');
});

test('cannot move browser secrets using an unsupported retention mode', () => {
  expect(() => setCredentialMode('unknown')).toThrow();
});
