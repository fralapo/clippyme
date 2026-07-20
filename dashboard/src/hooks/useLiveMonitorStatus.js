// Polls GET /api/live-monitor/status every `intervalMs` while mounted.
// ponytail: polls continuously rather than gating on "non-idle" — the view
// only mounts while the Live Monitor tab is open, and idle still needs to be
// observable (e.g. after a reload) before showing the start form; add a
// backoff-when-idle if the poll ever becomes a real cost concern.
import { useEffect, useRef, useState } from 'react';
import { getLiveMonitorStatus } from '../redesign/realApi';

export function useLiveMonitorStatus(intervalMs = 5000) {
  const [status, setStatus] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const s = await getLiveMonitorStatus();
        if (!cancelled) setStatus(s);
      } catch {
        // Backend unreachable — keep the last known status rather than
        // flashing to an error state on a transient blip.
      }
    };
    poll();
    timerRef.current = setInterval(poll, intervalMs);
    return () => { cancelled = true; clearInterval(timerRef.current); };
  }, [intervalMs]);

  return status;
}
