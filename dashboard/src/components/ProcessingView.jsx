import React from 'react';
import { Activity, AlertCircle, RotateCcw } from 'lucide-react';
import PipelineSteps from './PipelineSteps';
import LogsPanel from './LogsPanel';
import ProcessingAnimation from './ProcessingAnimation';

/**
 * Pre-clip processing / error view. Renders ONLY the "waiting for the first
 * segment" state and the error screen with retry.
 *
 * Once clips start streaming in, App.jsx swaps this out for the full editable
 * ResultsGrid (see the `isLive && results?.clips?.length > 0` branch in
 * App.jsx), so this component never has to render a clip grid itself.
 *
 * @param {{
 *   status: string,
 *   currentStep: string | null,
 *   processingMedia: object | null,
 *   syncedTime: number,
 *   isSyncedPlaying: boolean,
 *   syncTrigger: number,
 *   logs: string[],
 *   logsVisible: boolean,
 *   onLogsToggle: () => void,
 *   onRetry: (media: object) => void,
 *   onReset: () => void,
 * }} props
 */
export default function ProcessingView({
  status,
  currentStep,
  processingMedia,
  syncedTime,
  isSyncedPlaying,
  syncTrigger,
  logs,
  logsVisible,
  onLogsToggle,
  onRetry,
  onReset,
}) {
  return (
    <div className="space-y-6">
      <div
        className={`rounded-[3px] p-[1px] ${
          status === 'processing'
            ? 'bg-[oklch(74%_0.175_62)]/60 animate-pulse'
            : 'bg-[oklch(62%_0.22_25)]/50'
        }`}
      >
        <div className="rounded-[3px] bg-[oklch(14%_0.009_260)] p-6 space-y-6">
          {status === 'processing' && <PipelineSteps currentStep={currentStep} />}

          {processingMedia && (
            <ProcessingAnimation
              media={processingMedia}
              isComplete={status === 'complete'}
              syncedTime={syncedTime}
              isSyncedPlaying={isSyncedPlaying}
              syncTrigger={syncTrigger}
            />
          )}

          {status === 'error' && (
            <div className="flex flex-col items-center py-8 space-y-4">
              <div className="w-14 h-14 rounded-[3px] bg-[oklch(62%_0.22_25)]/10 flex items-center justify-center">
                <AlertCircle size={28} className="text-[oklch(78%_0.2_25)]" />
              </div>
              <div className="text-center">
                <p className="text-base font-semibold text-[oklch(78%_0.2_25)]">Processing Failed</p>
                <p className="text-sm text-zinc-500 mt-1">Check the logs below for details.</p>
              </div>
              <div className="flex gap-3">
                {processingMedia && (
                  <button
                    onClick={() => onRetry(processingMedia)}
                    className="flex items-center gap-2 px-5 h-11 rounded-[3px] bg-[oklch(74%_0.175_62)] hover:bg-[oklch(78%_0.175_65)] text-[oklch(14%_0.01_260)] text-[11px] font-mono uppercase tracking-[0.16em] font-semibold border border-[oklch(70%_0.18_62)] shadow-[0_1px_0_0_oklch(100%_0_0/0.3)_inset] active:translate-y-px transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/60"
                  >
                    <RotateCcw size={13} strokeWidth={2.2} /> Retry
                  </button>
                )}
                <button
                  onClick={onReset}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-[3px] bg-white/5 border border-white/10 text-zinc-300 text-sm font-medium hover:bg-white/10 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
                >
                  New Project
                </button>
              </div>
            </div>
          )}

          {status === 'processing' && (
            <div className="flex flex-col items-center py-6 space-y-4">
              <div className="relative">
                <div className="w-16 h-16 rounded-full border-[3px] border-zinc-800 border-t-[oklch(74%_0.175_62)] animate-spin" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <Activity size={20} className="text-[oklch(82%_0.16_68)] animate-pulse" />
                </div>
              </div>
              <p className="text-sm text-zinc-500">Waiting for first segment…</p>
            </div>
          )}
        </div>
      </div>

      <LogsPanel
        logs={logs}
        visible={logsVisible}
        onToggle={onLogsToggle}
        showWaiting={status === 'processing'}
      />
    </div>
  );
}
