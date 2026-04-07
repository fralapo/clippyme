import { useCallback, useEffect, useState } from 'react';

/**
 * Per-clip state: { disabled: boolean, deleted: boolean, publishedAt: number }
 * Keyed by clip index. Persisted in localStorage under `clippyme_clip_states_{jobId}`
 * so user choices (published flags, disabled clips, deleted clips) survive
 * page reloads without a backend round-trip.
 */
export function useClipStates(jobId) {
    const [states, setStates] = useState({});

    useEffect(() => {
        if (!jobId) {
            setStates({});
            return;
        }
        try {
            const raw = localStorage.getItem(`clippyme_clip_states_${jobId}`);
            setStates(raw ? JSON.parse(raw) : {});
        } catch {
            setStates({});
        }
    }, [jobId]);

    const persist = useCallback(
        (next) => {
            setStates(next);
            if (jobId) {
                try {
                    localStorage.setItem(`clippyme_clip_states_${jobId}`, JSON.stringify(next));
                } catch {
                    /* quota exceeded, ignore */
                }
            }
        },
        [jobId],
    );

    const updateClip = useCallback(
        (index, patch) => {
            setStates((prev) => {
                const current = prev[index] || {};
                const next = { ...prev, [index]: { ...current, ...patch } };
                if (jobId) {
                    try {
                        localStorage.setItem(`clippyme_clip_states_${jobId}`, JSON.stringify(next));
                    } catch {
                        /* ignore */
                    }
                }
                return next;
            });
        },
        [jobId],
    );

    const getClipState = useCallback(
        (index) => states[index] || {},
        [states],
    );

    const reset = useCallback(() => persist({}), [persist]);

    return { states, updateClip, getClipState, reset };
}
