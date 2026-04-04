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
import { getApiUrl } from './config';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';

const TikTokIcon = ({ size = 16, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

const SESSION_KEY = 'clippyme_session';
const SESSION_MAX_AGE = 3600000;
const HISTORY_KEY = 'clippyme_history';
const HISTORY_MAX_ITEMS = 50;

const pollJob = async (jobId) => {
  const res = await fetch(getApiUrl(`/api/status/${jobId}`));
  if (!res.ok) throw new Error('Status check failed');
  return res.json();
};

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
  const [history, setHistory] = useState([]);
  const [hfTokenSet, setHfTokenSet] = useState(true); // assume set until checked
  const [cookiesConfigured, setCookiesConfigured] = useState(false);

  const [currentStep, setCurrentStep] = useState(null);

  const [syncedTime, setSyncedTime] = useState(0);
  const [isSyncedPlaying, setIsSyncedPlaying] = useState(false);
  const [syncTrigger, setSyncTrigger] = useState(0);

  const [showConfetti, setShowConfetti] = useState(false);

  const handleClipPlay = (startTime) => {
    setSyncedTime(startTime);
    setIsSyncedPlaying(true);
    setSyncTrigger(prev => prev + 1);
  };

  const handleClipPause = () => {
    setIsSyncedPlaying(false);
  };

  // Session auto-recovery disabled — History tab replaces this.
  // Old sessions are cleaned up on mount.
  useEffect(() => {
    localStorage.removeItem(SESSION_KEY);
  }, []);

  useEffect(() => {
    if (status === 'idle') {
      localStorage.removeItem(SESSION_KEY);
      return;
    }
    try {
      const sessionData = {
        jobId,
        status,
        results,
        processingMedia: processingMedia?.type === 'url' ? processingMedia : null,
        activeTab,
        timestamp: Date.now()
      };
      localStorage.setItem(SESSION_KEY, JSON.stringify(sessionData));
    } catch (e) {
      console.debug('Skipping session persistence', e);
    }
  }, [jobId, status, results, activeTab, processingMedia]);

  useEffect(() => {
    if (apiKey) localStorage.setItem('gemini_key', apiKey);
  }, [apiKey]);

  // Check HF_TOKEN on mount
  useEffect(() => {
    fetch(getApiUrl('/api/config'))
      .then(r => r.ok ? r.json() : {})
      .then(data => setHfTokenSet(!!data.HF_TOKEN))
      .catch(() => {});
  }, []);

  // Check cookies configured on mount
  useEffect(() => {
    fetch(getApiUrl('/api/config/cookies/status'))
      .then(r => r.ok ? r.json() : {})
      .then(data => setCookiesConfigured(!!data.configured))
      .catch(() => {});
  }, []);

  // Load history on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(HISTORY_KEY);
      if (saved) setHistory(JSON.parse(saved));
    } catch { /* ignore */ }
  }, []);

  const saveToHistory = (entry) => {
    setHistory(prev => {
      const updated = [entry, ...prev.filter(h => h.jobId !== entry.jobId)].slice(0, HISTORY_MAX_ITEMS);
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(updated)); } catch { /* ignore */ }
      return updated;
    });
  };

  const deleteFromHistory = (jobId) => {
    setHistory(prev => {
      const updated = prev.filter(h => h.jobId !== jobId);
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(updated)); } catch { /* ignore */ }
      return updated;
    });
  };

  const clearHistory = () => {
    setHistory([]);
    localStorage.removeItem(HISTORY_KEY);
  };

  useEffect(() => {
    let interval;
    if (status === 'processing' && jobId) {
      interval = setInterval(async () => {
        try {
          const data = await pollJob(jobId);
          if (data.result) setResults(data.result);
          if (data.status === 'completed') {
            setStatus('complete');
            setShowConfetti(true);
            setTimeout(() => setShowConfetti(false), 3000);
            saveToHistory({
              jobId,
              status: 'complete',
              timestamp: Date.now(),
              source: processingMedia?.type === 'url' ? processingMedia.payload : processingMedia?.payload?.name || 'Local file',
              sourceType: processingMedia?.type || 'file',
              clipCount: data.result?.clips?.length || 0,
              cost: data.result?.cost_analysis?.total_cost || null,
            });
            clearInterval(interval);
          } else if (data.status === 'cancelled') {
            setStatus('idle');
            setJobId(null);
            setResults(null);
            setLogs([]);
            setCurrentStep(null);
            clearInterval(interval);
          } else if (data.status === 'failed') {
            setStatus('error');
            const errorMsg = data.error || (data.logs && data.logs.length > 0 ? data.logs[data.logs.length - 1] : "Process failed");
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
            clearInterval(interval);
          } else {
            if (data.logs) {
              setLogs(data.logs);
              // Detect current pipeline step from log keywords
              const joined = data.logs.join(' ');
              if (joined.includes('Processing Clip') || joined.includes('Step 4:') || joined.includes('Step 5:') || joined.includes('Step 6:')) setCurrentStep('processing');
              else if (joined.includes('Analyzing with Gemini') || joined.includes('Gemini')) setCurrentStep('analyzing');
              else if (joined.includes('Transcribing') || joined.includes('Faster-Whisper')) setCurrentStep('transcribing');
              else if (joined.includes('Downloading') || joined.includes('yt-dlp')) setCurrentStep('downloading');
              else if (joined.includes('queued') || joined.includes('started')) setCurrentStep('queued');
            }
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [status, jobId]);

  const handleProcess = async (data) => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    setStatus('processing');
    setLogs(["Initializing engine..."]);
    setResults(null);
    setProcessingMedia(data);

    try {
      let body;
      const headers = { 'X-Gemini-Key': apiKey };

      if (data.type === 'url') {
        headers['Content-Type'] = 'application/json';
        const jsonBody = { url: data.payload };
        if (data.instructions) jsonBody.instructions = data.instructions;
        body = JSON.stringify(jsonBody);
      } else {
        const formData = new FormData();
        formData.append('file', data.payload);
        body = formData;
      }

      const res = await fetch(getApiUrl('/api/process'), {
        method: 'POST',
        headers,
        body
      });

      if (!res.ok) throw new Error(await res.text());
      const resData = await res.json();
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

    try {
      const res = await fetch(getApiUrl('/api/batch'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Gemini-Key': apiKey },
        body: JSON.stringify({ urls: data.urls, instructions: data.instructions })
      });

      if (!res.ok) throw new Error(await res.text());
      const resData = await res.json();
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

  const HistoryTab = () => {
    const [serverHistory, setServerHistory] = React.useState([]);
    const [loading, setLoading] = React.useState(true);
    const [expanded, setExpanded] = React.useState(null);

    React.useEffect(() => {
      fetch(getApiUrl('/api/history'))
        .then(r => r.json())
        .then(data => { setServerHistory(data.jobs || []); setLoading(false); })
        .catch(() => setLoading(false));
    }, []);

    const handleDelete = async (jobId) => {
      if (!window.confirm('Delete this job and all its clip files?')) return;
      try {
        await fetch(getApiUrl(`/api/history/${jobId}`), { method: 'DELETE' });
        setServerHistory(prev => prev.filter(j => j.jobId !== jobId));
        deleteFromHistory(jobId);
      } catch { /* ignore */ }
    };

    const handleOpen = async (entry) => {
      try {
        const res = await fetch(getApiUrl(`/api/history/${entry.jobId}/restore`), { method: 'POST' });
        if (!res.ok) throw new Error('Restore failed');
        const data = await res.json();
        setJobId(entry.jobId);
        setResults(data.result);
        setStatus('complete');
        setProcessingMedia({ type: 'url', payload: entry.source });
        setActiveTab('dashboard');
      } catch (e) {
        console.error('Failed to restore job:', e);
      }
    };

    const handleDeleteAll = async () => {
      if (!window.confirm('Delete ALL jobs and files from disk?')) return;
      for (const job of serverHistory) {
        try { await fetch(getApiUrl(`/api/history/${job.jobId}`), { method: 'DELETE' }); } catch { /* ignore */ }
      }
      setServerHistory([]);
      clearHistory();
    };

    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-white">History</h2>
            <p className="text-zinc-500 text-sm mt-1">Past sessions and their clips on disk.</p>
          </div>
          {serverHistory.length > 0 && (
            <button onClick={handleDeleteAll} className="flex items-center gap-2 text-xs font-semibold text-zinc-400 hover:text-red-400 px-4 py-2 rounded-xl bg-white/5 border border-white/10 hover:border-red-500/30 transition-all">
              <X size={14} /> Clear All
            </button>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20"><Activity size={24} className="text-blue-400 animate-pulse" /></div>
        ) : serverHistory.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-zinc-600 space-y-4">
            <div className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center">
              <History size={32} className="opacity-30" />
            </div>
            <p className="text-sm font-medium text-zinc-500">No sessions on disk</p>
            <p className="text-xs text-zinc-600">Completed jobs will appear here.</p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {serverHistory.map((entry) => (
              <div key={entry.jobId} className="group rounded-2xl bg-[#16161d] border border-white/5 hover:border-white/10 overflow-hidden transition-all duration-300">
                <div className="p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-white truncate">{entry.source}</p>
                      <div className="flex items-center gap-3 mt-2 flex-wrap">
                        <span className="text-xs text-zinc-500">
                          {new Date(entry.timestamp).toLocaleDateString()} {new Date(entry.timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}
                        </span>
                        <span className="text-xs font-medium text-blue-400">{entry.clipCount} clips</span>
                        {entry.cost != null && <span className="text-xs font-mono text-emerald-400">${entry.cost.toFixed(4)}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => handleOpen(entry)}
                        className="px-3 py-1.5 text-xs font-medium text-blue-400 bg-blue-500/10 hover:bg-blue-500/20 rounded-lg transition-all"
                      >
                        Open
                      </button>
                      <button
                        onClick={() => handleDelete(entry.jobId)}
                        className="p-1.5 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all"
                        title="Delete job and files"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </div>
                </div>

                {/* Expand toggle */}
                {entry.clips && entry.clips.length > 0 && (
                  <>
                    <button
                      onClick={() => setExpanded(expanded === entry.jobId ? null : entry.jobId)}
                      className="w-full px-5 py-2 border-t border-white/5 flex items-center justify-between text-xs text-zinc-500 hover:text-zinc-300 hover:bg-white/[0.02] transition-all"
                    >
                      <span>{entry.clips.length} clip{entry.clips.length !== 1 ? 's' : ''}</span>
                      <ChevronDown size={14} className={`transition-transform ${expanded === entry.jobId ? 'rotate-180' : ''}`} />
                    </button>

                    {expanded === entry.jobId && (
                      <div className="border-t border-white/5 p-4 grid grid-cols-2 sm:grid-cols-3 gap-3">
                        {entry.clips.map((clip, ci) => (
                          <div key={ci} className="bg-black rounded-xl overflow-hidden">
                            <video
                              src={getApiUrl(clip.video_url)}
                              className="w-full aspect-[9/16] object-cover"
                              controls
                              playsInline
                              preload="metadata"
                            />
                            <div className="p-2">
                              <p className="text-[11px] font-medium text-zinc-400 truncate">{clip.title || `Clip ${ci + 1}`}</p>
                              <p className="text-[10px] text-zinc-600">{Math.round(clip.end - clip.start)}s</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    );
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
          <div className="animate-fade-in space-y-8">
            <div>
              <h2 className="text-2xl font-bold text-white">Settings</h2>
              <p className="text-zinc-500 text-sm mt-1">Manage your API keys and model configuration.</p>
            </div>

            <div className="rounded-2xl bg-[#0f0f13] border border-white/5 overflow-hidden">
              <div className="px-6 py-4 border-b border-white/5 flex items-center gap-2.5">
                <Shield size={16} className="text-emerald-400" />
                <span className="text-sm font-medium text-zinc-300">API Keys &amp; Security</span>
              </div>
              <div className="p-6">
                <KeyInput onKeySet={setApiKey} onHfTokenSet={() => setHfTokenSet(true)} />
              </div>
            </div>

            <div className="flex items-center gap-4 pt-2">
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); localStorage.removeItem('clippyme_skip_landing'); window.location.hash = ''; window.location.reload(); }}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/5 border border-white/5 hover:border-white/10 text-sm text-zinc-400 hover:text-white transition-all"
              >
                <Globe size={16} />
                Landing Page
              </a>
              <a
                href="https://github.com/fralapo/clippyme"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/5 border border-white/5 hover:border-white/10 text-sm text-zinc-400 hover:text-white transition-all"
              >
                <Github size={16} />
                Repository
              </a>
            </div>
          </div>
        )}

        {/* ============ HISTORY TAB ============ */}
        {activeTab === 'history' && (
          <div className="animate-fade-in">
            <HistoryTab />
          </div>
        )}

        {/* ============ CREATE TAB ============ */}
        {activeTab === 'dashboard' && (
          <div className="animate-fade-in">
            {/* Step 1: Media Input (idle) */}
            {status === 'idle' && (
              <div className="flex flex-col items-center text-center space-y-8 pt-6 sm:pt-16">
                <div className="space-y-4">
                  <div className="relative inline-block">
                    <div className="absolute -inset-6 bg-gradient-to-r from-pink-500/20 to-purple-500/20 blur-3xl rounded-full" />
                    <h1 className="text-5xl sm:text-6xl md:text-7xl font-extrabold text-white tracking-tight relative">
                      Go <span className="bg-gradient-to-r from-pink-500 to-purple-500 bg-clip-text text-transparent">Viral</span>
                    </h1>
                  </div>
                  <p className="text-zinc-500 text-base sm:text-lg max-w-md mx-auto leading-relaxed">
                    Drop a URL or upload a file to generate viral short clips with AI.
                  </p>
                </div>

                {!apiKey && (
                  <button
                    onClick={() => setActiveTab('settings')}
                    className="max-w-md w-full p-4 bg-amber-500/10 border border-amber-500/20 rounded-2xl flex items-center gap-3 text-left hover:bg-amber-500/15 transition-all"
                  >
                    <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center shrink-0">
                      <Key size={20} className="text-amber-400" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-amber-400">API Key Required</p>
                      <p className="text-xs text-zinc-400 mt-0.5">Set your Gemini API key in Settings to start.</p>
                    </div>
                  </button>
                )}

                {!hfTokenSet && (
                  <button
                    onClick={() => setActiveTab('settings')}
                    className="max-w-md w-full p-3 bg-blue-500/10 border border-blue-500/20 rounded-2xl flex items-center gap-3 text-left hover:bg-blue-500/15 transition-all"
                  >
                    <div className="w-9 h-9 rounded-xl bg-blue-500/20 flex items-center justify-center shrink-0">
                      <AlertCircle size={18} className="text-blue-400" />
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-blue-400">Hugging Face Token Not Set</p>
                      <p className="text-[11px] text-zinc-400 mt-0.5">Add a HF token in Settings for faster Whisper model downloads.</p>
                    </div>
                  </button>
                )}

                <div className="max-w-xl w-full">
                  <MediaInput onProcess={handleProcess} onBatchProcess={handleBatchProcess} isProcessing={status === 'processing'} cookiesConfigured={cookiesConfigured} />
                </div>

                <div className="flex items-center justify-center gap-8 pt-2">
                  <div className="flex items-center gap-2 text-zinc-600 hover:text-white transition-all duration-300">
                    <Youtube size={18} />
                    <span className="text-xs font-medium">YouTube</span>
                  </div>
                  <div className="flex items-center gap-2 text-zinc-600 hover:text-white transition-all duration-300">
                    <Instagram size={18} />
                    <span className="text-xs font-medium">Instagram</span>
                  </div>
                  <div className="flex items-center gap-2 text-zinc-600 hover:text-white transition-all duration-300">
                    <TikTokIcon size={18} />
                    <span className="text-xs font-medium">TikTok</span>
                  </div>
                </div>
              </div>
            )}

            {/* Step 2: Processing */}
            {(status === 'processing' || status === 'error') && !results?.clips?.length && (
              <div className="space-y-6">
                {/* Pulsing gradient border wrapper */}
                <div className={`rounded-2xl p-[1px] ${status === 'processing' ? 'bg-gradient-to-r from-pink-500 via-purple-500 to-blue-500 animate-pulse' : 'bg-red-500/50'}`}>
                  <div className="rounded-2xl bg-[#0f0f13] p-6 space-y-6">
                    {/* Pipeline steps */}
                    {status === 'processing' && (
                      <div className="flex items-center gap-2 flex-wrap">
                        {[
                          { key: 'downloading', label: 'Download' },
                          { key: 'transcribing', label: 'Transcribe' },
                          { key: 'analyzing', label: 'AI Analysis' },
                          { key: 'processing', label: 'Render' },
                        ].map((step, i, arr) => {
                          const steps = ['downloading', 'transcribing', 'analyzing', 'processing'];
                          const currentIdx = steps.indexOf(currentStep);
                          const stepIdx = steps.indexOf(step.key);
                          const isDone = stepIdx < currentIdx;
                          const isActive = stepIdx === currentIdx;
                          return (
                            <React.Fragment key={step.key}>
                              <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                                isDone ? 'text-emerald-400 bg-emerald-500/10' : isActive ? 'text-blue-400 bg-blue-500/10 border border-blue-500/20' : 'text-zinc-600'
                              }`}>
                                {isDone ? <Check size={12} /> : isActive ? <Zap size={12} className="animate-pulse" /> : null}
                                {step.label}
                              </div>
                              {i < arr.length - 1 && <div className={`w-6 h-px ${isDone ? 'bg-emerald-500/50' : 'bg-zinc-800'}`} />}
                            </React.Fragment>
                          );
                        })}
                      </div>
                    )}

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
                <div className="rounded-2xl bg-[#0f0f13] border border-white/5 overflow-hidden">
                  <button
                    onClick={() => setLogsVisible(!logsVisible)}
                    className="w-full px-5 py-3 flex items-center justify-between hover:bg-white/[0.02] transition-all"
                  >
                    <span className="text-xs font-medium text-zinc-500 flex items-center gap-2">
                      <Terminal size={13} /> Live Logs
                    </span>
                    <ChevronDown size={14} className={`text-zinc-600 transition-transform ${logsVisible ? '' : 'rotate-180'}`} />
                  </button>
                  {logsVisible && (
                    <div className="border-t border-white/5 p-5 max-h-64 overflow-y-auto font-mono text-[11px] space-y-1.5 text-zinc-500 leading-relaxed">
                      {logs.map((log, i) => (
                        <div key={i} className={`flex gap-3 ${log.toLowerCase().includes('error') ? 'text-red-400' : ''} ${log.startsWith('   ✅') || log.startsWith('✅') ? 'text-emerald-400' : ''}`}>
                          <span className="text-zinc-700 shrink-0 select-none">[{new Date().toLocaleTimeString()}]</span>
                          <span className="break-words">{log}</span>
                        </div>
                      ))}
                      {status === 'processing' && (
                        <div className="animate-pulse text-blue-400 font-medium">Waiting for output...</div>
                      )}
                    </div>
                  )}
                </div>
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
                <div className="flex items-center gap-2 flex-wrap">
                  {[
                    { key: 'downloading', label: 'Download' },
                    { key: 'transcribing', label: 'Transcribe' },
                    { key: 'analyzing', label: 'AI Analysis' },
                    { key: 'processing', label: 'Render' },
                  ].map((step, i, arr) => {
                    const steps = ['downloading', 'transcribing', 'analyzing', 'processing'];
                    const currentIdx = steps.indexOf(currentStep);
                    const stepIdx = steps.indexOf(step.key);
                    const isDone = stepIdx < currentIdx;
                    const isActive = stepIdx === currentIdx;
                    return (
                      <React.Fragment key={step.key}>
                        <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                          isDone ? 'text-emerald-400 bg-emerald-500/10' : isActive ? 'text-blue-400 bg-blue-500/10 border border-blue-500/20' : 'text-zinc-600'
                        }`}>
                          {isDone ? <Check size={12} /> : isActive ? <Zap size={12} className="animate-pulse" /> : null}
                          {step.label}
                        </div>
                        {i < arr.length - 1 && <div className={`w-6 h-px ${isDone ? 'bg-emerald-500/50' : 'bg-zinc-800'}`} />}
                      </React.Fragment>
                    );
                  })}
                </div>

                {/* Partial results grid */}
                <div className="grid gap-6 grid-cols-1 lg:grid-cols-2">
                  {results.clips.map((clip, i) => (
                    <ResultCard
                      key={i}
                      clip={clip}
                      index={i}
                      jobId={jobId}
                      onPlay={(time) => handleClipPlay(time)}
                      onPause={handleClipPause}
                    />
                  ))}
                </div>

                {/* Collapsible logs */}
                <div className="rounded-2xl bg-[#0f0f13] border border-white/5 overflow-hidden">
                  <button
                    onClick={() => setLogsVisible(!logsVisible)}
                    className="w-full px-5 py-3 flex items-center justify-between hover:bg-white/[0.02] transition-all"
                  >
                    <span className="text-xs font-medium text-zinc-500 flex items-center gap-2">
                      <Terminal size={13} /> Live Logs
                    </span>
                    <ChevronDown size={14} className={`text-zinc-600 transition-transform ${logsVisible ? '' : 'rotate-180'}`} />
                  </button>
                  {logsVisible && (
                    <div className="border-t border-white/5 p-5 max-h-48 overflow-y-auto font-mono text-[11px] space-y-1.5 text-zinc-500 leading-relaxed">
                      {logs.map((log, i) => (
                        <div key={i} className={`flex gap-3 ${log.toLowerCase().includes('error') ? 'text-red-400' : ''} ${log.startsWith('   ✅') || log.startsWith('✅') ? 'text-emerald-400' : ''}`}>
                          <span className="text-zinc-700 shrink-0 select-none">[{new Date().toLocaleTimeString()}]</span>
                          <span className="break-words">{log}</span>
                        </div>
                      ))}
                      <div className="animate-pulse text-blue-400 font-medium">Waiting for output...</div>
                    </div>
                  )}
                </div>
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
