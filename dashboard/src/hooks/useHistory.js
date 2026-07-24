
import { useCallback, useEffect, useState } from 'react';
import { HISTORY_KEY, HISTORY_MAX_ITEMS } from '../lib/constants';
import { readStoredJson, removeStoredValue, subscribeStoredJson, writeStoredJson } from '../lib/storage';

const validHistory = (value) => Array.isArray(value);
const normalize = (value) => (Array.isArray(value) ? value.filter((entry) => entry && typeof entry.jobId === 'string') : []);

export function useHistory() {
  const [history, setHistoryState] = useState(() => normalize(readStoredJson(HISTORY_KEY, [], { validate: validHistory })));

  useEffect(() => subscribeStoredJson(HISTORY_KEY, (value) => setHistoryState(normalize(value)), { validate: validHistory }), []);

  const replaceHistory = useCallback((next) => {
    const value = normalize(typeof next === 'function' ? next(history) : next).slice(0, HISTORY_MAX_ITEMS);
    setHistoryState(value);
    writeStoredJson(HISTORY_KEY, value);
  }, [history]);

  const saveToHistory = useCallback((entry) => {
    if (!entry?.jobId) return;
    setHistoryState((previous) => {
      const updated = [entry, ...previous.filter((item) => item.jobId !== entry.jobId)].slice(0, HISTORY_MAX_ITEMS);
      writeStoredJson(HISTORY_KEY, updated);
      return updated;
    });
  }, []);

  const purgeJobStorage = useCallback((jobId) => {
    removeStoredValue(`clippyme_clip_states_${jobId}`);
    removeStoredValue(`clippyme_preselections_job_${jobId}`);
  }, []);

  const deleteFromHistory = useCallback((jobId) => {
    setHistoryState((previous) => {
      const updated = previous.filter((entry) => entry.jobId !== jobId);
      writeStoredJson(HISTORY_KEY, updated);
      return updated;
    });
    purgeJobStorage(jobId);
  }, [purgeJobStorage]);

  const clearHistory = useCallback(() => {
    setHistoryState((previous) => {
      previous.forEach((entry) => entry?.jobId && purgeJobStorage(entry.jobId));
      return [];
    });
    removeStoredValue(HISTORY_KEY);
  }, [purgeJobStorage]);

  return { history, setHistory: replaceHistory, saveToHistory, deleteFromHistory, clearHistory };
}
