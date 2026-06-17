import React from 'react';
import { History, PlusCircle, Settings, Pause, Play, Square, Trash2 } from 'lucide-react';
import { getApiUrl } from '../config';

const TABS = [
  { id: 'dashboard', label: 'Create', numeral: 'I', icon: PlusCircle },
  { id: 'history', label: 'History', numeral: 'II', icon: History },
  { id: 'settings', label: 'Settings', numeral: 'III', icon: Settings },
];

/**
 * Sticky top navigation with tabs, status indicator and cancel/reset actions.
 *
 * @param {{
 *   activeTab: string,
 *   onTabChange: (tab: string) => void,
 *   status: string,
 *   jobId: string | null,
 *   onReset: () => void,
 *   onPaused: () => void,
 *   onResumed: () => void,
 *   onStopped: () => void,
 *   onCancelled: () => void,
 * }} props
 */
export default function TopNav({ activeTab, onTabChange, status, jobId, onReset, onPaused, onResumed, onStopped, onCancelled }) {
  const post = (path) => fetch(getApiUrl(path), { method: 'POST' });

  const pauseJob = async () => {
    try { await post(`/api/pause/${jobId}`); onPaused?.(); } catch { /* ignore */ }
  };

  const resumeJob = async () => {
    try { await post(`/api/resume/${jobId}`); onResumed?.(); } catch { /* ignore */ }
  };

  // Graceful stop — keep the clips finished so far. Polling observes the
  // backend flip to 'stopped' and drives the transition to the editable viewer.
  const stopJob = async () => {
    if (!window.confirm('Stop now and KEEP the clips finished so far? Remaining clips will not be generated.')) return;
    try { await post(`/api/stop/${jobId}`); onStopped?.(); } catch { /* ignore */ }
  };

  // Hard discard — kill AND delete all output for this job.
  const cancelJob = async () => {
    if (!window.confirm('Discard this job and DELETE all of its clips? This cannot be undone.')) return;
    try { await post(`/api/cancel/${jobId}`); onCancelled?.(); } catch { /* ignore */ }
  };

  const isLive = status === 'processing' || status === 'paused';

  return (
    <nav className="sticky top-0 z-50 w-full backdrop-blur-xl bg-background/85 border-b border-white/[0.07]">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between gap-6">
        {/* Logotype — Fraunces display italic paired with a mono subtitle */}
        <div className="flex items-center gap-3 shrink-0">
          <img src="/logo.svg" alt="" aria-hidden height={30} className="h-[30px] w-[30px] opacity-90" />
          <div className="hidden sm:flex items-baseline gap-2.5">
            <span
              className="type-display text-[22px] text-white"
              style={{ fontStyle: 'italic', fontWeight: 400 }}
            >
              ClippyMe
            </span>
          </div>
        </div>

        {/* Tab strip — mono labels, numbered I / II / III like chapters */}
        <div
          className="flex items-center gap-0 border border-white/[0.08] rounded-[3px] p-0.5 bg-white/[0.02]"
          role="tablist"
          aria-label="Primary"
        >
          {TABS.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => onTabChange(tab.id)}
                role="tab"
                aria-selected={active}
                className={`relative flex items-center gap-2 px-3.5 sm:px-4 h-9 text-[11px] font-mono uppercase tracking-[0.14em] transition-colors duration-150 ${
                  active
                    ? 'text-background bg-[oklch(74%_0.175_62)]'
                    : 'text-zinc-500 hover:text-zinc-200'
                }`}
              >
                <span className={`type-mono text-[10px] ${active ? 'text-background/75' : 'text-zinc-600'}`}>
                  {tab.numeral}
                </span>
                <tab.icon size={13} strokeWidth={active ? 2.2 : 1.8} />
                <span className="hidden sm:inline">{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Status indicator */}
        <div className="flex items-center gap-3">
          <div
            className="hidden md:flex items-center gap-2.5 px-3 h-9 border border-white/[0.08] rounded-[3px] bg-white/[0.02]"
            aria-live="polite"
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                status === 'processing'
                  ? 'bg-[oklch(74%_0.175_62)] animate-pulse shadow-[0_0_6px_oklch(74%_0.175_62/0.8)]'
                  : status === 'paused'
                  ? 'bg-[oklch(80%_0.16_85)]'
                  : status === 'error'
                  ? 'bg-[oklch(62%_0.22_25)]'
                  : status === 'complete'
                  ? 'bg-[oklch(68%_0.18_145)] shadow-[0_0_6px_oklch(68%_0.18_145/0.7)]'
                  : 'bg-zinc-600'
              }`}
            />
            <span className="type-label !text-zinc-400">
              {status === 'processing' ? 'Processing' : status === 'paused' ? 'Paused' : status === 'error' ? 'Error' : status === 'complete' ? 'Done' : 'Idle'}
            </span>
          </div>

          {/* Live job controls: Pause/Resume + graceful Stop (keep clips) + Discard */}
          {isLive && jobId && (
            <>
              {status === 'processing' ? (
                <button
                  onClick={pauseJob}
                  title="Pause processing (suspend the running job)"
                  className="flex items-center gap-1.5 h-9 px-3 text-[11px] font-mono uppercase tracking-[0.14em] text-[oklch(80%_0.16_85)] hover:text-[oklch(86%_0.16_85)] border border-[oklch(80%_0.16_85)]/30 hover:border-[oklch(80%_0.16_85)]/60 bg-[oklch(80%_0.16_85)]/[0.08] rounded-[3px]"
                >
                  <Pause size={12} strokeWidth={2.4} />
                  <span className="hidden sm:inline">Pause</span>
                </button>
              ) : (
                <button
                  onClick={resumeJob}
                  title="Resume processing"
                  className="flex items-center gap-1.5 h-9 px-3 text-[11px] font-mono uppercase tracking-[0.14em] text-[oklch(74%_0.175_62)] hover:text-[oklch(82%_0.175_62)] border border-[oklch(74%_0.175_62)]/30 hover:border-[oklch(74%_0.175_62)]/60 bg-[oklch(74%_0.175_62)]/[0.08] rounded-[3px]"
                >
                  <Play size={12} strokeWidth={2.4} />
                  <span className="hidden sm:inline">Resume</span>
                </button>
              )}
              <button
                onClick={stopJob}
                title="Stop now but keep the clips already finished"
                className="flex items-center gap-1.5 h-9 px-3 text-[11px] font-mono uppercase tracking-[0.14em] text-zinc-200 hover:text-white border border-white/15 hover:border-white/30 bg-white/[0.04] rounded-[3px]"
              >
                <Square size={12} strokeWidth={2.4} />
                <span className="hidden sm:inline">Stop&nbsp;&amp;&nbsp;keep</span>
              </button>
              <button
                onClick={cancelJob}
                title="Discard the job and delete all its clips"
                className="flex items-center gap-1.5 h-9 px-3 text-[11px] font-mono uppercase tracking-[0.14em] text-[oklch(62%_0.22_25)] hover:text-[oklch(70%_0.22_25)] border border-[oklch(62%_0.22_25)]/30 hover:border-[oklch(62%_0.22_25)]/60 bg-[oklch(62%_0.22_25)]/[0.08] rounded-[3px]"
              >
                <Trash2 size={12} strokeWidth={2.4} />
                <span className="hidden sm:inline">Discard</span>
              </button>
            </>
          )}
          {status !== 'idle' && !isLive && (
            <button
              onClick={onReset}
              title="Start a fresh session (clear the current results)"
              className="flex items-center gap-1.5 h-9 px-3 text-[11px] font-mono uppercase tracking-[0.14em] text-zinc-300 hover:text-white border border-white/10 hover:border-white/25 bg-white/[0.02] rounded-[3px]"
            >
              <PlusCircle size={12} strokeWidth={2.2} />
              <span className="hidden sm:inline">Start&nbsp;over</span>
            </button>
          )}
        </div>
      </div>
    </nav>
  );
}
