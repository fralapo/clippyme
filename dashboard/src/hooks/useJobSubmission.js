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

      // 3. Unified polling: track each job_id individually until all done
      const total = allJobIds.length;
      const finished = new Set();
      let succeeded = 0;
      let failed = 0;

      const pollAll = setInterval(async () => {
        for (const jid of allJobIds) {
          if (finished.has(jid)) continue;
          try {
            const r = await fetch(getApiUrl(`/api/status/${jid}`));
            if (!r.ok) continue;
            const s = await r.json();
            if (s.status === 'completed') {
              finished.add(jid);
              succeeded += 1;
            } else if (s.status === 'failed' || s.status === 'cancelled') {
              finished.add(jid);
              failed += 1;
            }
          } catch {
            /* ignore poll errors */
          }
        }
        setLogs([
          `Batch progress: ${succeeded + failed}/${total} done (${succeeded} ok, ${failed} failed)`,
        ]);
        if (finished.size >= total) {
          clearInterval(pollAll);
          setStatus('complete');
          setLogs((l) => [
            ...l,
            `Batch complete! ${succeeded} succeeded, ${failed} failed.`,
          ]);
        }
      }, 3000);
    } catch (e) {
      setStatus('error');
      setLogs((l) => [...l, `Batch error: ${e.message}`]);
    }
  };

  return { handleProcess, handleBatchProcess };
}
