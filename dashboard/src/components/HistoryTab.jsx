import React, { useEffect, useState } from 'react';
import { Activity, ChevronDown, History, X } from 'lucide-react';
import { toast } from 'sonner';
import { getApiUrl } from '../config';

/**
 * Server-side job history listing. Restore/delete/open actions are delegated
 * to the parent via callbacks.
 *
 * @param {{
 *   onRestore: (entry: { jobId: string, source: string }, data: { result: unknown }) => void,
 *   onJobDeleted: (jobId: string) => void,
 *   onAllCleared: () => void,
 * }} props
 */
export default function HistoryTab({ onRestore, onJobDeleted, onAllCleared }) {
  const [serverHistory, setServerHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);

  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(getApiUrl('/api/history'));
        if (!r.ok) throw new Error(`History request failed (${r.status})`);
        const data = await r.json();
        if (cancelled) return;
        setServerHistory(data.jobs || []);
        setLoadError(null);
      } catch (e) {
        if (cancelled) return;
        console.error('Failed to load history:', e);
        setLoadError(e.message || 'Failed to load history');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleDelete = async (jobId) => {
    if (!window.confirm('Delete this job and all its clip files?')) return;
    try {
      const res = await fetch(getApiUrl(`/api/history/${jobId}`), { method: 'DELETE' });
      if (!res.ok) {
        throw new Error(`Delete failed (${res.status})`);
      }
      setServerHistory((prev) => prev.filter((j) => j.jobId !== jobId));
      onJobDeleted(jobId);
    } catch (e) {
      console.error('Failed to delete job:', e);
      toast.error(`Could not delete job: ${e.message || 'unknown error'}`);
    }
  };

  const handleOpen = async (entry) => {
    try {
      const res = await fetch(getApiUrl(`/api/history/${entry.jobId}/restore`), { method: 'POST' });
      if (!res.ok) throw new Error(`Restore failed (${res.status})`);
      const data = await res.json();
      onRestore(entry, data);
    } catch (e) {
      console.error('Failed to restore job:', e);
      toast.error(`Could not open job: ${e.message || 'unknown error'}`);
    }
  };

  const handleDeleteAll = async () => {
    if (!window.confirm('Delete ALL jobs and files from disk?')) return;
    const failures = [];
    for (const job of serverHistory) {
      try {
        const res = await fetch(getApiUrl(`/api/history/${job.jobId}`), { method: 'DELETE' });
        if (!res.ok) failures.push(job.jobId);
      } catch {
        failures.push(job.jobId);
      }
    }
    if (failures.length === 0) {
      setServerHistory([]);
      onAllCleared();
    } else {
      // Re-fetch to show the true state
      try {
        const r = await fetch(getApiUrl('/api/history'));
        if (r.ok) {
          const data = await r.json();
          setServerHistory(data.jobs || []);
        }
      } catch {
        /* ignore */
      }
      toast.error(`Failed to delete ${failures.length} job(s). Refreshed from server.`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">History</h2>
          <p className="text-zinc-500 text-sm mt-1">Past sessions and their clips on disk.</p>
        </div>
        {serverHistory.length > 0 && (
          <button
            onClick={handleDeleteAll}
            className="flex items-center gap-2 text-xs font-semibold text-zinc-400 hover:text-red-400 px-4 py-2 rounded-xl bg-white/5 border border-white/10 hover:border-red-500/30 transition-all"
          >
            <X size={14} /> Clear All
          </button>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Activity size={24} className="text-[oklch(74%_0.175_62)] animate-pulse" />
        </div>
      ) : loadError ? (
        <div className="flex flex-col items-center justify-center py-20 text-center space-y-3 max-w-md mx-auto">
          <div className="w-14 h-14 rounded-[3px] bg-[oklch(62%_0.22_25)]/10 border border-[oklch(62%_0.22_25)]/30 flex items-center justify-center">
            <X size={24} className="text-[oklch(70%_0.2_25)]" />
          </div>
          <p className="text-sm font-medium text-[oklch(78%_0.2_25)]">Could not load history</p>
          <p className="text-xs text-zinc-500 font-mono">{loadError}</p>
          <button
            type="button"
            onClick={() => {
              setLoading(true);
              setLoadError(null);
              fetch(getApiUrl('/api/history'))
                .then((r) => {
                  if (!r.ok) throw new Error(`History request failed (${r.status})`);
                  return r.json();
                })
                .then((data) => setServerHistory(data.jobs || []))
                .catch((e) => setLoadError(e.message || 'Failed'))
                .finally(() => setLoading(false));
            }}
            className="mt-2 px-4 h-9 rounded-[3px] border border-white/[0.1] hover:border-white/[0.2] bg-white/[0.02] text-[11px] font-mono uppercase tracking-[0.14em] text-zinc-300 hover:text-white transition-colors"
          >
            Retry
          </button>
        </div>
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
            <div
              key={entry.jobId}
              className="group rounded-2xl bg-[#16161d] border border-white/5 hover:border-white/10 overflow-hidden transition-all duration-300"
            >
              <div className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-white truncate">{entry.source}</p>
                    <div className="flex items-center gap-3 mt-2 flex-wrap">
                      <span className="text-xs text-zinc-500">
                        {new Date(entry.timestamp).toLocaleDateString()}{' '}
                        {new Date(entry.timestamp).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>
                      <span className="text-xs font-medium text-blue-400">
                        {entry.clipCount} clips
                      </span>
                      {entry.cost != null && (
                        <span className="text-xs font-mono text-emerald-400">
                          ${entry.cost.toFixed(4)}
                        </span>
                      )}
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

              {entry.clips && entry.clips.length > 0 && (
                <>
                  <button
                    onClick={() => setExpanded(expanded === entry.jobId ? null : entry.jobId)}
                    className="w-full px-5 py-2 border-t border-white/5 flex items-center justify-between text-xs text-zinc-500 hover:text-zinc-300 hover:bg-white/[0.02] transition-all"
                  >
                    <span>
                      {entry.clips.length} clip{entry.clips.length !== 1 ? 's' : ''}
                    </span>
                    <ChevronDown
                      size={14}
                      className={`transition-transform ${expanded === entry.jobId ? 'rotate-180' : ''}`}
                    />
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
                            <p className="text-[11px] font-medium text-zinc-400 truncate">
                              {clip.title || `Clip ${ci + 1}`}
                            </p>
                            <p className="text-[10px] text-zinc-600">
                              {Math.round(clip.end - clip.start)}s
                            </p>
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
}
