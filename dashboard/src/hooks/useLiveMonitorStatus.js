
import { useCallback, useEffect, useRef, useState } from 'react';
import { getLiveMonitorStatus } from '../redesign/realApi';

export function useLiveMonitorStatus(intervalMs = 5000) {
  const [monitors, setMonitors] = useState([]);
  const [meta, setMeta] = useState({ loading: true, error: null, updatedAt: null });
  const timerRef = useRef(null);
  const controllerRef = useRef(null);
  const mountedRef = useRef(false);

  const refresh = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const data = await getLiveMonitorStatus({ signal: controller.signal });
      if (!mountedRef.current) return;
      setMonitors(Array.isArray(data?.monitors) ? data.monitors : []);
      setMeta({ loading: false, error: null, updatedAt: Date.now() });
    } catch (error) {
      if (!mountedRef.current || error?.name === 'AbortError') return;
      setMeta((current) => ({ ...current, loading: false, error }));
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    let disposed = false;
    const tick = async () => {
      await refresh();
      if (!disposed) timerRef.current = setTimeout(tick, typeof document !== 'undefined' && document.hidden ? intervalMs * 3 : intervalMs);
    };
    tick();
    return () => {
      disposed = true;
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      controllerRef.current?.abort();
    };
  }, [intervalMs, refresh]);

  return [monitors, refresh, meta];
}
