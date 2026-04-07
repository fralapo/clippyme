import React from 'react';
import { History, PlusCircle, Settings, X } from 'lucide-react';
import { getApiUrl } from '../config';

const TABS = [
  { id: 'dashboard', label: 'Create', icon: PlusCircle },
  { id: 'history', label: 'History', icon: History },
  { id: 'settings', label: 'Settings', icon: Settings },
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
 *   onCancelled: () => void,
 * }} props
 */
export default function TopNav({ activeTab, onTabChange, status, jobId, onReset, onCancelled }) {
  const cancelJob = async () => {
    if (!window.confirm('Stop the current processing job?')) return;
    try {
      await fetch(getApiUrl(`/api/cancel/${jobId}`), { method: 'POST' });
      onCancelled();
    } catch {
      /* ignore */
    }
  };

  return (
    <nav className="sticky top-0 z-50 w-full backdrop-blur-xl bg-[#050507]/80 border-b border-white/5">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
        <div className="flex items-center gap-2.5 shrink-0">
          <img src="/logo.svg" alt="ClippyMe" height={32} className="h-8 w-8" />
          <span className="text-lg font-bold text-white tracking-tight hidden sm:block">
            ClippyMe
          </span>
        </div>

        <div className="flex items-center gap-1 bg-white/5 rounded-full p-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
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

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <div
              className={`w-2 h-2 rounded-full ${
                status === 'processing'
                  ? 'bg-amber-400 animate-pulse'
                  : status === 'error'
                  ? 'bg-red-400'
                  : status === 'complete'
                  ? 'bg-emerald-400 shadow-[0_0_6px_rgba(16,185,129,0.5)]'
                  : 'bg-zinc-500'
              }`}
            />
            <span className="hidden sm:inline font-medium">
              {status === 'processing'
                ? 'Processing'
                : status === 'error'
                ? 'Error'
                : status === 'complete'
                ? 'Done'
                : 'Idle'}
            </span>
          </div>
          {status === 'processing' && jobId && (
            <button
              onClick={cancelJob}
              className="flex items-center gap-1.5 text-xs font-medium text-red-400 hover:text-red-300 bg-red-500/10 px-3 py-1.5 rounded-lg border border-red-500/20 transition-all"
            >
              <X size={12} />
              Stop
            </button>
          )}
          {status !== 'idle' && (
            <button
              onClick={onReset}
              title="Start a fresh session (clear the current results)"
              className="flex items-center gap-1.5 text-xs font-medium text-blue-400 hover:text-blue-300 bg-blue-500/10 px-3 py-1.5 rounded-lg border border-blue-500/20 transition-all"
            >
              <PlusCircle size={12} />
              <span className="hidden sm:inline">Start over</span>
            </button>
          )}
        </div>
      </div>
    </nav>
  );
}
