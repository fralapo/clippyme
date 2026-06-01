// ClippyMe redesign — wired to the real backend via the production hooks.
// Visual layer is the Claude Design handoff; data layer reuses the same
// useJobSubmission / useJobPolling / useHistory / useClipStates the production
// app uses, so the pipeline behaves identically.
import { useState, useEffect, useMemo, useCallback } from 'react';
import './tokens.css';
import './app.css';
import { Icon, Btn } from './primitives';
import { TopNav } from './chrome';
import { CreateView } from './create';
import { ProcessingView } from './processing';
import { ResultsView } from './results';
import { PublishModal } from './publish';
import { HistoryView, SettingsView, ApiKeyModal } from './views';
import { CaptionEditModal } from './captions';
import { optsToPreselections, restoreJob } from './realApi';

import { useJobSubmission } from '../hooks/useJobSubmission';
import { useJobPolling } from '../hooks/useJobPolling';
import { useHistory } from '../hooks/useHistory';
import { useClipStates } from '../hooks/useClipStates';
import { useBackendStatus } from '../hooks/useBackendStatus';
import { useSessionPersistence } from '../hooks/useSessionPersistence';

const DEFAULT_OPTS = {
  mode: 'single', source: 'url', url: '', file: null, fileName: '', batch: '', batchFiles: [], instructions: '',
  clips: 7, aspect: '9:16',
  detect: true, reframe: true, smartcut: true, zoom: true,
  subtitles: true, subMode: 'karaoke', subPreset: 'hormozi_bold', subPosition: 'center',
  hooks: true, hookPos: 'top', hookSize: 'M',
  language: 'multi',
  platforms: { tiktok: true, ig: true, yt: false },
  preset: 'viral',
};

const CONFETTI_COLORS = ['#E6428D', '#9850C3', '#675ADD', '#0A81D9', '#02C5BF', '#F7BC59'];

function Confetti() {
  const pieces = useMemo(() => Array.from({ length: 90 }, (_, i) => ({
    left: Math.random() * 100, delay: Math.random() * 0.6, dur: 2.2 + Math.random() * 1.6,
    color: CONFETTI_COLORS[i % CONFETTI_COLORS.length], rot: Math.random() * 360, w: 6 + Math.random() * 6,
  })), []);
  return (
    <div className="confetti">
      {pieces.map((p, i) => (
        <i key={i} style={{ left: p.left + '%', background: p.color, width: p.w, height: p.w * 1.6,
          transform: `rotate(${p.rot}deg)`, animationDelay: p.delay + 's', animationDuration: p.dur + 's' }} />
      ))}
    </div>
  );
}

function Toasts({ items }) {
  const ic = { success: 'circle-check', warn: 'triangle-alert', info: 'info', error: 'triangle-alert' };
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={'toast ' + (t.type === 'error' ? 'warn' : t.type)}>
          <span className="ti"><Icon n={ic[t.type] || 'info'} /></span>
          <span>{t.msg}</span>
        </div>
      ))}
    </div>
  );
}

export default function RedesignApp() {
  const [apiKey, setApiKey] = useState(localStorage.getItem('gemini_key') || '');
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [tab, setTab] = useState('create');
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | processing | complete | error
  const [results, setResults] = useState(null);
  const [logs, setLogs] = useState([]);
  const [currentStep, setCurrentStep] = useState(null);
  const [processingMedia, setProcessingMedia] = useState(null);
  const [opts, setOpts] = useState(DEFAULT_OPTS);
  const [preselections, setPreselectionsRaw] = useState(null);
  const [confetti, setConfetti] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [publishClips, setPublishClips] = useState(null);
  const [captionsClip, setCaptionsClip] = useState(null);
  const [viewingHistory, setViewingHistory] = useState(false);

  const { history, saveToHistory, deleteFromHistory, clearHistory } = useHistory();
  const { cookiesConfigured } = useBackendStatus();
  const { states: clipStates, updateClip: updateClipState } = useClipStates(jobId);

  useEffect(() => { if (apiKey) localStorage.setItem('gemini_key', apiKey); }, [apiKey]);
  useSessionPersistence({ status, jobId, results, processingMedia, activeTab: tab, preselections });

  const pushToast = useCallback((type, msg) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, type, msg }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3600);
  }, []);

  const setPreselections = (value) => {
    setPreselectionsRaw(value);
    try { if (jobId && value) localStorage.setItem(`clippyme_preselections_job_${jobId}`, JSON.stringify(value)); } catch { /* */ }
  };

  // recipe / manual-edit handling on opts
  const set = (patch) => setOpts((o) => ({ ...o, ...patch, preset: null }));
  const pickPreset = (p) => setOpts((o) => ({ ...o, ...p.opts, preset: p.id }));

  useJobPolling({
    jobId,
    isActive: status === 'processing',
    onResult: setResults,
    onCompleted: (data) => {
      setStatus('complete');
      setConfetti(true);
      setTimeout(() => setConfetti(false), 3000);
      pushToast('success', `${data.result?.clips?.length || 0} clips ready`);
      saveToHistory({
        jobId,
        status: 'complete',
        timestamp: Date.now(),
        source: processingMedia?.type === 'url' ? processingMedia.payload : processingMedia?.payload?.name || 'Local file',
        sourceType: processingMedia?.type || 'file',
        clipCount: data.result?.clips?.length || 0,
        cost: data.result?.cost_analysis?.total_cost || null,
      });
    },
    onCancelled: () => { setStatus('idle'); setJobId(null); setResults(null); setLogs([]); setCurrentStep(null); },
    onFailed: (errorMsg) => {
      setStatus('error');
      setLogs((prev) => [...prev, 'Error: ' + errorMsg]);
      pushToast('error', 'Job failed — ' + String(errorMsg).slice(0, 80));
    },
    onProgress: (lg, step) => { setLogs(lg); if (step) setCurrentStep(step); },
  });

  const { handleProcess, handleBatchProcess } = useJobSubmission({
    apiKey, setShowKeyModal, setStatus, setLogs, setResults, setProcessingMedia,
    setPreselections, setJobId,
    onBatchFinished: ({ succeeded, failed, total }) => {
      setTab('history');
      pushToast(failed === 0 ? 'success' : 'warn', `Batch: ${succeeded}/${total} ok${failed ? `, ${failed} failed` : ''}`);
    },
  });

  const startJob = () => {
    const pre = optsToPreselections(opts);
    if (opts.mode === 'single') {
      if (opts.source === 'url') {
        if (!opts.url.trim()) return;
        handleProcess({ type: 'url', payload: opts.url.trim(), instructions: opts.instructions, preselections: pre });
      } else {
        if (!opts.file) return;
        handleProcess({ type: 'file', payload: opts.file, instructions: opts.instructions, preselections: pre });
      }
    } else {
      const urls = opts.batch.split('\n').map((l) => l.trim()).filter(Boolean);
      handleBatchProcess({ urls, files: opts.batchFiles, instructions: opts.instructions, preselections: pre });
    }
  };

  const resetToCreate = () => {
    setStatus('idle'); setJobId(null); setResults(null); setLogs([]); setProcessingMedia(null);
    setCurrentStep(null); setViewingHistory(false); setTab('create');
    try { localStorage.removeItem('clippyme_session'); } catch { /* */ }
  };

  const openPublish = (clips) => setPublishClips(Array.isArray(clips) ? clips : [clips]);

  const goTab = (next) => {
    if (next === 'create' && (status === 'complete' || status === 'error')) {
      setStatus('idle'); setJobId(null); setResults(null); setLogs([]); setProcessingMedia(null); setCurrentStep(null);
    }
    setViewingHistory(false);
    setTab(next);
  };

  const openHistoryJob = async (h) => {
    try {
      const data = await restoreJob(h.jobId);
      setJobId(h.jobId);
      setResults(data.result);
      setStatus('complete');
      setProcessingMedia({ type: h.sourceType || 'url', payload: h.source });
      try {
        const saved = localStorage.getItem(`clippyme_preselections_job_${h.jobId}`);
        setPreselectionsRaw(saved ? JSON.parse(saved) : null);
      } catch { setPreselectionsRaw(null); }
      setViewingHistory(true);
    } catch {
      pushToast('error', 'Could not restore this job');
    }
  };

  const clips = results?.clips || [];

  return (
    <div>
      <TopNav tab={tab} setTab={goTab} busy={status === 'processing'} />
      {confetti && <Confetti />}

      {tab === 'create' && status === 'idle' && (
        <CreateView opts={opts} set={set} onPickPreset={pickPreset} onCreate={startJob} />
      )}
      {tab === 'create' && (status === 'processing' || status === 'error') && (
        <ProcessingView media={processingMedia} status={status} logs={logs} step={currentStep}
          clips={clips} onCancel={resetToCreate} onRetry={startJob} />
      )}
      {tab === 'create' && status === 'complete' && (
        <ResultsView clips={clips} jobId={jobId} preselections={preselections}
          clipStates={clipStates} onUpdateClipState={updateClipState} onBack={resetToCreate}
          onPublish={openPublish} onPublishAll={openPublish} onCaptions={(c, i) => setCaptionsClip({ clip: c, idx: i })}
          pushToast={pushToast} />
      )}

      {tab === 'history' && !viewingHistory && (
        <HistoryView history={history}
          onOpen={openHistoryJob}
          onDelete={(id) => { deleteFromHistory(id); pushToast('info', 'Job deleted'); }}
          onClear={() => { clearHistory(); pushToast('info', 'History cleared'); }} />
      )}
      {tab === 'history' && viewingHistory && (
        <div className="fade-in">
          <div className="container" style={{ paddingTop: 24, paddingBottom: 0 }}>
            <Btn variant="secondary" size="sm" icon="arrow-left" onClick={() => setViewingHistory(false)}>Back to history</Btn>
          </div>
          <ResultsView clips={clips} jobId={jobId} preselections={preselections} embedded
            clipStates={clipStates} onUpdateClipState={updateClipState}
            onPublish={openPublish} onPublishAll={openPublish} onCaptions={(c, i) => setCaptionsClip({ clip: c, idx: i })}
            pushToast={pushToast} />
        </div>
      )}

      {tab === 'settings' && <SettingsView apiKey={apiKey} onApiKey={setApiKey} cookiesConfigured={cookiesConfigured} pushToast={pushToast} />}

      {publishClips && (
        <PublishModal clips={publishClips} jobId={jobId} clipStates={clipStates} preselections={preselections}
          onClose={() => setPublishClips(null)}
          onPublished={(idx) => updateClipState(idx, { publishedAt: Date.now() })}
          pushToast={pushToast} />
      )}
      {captionsClip && (
        <CaptionEditModal clip={captionsClip.clip} idx={captionsClip.idx}
          initial={clipStates[captionsClip.idx]} preselections={preselections}
          onClose={() => setCaptionsClip(null)}
          onSave={(patch) => { updateClipState(captionsClip.idx, patch); setCaptionsClip(null); pushToast('success', 'Captions updated'); }} />
      )}
      {showKeyModal && <ApiKeyModal onClose={() => setShowKeyModal(false)} onGoToSettings={() => { setShowKeyModal(false); setTab('settings'); }} />}

      <Toasts items={toasts} />
    </div>
  );
}
