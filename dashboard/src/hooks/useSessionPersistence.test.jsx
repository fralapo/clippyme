
import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, test } from 'vitest';
import { SESSION_KEY } from '../lib/constants';
import { clearPersistedSession, loadPersistedSession, useSessionPersistence } from './useSessionPersistence';

beforeEach(() => localStorage.clear());

test('persists and restores an active URL job', () => {
  renderHook(() => useSessionPersistence({ status: 'processing', jobId: 'j', results: null, processingMedia: { type: 'url', payload: 'https://youtu.be/a' }, activeTab: 'create', preselections: { aspect: '9:16' } }));
  expect(loadPersistedSession()).toMatchObject({ jobId: 'j', status: 'processing', activeTab: 'create' });
});

test('idle clears the saved session', () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ jobId: 'j' }));
  renderHook(() => useSessionPersistence({ status: 'idle', jobId: null, results: null, processingMedia: null, activeTab: 'create' }));
  expect(localStorage.getItem(SESSION_KEY)).toBeNull();
});

test('explicit clear removes persisted state', () => {
  localStorage.setItem(SESSION_KEY, '{}');
  act(() => clearPersistedSession());
  expect(localStorage.getItem(SESSION_KEY)).toBeNull();
});
