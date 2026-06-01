import React, { useState, useEffect, useCallback } from 'react';
import HistoryTab from './components/HistoryTab';
import SettingsTab from './components/SettingsTab';
import PipelineSteps from './components/PipelineSteps';
import LogsPanel from './components/LogsPanel';
import IdleHero from './components/IdleHero';
import ResultsGrid from './components/ResultsGrid';
import TopNav from './components/TopNav';
import ApiKeyModal from './components/ApiKeyModal';
import ProcessingView from './components/ProcessingView';
import ConfettiOverlay from './components/ConfettiOverlay';
import { getApiUrl } from './config';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { useJobSubmission } from './hooks/useJobSubmission';
import { useHistory } from './hooks/useHistory';
import { useSessionPersistence } from './hooks/useSessionPersistence';
import { useJobPolling } from './hooks/useJobPolling';
import { useClipStates } from './hooks/useClipStates';
import { useBackendStatus } from './hooks/useBackendStatus';

function App() {
  const [apiKey, setApiKey] = useState(localStorage.getItem('gemini_key') || '');
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle');
  const [results, setResults] = useState(null);
  const [logs, setLogs] = useState([]);
  const [logsVisible, setLogsVisible] = useState(true);
  const [processingMedia, setProcessingMedia] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard');
  const { history, saveToHistory, deleteFromHistory, clearHistory } = useHistory();
  const { hfTokenSet, setHfTokenSet, cookiesConfigured, setCookiesConfigured } = useBackendStatus();

  const [currentStep, setCurrentStep] = useState(null);

  const [syncedTime, setSyncedTime] = useState(0);
  const [isSyncedPlaying, setIsSyncedPlaying] = useState(false);
  const [syncTrigger, setSyncTrigger] = useState(0);

  const [showConfetti, setShowConfetti] = useState(false);
  const [preselections, setPreselectionsRaw] = useState(null);

  // Wrap setPreselections so every time preselections change we also persist
  // them against the current jobId (if known) — that way History restore and
  // page reload can rehydrate the exact toggle defaults the user picked.
  const setPreselections = (value) => {
    setPreselectionsRaw(value);
    try {
      if (jobId && value) {
        localStorage.setItem(`clippyme_preselections_job_${jobId}`, JSON.stringify(value));
      }
    } catch {
      /* localStorage full/disabled — silent */
    }
  };

  // When jobId becomes known AFTER preselections were set (submit flow),
  // persist the snapshot retroactively so it's recoverable.
  useEffect(() => {
    if (jobId && preselections) {
      try {
        localStorage.setItem(`clippyme_preselections_job_${jobId}`, JSON.stringify(preselections));
      } catch {
        /* silent */
      }
    }
  }, [jobId, preselections]);

  // When we restore a job from history (jobId set without preselections),
  // try to recover the saved preselection snapshot from localStorage.
  useEffect(() => {
    if (jobId && !preselections) {
      try {
        const saved = localStorage.getItem(`clippyme_preselections_job_${jobId}`);
        if (saved) setPreselectionsRaw(JSON.parse(saved));
      } catch {
        /* silent */
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);
  const { states: clipStates, updateClip: updateClipState } = useClipStates(jobId);

  // Memoized so the stable refs flow down ResultsGrid → React.memo(ResultCard)
  // and don't force every card to re-render on each 2s poll tick. State setters
  // are stable, so [] deps are correct.
  const handleClipPlay = useCallback((startTime) => {
    setSyncedTime(startTime);
    setIsSyncedPlaying(true);
    setSyncTrigger(prev => prev + 1);
  }, []);

  const handleClipPause = useCallback(() => {
    setIsSyncedPlaying(false);
  }, []);

  useSessionPersistence({ status, jobId, results, processingMedia, activeTab, preselections });

  useEffect(() => {
    if (apiKey) localStorage.setItem('gemini_key', apiKey);
  }, [apiKey]);

  useJobPolling({
    jobId,
    isActive: status === 'processing',
    onResult: setResults,
    onCompleted: (data) => {
      setStatus('complete');
      setShowConfetti(true);
      setTimeout(() => setShowConfetti(false), 3000);
      // Auto-switch to History tab once the job is done — Create is only
      // for launching, History hosts both the list AND the viewer for
      // completed jobs. This also matches the "delete from history while
      // looking at Create" bug: Create never shows results anymore, so
      // there's no stale view to worry about.
      setActiveTab('history');
      // Auto-apply smartcut pre-selection: fire-and-forget so files are ready at download time
      if (preselections?.smartcut && data.result?.clips) {
        data.result.clips.forEach((clip, i) => {
          fetch(getApiUrl(`/api/smartcut/${jobId}/${i}`), { method: 'POST' })
            .catch(err => console.warn('Pre-smartcut failed for clip', i, err));
        });
      }
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
    onCancelled: () => {
      setStatus('idle');
      setJobId(null);
      setResults(null);
      setLogs([]);
      setCurrentStep(null);
    },
    onFailed: (errorMsg) => {
      setStatus('error');
      setLogs(prev => [...prev, "Error: " + errorMsg]);
      saveToHistory({
        jobId,
        status: 'error',
        timestamp: Date.now(),
        source: processingMedia?.type === 'url' ? processingMedia.payload : processingMedia?.payload?.name || 'Local file',
        sourceType: processingMedia?.type || 'file',
        clipCount: 0,
        cost: null,
      });
    },
    onProgress: (logs, step) => {
      setLogs(logs);
      if (step) setCurrentStep(step);
    },
  });

  const { handleProcess, handleBatchProcess } = useJobSubmission({
    apiKey,
    setShowKeyModal,
    setStatus,
    setLogs,
    setResults,
    setProcessingMedia,
    setPreselections,
    setJobId,
    // When a batch run finishes, land the user in the History tab
    // (the list view, since there's no single jobId to open inline)
    // and surface a toast summarising the outcome. This matches the
    // single-job flow where onCompleted auto-switches on completion.
    onBatchFinished: ({ succeeded, failed, total }) => {
      setActiveTab('history');
      // Lightweight toast via window.dispatchEvent so we don't have
      // to import sonner up here; App.jsx already renders <Toaster />
      // and HistoryTab / ResultsGrid use toast() directly.
      import('sonner').then(({ toast }) => {
        if (failed === 0) {
          toast.success(`Batch complete — ${succeeded} / ${total} jobs finished`);
        } else {
          toast.warning(`Batch finished with errors — ${succeeded} ok / ${failed} failed (${total} total)`);
        }
      }).catch(() => { /* silent */ });
    },
  });

  const handleReset = (skipConfirm = false) => {
    if (!skipConfirm && status === 'processing') {
      if (!window.confirm('A job is still processing. Are you sure you want to start over? Progress will be lost.')) return;
    }
    setStatus('idle');
    setJobId(null);
    setResults(null);
    setLogs([]);
    setProcessingMedia(null);
    setCurrentStep(null);
    // Always land on Create when the user asks to start over —
    // otherwise a reset from the history viewer leaves them staring
    // at an empty history entry.
    setActiveTab('dashboard');
    try { localStorage.removeItem('clippyme_session'); } catch { /* silent */ }
  };



  return (
    <div className="min-h-screen bg-background text-zinc-300 font-sans">
      {/* Single warm ambient wash — replaces the dead .bg-gradient-mesh class */}
      <div className="fixed inset-0 bg-ambient pointer-events-none -z-10" />

      <ConfettiOverlay visible={showConfetti} />

      <TopNav
        activeTab={activeTab}
        onTabChange={(nextTab) => {
          // Special case: the Create tab only renders IdleHero / the
          // live ProcessingView. It has NO branch for status==='complete'
          // (results live in the History viewer now), so if the user
          // clicks Create while we're in a complete state we'd end up
          // with an empty screen. Silently reset the completed job
          // state on tab-enter so they always land on the IdleHero.
          if (nextTab === 'dashboard' && status === 'complete') {
            setStatus('idle');
            setJobId(null);
            setResults(null);
            setLogs([]);
            setProcessingMedia(null);
            setCurrentStep(null);
          }
          setActiveTab(nextTab);
        }}
        status={status}
        jobId={jobId}
        onReset={handleReset}
        onCancelled={() => {
          setStatus('idle');
          setJobId(null);
          setResults(null);
          setLogs([]);
          setProcessingMedia(null);
          setCurrentStep(null);
        }}
      />

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-10 pb-20">
        {/* ============ SETTINGS TAB ============ */}
        {activeTab === 'settings' && (
          <SettingsTab
            onKeySet={setApiKey}
            onHfTokenSet={() => setHfTokenSet(true)}
            onCookiesChange={setCookiesConfigured}
          />
        )}

        {/* ============ HISTORY TAB ============
             History now hosts BOTH the list and the per-job viewer. When
             `status === 'complete'` and a jobId is loaded (either just
             finished from Create or restored from the list), we render
             the ResultsGrid for that job. Otherwise we show the list. */}
        {activeTab === 'history' && (
          <div className="animate-fade-in">
            {status === 'complete' && jobId && results?.clips?.length > 0 ? (
              <div className="space-y-5">
                {/* Sticky back-to-history bar — pinned right under the
                    TopNav (56px tall) so it stays reachable no matter
                    how far the user has scrolled into a long clip grid.
                    The ResultsGrid's own sticky action rail sits at
                    top-[100px] below this bar (see ResultsGrid.jsx).
                    Background blur + hairline keep it legible over any
                    content scrolling behind it. */}
                <div className="sticky top-[56px] z-50 -mx-4 px-4 py-2 backdrop-blur-md bg-[oklch(9%_0.006_260)]/85 border-b border-white/[0.06]">
                  <button
                    type="button"
                    onClick={() => {
                      setStatus('idle');
                      setJobId(null);
                      setResults(null);
                      setLogs([]);
                      setProcessingMedia(null);
                      setCurrentStep(null);
                      setPreselectionsRaw(null);
                      try { localStorage.removeItem('clippyme_session'); } catch { /* silent */ }
                    }}
                    className="flex items-center gap-2 h-9 px-3 rounded-[3px] border border-white/10 hover:border-white/25 text-zinc-400 hover:text-white type-mono text-[10px] uppercase tracking-[0.14em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/50"
                  >
                    ← Back&nbsp;to&nbsp;history
                  </button>
                </div>
                <ResultsGrid
                  results={results}
                  status={status}
                  jobId={jobId}
                  preselections={preselections}
                  processingMedia={processingMedia}
                  syncedTime={syncedTime}
                  isSyncedPlaying={isSyncedPlaying}
                  syncTrigger={syncTrigger}
                  logs={logs}
                  logsVisible={logsVisible}
                  onLogsToggle={() => setLogsVisible(!logsVisible)}
                  onClipPlay={handleClipPlay}
                  onClipPause={handleClipPause}
                  onRetry={handleProcess}
                  clipStates={clipStates}
                  onUpdateClipState={updateClipState}
                />
              </div>
            ) : (
              <HistoryTab
                onRestore={(entry, data) => {
                  setJobId(entry.jobId);
                  setResults(data.result);
                  setStatus('complete');
                  setProcessingMedia({ type: 'url', payload: entry.source });
                  // Stay on the History tab — the viewer renders inline
                  // thanks to the conditional above.
                  // Rehydrate the clip preselections for THIS job id.
                  try {
                    const saved = localStorage.getItem(`clippyme_preselections_job_${entry.jobId}`);
                    setPreselectionsRaw(saved ? JSON.parse(saved) : null);
                  } catch {
                    setPreselectionsRaw(null);
                  }
                }}
                onJobDeleted={(deletedJobId) => {
                  deleteFromHistory(deletedJobId);
                  // If the user deletes the job they are currently
                  // viewing, wipe the inline viewer so they don't stare
                  // at a stale ResultsGrid pointing at missing files.
                  if (jobId === deletedJobId) {
                    setStatus('idle');
                    setJobId(null);
                    setResults(null);
                    setLogs([]);
                    setProcessingMedia(null);
                    setCurrentStep(null);
                  }
                }}
                onAllCleared={() => {
                  clearHistory();
                  // Same wipe: if we were viewing a clip grid, drop it.
                  if (jobId) {
                    setStatus('idle');
                    setJobId(null);
                    setResults(null);
                    setLogs([]);
                    setProcessingMedia(null);
                    setCurrentStep(null);
                  }
                }}
              />
            )}
          </div>
        )}

        {/* ============ CREATE TAB ============
             Create is ONLY for launching jobs and monitoring the live
             pipeline. As soon as a job completes, the polling callback
             auto-switches to the History tab where the viewer lives.
             Never renders a ResultsGrid here — results always live in
             the History tab so a delete-from-history action can never
             leave a stale grid rendered in Create. */}
        {activeTab === 'dashboard' && (
          <div className="animate-fade-in">
            {/* Step 1: Media Input (idle) */}
            {status === 'idle' && (
              <IdleHero
                apiKey={apiKey}
                hfTokenSet={hfTokenSet}
                cookiesConfigured={cookiesConfigured}
                isProcessing={status === 'processing'}
                onOpenSettings={() => setActiveTab('settings')}
                onProcess={handleProcess}
                onBatchProcess={handleBatchProcess}
              />
            )}

            {/* Step 2: Processing / error (no clips yet) + Step 2b: partial results */}
            {((status === 'processing' || status === 'error') && !results?.clips?.length) ||
            (status === 'processing' && results?.clips?.length > 0) ? (
              <ProcessingView
                status={status}
                currentStep={currentStep}
                processingMedia={processingMedia}
                results={results}
                jobId={jobId}
                preselections={preselections}
                syncedTime={syncedTime}
                isSyncedPlaying={isSyncedPlaying}
                syncTrigger={syncTrigger}
                logs={logs}
                logsVisible={logsVisible}
                onLogsToggle={() => setLogsVisible(!logsVisible)}
                onClipPlay={handleClipPlay}
                onClipPause={handleClipPause}
                onRetry={handleProcess}
                onReset={handleReset}
              />
            ) : null}
          </div>
        )}
      </main>

      {showKeyModal && (
        <ApiKeyModal
          onClose={() => setShowKeyModal(false)}
          onGoToSettings={() => {
            setShowKeyModal(false);
            setActiveTab('settings');
          }}
        />
      )}

      <Toaster position="bottom-right" richColors closeButton />
    </div>
  );
}

function AppWithProviders() {
  return (
    <TooltipProvider delayDuration={300}>
      <App />
    </TooltipProvider>
  );
}

export default AppWithProviders;
