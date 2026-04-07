import React, { useState, useEffect } from 'react';
import {
  Upload, FileVideo, Sparkles, Youtube, Instagram, Share2, LogOut,
  ChevronDown, Check, Activity, LayoutDashboard, Settings, PlusCircle,
  History, Menu, X, Terminal, Shield, LayoutGrid, Image, Globe,
  RotateCcw, Cpu, Zap, Wand2, Github, AlertCircle, Key
} from 'lucide-react';
import KeyInput from './components/KeyInput';
import MediaInput from './components/MediaInput';
import ResultCard from './components/ResultCard';
import ProcessingAnimation from './components/ProcessingAnimation';
import HistoryTab from './components/HistoryTab';
import SettingsTab from './components/SettingsTab';
import PipelineSteps from './components/PipelineSteps';
import LogsPanel from './components/LogsPanel';
import IdleHero from './components/IdleHero';
import { getApiUrl } from './config';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { submitProcessJob, submitBatchJob } from './lib/api';
import { useHistory } from './hooks/useHistory';
import { useSessionPersistence } from './hooks/useSessionPersistence';
import { useJobPolling } from './hooks/useJobPolling';
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
  const [sessionRecovered, setSessionRecovered] = useState(false);
  const { history, saveToHistory, deleteFromHistory, clearHistory } = useHistory();
  const { hfTokenSet, setHfTokenSet, cookiesConfigured, setCookiesConfigured } = useBackendStatus();

  const [currentStep, setCurrentStep] = useState(null);

  const [syncedTime, setSyncedTime] = useState(0);
  const [isSyncedPlaying, setIsSyncedPlaying] = useState(false);
  const [syncTrigger, setSyncTrigger] = useState(0);

  const [showConfetti, setShowConfetti] = useState(false);
  const [preselections, setPreselections] = useState(null);

  const handleClipPlay = (startTime) => {
    setSyncedTime(startTime);
    setIsSyncedPlaying(true);
    setSyncTrigger(prev => prev + 1);
  };

  const handleClipPause = () => {
    setIsSyncedPlaying(false);
  };

  useSessionPersistence({ status, jobId, results, processingMedia, activeTab });

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

  const handleProcess = async (data) => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    setStatus('processing');
    setLogs(["Initializing engine..."]);
    setResults(null);
    setProcessingMedia(data);

    // Store preselections for use by ResultCards (Tasks 12/13)
    if (data.preselections) {
      setPreselections(data.preselections);
    }

    try {
      const resData = await submitProcessJob(data, apiKey);
      setJobId(resData.job_id);
    } catch (e) {
      setStatus('error');
      setLogs(l => [...l, `Error: ${e.message}`]);
    }
  };

  const handleBatchProcess = async (data) => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    setStatus('processing');
    setLogs(["Launching batch processing..."]);
    setResults(null);

    // Store preselections for batch jobs
    if (data.preselections) {
      setPreselections(data.preselections);
    }

    try {
      const resData = await submitBatchJob(data, apiKey);
      setLogs(l => [...l, `Batch ${resData.batch_id}: ${resData.total} jobs queued`]);

      // Poll batch status
      const batchId = resData.batch_id;
      const pollBatch = setInterval(async () => {
        try {
          const statusRes = await fetch(getApiUrl(`/api/batch/${batchId}`));
          if (!statusRes.ok) return;
          const statusData = await statusRes.json();
          setLogs([`Batch progress: ${statusData.completed}/${statusData.total} completed, ${statusData.failed} failed`]);
          if (statusData.completed + statusData.failed >= statusData.total) {
            clearInterval(pollBatch);
            setStatus('completed');
            setLogs(l => [...l, `Batch complete! ${statusData.completed} succeeded, ${statusData.failed} failed.`]);
          }
        } catch { /* ignore poll errors */ }
      }, 3000);

    } catch (e) {
      setStatus('error');
      setLogs(l => [...l, `Batch error: ${e.message}`]);
    }
  };

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
    localStorage.removeItem(SESSION_KEY);
  };


  const TopNav = () => (
    <nav className="sticky top-0 z-50 w-full backdrop-blur-xl bg-[#050507]/80 border-b border-white/5">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-2.5 shrink-0">
          <img src="/logo.svg" alt="ClippyMe" height={32} className="h-8 w-8" />
          <span className="text-lg font-bold text-white tracking-tight hidden sm:block">ClippyMe</span>
        </div>

        {/* Tab pills */}
        <div className="flex items-center gap-1 bg-white/5 rounded-full p-1">
          {[
            { id: 'dashboard', label: 'Create', icon: PlusCircle },
            { id: 'history', label: 'History', icon: History },
            { id: 'settings', label: 'Settings', icon: Settings },
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-medium transition-all duration-200 ${
                activeTab === tab.id
                  ? 'bg-white/10 text-white shadow-sm'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              <tab.icon size={15} />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          ))}
        </div>

        {/* Status indicator */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <div className={`w-2 h-2 rounded-full ${status === 'processing' ? 'bg-amber-400 animate-pulse' : status === 'error' ? 'bg-red-400' : 'bg-emerald-400 shadow-[0_0_6px_rgba(16,185,129,0.5)]'}`} />
            <span className="hidden sm:inline font-medium">
              {status === 'processing' ? 'Processing' : status === 'error' ? 'Error' : 'Ready'}
            </span>
          </div>
          {status === 'processing' && jobId && (
            <button
              onClick={async () => {
                if (!window.confirm('Stop the current processing job?')) return;
                try {
                  await fetch(getApiUrl(`/api/cancel/${jobId}`), { method: 'POST' });
                  setStatus('idle');
                  setJobId(null);
                  setResults(null);
                  setLogs([]);
                  setProcessingMedia(null);
                  setCurrentStep(null);
                } catch { /* ignore */ }
              }}
              className="flex items-center gap-1.5 text-xs font-medium text-red-400 hover:text-red-300 bg-red-500/10 px-3 py-1.5 rounded-lg border border-red-500/20 transition-all"
            >
              <X size={12} />
              Stop
            </button>
          )}
          {status !== 'idle' && (
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 text-xs font-medium text-blue-400 hover:text-blue-300 bg-blue-500/10 px-3 py-1.5 rounded-lg border border-blue-500/20 transition-all"
            >
              <PlusCircle size={12} />
              <span className="hidden sm:inline">New</span>
            </button>
          )}
        </div>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen bg-[#050507] text-zinc-300 font-sans selection:bg-blue-500/20 selection:text-white">
      {/* Background effects */}
      <div className="fixed inset-0 bg-gradient-mesh opacity-20 pointer-events-none -z-10" />

      {/* Confetti celebration on completion */}
      {showConfetti && (
        <div className="fixed inset-0 z-[200] pointer-events-none overflow-hidden">
          {Array.from({ length: 40 }).map((_, i) => (
            <div
              key={i}
              className="absolute w-2 h-2 rounded-full animate-confetti"
              style={{
                left: `${Math.random() * 100}%`,
                top: '-10px',
                backgroundColor: ['#3b82f6', '#ec4899', '#a855f7', '#10b981', '#f59e0b'][i % 5],
                animationDelay: `${Math.random() * 1}s`,
                animationDuration: `${1.5 + Math.random() * 2}s`,
              }}
            />
          ))}
        </div>
      )}

      <TopNav />

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-10 pb-20">
        {/* ============ SETTINGS TAB ============ */}
        {activeTab === 'settings' && (
          <SettingsTab
            onKeySet={setApiKey}
            onHfTokenSet={() => setHfTokenSet(true)}
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

            {/* Step 2: Processing */}
            {(status === 'processing' || status === 'error') && !results?.clips?.length && (
              <div className="space-y-6">
                {/* Pulsing gradient border wrapper */}
                <div className={`rounded-2xl p-[1px] ${status === 'processing' ? 'bg-gradient-to-r from-pink-500 via-purple-500 to-blue-500 animate-pulse' : 'bg-red-500/50'}`}>
                  <div className="rounded-2xl bg-[#0f0f13] p-6 space-y-6">
                    {/* Pipeline steps */}
                    {status === 'processing' && <PipelineSteps currentStep={currentStep} />}

                    {/* Processing animation */}
                    {processingMedia && (
                      <ProcessingAnimation
                        media={processingMedia}
                        isComplete={status === 'complete'}
                        syncedTime={syncedTime}
                        isSyncedPlaying={isSyncedPlaying}
                        syncTrigger={syncTrigger}
                      />
                    )}

                    {/* Error state */}
                    {status === 'error' && (
                      <div className="flex flex-col items-center py-8 space-y-4">
                        <div className="w-14 h-14 rounded-2xl bg-red-500/10 flex items-center justify-center">
                          <AlertCircle size={28} className="text-red-400" />
                        </div>
                        <div className="text-center">
                          <p className="text-base font-semibold text-red-400">Processing Failed</p>
                          <p className="text-sm text-zinc-500 mt-1">Check the logs below for details.</p>
                        </div>
                        <div className="flex gap-3">
                          {processingMedia && (
                            <button
                              onClick={() => handleProcess(processingMedia)}
                              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-pink-500 to-purple-500 text-white text-sm font-semibold hover:opacity-90 transition-all"
                            >
                              <RotateCcw size={14} /> Retry
                            </button>
                          )}
                          <button
                            onClick={handleReset}
                            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/5 border border-white/10 text-zinc-300 text-sm font-medium hover:bg-white/10 transition-all"
                          >
                            New Project
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Waiting spinner for processing (no clips yet, no error) */}
                    {status === 'processing' && (
                      <div className="flex flex-col items-center py-6 space-y-4">
                        <div className="relative">
                          <div className="w-16 h-16 rounded-full border-[3px] border-zinc-800 border-t-blue-400 animate-spin" />
                          <div className="absolute inset-0 flex items-center justify-center">
                            <Activity size={20} className="text-blue-400 animate-pulse" />
                          </div>
                        </div>
                        <p className="text-sm text-zinc-500">Waiting for first segment...</p>
                      </div>
                    )}
                  </div>
                </div>

                {/* Logs panel */}
                <LogsPanel
                  logs={logs}
                  visible={logsVisible}
                  onToggle={() => setLogsVisible(!logsVisible)}
                  showWaiting={status === 'processing'}
                />
              </div>
            )}

            {/* Step 2b: Processing with partial results */}
            {status === 'processing' && results?.clips?.length > 0 && (
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-xl font-bold text-white flex items-center gap-2">
                      <Sparkles size={20} className="text-blue-400" />
                      Generating Clips...
                    </h2>
                    <p className="text-zinc-500 text-sm mt-1">{results.clips.length} segment{results.clips.length !== 1 ? 's' : ''} found so far</p>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20">
                    <Activity size={14} className="text-blue-400 animate-pulse" />
                    <span className="text-xs font-medium text-blue-400">Processing</span>
                  </div>
                </div>

                {/* Pipeline steps */}
                <PipelineSteps currentStep={currentStep} />

                {/* Partial results grid */}
                <div className="grid gap-6 grid-cols-1 lg:grid-cols-2">
                  {results.clips.map((clip, i) => (
                    <ResultCard
                      key={i}
                      clip={clip}
                      index={i}
                      jobId={jobId}
                      preselections={preselections}
                      onPlay={(time) => handleClipPlay(time)}
                      onPause={handleClipPause}
                    />
                  ))}
                </div>

                {/* Collapsible logs */}
                <LogsPanel
                  logs={logs}
                  visible={logsVisible}
                  onToggle={() => setLogsVisible(!logsVisible)}
                  maxHeightClass="max-h-48"
                  showWaiting
                />
              </div>
            )}

            {/* Step 3: Results (complete or error with results) */}
            {(status === 'complete' || (status === 'error' && results?.clips?.length > 0)) && (
              <div className="space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div>
                    <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                      <Sparkles size={22} className="text-purple-400" />
                      Your Clips
                    </h2>
                    <p className="text-zinc-500 text-sm mt-1">AI-curated high-engagement segments</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {results?.clips?.length > 0 && (
                      <div className="flex items-center gap-3 px-4 py-2 rounded-xl backdrop-blur-xl bg-white/5 border border-white/10">
                        <span className="text-sm font-semibold text-white">{results.clips.length} clips</span>
                        {results?.cost_analysis && (
                          <>
                            <div className="h-4 w-px bg-white/10" />
                            <span className="text-sm font-mono text-emerald-400" title={`Tokens: ${results.cost_analysis.input_tokens}i / ${results.cost_analysis.output_tokens}o`}>
                              ${results.cost_analysis.total_cost.toFixed(4)}
                            </span>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* Source preview */}
                {processingMedia && (
                  <div className="rounded-2xl bg-[#0f0f13] border border-white/5 p-4">
                    <ProcessingAnimation
                      media={processingMedia}
                      isComplete={status === 'complete'}
                      syncedTime={syncedTime}
                      isSyncedPlaying={isSyncedPlaying}
                      syncTrigger={syncTrigger}
                    />
                  </div>
                )}

                {/* Results grid */}
                {results && results.clips && results.clips.length > 0 ? (
                  <div className="grid gap-6 grid-cols-1 lg:grid-cols-2">
                    {results.clips.map((clip, i) => (
                      <ResultCard
                        key={i}
                        clip={clip}
                        index={i}
                        jobId={jobId}
                        preselections={preselections}
                        onPlay={(time) => handleClipPlay(time)}
                        onPause={handleClipPause}
                      />
                    ))}
                  </div>
                ) : null}

                {/* Error banner with retry (when error but some clips exist) */}
                {status === 'error' && (
                  <div className="rounded-2xl bg-red-500/10 border border-red-500/20 p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <AlertCircle size={18} className="text-red-400 shrink-0" />
                      <p className="text-sm text-red-400">Processing encountered an error. Some clips may be incomplete.</p>
                    </div>
                    {processingMedia && (
                      <button
                        onClick={() => handleProcess(processingMedia)}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-pink-500 to-purple-500 text-white text-xs font-semibold hover:opacity-90 transition-all shrink-0 ml-3"
                      >
                        <RotateCcw size={12} /> Retry
                      </button>
                    )}
                  </div>
                )}

                {/* Collapsed logs for completed state */}
                <div className="rounded-2xl bg-[#0f0f13] border border-white/5 overflow-hidden opacity-60 hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => setLogsVisible(!logsVisible)}
                    className="w-full px-5 py-3 flex items-center justify-between hover:bg-white/[0.02] transition-all"
                  >
                    <span className="text-xs font-medium text-zinc-500 flex items-center gap-2">
                      <Terminal size={13} /> Session Logs
                    </span>
                    <ChevronDown size={14} className={`text-zinc-600 transition-transform ${logsVisible ? '' : 'rotate-180'}`} />
                  </button>
                  {logsVisible && (
                    <div className="border-t border-white/5 p-5 max-h-40 overflow-y-auto font-mono text-[11px] space-y-1.5 text-zinc-500 leading-relaxed">
                      {logs.map((log, i) => (
                        <div key={i} className={`flex gap-3 ${log.toLowerCase().includes('error') ? 'text-red-400' : ''} ${log.startsWith('   ✅') || log.startsWith('✅') ? 'text-emerald-400' : ''}`}>
                          <span className="text-zinc-700 shrink-0 select-none">[{new Date().toLocaleTimeString()}]</span>
                          <span className="break-words">{log}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {/* API Key Modal */}
      {showKeyModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-md animate-fade-in" onClick={() => setShowKeyModal(false)}>
          <div className="rounded-2xl bg-[#16161d] border border-white/10 max-w-md w-full mx-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="p-8 space-y-6">
              <div className="w-14 h-14 rounded-2xl bg-amber-500/10 text-amber-400 flex items-center justify-center mx-auto">
                <Key size={28} />
              </div>
              <div className="text-center space-y-2">
                <h2 className="text-2xl font-bold text-white">API Key Required</h2>
                <p className="text-sm text-zinc-500">
                  You need a Google Gemini API key to use the clip engine.
                </p>
              </div>
              <div className="bg-[#0f0f13] border border-white/5 rounded-xl p-5 space-y-4">
                <p className="text-xs font-medium text-zinc-500">Quick Setup:</p>
                <ol className="text-sm text-zinc-400 space-y-3">
                  <li className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-lg bg-white/5 flex items-center justify-center text-xs font-semibold text-blue-400 border border-white/5 shrink-0">1</span>
                    Visit <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline font-medium">Google AI Studio</a>
                  </li>
                  <li className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-lg bg-white/5 flex items-center justify-center text-xs font-semibold text-blue-400 border border-white/5 shrink-0">2</span>
                    Sign in and generate a free API key
                  </li>
                  <li className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-lg bg-white/5 flex items-center justify-center text-xs font-semibold text-blue-400 border border-white/5 shrink-0">3</span>
                    Configure it in Settings
                  </li>
                </ol>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => setShowKeyModal(false)}
                  className="flex-1 px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-sm font-medium text-zinc-300 hover:bg-white/10 transition-all"
                >
                  Dismiss
                </button>
                <button
                  onClick={() => { setShowKeyModal(false); setActiveTab('settings'); }}
                  className="flex-1 px-4 py-3 rounded-xl bg-gradient-to-r from-pink-500 to-purple-500 text-sm font-semibold text-white hover:opacity-90 transition-all"
                >
                  Go to Settings
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Confetti animation styles */}
      <style>{`
        @keyframes confetti-fall {
          0% { transform: translateY(0) rotate(0deg); opacity: 1; }
          100% { transform: translateY(100vh) rotate(720deg); opacity: 0; }
        }
        .animate-confetti {
          animation: confetti-fall 2s ease-out forwards;
        }
      `}</style>
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
