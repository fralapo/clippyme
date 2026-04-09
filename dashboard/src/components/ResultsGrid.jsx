import React, { useMemo, useState } from 'react';
import { AlertCircle, RotateCcw, Sparkles, Send, ArrowUpDown, Check, EyeOff, ChevronDown, ChevronUp } from 'lucide-react';
import ResultCard from './ResultCard';
import ProcessingAnimation from './ProcessingAnimation';
import LogsPanel from './LogsPanel';
import BatchPublishModal from './BatchPublishModal';

const SORT_OPTIONS = [
  { id: 'viral_desc', label: 'Highest viral score' },
  { id: 'order', label: 'Original order' },
  { id: 'duration_asc', label: 'Shortest first' },
  { id: 'duration_desc', label: 'Longest first' },
];

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
  const [sortBy, setSortBy] = useState('viral_desc');
  // Collapse the source-video preview once the job is complete — users
  // want the clips grid, not a big player of the original 1h video.
  const [sourcePreviewOpen, setSourcePreviewOpen] = useState(status !== 'complete');

  const allClips = results?.clips || [];
  // Filter out deleted clips from the grid.
  //
  // CRITICAL: `originalIndex` MUST come from `clip.original_index` emitted
  // by the backend _build_clips(), NOT the position in the returned array.
  // During partial-result polling the backend returns only ready clips,
  // so positional index shifts as more clips come online — which would
  // cause React to reconcile a stale <video> element with a different
  // clip's video_url (grey-screen bug while processing). Falling back
  // to positional index only for legacy/restore paths that don't ship
  // the field yet.
  const visibleClips = useMemo(() => {
    const base = allClips
      .map((clip, i) => ({
        clip,
        originalIndex: typeof clip.original_index === 'number' ? clip.original_index : i,
      }))
      .filter(({ originalIndex }) => !clipStates[originalIndex]?.deleted);

    const sorted = [...base];
    if (sortBy === 'viral_desc') {
      sorted.sort((a, b) => (b.clip.viral_score || 0) - (a.clip.viral_score || 0));
    } else if (sortBy === 'duration_asc') {
      sorted.sort((a, b) => (a.clip.end - a.clip.start) - (b.clip.end - b.clip.start));
    } else if (sortBy === 'duration_desc') {
      sorted.sort((a, b) => (b.clip.end - b.clip.start) - (a.clip.end - a.clip.start));
    }
    // else: keep original order

    // Annotate each entry with its rank (by viral score, global across visible)
    const byScore = [...base].sort((a, b) => (b.clip.viral_score || 0) - (a.clip.viral_score || 0));
    const rankMap = new Map(byScore.map((entry, i) => [entry.originalIndex, i + 1]));

    return sorted.map((entry) => ({ ...entry, rank: rankMap.get(entry.originalIndex) }));
  }, [allClips, clipStates, sortBy]);

  const clipCount = visibleClips.length;

  // Stats for the header: how many are published / disabled / publishable
  const stats = useMemo(() => {
    let published = 0;
    let disabled = 0;
    let publishable = 0;
    for (const { originalIndex } of visibleClips) {
      const state = clipStates[originalIndex] || {};
      if (state.publishedAt) published += 1;
      if (state.disabled) disabled += 1;
      if (!state.disabled && !state.publishedAt) publishable += 1;
    }
    return { published, disabled, publishable };
  }, [visibleClips, clipStates]);

  const publishableClips = visibleClips.filter(({ originalIndex }) => {
    const state = clipStates[originalIndex] || {};
    return !state.disabled && !state.publishedAt;
  });

  return (
    <div className="space-y-8">
      {/* Results masthead — serif headline + mono deck line */}
      <header className="space-y-4">
        <div className="flex items-baseline gap-3 text-zinc-600">
          <span className="type-label">Results</span>
          <hr className="hairline flex-1" />
          <span className="type-label tabular-nums">
            {String(clipCount).padStart(2, '0')}&nbsp;clips
          </span>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-5">
          <div className="space-y-3">
            <h2 className="type-display text-[clamp(2.25rem,5vw,3.75rem)] text-white flex items-baseline gap-4">
              <Sparkles size={28} className="text-[oklch(74%_0.175_62)] shrink-0 self-center" strokeWidth={1.4} />
              <span>
                {clipCount > 0 ? (
                  <>
                    <em className="not-italic text-white">Your clips,</em>{' '}
                    <span className="italic text-zinc-400 font-light">ready to publish</span>
                  </>
                ) : (
                  <span className="italic text-zinc-400 font-light">Waiting for clips…</span>
                )}
              </span>
            </h2>
            {clipCount > 0 ? (
              <div className="flex items-center gap-3 flex-wrap text-[11px] font-mono uppercase tracking-[0.14em] text-zinc-500">
                <span>
                  <span className="text-zinc-600">Sort&nbsp;/&nbsp;</span>
                  {SORT_OPTIONS.find((s) => s.id === sortBy)?.label}
                </span>
                {stats.published > 0 && (
                  <span className="inline-flex items-center gap-1.5 px-2 py-1 border border-[oklch(68%_0.18_145)]/30 text-[oklch(78%_0.17_145)] bg-[oklch(68%_0.18_145)]/[0.06]">
                    <Check size={10} strokeWidth={2.4} /> {String(stats.published).padStart(2, '0')}&nbsp;published
                  </span>
                )}
                {stats.disabled > 0 && (
                  <span className="inline-flex items-center gap-1.5 px-2 py-1 border border-white/10 text-zinc-500 bg-white/[0.02]">
                    <EyeOff size={10} strokeWidth={2.2} /> {String(stats.disabled).padStart(2, '0')}&nbsp;muted
                  </span>
                )}
                {results?.cost_analysis && (
                  <span
                    className="inline-flex items-center gap-1.5 px-2 py-1 border border-white/10 text-zinc-400 bg-white/[0.02] tabular-nums"
                    title={`Tokens: ${results.cost_analysis.input_tokens}i / ${results.cost_analysis.output_tokens}o`}
                  >
                    ${results.cost_analysis.total_cost.toFixed(4)}&nbsp;Gemini
                  </span>
                )}
              </div>
            ) : (
              <p className="type-label !normal-case !tracking-normal !text-sm !font-sans text-zinc-500 max-w-lg">
                High-engagement segments, curated by Gemini against a 5-axis rubric.
              </p>
            )}
          </div>

          {/* Control rail */}
          <div className="flex items-stretch gap-2 flex-wrap">
            {clipCount > 1 && (
              <div className="relative">
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                  className="appearance-none bg-white/[0.02] border border-white/10 hover:border-white/25 text-zinc-200 text-[11px] font-mono uppercase tracking-[0.12em] px-3.5 pr-9 h-11 rounded-[3px] cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/50"
                  title="Sort clips"
                >
                  {SORT_OPTIONS.map((opt) => (
                    <option key={opt.id} value={opt.id} className="bg-background text-white">
                      {opt.label}
                    </option>
                  ))}
                </select>
                <ArrowUpDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
              </div>
            )}
            {publishableClips.length > 0 && (
              <button
                onClick={() => setBatchPublishOpen(true)}
                className="group flex items-center gap-2.5 h-11 px-4 rounded-[3px] bg-[oklch(74%_0.175_62)] hover:bg-[oklch(78%_0.175_65)] text-[oklch(12%_0.01_260)] text-[11px] font-mono uppercase tracking-[0.16em] font-semibold border border-[oklch(70%_0.18_62)] shadow-[0_1px_0_0_oklch(100%_0_0/0.3)_inset,0_10px_24px_-14px_oklch(74%_0.175_62/0.55)] active:translate-y-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)] focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                title={`Publish ${publishableClips.length} active clips (ignores disabled and already-published)`}
              >
                <Send size={13} strokeWidth={2.2} />
                Publish&nbsp;
                <span className="tabular-nums">
                  {String(publishableClips.length).padStart(2, '0')}
                </span>
              </button>
            )}
          </div>
        </div>
      </header>

      {processingMedia && (
        <div className="rounded-[3px] bg-[oklch(9%_0.006_260)] border border-white/5 overflow-hidden">
          {/* Collapsible source-preview. When the job is done the user
              wants the clip grid, not a big player of the original video,
              so we default to collapsed on completion. */}
          <button
            type="button"
            onClick={() => setSourcePreviewOpen((v) => !v)}
            className="w-full px-5 py-2.5 flex items-center justify-between hover:bg-white/[0.02] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[oklch(74%_0.175_62)]/50"
            title={sourcePreviewOpen ? 'Hide source preview' : 'Show source preview'}
          >
            <span className="type-label flex items-center gap-2.5">
              Source preview
              <span className="type-mono text-[10px] text-zinc-600 normal-case tracking-normal">
                {status === 'complete' ? 'Job complete' : 'Live'}
              </span>
            </span>
            {sourcePreviewOpen ? (
              <ChevronUp size={12} className="text-zinc-600" />
            ) : (
              <ChevronDown size={12} className="text-zinc-600" />
            )}
          </button>
          {sourcePreviewOpen && (
            <div className="border-t border-white/5 p-4">
              <ProcessingAnimation
                media={processingMedia}
                isComplete={status === 'complete'}
                syncedTime={syncedTime}
                isSyncedPlaying={isSyncedPlaying}
                syncTrigger={syncTrigger}
              />
            </div>
          )}
        </div>
      )}

      {clipCount > 0 && (publishableClips.length > 0 || clipCount > 1) && (
        /* Sticky action rail — stays pinned under the top nav while the user
           scrolls through a long clip list, so 'Publish all' and 'Sort' are
           always one click away. Editorial hairline border + backdrop blur
           to stay legible over whatever grid section sits behind it. */
        <div className="sticky top-[56px] z-40 -mx-4 px-4 py-2 backdrop-blur-md bg-[oklch(9%_0.006_260)]/82 border-y border-white/[0.06]">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="type-label flex items-center gap-3 text-zinc-500">
              <span>
                <span className="text-zinc-700">on&nbsp;grid&nbsp;/&nbsp;</span>
                <span className="tabular-nums text-zinc-300">{String(clipCount).padStart(2, '0')}</span>
              </span>
              {stats.published > 0 && (
                <span className="text-[oklch(78%_0.17_145)] tabular-nums">
                  · {String(stats.published).padStart(2, '0')}&nbsp;live
                </span>
              )}
              {stats.disabled > 0 && (
                <span className="text-zinc-600 tabular-nums">
                  · {String(stats.disabled).padStart(2, '0')}&nbsp;muted
                </span>
              )}
            </div>
            <div className="flex items-stretch gap-2">
              {clipCount > 1 && (
                <div className="relative">
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    className="appearance-none bg-white/[0.02] border border-white/10 hover:border-white/20 text-zinc-200 text-[10px] font-mono uppercase tracking-[0.12em] pl-3 pr-8 h-9 rounded-[3px] cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/50"
                  >
                    {SORT_OPTIONS.map((opt) => (
                      <option key={opt.id} value={opt.id} className="bg-background text-white">
                        {opt.label}
                      </option>
                    ))}
                  </select>
                  <ArrowUpDown size={11} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
                </div>
              )}
              {publishableClips.length > 0 && (
                <button
                  onClick={() => setBatchPublishOpen(true)}
                  className="flex items-center gap-2 h-9 px-3.5 rounded-[3px] bg-[oklch(74%_0.175_62)] hover:bg-[oklch(78%_0.175_65)] text-[oklch(12%_0.01_260)] text-[10px] font-mono uppercase tracking-[0.14em] font-semibold border border-[oklch(70%_0.18_62)] shadow-[0_6px_18px_-10px_oklch(74%_0.175_62/0.6)] active:translate-y-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]"
                  title={`Publish ${publishableClips.length} active clips`}
                >
                  <Send size={11} strokeWidth={2.4} />
                  Publish&nbsp;
                  <span className="tabular-nums">{String(publishableClips.length).padStart(2, '0')}</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {clipCount > 0 && (
        /* Single flat grid. The previous tier grouping (High viral /
           Good candidates / Lower score) was confusing because users
           didn't realise "Good candidates" was still the same sorted
           list — just broken up with a section header. Now every clip
           lives in one grid, already ordered by the active `sortBy`
           (defaults to viral_desc). Viral score is still rendered on
           each card so the visual hierarchy is preserved without the
           artificial chapter breaks. */
        <div className="grid gap-6 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
          {visibleClips.map(({ clip, originalIndex, rank }, i) => (
            <div
              key={originalIndex}
              className="animate-rise-in"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <ResultCard
                clip={clip}
                index={originalIndex}
                rank={rank}
                totalClips={visibleClips.length}
                jobId={jobId}
                preselections={preselections}
                onPlay={(time) => onClipPlay(time)}
                onPause={onClipPause}
                clipState={clipStates[originalIndex] || {}}
                onUpdateState={(patch) => onUpdateClipState(originalIndex, patch)}
              />
            </div>
          ))}
        </div>
      )}

      <BatchPublishModal
        isOpen={batchPublishOpen}
        onClose={() => setBatchPublishOpen(false)}
        jobId={jobId}
        clips={publishableClips}
        clipStates={clipStates}
        onPublished={(originalIndex) => onUpdateClipState(originalIndex, { publishedAt: Date.now() })}
      />

      {status === 'error' && (
        <div className="rounded-[3px] bg-red-500/10 border border-red-500/20 p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AlertCircle size={18} className="text-red-400 shrink-0" />
            <p className="text-sm text-red-400">
              Processing encountered an error. Some clips may be incomplete.
            </p>
          </div>
          {processingMedia && (
            <button
              onClick={() => onRetry(processingMedia)}
              className="flex items-center gap-2 px-4 h-10 rounded-[3px] bg-[oklch(74%_0.175_62)] hover:bg-[oklch(78%_0.175_65)] text-[oklch(14%_0.01_260)] text-[11px] font-mono uppercase tracking-[0.16em] font-semibold border border-[oklch(70%_0.18_62)] transition-all shrink-0 ml-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/60"
            >
              <RotateCcw size={12} strokeWidth={2.2} /> Retry
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
