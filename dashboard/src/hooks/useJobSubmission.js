import { submitProcessJob, submitBatchJob } from '../lib/api';
import { getApiUrl } from '../config';

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
}) {
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
      const resData = await submitProcessJob(data, apiKey);
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
        const batchRes = await submitBatchJob({ ...data, urls }, apiKey);
        allJobIds.push(...batchRes.jobs.map((j) => j.job_id));
        setLogs((l) => [...l, `Submitted ${batchRes.total} URL job(s)`]);
      }

      // 2. Submit each file individually to /api/process
      for (const f of files) {
        try {
          const fileRes = await submitProcessJob(
            {
              type: 'file',
              payload: f,
              instructions: data.instructions,
              preselections: data.preselections,
            },
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

      const pollAll = setInterval(async () => {
        for (const jid of allJobIds) {
          try {
            const r = await fetch(getApiUrl(`/api/status/${jid}`));
            if (!r.ok) continue;
            const s = await r.json();
            if (Array.isArray(s.logs)) lastLogs.set(jid, s.logs);
            if (!finished.has(jid)) {
              if (s.status === 'completed') {
                finished.add(jid);
                succeeded += 1;
              } else if (s.status === 'failed' || s.status === 'cancelled') {
                finished.add(jid);
                failed += 1;
              }
            }
          } catch {
            /* ignore poll errors */
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
          clearInterval(pollAll);
          setStatus('complete');
          setLogs((l) => [
            ...l,
            `Batch complete! ${succeeded} succeeded, ${failed} failed.`,
          ]);
        }
      }, 2000);
    } catch (e) {
      setStatus('error');
      setLogs((l) => [...l, `Batch error: ${e.message}`]);
    }
  };

  return { handleProcess, handleBatchProcess };
}
