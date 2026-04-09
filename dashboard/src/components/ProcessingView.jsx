import React from 'react';
import { Activity, AlertCircle, RotateCcw, Sparkles } from 'lucide-react';
import PipelineSteps from './PipelineSteps';
import LogsPanel from './LogsPanel';
import ProcessingAnimation from './ProcessingAnimation';
import ResultCard from './ResultCard';

/**
 * Processing / error view — renders either the "waiting for first segment"
 * state, the error screen with retry, or the partial-results grid while the
 * pipeline is still running.
 *
 * @param {{
 *   status: string,
 *   currentStep: string | null,
 *   processingMedia: object | null,
 *   results: { clips?: Array<object> } | null,
 *   jobId: string | null,
 *   preselections: object | null,
 *   syncedTime: number,
 *   isSyncedPlaying: boolean,
 *   syncTrigger: number,
 *   logs: string[],
 *   logsVisible: boolean,
 *   onLogsToggle: () => void,
 *   onClipPlay: (time: number) => void,
 *   onClipPause: () => void,
 *   onRetry: (media: object) => void,
 *   onReset: () => void,
 * }} props
 */
export default function ProcessingView({
  status,
  currentStep,
  processingMedia,
  results,
  jobId,
  preselections,
  syncedTime,
  isSyncedPlaying,
  syncTrigger,
  logs,
  logsVisible,
  onLogsToggle,
  onClipPlay,
  onClipPause,
  onRetry,
  onReset,
}) {
  const hasClips = (results?.clips?.length || 0) > 0;

  // Partial-results variant: pipeline is still running but clips are streaming in
  if (status === 'processing' && hasClips) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <Sparkles size={20} className="text-blue-400" />
              Generating Clips...
            </h2>
            <p className="text-zinc-500 text-sm mt-1">
              {results.clips.length} segment{results.clips.length !== 1 ? 's' : ''} found so far
            </p>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-[3px] bg-blue-500/10 border border-blue-500/20">
            <Activity size={14} className="text-blue-400 animate-pulse" />
            <span className="text-xs font-medium text-blue-400">Processing</span>
          </div>
        </div>

        <PipelineSteps currentStep={currentStep} />

        <div className="grid gap-6 grid-cols-1 lg:grid-cols-2">
          {results.clips.map((clip, i) => (
            <ResultCard
              key={i}
              clip={clip}
              index={i}
              jobId={jobId}
              preselections={preselections}
              onPlay={(time) => onClipPlay(time)}
              onPause={onClipPause}
            />
          ))}
        </div>

        <LogsPanel
          logs={logs}
          visible={logsVisible}
          onToggle={onLogsToggle}
          maxHeightClass="max-h-48"
          showWaiting
        />
      </div>
    );
  }

  // Processing-waiting or error variant (no clips yet)
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
              <div className="w-14 h-14 rounded-[3px] bg-red-500/10 flex items-center justify-center">
                <AlertCircle size={28} className="text-red-400" />
              </div>
              <div className="text-center">
                <p className="text-base font-semibold text-red-400">Processing Failed</p>
                <p className="text-sm text-zinc-500 mt-1">Check the logs below for details.</p>
              </div>
              <div className="flex gap-3">
                {processingMedia && (
                  <button
                    onClick={() => onRetry(processingMedia)}
                    className="flex items-center gap-2 px-5 h-11 rounded-[3px] bg-[oklch(74%_0.175_62)] hover:bg-[oklch(78%_0.175_65)] text-[oklch(14%_0.01_260)] text-[11px] font-mono uppercase tracking-[0.16em] font-semibold border border-[oklch(70%_0.18_62)] shadow-[0_1px_0_0_oklch(100%_0_0/0.3)_inset] active:translate-y-px transition-all"
                  >
                    <RotateCcw size={13} strokeWidth={2.2} /> Retry
                  </button>
                )}
                <button
                  onClick={onReset}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-[3px] bg-white/5 border border-white/10 text-zinc-300 text-sm font-medium hover:bg-white/10 transition-all"
                >
                  New Project
                </button>
              </div>
            </div>
          )}

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

      <LogsPanel
        logs={logs}
        visible={logsVisible}
        onToggle={onLogsToggle}
        showWaiting={status === 'processing'}
      />
    </div>
  );
}
