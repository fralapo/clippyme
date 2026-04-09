import React, { useState, useEffect } from 'react';
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

  const handleClipPlay = (startTime) => {
    setSyncedTime(startTime);
    setIsSyncedPlaying(true);
    setSyncTrigger(prev => prev + 1);
  };

  const handleClipPause = () => {
    setIsSyncedPlaying(false);
  };

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
    try { localStorage.removeItem('clippyme_session'); } catch { /* silent */ }
  };



  return (
    <div className="min-h-screen bg-background text-zinc-300 font-sans">
      {/* Single warm ambient wash — replaces the dead .bg-gradient-mesh class */}
      <div className="fixed inset-0 bg-ambient pointer-events-none -z-10" />

      <ConfettiOverlay visible={showConfetti} />

      <TopNav
        activeTab={activeTab}
        onTabChange={setActiveTab}
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

        {/* ============ HISTORY TAB ============ */}
        {activeTab === 'history' && (
          <div className="animate-fade-in">
            <HistoryTab
              onRestore={(entry, data) => {
                setJobId(entry.jobId);
                setResults(data.result);
                setStatus('complete');
                setProcessingMedia({ type: 'url', payload: entry.source });
                setActiveTab('dashboard');
                // Rehydrate the clip preselections for THIS job id. The
                // per-job snapshot was written at submission time into
                // localStorage via setPreselections(). Without this
                // explicit read, a lingering `preselections` state from
                // the previous session would leak into the restored
                // job's ResultCards (wrong defaults for subs/hook/etc).
                try {
                  const saved = localStorage.getItem(`clippyme_preselections_job_${entry.jobId}`);
                  setPreselectionsRaw(saved ? JSON.parse(saved) : null);
                } catch {
                  setPreselectionsRaw(null);
                }
              }}
              onJobDeleted={deleteFromHistory}
              onAllCleared={clearHistory}
            />
          </div>
        )}

        {/* ============ CREATE TAB ============ */}
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

            {/* Step 3: Results (complete or error with results) */}
            {(status === 'complete' || (status === 'error' && results?.clips?.length > 0)) && (
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
            )}
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
