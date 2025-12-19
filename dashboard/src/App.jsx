import React, { useState, useEffect } from 'react';
import { Upload, FileVideo, Sparkles, Youtube, Instagram, Share2, LogOut, ChevronDown, Check, Activity } from 'lucide-react';
import KeyInput from './components/KeyInput';
import MediaInput from './components/MediaInput';
import ResultCard from './components/ResultCard';
import ProcessingAnimation from './components/ProcessingAnimation';

// Simple TikTok icon sine Lucide might not have it or it varies
const TikTokIcon = ({ size = 16, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

const UserProfileSelector = ({ profiles, selectedUserId, onSelect }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!profiles || profiles.length === 0) return null;

  const selectedProfile = profiles.find(p => p.username === selectedUserId) || profiles[0];

  return (
    <div className="relative">
      <label className="text-xs text-zinc-500 font-medium ml-1 mb-1 block">Select User Profile</label>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-sm text-zinc-300 hover:bg-black/30 transition-colors"
      >
        <span className="flex items-center gap-2">
          <span className="font-medium text-white">{selectedProfile?.username || "Select User"}</span>
          {selectedProfile && (
            <div className="flex gap-1">
              {selectedProfile.connected.includes('tiktok') && <TikTokIcon size={12} className="text-white" />}
              {selectedProfile.connected.includes('instagram') && <Instagram size={12} className="text-pink-500" />}
              {selectedProfile.connected.includes('youtube') && <Youtube size={12} className="text-red-500" />}
            </div>
          )}
        </span>
        <ChevronDown size={14} className={`text-zinc-500 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute bottom-full mb-2 left-0 right-0 bg-[#1a1a1a] border border-white/10 rounded-xl shadow-xl z-50 overflow-hidden">
          <div className="max-h-60 overflow-y-auto custom-scrollbar">
            {profiles.map((profile) => (
              <button
                key={profile.username}
                onClick={() => {
                  onSelect(profile.username);
                  setIsOpen(false);
                }}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors text-left group border-b border-white/5 last:border-0"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-purple-500/20 flex items-center justify-center text-xs font-bold text-white border border-white/10 shrink-0">
                    {profile.username.substring(0, 2).toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-zinc-200 group-hover:text-white transition-colors truncate">
                      {profile.username}
                    </div>
                    <div className="flex gap-2 mt-0.5">
                      {/* Status indicators */}
                      <div className={`flex items-center gap-1 text-[10px] ${profile.connected.includes('tiktok') ? 'text-zinc-300' : 'text-zinc-600'}`}>
                        <TikTokIcon size={10} />
                      </div>
                      <div className={`flex items-center gap-1 text-[10px] ${profile.connected.includes('instagram') ? 'text-pink-400' : 'text-zinc-600'}`}>
                        <Instagram size={10} />
                      </div>
                      <div className={`flex items-center gap-1 text-[10px] ${profile.connected.includes('youtube') ? 'text-red-400' : 'text-zinc-600'}`}>
                        <Youtube size={10} />
                      </div>
                    </div>
                  </div>
                </div>
                {selectedUserId === profile.username && <Check size={14} className="text-primary shrink-0" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// Mock polling function
const pollJob = async (jobId) => {
  const res = await fetch(`/api/status/${jobId}`);
  if (!res.ok) throw new Error('Status check failed');
  return res.json();
};

function App() {
  const [apiKey, setApiKey] = useState(localStorage.getItem('gemini_key') || '');
  // Social API State
  const [uploadPostKey, setUploadPostKey] = useState(() => localStorage.getItem('uploadPostKey') || '');
  const [uploadUserId, setUploadUserId] = useState(() => localStorage.getItem('uploadUserId') || '');
  const [userProfiles, setUserProfiles] = useState([]); // List of {username, connected: []}
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle, processing, complete, error
  const [results, setResults] = useState(null);
  const [logs, setLogs] = useState([]);
  const [logsVisible, setLogsVisible] = useState(false);
  const [processingMedia, setProcessingMedia] = useState(null);

  useEffect(() => {
    if (apiKey) localStorage.setItem('gemini_key', apiKey);
  }, [apiKey]);

  useEffect(() => {
    localStorage.setItem('uploadPostKey', uploadPostKey);
    localStorage.setItem('uploadUserId', uploadUserId);
  }, [uploadPostKey, uploadUserId]);

  // Auto-fetch profiles when key is set (and not just on mount, but when key changes we might want to debounce or wait)
  // But user said "when I reload the web I have to hit load profiles". 
  // So on mount, if key exists, fetch.
  useEffect(() => {
    if (uploadPostKey && userProfiles.length === 0) {
      fetchUserProfiles();
    }
  }, [uploadPostKey]);

  useEffect(() => {
    let interval;
    if ((status === 'processing' || status === 'completed') && jobId) {
      interval = setInterval(async () => {
        try {
          const data = await pollJob(jobId);
          console.log("Job status:", data);

          // Update results if available (real-time)
          if (data.result) {
            setResults(data.result);
          }

          if (data.status === 'completed') {
            setStatus('complete');
            clearInterval(interval);
          } else if (data.status === 'failed') {
            setStatus('error');
            setLogs(prev => [...prev, "Error: " + data.error]);
            clearInterval(interval);
          } else {
            // Update logs if available
            if (data.logs) setLogs(data.logs);
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [status, jobId]);


  const fetchUserProfiles = async () => {
    if (!uploadPostKey) return;
    try {
      const res = await fetch('/api/social/user', {
        headers: { 'X-Upload-Post-Key': uploadPostKey }
      });
      if (!res.ok) throw new Error("Failed to fetch");
      const data = await res.json();
      if (data.profiles && data.profiles.length > 0) {
        setUserProfiles(data.profiles);
        // Auto select first if none selected
        if (!uploadUserId) {
          setUploadUserId(data.profiles[0].username);
        }
      } else {
        alert("No profiles found for this API Key.");
      }
    } catch (e) {
      alert("Error fetching User Profiles. Please check key.");
      console.error(e);
    }
  };

  const handleProcess = async (data) => {
    setStatus('processing');
    setLogs(["Starting process..."]);
    setResults(null);
    setProcessingMedia(data);

    try {
      let body;
      const headers = { 'X-Gemini-Key': apiKey };

      if (data.type === 'url') {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify({ url: data.payload });
      } else {
        const formData = new FormData();
        formData.append('file', data.payload);
        body = formData;
        // Content-Type is auto-set for FormData
      }

      const res = await fetch('/api/process', {
        method: 'POST',
        headers: data.type === 'url' ? headers : { 'X-Gemini-Key': apiKey },
        body
      });

      if (!res.ok) throw new Error(await res.text());
      const resData = await res.json();
      setJobId(resData.job_id);

    } catch (e) {
      setStatus('error');
      setLogs(l => [...l, `Error starting job: ${e.message}`]);
    }
  };

  return (
    <div className="min-h-screen bg-background relative overflow-x-hidden p-6 md:p-12">
      {/* Background Gradients */}
      <div className="fixed top-0 left-0 w-full h-full overflow-hidden -z-10 pointer-events-none">
        <div className="absolute -top-[10%] -left-[10%] w-[50%] h-[50%] bg-primary/10 rounded-full blur-[120px]" />
        <div className="absolute top-[20%] -right-[10%] w-[40%] h-[60%] bg-accent/10 rounded-full blur-[120px]" />
      </div>

      <div className="max-w-4xl mx-auto">
        <header className="mb-12 text-center animate-[fadeIn_0.5s_ease-out]">
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-white/5 rounded-full border border-white/10 mb-4">
            <Sparkles size={14} className="text-yellow-400" />
            <span className="text-xs font-medium text-zinc-300">AI Viral Clipper</span>
          </div>
          <h1 className="text-5xl md:text-6xl font-black bg-gradient-to-br from-white via-white to-white/50 bg-clip-text text-transparent mb-4 tracking-tight">
            OpenShorts<span className="text-primary">.app</span>
          </h1>
          <p className="text-zinc-400 text-lg max-w-lg mx-auto">
            Transform long-form videos into viral Shorts, Reels, and TikToks instantly with Gemini AI.
          </p>
        </header>

        <div className="space-y-4 mb-8">
          <KeyInput onKeySet={setApiKey} savedKey={apiKey} />

          <div className="p-4 rounded-xl bg-white/5 border border-white/10 backdrop-blur-sm">
            <div className="flex flex-col md:flex-row gap-6">
              <div className="flex-1 space-y-4">
                <div className="relative">
                  <label className="text-xs text-zinc-500 font-medium ml-1 mb-1 block">Upload-Post API Key (Optional)</label>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      placeholder="ey..."
                      value={uploadPostKey}
                      onChange={(e) => setUploadPostKey(e.target.value)}
                      className="flex-1 bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-sm text-zinc-300 focus:outline-none focus:border-primary/50 transition-colors"
                    />
                    <button
                      onClick={fetchUserProfiles}
                      className="px-3 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-medium text-zinc-300 transition-colors"
                      title="Fetch User Profiles"
                    >
                      Load Profiles
                    </button>
                  </div>
                </div>

                {userProfiles.length > 0 ? (
                  <UserProfileSelector
                    profiles={userProfiles}
                    selectedUserId={uploadUserId}
                    onSelect={setUploadUserId}
                  />
                ) : (
                  <div className="relative">
                    <label className="text-xs text-zinc-500 font-medium ml-1 mb-1 block">Upload-Post User ID</label>
                    <input
                      type="text"
                      placeholder="User Identifier (or Load Profiles)"
                      value={uploadUserId}
                      onChange={(e) => setUploadUserId(e.target.value)}
                      className="w-full bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-sm text-zinc-300 focus:outline-none focus:border-primary/50 transition-colors"
                    />
                  </div>
                )}
              </div>

              <div className="md:w-64 bg-primary/5 border border-primary/10 rounded-lg p-3">
                <h4 className="text-xs font-bold text-primary mb-2 flex items-center gap-1.5">
                  <Sparkles size={12} /> Social Auto-Post
                </h4>
                <p className="text-[11px] text-zinc-400 leading-relaxed mb-2">
                  Connect your accounts to post directly to TikTok, Instagram & YouTube.
                </p>
                <p className="text-[11px] text-zinc-400 leading-relaxed mb-3 border-l-2 border-white/10 pl-2">
                  Post directly to all your social networks. Start with a free trial (no credit card required). Simply connect your accounts, generate an API Key, and you're ready to go.
                </p>
                <a
                  href="https://app.upload-post.com/"
                  target="_blank"
                  className="block w-full py-1.5 bg-primary/10 hover:bg-primary/20 text-primary text-center rounded text-xs font-medium transition-colors"
                >
                  Get Account Used
                </a>
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-8">
          <MediaInput onProcess={handleProcess} isProcessing={status === 'processing'} />

          {status === 'processing' && processingMedia && (
            <ProcessingAnimation media={processingMedia} />
          )}

          {(status === 'processing' || status === 'error') && (
            <div className={`glass-panel p-6 ${status === 'error' ? 'border-red-500/30' : ''}`}>
              <div className="flex items-center justify-between mb-4">
                <div className={`flex items-center gap-3 ${status === 'error' ? 'text-red-400' : 'text-zinc-300'}`}>
                  <Activity size={20} className={status === 'processing' ? "animate-pulse text-primary" : ""} />
                  <span className="font-mono text-sm">{status === 'error' ? 'Process Failed' : 'Processing Status'}</span>
                </div>
                <button
                  onClick={() => setLogsVisible(!logsVisible)}
                  className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  {logsVisible ? 'Hide Logs' : 'Show Logs'}
                </button>
              </div>

              {logsVisible && (
                <div className="h-48 overflow-y-auto font-mono text-xs text-zinc-400 space-y-1 custom-scrollbar bg-black/20 p-4 rounded-lg animate-[fadeIn_0.2s_ease-out]">
                  {logs.map((log, i) => (
                    <div key={i} className={log.toLowerCase().includes('error') || log.toLowerCase().includes('failed') ? 'text-red-400' : ''}>
                      {'>'} {log}
                    </div>
                  ))}
                  {status === 'processing' && <div className="animate-pulse">{'>'} _</div>}
                </div>
              )}
              {!logsVisible && status === 'processing' && (
                <div className="text-zinc-500 text-sm animate-pulse">
                  Analyzing video content with Gemini AI...
                </div>
              )}
            </div>
          )}

          {status === 'error' && (
            <div className="mt-4 bg-red-500/10 border border-red-500/20 text-red-400 p-4 rounded-xl text-center text-sm">
              Processing encountered an error.
              <button
                onClick={() => setLogsVisible(true)}
                className="ml-2 underline hover:text-white"
              >
                Check Logs
              </button>
              <button
                onClick={() => setStatus('idle')}
                className="ml-4 underline hover:text-white"
              >
                Try Again
              </button>
            </div>
          )}

          {status === 'complete' && results && (
            <div className="space-y-6">
              <h2 className="text-2xl font-bold text-white mb-6 flex items-center gap-2">
                <Sparkles className="text-yellow-400" /> Results Generated
              </h2>
              <div className="grid gap-6">
                {results.clips.map((clip, i) => (
                  <ResultCard
                    key={i}
                    clip={clip}
                    index={i}
                    jobId={jobId}
                    uploadPostKey={uploadPostKey}
                    uploadUserId={uploadUserId}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
