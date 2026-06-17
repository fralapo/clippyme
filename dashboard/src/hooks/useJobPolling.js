import { useEffect } from 'react';
import { pollJob } from '../lib/api';
import { detectPipelineStep } from '../lib/pipelineStep';

/**
 * Polls the backend for job status every 2 seconds while the job is active,
 * and invokes the provided callbacks on state transitions.
 *
 * @param {{
 *   jobId: string | null,
 *   isActive: boolean,
 *   onResult: (result: object) => void,
 *   onCompleted: (data: object) => void,
 *   onCancelled: () => void,
 *   onFailed: (errorMsg: string) => void,
 *   onProgress: (logs: string[], step: string | null) => void,
 * }} params
 */
export function useJobPolling({
  jobId,
  isActive,
  onResult,
  onCompleted,
  onCancelled,
  onFailed,
  onProgress,
}) {
  useEffect(() => {
    if (!isActive || !jobId) return undefined;

    let cancelled = false;
    let timer = null;
    // Stop hammering a dead backend: after this many consecutive poll
    // failures we surface the error instead of spinning on "processing"
    // forever (previously errors were swallowed with console.error only).
    const MAX_CONSECUTIVE_ERRORS = 5;
    const BASE_DELAY = 2000;
    let consecutiveErrors = 0;

    const schedule = (delay) => {
      if (cancelled) return;
      timer = setTimeout(tick, delay);
    };

    const tick = async () => {
      try {
        const data = await pollJob(jobId);
        if (cancelled) return;
        consecutiveErrors = 0;

        if (data.result) onResult(data.result);

        if (data.status === 'completed') {
          onCompleted(data);
          return; // stop polling
        } else if (data.status === 'cancelled') {
          onCancelled();
          return;
        } else if (data.status === 'failed') {
          const errorMsg =
            data.error ||
            (data.logs && data.logs.length > 0 ? data.logs[data.logs.length - 1] : 'Process failed');
          onFailed(errorMsg);
          return;
        } else if (data.logs) {
          onProgress(data.logs, detectPipelineStep(data.logs));
        }
        schedule(BASE_DELAY);
      } catch (e) {
        if (cancelled) return;
        consecutiveErrors += 1;
        console.error(`Polling error (${consecutiveErrors}/${MAX_CONSECUTIVE_ERRORS})`, e);
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          onFailed('Lost connection to the server. Please refresh the page.');
          return;
        }
        // Exponential backoff with a ceiling so transient blips recover
        // without stampeding the backend.
        schedule(Math.min(BASE_DELAY * 2 ** consecutiveErrors, 30000));
      }
    };

    schedule(BASE_DELAY);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive, jobId]);
}
