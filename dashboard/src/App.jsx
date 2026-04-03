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

  const [currentStep, setCurrentStep] = useState(null);

  const [syncedTime, setSyncedTime] = useState(0);
  const [isSyncedPlaying, setIsSyncedPlaying] = useState(false);
  const [syncTrigger, setSyncTrigger] = useState(0);

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
        if (data.cookiesFile) {
          const formData = new FormData();
          formData.append('url', data.payload);
          formData.append('cookies_file', data.cookiesFile);
          body = formData;
        } else {
          headers['Content-Type'] = 'application/json';
          body = JSON.stringify({ url: data.payload });
        }
      } else {
        const formData = new FormData();
        formData.append('file', data.payload);
        body = formData;
      }

      const res = await fetch(getApiUrl('/api/process'), {
        method: 'POST',
        headers: data.type === 'url' && !data.cookiesFile ? headers : { 'X-Gemini-Key': apiKey },
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
      <div className="h-full overflow-y-auto p-4 md:p-10 custom-scrollbar animate-fade-in">
        <div className="max-w-4xl mx-auto space-y-6 md:space-y-10">
          <div className="flex items-center justify-between">
            <div className="flex flex-col gap-2 text-left">
              <h2 className="text-2xl md:text-4xl font-black text-white tracking-tighter uppercase text-left">History</h2>
              <p className="text-zinc-500 font-medium text-sm md:text-base text-left">Past sessions and their clips on disk.</p>
            </div>
            {serverHistory.length > 0 && (
              <button onClick={handleDeleteAll} className="btn-secondary text-[10px] font-black uppercase tracking-widest !py-2 !px-4">
                <X size={12} /> Clear All
              </button>
            )}
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-20"><Activity size={24} className="text-primary animate-pulse" /></div>
          ) : serverHistory.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-zinc-600 space-y-4">
              <History size={48} className="opacity-30" />
              <p className="text-sm font-bold uppercase tracking-widest">No sessions on disk</p>
              <p className="text-xs text-zinc-700">Completed jobs will appear here.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {serverHistory.map((entry) => (
                <div key={entry.jobId} className="glass-panel p-1 overflow-hidden">
                  <button
                    onClick={() => setExpanded(expanded === entry.jobId ? null : entry.jobId)}
                    className="w-full p-4 md:p-6 flex items-center gap-4 text-left hover:bg-white/[0.02] transition-all"
                  >
                    <div className="w-10 h-10 rounded-xl bg-success/10 text-success flex items-center justify-center shrink-0">
                      <Check size={20} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-bold text-white truncate">{entry.source}</p>
                      <div className="flex items-center gap-3 mt-1 flex-wrap">
                        <span className="text-[10px] text-zinc-500 font-bold uppercase">
                          {new Date(entry.timestamp).toLocaleDateString()} {new Date(entry.timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}
                        </span>
                        <span className="text-[10px] font-black text-primary">{entry.clipCount} clips</span>
                        {entry.cost != null && <span className="text-[10px] font-mono text-success">${entry.cost.toFixed(4)}</span>}
                      </div>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleOpen(entry); }}
                      className="px-3 py-1.5 bg-primary/10 border border-primary/20 text-primary rounded-lg text-[10px] font-black uppercase tracking-widest hover:bg-primary/20 transition-all shrink-0"
                    >
                      Open
                    </button>
                    <ChevronDown size={16} className={`text-zinc-500 transition-transform ${expanded === entry.jobId ? 'rotate-180' : ''}`} />
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(entry.jobId); }}
                      className="p-2 text-zinc-600 hover:text-error hover:bg-error/10 rounded-xl transition-all shrink-0"
                      title="Delete job and files"
                    >
                      <X size={16} />
                    </button>
                  </button>

                  {expanded === entry.jobId && entry.clips && entry.clips.length > 0 && (
                    <div className="border-t border-white/5 p-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                      {entry.clips.map((clip, ci) => (
                        <div key={ci} className="bg-black rounded-xl overflow-hidden group">
                          <video
                            src={getApiUrl(clip.video_url)}
                            className="w-full aspect-[9/16] object-cover"
                            controls
                            playsInline
                            preload="metadata"
                          />
                          <div className="p-2">
                            <p className="text-[10px] font-bold text-zinc-400 truncate">{clip.title || `Clip ${ci + 1}`}</p>
                            <p className="text-[9px] text-zinc-600">{Math.round(clip.end - clip.start)}s</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  };

  const Sidebar = () => (
    <div className="hidden md:flex w-16 lg:w-72 bg-surface-darker/50 backdrop-blur-2xl border-r border-white/5 flex-col h-full shrink-0 transition-all duration-500 z-50">
      <div className="p-4 lg:p-8 flex items-center justify-center lg:justify-start gap-4">
        <div className="w-10 h-10 lg:w-12 lg:h-12 rounded-2xl bg-primary flex items-center justify-center shadow-glow-primary overflow-hidden border border-white/10 shrink-0">
          <img src="/logo-clippyme.png" alt="Logo" className="w-6 h-6 lg:w-8 lg:h-8 object-contain" />
        </div>
        <div className="hidden lg:block overflow-hidden">
            <h1 className="font-black text-xl text-white tracking-tighter leading-none text-left uppercase">CLIPPYME</h1>
            <p className="text-[10px] font-bold text-primary tracking-widest mt-1 uppercase text-left">AI Engine v2.5</p>
        </div>
      </div>

      <nav className="flex-1 px-2 lg:px-4 py-6 space-y-2 text-left">
        <button
          onClick={() => setActiveTab('dashboard')}
          className={`w-full flex items-center justify-center lg:justify-start gap-4 px-3 lg:px-4 py-4 rounded-2xl transition-all duration-300 ${activeTab === 'dashboard' ? 'bg-primary text-white shadow-glow-primary' : 'text-zinc-500 hover:text-white hover:bg-white/5'}`}
        >
          <LayoutDashboard size={22} strokeWidth={activeTab === 'dashboard' ? 2.5 : 2} />
          <span className="font-bold text-sm hidden lg:block tracking-tight uppercase">Clip Generator</span>
        </button>

        <button
          onClick={() => setActiveTab('history')}
          className={`w-full flex items-center justify-center lg:justify-start gap-4 px-3 lg:px-4 py-4 rounded-2xl transition-all duration-300 ${activeTab === 'history' ? 'bg-primary text-white shadow-glow-primary' : 'text-zinc-500 hover:text-white hover:bg-white/5'}`}
        >
          <History size={22} strokeWidth={activeTab === 'history' ? 2.5 : 2} />
          <span className="font-bold text-sm hidden lg:block tracking-tight uppercase">History</span>
        </button>

        <button
          onClick={() => setActiveTab('settings')}
          className={`w-full flex items-center justify-center lg:justify-start gap-4 px-3 lg:px-4 py-4 rounded-2xl transition-all duration-300 ${activeTab === 'settings' ? 'bg-primary text-white shadow-glow-primary' : 'text-zinc-500 hover:text-white hover:bg-white/5'}`}
        >
          <Settings size={22} strokeWidth={activeTab === 'settings' ? 2.5 : 2} />
          <span className="font-bold text-sm hidden lg:block tracking-tight uppercase">System Settings</span>
        </button>
      </nav>

      <div className="p-2 lg:p-6 border-t border-white/5 space-y-2 lg:space-y-3">
        <a
          href="#"
          onClick={(e) => { e.preventDefault(); localStorage.removeItem('clippyme_skip_landing'); window.location.hash = ''; window.location.reload(); }}
          className="flex items-center justify-center lg:justify-start gap-3 p-2 lg:p-4 bg-white/5 hover:bg-white/10 rounded-2xl transition-all group border border-white/5"
        >
          <div className="w-8 h-8 lg:w-10 lg:h-10 rounded-xl bg-accent/20 text-accent flex items-center justify-center shrink-0 group-hover:rotate-12 transition-transform">
            <Globe size={18} />
          </div>
          <div className="hidden lg:block text-left">
            <p className="text-sm font-black text-white leading-none mb-1 tracking-tight uppercase">Website</p>
            <p className="text-[10px] text-zinc-500 group-hover:text-zinc-300 transition-colors">Landing page</p>
          </div>
        </a>
        <a
          href="https://github.com/fralapo/clippyme"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center lg:justify-start gap-3 p-2 lg:p-4 bg-white/5 hover:bg-white/10 rounded-2xl transition-all group border border-white/5"
        >
          <div className="w-8 h-8 lg:w-10 lg:h-10 rounded-xl bg-white text-black flex items-center justify-center shrink-0 group-hover:-rotate-12 transition-transform">
            <Github size={18} />
          </div>
          <div className="hidden lg:block text-left">
            <p className="text-sm font-black text-white leading-none mb-1 tracking-tight uppercase">Repository</p>
            <p className="text-[10px] text-zinc-500 group-hover:text-zinc-300 transition-colors">Source code</p>
          </div>
        </a>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen bg-background text-zinc-300 font-sans overflow-hidden selection:bg-primary/20 selection:text-white">
      <div className="fixed inset-0 bg-gradient-mesh opacity-30 pointer-events-none -z-10" />
      <div className="fixed inset-0 bg-grid pointer-events-none -z-10 opacity-20" />

      <Sidebar />

      <main className="flex-1 flex flex-col h-full overflow-hidden relative pb-14 md:pb-0">
        <header className="h-14 md:h-20 border-b border-white/5 bg-background/40 backdrop-blur-xl flex items-center justify-between px-4 md:px-10 shrink-0 z-10">
          <div className="flex items-center gap-6">
            <div className="hidden md:flex items-center gap-2 text-xs font-black text-zinc-500 uppercase tracking-widest">
                <div className={`w-2 h-2 rounded-full ${status === 'processing' ? 'bg-warning animate-pulse' : 'bg-success shadow-[0_0_8px_rgba(16,185,129,0.5)]'}`} />
                System Status: {status === 'processing' ? 'Busy' : 'Operational'}
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
                className="flex items-center gap-2 text-xs font-black text-error hover:text-white transition-colors bg-error/10 px-4 py-2 rounded-xl border border-error/20 uppercase tracking-widest"
              >
                <X size={14} />
                Stop
              </button>
            )}
            {status !== 'idle' && (
              <button
                onClick={handleReset}
                className="flex items-center gap-2 text-xs font-black text-primary hover:text-white transition-colors bg-primary/10 px-4 py-2 rounded-xl border border-primary/20 uppercase tracking-widest"
              >
                <PlusCircle size={14} />
                New Project
              </button>
            )}
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 px-4 py-2 bg-black/40 rounded-xl border border-white/5">
                <div className="flex flex-col text-right">
                    <span className="text-[10px] font-black text-zinc-500 uppercase leading-none">AI Agent</span>
                    <span className="text-xs font-bold text-white tracking-tight">Clippy Assistant</span>
                </div>
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-accent flex items-center justify-center text-white shadow-lg">
                    <Wand2 size={16} />
                </div>
            </div>
          </div>
        </header>

        {false && (
          <div></div>
        )}

        <div className="flex-1 overflow-hidden relative">
          {activeTab === 'settings' && (
            <div className="h-full overflow-y-auto p-4 md:p-10 custom-scrollbar animate-fade-in">
              <div className="max-w-3xl mx-auto space-y-6 md:space-y-10">
                <div className="flex flex-col gap-2 text-left">
                    <h2 className="text-2xl md:text-4xl font-black text-white tracking-tighter uppercase text-left">Configuration</h2>
                    <p className="text-zinc-500 font-medium text-sm md:text-base text-left">Control your API keys and model parameters.</p>
                </div>
                
                <div className="grid gap-8">
                    <div className="glass-panel p-1 border-white/5 overflow-hidden">
                        <div className="p-8 space-y-6">
                            <div className="flex items-center gap-3 text-xs font-black text-zinc-500 uppercase tracking-[0.2em]">
                                <Shield size={14} className="text-success" />
                                Security Node
                            </div>
                            <KeyInput onKeySet={setApiKey} onHfTokenSet={() => setHfTokenSet(true)} />
                        </div>
                    </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'history' && (
            <HistoryTab />
          )}

          {activeTab === 'dashboard' && status === 'idle' && (
            <div className="h-full flex flex-col items-center justify-center p-4 md:p-10 animate-fade-in overflow-y-auto">
              <div className="max-w-2xl w-full text-center space-y-8 md:space-y-12">
                <div className="space-y-4 md:space-y-6">
                  <div className="relative inline-block">
                    <div className="absolute -inset-4 bg-primary/20 blur-2xl rounded-full" />
                    <h1 className="text-4xl sm:text-6xl md:text-7xl font-black text-white tracking-tighter uppercase italic relative">
                        GO <span className="brand-gradient-text">VIRAL.</span>
                    </h1>
                  </div>
                  <p className="text-zinc-500 text-base md:text-xl font-medium max-w-lg mx-auto leading-relaxed px-2">
                    Drop a URL or local file to trigger the high-performance AI clipping engine.
                  </p>
                </div>

                {!apiKey && (
                  <div className="max-w-xl mx-auto w-full px-2">
                    <button
                      onClick={() => setActiveTab('settings')}
                      className="w-full p-4 bg-warning/10 border border-warning/20 rounded-2xl flex items-center gap-3 text-left hover:bg-warning/15 transition-all group"
                    >
                      <div className="w-10 h-10 rounded-xl bg-warning/20 flex items-center justify-center shrink-0">
                        <Key size={20} className="text-warning" />
                      </div>
                      <div>
                        <p className="text-sm font-black text-warning uppercase tracking-wider">API Key Required</p>
                        <p className="text-xs text-zinc-400 mt-0.5">Set your Gemini API key in Settings to start processing videos.</p>
                      </div>
                    </button>
                  </div>
                )}

                {!hfTokenSet && (
                  <div className="max-w-xl mx-auto w-full px-2">
                    <button
                      onClick={() => setActiveTab('settings')}
                      className="w-full p-3 bg-blue-500/10 border border-blue-500/20 rounded-2xl flex items-center gap-3 text-left hover:bg-blue-500/15 transition-all group"
                    >
                      <div className="w-9 h-9 rounded-xl bg-blue-500/20 flex items-center justify-center shrink-0">
                        <AlertCircle size={18} className="text-blue-400" />
                      </div>
                      <div>
                        <p className="text-xs font-bold text-blue-400 uppercase tracking-wider">Hugging Face Token Not Set</p>
                        <p className="text-[11px] text-zinc-400 mt-0.5">Add a HF token in Settings for faster Whisper model downloads and no rate limits.</p>
                      </div>
                    </button>
                  </div>
                )}

                <div className="max-w-xl mx-auto w-full px-2">
                    <MediaInput onProcess={handleProcess} isProcessing={status === 'processing'} />
                </div>

                <div className="flex items-center justify-center gap-6 md:gap-10">
                  <div className="flex items-center gap-2 text-zinc-600 grayscale hover:grayscale-0 hover:text-white transition-all duration-500">
                    <Youtube size={20} />
                    <span className="text-[10px] font-black tracking-[0.2em] uppercase">YouTube</span>
                  </div>
                  <div className="flex items-center gap-2 text-zinc-600 grayscale hover:grayscale-0 hover:text-white transition-all duration-500">
                    <Instagram size={20} />
                    <span className="text-[10px] font-black tracking-[0.2em] uppercase">Instagram</span>
                  </div>
                  <div className="flex items-center gap-2 text-zinc-600 grayscale hover:grayscale-0 hover:text-white transition-all duration-500">
                    <TikTokIcon size={20} />
                    <span className="text-[10px] font-black tracking-[0.2em] uppercase">TikTok</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'dashboard' && (status === 'processing' || status === 'complete' || status === 'error') && (
            <div className="h-full flex flex-col md:flex-row animate-fade-in overflow-hidden">
              <div className={`${status === 'complete' ? 'w-full md:w-[350px]' : 'w-full md:w-[500px]'} h-full flex flex-col border-r border-white/5 bg-surface-darker/30 p-4 md:p-8 overflow-y-auto custom-scrollbar transition-all duration-1000 ease-in-out shrink-0`}>
                <div className="mb-6 md:mb-10 flex items-center justify-between">
                  <div className="flex flex-col gap-1 text-left">
                    <h2 className="text-sm font-black text-white uppercase tracking-widest flex items-center gap-2">
                        <Activity className={`text-primary ${status === 'processing' ? 'animate-pulse' : ''}`} size={18} />
                        Engine Feed
                    </h2>
                    <p className="text-[10px] font-bold text-zinc-600 uppercase tracking-widest text-left">Real-time Telemetry</p>
                  </div>
                  <span className={`text-[10px] font-black px-3 py-1.5 rounded-lg border tracking-widest ${status === 'processing' ? 'bg-primary/10 border-primary/20 text-primary animate-pulse' :
                    status === 'complete' ? 'bg-success/10 border-success/20 text-success shadow-[0_0_15px_rgba(16,185,129,0.1)]' :
                      'bg-error/10 border-error/20 text-error'
                    }`}>
                    {status.toUpperCase()}
                  </span>
                </div>

                {/* Pipeline Step Indicator */}
                {status === 'processing' && (
                  <div className="mb-6 flex items-center gap-1 text-left">
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
                          <div className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-[9px] font-black uppercase tracking-wider transition-all ${
                            isDone ? 'text-success' : isActive ? 'text-primary bg-primary/10 border border-primary/20' : 'text-zinc-700'
                          }`}>
                            {isDone ? <Check size={10} /> : isActive ? <Zap size={10} className="animate-pulse" /> : null}
                            <span className="hidden sm:inline">{step.label}</span>
                            <span className="sm:hidden">{(i + 1)}</span>
                          </div>
                          {i < arr.length - 1 && <div className={`w-3 h-px ${isDone ? 'bg-success' : 'bg-zinc-800'}`} />}
                        </React.Fragment>
                      );
                    })}
                  </div>
                )}

                <div className="shrink-0">
                    {processingMedia && (
                    <ProcessingAnimation
                        media={processingMedia}
                        isComplete={status === 'complete'}
                        syncedTime={syncedTime}
                        isSyncedPlaying={isSyncedPlaying}
                        syncTrigger={syncTrigger}
                    />
                    )}
                </div>

                <div className={`mt-8 bg-zinc-950/50 rounded-2xl border border-white/5 overflow-hidden flex flex-col transition-all duration-700 ${status === 'complete' ? 'h-40 min-h-0 opacity-40 hover:opacity-100' : 'flex-1 min-h-[300px]'}`}>
                  <div className="px-5 py-3 border-b border-white/5 flex items-center justify-between bg-white/[0.02] shrink-0">
                    <span className="text-[10px] font-black text-zinc-500 flex items-center gap-2 uppercase tracking-widest">
                      <Terminal size={12} /> System_Logs.txt
                    </span>
                    <button onClick={() => setLogsVisible(!logsVisible)} className="text-zinc-600 hover:text-white transition-colors">
                      {logsVisible ? <ChevronDown size={16} /> : <ChevronDown size={16} className="rotate-180" />}
                    </button>
                  </div>
                  {logsVisible && (
                    <div className="flex-1 p-5 overflow-y-auto font-mono text-[11px] space-y-2 custom-scrollbar text-zinc-500 leading-relaxed text-left">
                      {logs.map((log, i) => (
                        <div key={i} className={`flex gap-3 ${log.toLowerCase().includes('error') ? 'text-error' : ''} ${log.startsWith('   ✅') || log.startsWith('✅') ? 'text-success' : ''}`}>
                          <span className="text-zinc-800 shrink-0 select-none">[{new Date().toLocaleTimeString()}]</span>
                          <span className="break-words">{log}</span>
                        </div>
                      ))}
                      {status === 'processing' && (
                        <div className="animate-pulse text-primary font-black tracking-tighter cursor-default text-left">_SYSTEM_WAITING_FOR_BUFFER_</div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex-1 h-full flex flex-col bg-background/50 p-4 md:p-8 transition-all duration-1000 ease-in-out relative">
                <div className="absolute top-0 right-0 p-8 pointer-events-none opacity-10">
                    <Sparkles size={200} className="text-primary" />
                </div>

                <div className="mb-6 md:mb-10 flex items-end justify-between relative z-10">
                    <div className="flex flex-col gap-2 text-left">
                        <h2 className="text-xl md:text-3xl font-black text-white tracking-tighter uppercase italic flex items-center gap-2 md:gap-3 text-left">
                            <Sparkles className="text-primary" size={22} />
                            Generated <span className="brand-gradient-text underline decoration-primary/30 underline-offset-8">Clips</span>
                        </h2>
                        <p className="text-zinc-500 font-bold text-[10px] md:text-xs uppercase tracking-widest text-left">AI curated high-engagement segments</p>
                    </div>
                    
                    <div className="flex items-center gap-3">
                        {results?.clips?.length > 0 && (
                            <div className="bg-white/5 border border-white/10 px-4 py-2 rounded-xl flex items-center gap-3">
                                <span className="text-xs font-black text-white tracking-widest">{results.clips.length} SEGMENTS</span>
                                {results?.cost_analysis && (
                                    <div className="h-4 w-[1px] bg-white/10" />
                                )}
                                {results?.cost_analysis && (
                                    <span className="text-xs font-mono text-success font-bold" title={`Tokens: ${results.cost_analysis.input_tokens}i / ${results.cost_analysis.output_tokens}o`}>
                                        ${results.cost_analysis.total_cost.toFixed(4)}
                                    </span>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto custom-scrollbar p-1 relative z-10">
                  {results && results.clips && results.clips.length > 0 ? (
                    <div className={`grid gap-6 pb-20 ${status === 'complete' ? 'grid-cols-1 xl:grid-cols-2' : 'grid-cols-1'}`}>
                      {results.clips.map((clip, i) => (
                        <ResultCard
                          key={i}
                          clip={clip}
                          index={i}
                          jobId={jobId}
                          geminiApiKey={apiKey}
                          onPlay={(time) => handleClipPlay(time)}
                          onPause={handleClipPause}
                        />
                      ))}
                    </div>
                  ) : (
                    status === 'processing' ? (
                      <div className="h-full flex flex-col items-center justify-center text-zinc-600 space-y-6">
                        <div className="relative">
                            <div className="w-20 h-20 rounded-full border-4 border-zinc-900 border-t-primary animate-spin" />
                            <div className="absolute inset-0 flex items-center justify-center">
                                <Activity size={24} className="text-primary animate-pulse" />
                            </div>
                        </div>
                        <div className="text-center space-y-2">
                            <p className="font-black text-xs uppercase tracking-[0.3em] text-zinc-500">Processing Pipeline Active</p>
                            <p className="text-[10px] font-mono opacity-50">Waiting for first segment broadcast...</p>
                        </div>
                      </div>
                    ) : status === 'error' ? (
                      <div className="h-full flex flex-col items-center justify-center text-error space-y-6">
                        <div className="w-16 h-16 rounded-2xl bg-error/10 flex items-center justify-center">
                            <AlertCircle size={32} />
                        </div>
                        <div className="text-center space-y-1">
                            <p className="font-black uppercase tracking-widest text-sm">Processing Failed</p>
                            <p className="text-xs opacity-60">Check system logs for details.</p>
                        </div>
                        <div className="flex gap-3">
                          {processingMedia && (
                            <button
                              onClick={() => handleProcess(processingMedia)}
                              className="btn-primary-glow text-xs font-black uppercase tracking-widest !py-3 !px-6"
                            >
                              <RotateCcw size={14} /> Retry
                            </button>
                          )}
                          <button
                            onClick={handleReset}
                            className="btn-secondary text-xs font-black uppercase tracking-widest !py-3 !px-6"
                          >
                            New Project
                          </button>
                        </div>
                      </div>
                    ) : null
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="hidden md:flex h-10 border-t border-white/5 bg-background/80 items-center px-8 shrink-0 relative z-20">
          <div className="flex items-center justify-between w-full">
            <span className="text-[9px] font-black text-zinc-500 tracking-[0.3em] uppercase">Engine Status: {status.toUpperCase()} | Build 2026.04.01</span>
            <span className="text-[9px] font-black text-zinc-500 tracking-[0.3em] uppercase">ClippyMe — AI Powered Video Precision</span>
          </div>
        </div>

        {/* Mobile bottom nav */}
        <div className="md:hidden fixed bottom-0 left-0 right-0 h-14 bg-surface-darker/95 backdrop-blur-xl border-t border-white/10 flex items-center justify-around z-50">
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`flex flex-col items-center gap-1 px-4 py-1 rounded-xl transition-all ${activeTab === 'dashboard' ? 'text-primary' : 'text-zinc-500'}`}
          >
            <LayoutDashboard size={20} />
            <span className="text-[9px] font-black uppercase tracking-wider">Clips</span>
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`flex flex-col items-center gap-1 px-4 py-1 rounded-xl transition-all relative ${activeTab === 'history' ? 'text-primary' : 'text-zinc-500'}`}
          >
            <History size={20} />
            <span className="text-[9px] font-black uppercase tracking-wider">History</span>
          </button>
          <button
            onClick={() => setActiveTab('settings')}
            className={`flex flex-col items-center gap-1 px-4 py-1 rounded-xl transition-all ${activeTab === 'settings' ? 'text-primary' : 'text-zinc-500'}`}
          >
            <Settings size={20} />
            <span className="text-[9px] font-black uppercase tracking-wider">Settings</span>
          </button>
        </div>
      </main>

      {showKeyModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-md animate-fade-in" onClick={() => setShowKeyModal(false)}>
          <div className="glass-panel p-1 max-w-md w-full mx-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="p-8 space-y-6">
                <div className="w-14 h-14 rounded-2xl bg-warning/10 text-warning flex items-center justify-center shadow-lg shadow-warning/5 mx-auto mb-4">
                    <Key size={32} />
                </div>
                <div className="text-center space-y-2">
                    <h2 className="text-2xl font-black text-white tracking-tighter uppercase">API Access Required</h2>
                    <p className="text-sm text-zinc-500 font-medium">
                    You need a Google Gemini API key to unlock the clip engine.
                    </p>
                </div>
                <div className="bg-black/40 border border-white/5 rounded-2xl p-6 space-y-4">
                    <p className="text-[10px] font-black text-zinc-500 uppercase tracking-widest">Fast Track Setup:</p>
                    <ol className="text-xs text-zinc-400 space-y-3 font-medium text-left">
                        <li className="flex items-center gap-3">
                            <span className="w-5 h-5 rounded-md bg-white/5 flex items-center justify-center text-[10px] font-black text-primary border border-white/5">1</span>
                            Visit <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline font-bold">Google AI Studio</a>
                        </li>
                        <li className="flex items-center gap-3 text-left">
                            <span className="w-5 h-5 rounded-md bg-white/5 flex items-center justify-center text-[10px] font-black text-primary border border-white/5 shrink-0">2</span>
                            Sign in and generate a free API key
                        </li>
                        <li className="flex items-center gap-3 text-left">
                            <span className="w-5 h-5 rounded-md bg-white/5 flex items-center justify-center text-[10px] font-black text-primary border border-white/5 shrink-0">3</span>
                            Configure it in the system settings
                        </li>
                    </ol>
                </div>

                <div className="flex gap-4 pt-2">
                <button
                    onClick={() => setShowKeyModal(false)}
                    className="flex-1 btn-secondary text-xs font-black uppercase tracking-widest"
                >
                    Dismiss
                </button>
                <button
                    onClick={() => { setShowKeyModal(false); setActiveTab('settings'); }}
                    className="flex-1 btn-primary-glow text-xs font-black uppercase tracking-widest"
                >
                    Go to Settings
                </button>
                </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
