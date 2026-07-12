import { useEffect, useRef } from 'react';
import { submitProcessJob, submitBatchJob } from '../lib/api';
import { getApiUrl } from '../config';
import { apiFetch } from '../lib/apiToken';
import { tasteInstructionSuffix } from '../lib/taste';

// Append the cross-job taste hint (#8) to a job's AI instructions so Gemini
// biases viral detection toward what the user actually kept in past jobs.
function withTaste(data) {
  const hint = tasteInstructionSuffix();
  if (!hint) return data;
  const base = (data.instructions || '').trim();
  return { ...data, instructions: base ? `${base} ${hint}` : hint };
}

/**
 * Custom hook factory that returns process/batch submission handlers.
 * Receives the state setters from App.jsx so handlers stay declarative.
 */
export function useJobSubmission({
  apiKey,
  setShowKeyModal,
  setStatus,
  setLogs,
  setResults,
  setProcessingMedia,
  setPreselections,
  setJobId,
  // Optional: called when a batch run hits every job's terminal
  // state. Lets the parent auto-navigate (e.g. to History) without
  // coupling this hook to a tab state machine.
  onBatchFinished,
}) {
  // Hold the batch poll timer so it can be cleared on unmount (the loop is
  // created inside an async handler, not a useEffect, so without this it
  // leaks and keeps calling fetch/setState on an unmounted component).
  const pollRef = useRef(null);
  useEffect(
    () => () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    },
    [],
  );

  const handleProcess = async (data) => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    setStatus('processing');
    setLogs(['Initializing engine...']);
    setResults(null);
    setProcessingMedia(data);
    if (data.preselections) setPreselections(data.preselections);

    try {
      const resData = await submitProcessJob(withTaste(data), apiKey);
      setJobId(resData.job_id);
    } catch (e) {
      setStatus('error');
      setLogs((l) => [...l, `Error: ${e.message}`]);
    }
  };

  const handleBatchProcess = async (data) => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    setStatus('processing');
    setLogs(['Launching batch processing...']);
    setResults(null);
    if (data.preselections) setPreselections(data.preselections);

    const urls = data.urls || [];
    const files = data.files || [];

    try {
      const allJobIds = [];

      // 1. Submit URLs as a single backend batch (if any)
      if (urls.length > 0) {
        const batchRes = await submitBatchJob(withTaste({ ...data, urls }), apiKey);
        allJobIds.push(...batchRes.jobs.map((j) => j.job_id));
        setLogs((l) => [...l, `Submitted ${batchRes.total} URL job(s)`]);
      }

      // 2. Submit each file individually to /api/process
      for (const f of files) {
        try {
          const fileRes = await submitProcessJob(
            withTaste({
              type: 'file',
              payload: f,
              instructions: data.instructions,
              preselections: data.preselections,
            }),
            apiKey,
          );
          allJobIds.push(fileRes.job_id);
          setLogs((l) => [...l, `Submitted file: ${f.name}`]);
        } catch (e) {
          setLogs((l) => [...l, `Failed to submit ${f.name}: ${e.message}`]);
        }
      }

      if (allJobIds.length === 0) {
        setStatus('error');
        setLogs((l) => [...l, 'No jobs were submitted.']);
        return;
      }

      // Seed processingMedia so the Create tab's ProcessingView shows a
      // batch-aware header instead of the generic "no media" placeholder.
      // We stuff the first URL (or filename) as the label and attach the
      // full job list so the ProcessingView can render a per-job progress
      // strip if it wants to in the future.
      try {
        setProcessingMedia({
          type: 'batch',
          payload: urls[0] || files[0]?.name || `${allJobIds.length} jobs`,
          batch: {
            jobIds: allJobIds,
            total: allJobIds.length,
            urls: urls.length,
            files: files.length,
          },
        });
      } catch {
        /* ignore — processingMedia is cosmetic for the live view */
      }

      // 3. Unified polling: track each job_id individually until all done.
      //    We also stream the tail of each job's log buffer so the Live Logs
      //    panel actually advances while the backend is busy.
      const total = allJobIds.length;
      const finished = new Set();
      const lastLogs = new Map(); // jid -> last `logs` array from status
      let succeeded = 0;
      let failed = 0;

      // Short label per job so lines are identifiable in the merged stream.
      const labels = new Map();
      allJobIds.forEach((jid, i) => labels.set(jid, `[job ${i + 1}]`));

      const TAIL = 6; // how many recent lines per job to show in the panel

      // Resilient poll loop, mirroring useJobPolling: a recursive setTimeout
      // (the next tick is armed only after this one finishes, so slow
      // responses can never overlap into a fetch storm the way the old
      // setInterval could with 20 sequential awaits per tick), exponential
      // backoff while the backend errors, and termination with a visible
      // message after MAX_POLL_ERRORS consecutive dead rounds instead of
      // silently swallowing errors forever.
      const POLL_MS = 2000;
      const MAX_POLL_ERRORS = 5;
      let consecutiveErrors = 0;

      // Clear any poll loop still running from a previous batch submission
      // before starting a new one (rapid re-submit would otherwise stack them).
      if (pollRef.current) clearTimeout(pollRef.current);

      const tick = async () => {
        let roundHadSuccess = false;
        for (const jid of allJobIds) {
          if (finished.has(jid)) continue; // terminal logs are already cached
          try {
            const r = await apiFetch(getApiUrl(`/api/status/${jid}`));
            if (!r.ok) continue;
            roundHadSuccess = true;
            const s = await r.json();
            if (Array.isArray(s.logs)) lastLogs.set(jid, s.logs);
            // 'stopped' is terminal-with-clips (graceful stop keeps finished
            // clips), so count it as a success. Without it the batch never
            // reaches all-terminal and the poll loop hangs forever.
            if (s.status === 'completed' || s.status === 'stopped') {
              finished.add(jid);
              succeeded += 1;
            } else if (s.status === 'failed' || s.status === 'cancelled') {
              finished.add(jid);
              failed += 1;
            }
          } catch {
            /* counted per-round via roundHadSuccess */
          }
        }

        // Build a merged view: progress header + per-job log tails.
        const header = `Batch progress: ${succeeded + failed}/${total} done (${succeeded} ok, ${failed} failed)`;
        const merged = [header, ''];
        for (const jid of allJobIds) {
          const label = labels.get(jid);
          const jlogs = lastLogs.get(jid) || [];
          const done = finished.has(jid);
          const tag = done ? '✓' : '●';
          merged.push(`${tag} ${label}`);
          if (jlogs.length === 0) {
            merged.push('   (waiting for output…)');
          } else {
            for (const line of jlogs.slice(-TAIL)) {
              merged.push(`   ${line}`);
            }
          }
          merged.push('');
        }
        setLogs(merged);

        if (finished.size >= total) {
          pollRef.current = null;
          setStatus('complete');
          setLogs((l) => [
            ...l,
            `Batch complete! ${succeeded} succeeded, ${failed} failed.`,
          ]);
          // Notify the parent so it can route the user to the History
          // tab (where the per-job viewer lives). The parent receives
          // the full job id list + counts so it can show a toast or
          // pre-seed the history filter if it wants to.
          if (typeof onBatchFinished === 'function') {
            try {
              onBatchFinished({
                jobIds: allJobIds,
                succeeded,
                failed,
                total,
              });
            } catch (err) {
              console.warn('onBatchFinished callback threw:', err);
            }
          }
          return;
        }

        consecutiveErrors = roundHadSuccess ? 0 : consecutiveErrors + 1;
        if (consecutiveErrors >= MAX_POLL_ERRORS) {
          pollRef.current = null;
          setStatus('error');
          setLogs((l) => [
            ...l,
            `Lost contact with the backend after ${MAX_POLL_ERRORS} failed polls — batch polling stopped. The jobs may still be running; check the History tab once the server is reachable again.`,
          ]);
          return;
        }
        const delay = consecutiveErrors > 0
          ? Math.min(POLL_MS * 2 ** consecutiveErrors, 30_000)
          : POLL_MS;
        pollRef.current = setTimeout(tick, delay);
      };
      pollRef.current = setTimeout(tick, POLL_MS);
    } catch (e) {
      setStatus('error');
      setLogs((l) => [...l, `Batch error: ${e.message}`]);
    }
  };

  return { handleProcess, handleBatchProcess };
}
