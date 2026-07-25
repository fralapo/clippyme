
import { useEffect, useRef } from 'react';
import { pollJob } from '../lib/api';
import { detectPipelineStep } from '../lib/pipelineStep';

const BASE_DELAY = 2000;
const MAX_DELAY = 30000;

export function useJobPolling({
  jobId,
  isActive,
  onResult,
  onCompleted,
  onStopped,
  onCancelled,
  onFailed,
  onProgress,
  onPaused,
  onConnectionChange,
}) {
  const callbacks = useRef({});
  callbacks.current = { onResult, onCompleted, onStopped, onCancelled, onFailed, onProgress, onPaused, onConnectionChange };

  useEffect(() => {
    if (!isActive || !jobId) return undefined;

    let disposed = false;
    let timer = null;
    let controller = null;
    let consecutiveErrors = 0;
    let disconnectedAnnounced = false;

    const schedule = (delay) => {
      if (!disposed) timer = setTimeout(tick, delay);
    };

    const terminal = (callback, data) => {
      disposed = true;
      callback?.(data);
    };

    const tick = async () => {
      controller = new AbortController();
      try {
        const data = await pollJob(jobId, { signal: controller.signal });
        if (disposed) return;
        consecutiveErrors = 0;
        if (disconnectedAnnounced) callbacks.current.onConnectionChange?.(true);
        disconnectedAnnounced = false;

        if (data.result) callbacks.current.onResult?.(data.result);
        if (data.status === 'completed') return terminal(callbacks.current.onCompleted, data);
        if (data.status === 'stopped') return terminal(callbacks.current.onStopped || callbacks.current.onCompleted, data);
        if (data.status === 'cancelled') return terminal(callbacks.current.onCancelled);
        if (data.status === 'failed') {
          const errorMsg = data.error || data.logs?.at?.(-1) || 'Process failed';
          return terminal(callbacks.current.onFailed, errorMsg);
        }
        if (data.status === 'paused') callbacks.current.onPaused?.(data);
        if (Array.isArray(data.logs)) callbacks.current.onProgress?.(data.logs, data.operations?.stage || detectPipelineStep(data.logs));
        schedule(typeof document !== 'undefined' && document.hidden ? 10000 : BASE_DELAY);
      } catch (error) {
        if (disposed || error?.name === 'AbortError') return;
        consecutiveErrors += 1;
        if (consecutiveErrors >= 3 && !disconnectedAnnounced) {
          disconnectedAnnounced = true;
          callbacks.current.onConnectionChange?.(false, error);
        }
        // A network outage is not a pipeline failure. Keep the durable backend
        // job alive and retry with a ceiling instead of changing its status.
        schedule(Math.min(BASE_DELAY * 2 ** consecutiveErrors, MAX_DELAY));
      }
    };

    tick();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      controller?.abort();
    };
  }, [isActive, jobId]);
}
