// Polls GET /api/live-monitor/status every `intervalMs` while mounted.
// Backend now runs multiple concurrent monitors, so this returns the full
// `monitors` list rather than one status object.
// ponytail: polls continuously rather than gating on "any running" — the view
// only mounts while the Live Monitor tab is open, and an all-idle list still
// needs to be observable (e.g. after a reload); add a backoff-when-idle if
// the poll ever becomes a real cost concern.
import { useEffect, useRef, useState } from 'react';
import { getLiveMonitorStatus } from '../redesign/realApi';

export function useLiveMonitorStatus(intervalMs = 5000) {
  const [monitors, setMonitors] = useState([]);
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const s = await getLiveMonitorStatus();
        if (!cancelled) setMonitors(Array.isArray(s?.monitors) ? s.monitors : []);
      } catch {
        // Backend unreachable — keep the last known list rather than
        // flashing to an error state on a transient blip.
      }
    };
    poll();
    timerRef.current = setInterval(poll, intervalMs);
    return () => { cancelled = true; clearInterval(timerRef.current); };
  }, [intervalMs]);

  return monitors;
}
