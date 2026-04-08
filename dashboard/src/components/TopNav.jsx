import React from 'react';
import { History, PlusCircle, Settings, X } from 'lucide-react';
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
            <span className="type-label hidden md:inline">Cutting&nbsp;Room</span>
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

        {/* Status block — looks like an editor's take-log */}
        <div className="flex items-center gap-3">
          <div
            className="hidden md:flex items-center gap-2.5 px-3 h-9 border border-white/[0.08] rounded-[3px] bg-white/[0.02]"
            aria-live="polite"
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                status === 'processing'
                  ? 'bg-[oklch(74%_0.175_62)] animate-pulse shadow-[0_0_6px_oklch(74%_0.175_62/0.8)]'
                  : status === 'error'
                  ? 'bg-[oklch(62%_0.22_25)]'
                  : status === 'complete'
                  ? 'bg-[oklch(68%_0.18_145)] shadow-[0_0_6px_oklch(68%_0.18_145/0.7)]'
                  : 'bg-zinc-600'
              }`}
            />
            <span className="type-label !text-zinc-400">
              {status === 'processing' ? 'Rec' : status === 'error' ? 'Err' : status === 'complete' ? 'Cut' : 'Idle'}
            </span>
          </div>

          {status === 'processing' && jobId && (
            <button
              onClick={cancelJob}
              className="flex items-center gap-1.5 h-9 px-3 text-[11px] font-mono uppercase tracking-[0.14em] text-[oklch(62%_0.22_25)] hover:text-[oklch(70%_0.22_25)] border border-[oklch(62%_0.22_25)]/30 hover:border-[oklch(62%_0.22_25)]/60 bg-[oklch(62%_0.22_25)]/[0.08] rounded-[3px]"
            >
              <X size={12} strokeWidth={2.4} />
              Stop
            </button>
          )}
          {status !== 'idle' && (
            <button
              onClick={onReset}
              title="Start a fresh session (clear the current results)"
              className="flex items-center gap-1.5 h-9 px-3 text-[11px] font-mono uppercase tracking-[0.14em] text-zinc-300 hover:text-white border border-white/10 hover:border-white/25 bg-white/[0.02] rounded-[3px]"
            >
              <PlusCircle size={12} strokeWidth={2.2} />
              <span className="hidden sm:inline">New&nbsp;Take</span>
            </button>
          )}
        </div>
      </div>
    </nav>
  );
}
