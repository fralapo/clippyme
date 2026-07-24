
import { useCallback, useEffect, useState } from 'react';
import { readStoredJson, removeStoredValue, subscribeStoredJson, writeStoredJson } from '../lib/storage';

const validStates = (value) => value && typeof value === 'object' && !Array.isArray(value);

function keyFor(jobId) { return `clippyme_clip_states_${jobId}`; }

function normalize(value) {
  if (!validStates(value)) return {};
  const next = {};
  for (const [key, state] of Object.entries(value)) {
    if (!/^\d+$/.test(key) || !state || typeof state !== 'object') continue;
    next[key] = state.processing ? { ...state, processing: false } : state;
  }
  return next;
}

export function useClipStates(jobId) {
  const [states, setStates] = useState({});

  useEffect(() => {
    if (!jobId) { setStates({}); return undefined; }
    const key = keyFor(jobId);
    setStates(normalize(readStoredJson(key, {}, { validate: validStates })));
    return subscribeStoredJson(key, (value) => setStates(normalize(value)), { validate: validStates });
  }, [jobId]);

  const updateClip = useCallback((index, patch) => {
    if (!Number.isInteger(Number(index)) || !patch || typeof patch !== 'object') return;
    setStates((previous) => {
      const next = { ...previous, [index]: { ...(previous[index] || {}), ...patch } };
      if (jobId) writeStoredJson(keyFor(jobId), next);
      return next;
    });
  }, [jobId]);

  const getClipState = useCallback((index) => states[index] || {}, [states]);
  const reset = useCallback(() => {
    setStates({});
    if (jobId) removeStoredValue(keyFor(jobId));
  }, [jobId]);

  return { states, updateClip, getClipState, reset };
}
