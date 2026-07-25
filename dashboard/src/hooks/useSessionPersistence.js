
import { useEffect } from 'react';
import { SESSION_KEY } from '../lib/constants';
import { readStoredJson, removeStoredValue, writeStoredJson } from '../lib/storage';

const MAX_SESSION_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const VALID_STATUSES = new Set(['processing', 'complete', 'error']);

export function clearPersistedSession() {
  removeStoredValue(SESSION_KEY);
}

export function loadPersistedSession() {
  const value = readStoredJson(SESSION_KEY, null);
  if (!value || typeof value !== 'object' || !value.jobId || !VALID_STATUSES.has(value.status)) return null;
  if (!Number.isFinite(value.timestamp) || Date.now() - value.timestamp > MAX_SESSION_AGE_MS) {
    clearPersistedSession();
    return null;
  }
  if (value.status === 'complete' && !value.results) return null;
  return {
    jobId: value.jobId,
    status: value.status,
    results: value.results || null,
    processingMedia: value.processingMedia || null,
    activeTab: value.status === 'processing' || value.status === 'complete' ? 'create' : (value.activeTab || 'create'),
    preselections: value.preselections || null,
  };
}

export function useSessionPersistence({ status, jobId, results, processingMedia, activeTab, preselections }) {
  useEffect(() => {
    if (status === 'idle' || !jobId) {
      clearPersistedSession();
      return;
    }
    const safeMedia = processingMedia?.type === 'url' || processingMedia?.type === 'batch'
      ? processingMedia
      : processingMedia?.payload?.name
        ? { type: 'file', payload: { name: processingMedia.payload.name } }
        : null;
    const payload = {
      jobId,
      status,
      results: status === 'complete' ? results : (results ? { clips: results.clips || [], operations: results.operations } : null),
      processingMedia: safeMedia,
      activeTab,
      preselections: preselections || null,
      timestamp: Date.now(),
    };
    if (!writeStoredJson(SESSION_KEY, payload) && payload.results) {
      writeStoredJson(SESSION_KEY, { ...payload, results: { clips: payload.results.clips || [] } });
    }
  }, [jobId, status, results, activeTab, processingMedia, preselections]);
}
