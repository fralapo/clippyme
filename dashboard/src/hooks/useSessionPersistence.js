import { useEffect } from 'react';
import { SESSION_KEY } from '../lib/constants';

/**
 * Persists the current job/session snapshot to localStorage while the job is
 * active, and clears it when the app returns to idle.
 *
 * @param {{
 *   status: string,
 *   jobId: string | null,
 *   results: unknown,
 *   processingMedia: { type?: string } | null,
 *   activeTab: string,
 * }} params
 */
export function useSessionPersistence({ status, jobId, results, processingMedia, activeTab }) {
  // Clear any stale session on mount — History tab replaces recovery.
  useEffect(() => {
    localStorage.removeItem(SESSION_KEY);
  }, []);

  useEffect(() => {
    if (status === 'idle') {
      localStorage.removeItem(SESSION_KEY);
      return;
    }
    try {
      const sessionData = {
        jobId,
        status,
        results,
        processingMedia: processingMedia?.type === 'url' ? processingMedia : null,
        activeTab,
        timestamp: Date.now(),
      };
      localStorage.setItem(SESSION_KEY, JSON.stringify(sessionData));
    } catch (e) {
      console.debug('Skipping session persistence', e);
    }
  }, [jobId, status, results, activeTab, processingMedia]);
}
