import React, { useState } from 'react';
import { AlertCircle, RotateCcw, Sparkles, Send } from 'lucide-react';
import ResultCard from './ResultCard';
import ProcessingAnimation from './ProcessingAnimation';
import LogsPanel from './LogsPanel';
import BatchPublishModal from './BatchPublishModal';

/**
 * Final-state view of the Dashboard tab: header, clip grid, optional error
 * banner with retry, and a collapsed logs panel.
 *
 * @param {{
 *   results: { clips?: Array<object>, cost_analysis?: object } | null,
 *   status: string,
 *   jobId: string | null,
 *   preselections: object | null,
 *   processingMedia: object | null,
 *   syncedTime: number,
 *   isSyncedPlaying: boolean,
 *   syncTrigger: number,
 *   logs: string[],
 *   logsVisible: boolean,
 *   onLogsToggle: () => void,
 *   onClipPlay: (time: number) => void,
 *   onClipPause: () => void,
 *   onRetry: (media: object) => void,
 * }} props
 */
export default function ResultsGrid({
  results,
  status,
  jobId,
  preselections,
  processingMedia,
  syncedTime,
  isSyncedPlaying,
  syncTrigger,
  logs,
  logsVisible,
  onLogsToggle,
  onClipPlay,
  onClipPause,
  onRetry,
  clipStates = {},
  onUpdateClipState = () => {},
}) {
  const [batchPublishOpen, setBatchPublishOpen] = useState(false);

  const allClips = results?.clips || [];
  // Filter out deleted clips from the grid
  const visibleClips = allClips
    .map((clip, i) => ({ clip, originalIndex: i }))
    .filter(({ originalIndex }) => !clipStates[originalIndex]?.deleted);
  const clipCount = visibleClips.length;

  // Clips eligible for batch publish: not deleted, not disabled, not already published
  const publishableClips = visibleClips.filter(({ originalIndex }) => {
    const state = clipStates[originalIndex] || {};
    return !state.disabled && !state.publishedAt;
  });

  return (
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
          {clipCount > 0 && (
            <div className="flex items-center gap-3 px-4 py-2 rounded-xl backdrop-blur-xl bg-white/5 border border-white/10">
              <span className="text-sm font-semibold text-white">{clipCount} clips</span>
              {results?.cost_analysis && (
                <>
                  <div className="h-4 w-px bg-white/10" />
                  <span
                    className="text-sm font-mono text-emerald-400"
                    title={`Tokens: ${results.cost_analysis.input_tokens}i / ${results.cost_analysis.output_tokens}o`}
                  >
                    ${results.cost_analysis.total_cost.toFixed(4)}
                  </span>
                </>
              )}
            </div>
          )}
          {publishableClips.length > 0 && (
            <button
              onClick={() => setBatchPublishOpen(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-accent-pink to-accent-purple text-white text-xs font-semibold shadow-glow-pink hover:opacity-90 transition-all"
              title="Publish all active, not-yet-published clips to social platforms via Zernio"
            >
              <Send size={13} />
              Publish all ({publishableClips.length})
            </button>
          )}
        </div>
      </div>

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

      {clipCount > 0 && (
        <div className="grid gap-6 grid-cols-1 lg:grid-cols-2">
          {visibleClips.map(({ clip, originalIndex }) => (
            <ResultCard
              key={originalIndex}
              clip={clip}
              index={originalIndex}
              jobId={jobId}
              preselections={preselections}
              onPlay={(time) => onClipPlay(time)}
              onPause={onClipPause}
              clipState={clipStates[originalIndex] || {}}
              onUpdateState={(patch) => onUpdateClipState(originalIndex, patch)}
            />
          ))}
        </div>
      )}

      <BatchPublishModal
        isOpen={batchPublishOpen}
        onClose={() => setBatchPublishOpen(false)}
        jobId={jobId}
        clips={publishableClips}
        onPublished={(originalIndex) => onUpdateClipState(originalIndex, { publishedAt: Date.now() })}
      />

      {status === 'error' && (
        <div className="rounded-2xl bg-red-500/10 border border-red-500/20 p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AlertCircle size={18} className="text-red-400 shrink-0" />
            <p className="text-sm text-red-400">
              Processing encountered an error. Some clips may be incomplete.
            </p>
          </div>
          {processingMedia && (
            <button
              onClick={() => onRetry(processingMedia)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-pink-500 to-purple-500 text-white text-xs font-semibold hover:opacity-90 transition-all shrink-0 ml-3"
            >
              <RotateCcw size={12} /> Retry
            </button>
          )}
        </div>
      )}

      <div className="opacity-60 hover:opacity-100 transition-opacity">
        <LogsPanel
          logs={logs}
          visible={logsVisible}
          onToggle={onLogsToggle}
          maxHeightClass="max-h-40"
        />
      </div>
    </div>
  );
}
