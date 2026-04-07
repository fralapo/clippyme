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
    const interval = setInterval(async () => {
      try {
        const data = await pollJob(jobId);
        if (cancelled) return;

        if (data.result) onResult(data.result);

        if (data.status === 'completed') {
          onCompleted(data);
          clearInterval(interval);
        } else if (data.status === 'cancelled') {
          onCancelled();
          clearInterval(interval);
        } else if (data.status === 'failed') {
          const errorMsg =
            data.error ||
            (data.logs && data.logs.length > 0 ? data.logs[data.logs.length - 1] : 'Process failed');
          onFailed(errorMsg);
          clearInterval(interval);
        } else if (data.logs) {
          onProgress(data.logs, detectPipelineStep(data.logs));
        }
      } catch (e) {
        console.error('Polling error', e);
      }
    }, 2000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive, jobId]);
}
