import { useCallback, useEffect, useState } from 'react';

/**
 * Per-clip state: { selected: boolean, deleted: boolean, publishedAt: number,
 *                    reframeMode: 'auto' | 'object' | 'disabled', processing: boolean,
 *                    previewUrl, previewBust, reframeBust,
 *                    toggles: {...}, hookParams: {...}, subtitleParams: {...} }
 * `processing` is transient (background reprocess in flight) and cleared on load.
 * Keyed by clip index. Persisted in localStorage under `clippyme_clip_states_{jobId}`
 * so user choices (selection, published flags, deleted clips) survive page
 * reloads without a backend round-trip.
 *
 * NOTE: 'disabled' was the legacy field for "exclude from batch publish".
 * Replaced by 'selected' (inverse meaning) in v2 of the shape — the new
 * workflow is opt-in selection ("tick 3 of 12") instead of opt-out muting
 * ("disable 9 of 12"). Legacy records without `selected` are treated as
 * selected=true so nothing disappears on upgrade.
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
            const parsed = raw ? JSON.parse(raw) : {};
            // `processing` is a transient background-reprocess flag. A reload mid-
            // render would otherwise persist it and leave a card stuck on the
            // "Reprocessing…" overlay with its Edit button disabled forever —
            // clear it on load so the UI never wedges.
            for (const k of Object.keys(parsed)) {
                if (parsed[k] && parsed[k].processing) parsed[k] = { ...parsed[k], processing: false };
            }
            setStates(parsed);
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
