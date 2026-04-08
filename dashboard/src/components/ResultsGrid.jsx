import React, { useMemo, useState } from 'react';
import { AlertCircle, RotateCcw, Sparkles, Send, ArrowUpDown, Check, EyeOff } from 'lucide-react';
import ResultCard from './ResultCard';
import ProcessingAnimation from './ProcessingAnimation';
import LogsPanel from './LogsPanel';
import BatchPublishModal from './BatchPublishModal';

const SORT_OPTIONS = [
  { id: 'viral_desc', label: 'Per viral score' },
  { id: 'order', label: 'Ordine originale' },
  { id: 'duration_asc', label: 'Più corte prima' },
  { id: 'duration_desc', label: 'Più lunghe prima' },
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

  const allClips = results?.clips || [];
  // Filter out deleted clips from the grid
  const visibleClips = useMemo(() => {
    const base = allClips
      .map((clip, i) => ({ clip, originalIndex: i }))
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
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-white flex items-center gap-2">
              <Sparkles size={22} className="text-purple-400" />
              {clipCount > 0
                ? `${clipCount} clip pronte${clipCount === 1 ? '' : ''}`
                : 'Le tue clip'}
            </h2>
            {clipCount > 0 ? (
              <p className="text-zinc-500 text-xs mt-1.5 flex items-center gap-2 flex-wrap">
                <span>Ordinate: {SORT_OPTIONS.find((s) => s.id === sortBy)?.label.toLowerCase()}</span>
                {stats.published > 0 && (
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300">
                    <Check size={9} /> {stats.published} pubblicate
                  </span>
                )}
                {stats.disabled > 0 && (
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-white/[0.04] text-zinc-500">
                    <EyeOff size={9} /> {stats.disabled} disattivate
                  </span>
                )}
                {results?.cost_analysis && (
                  <span
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-white/[0.04] font-mono text-emerald-400/80"
                    title={`Tokens: ${results.cost_analysis.input_tokens}i / ${results.cost_analysis.output_tokens}o`}
                  >
                    ${results.cost_analysis.total_cost.toFixed(4)} Gemini
                  </span>
                )}
              </p>
            ) : (
              <p className="text-zinc-500 text-sm mt-1">Momenti ad alto potenziale virale individuati dall&apos;AI</p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {clipCount > 1 && (
              <div className="relative">
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                  className="appearance-none bg-white/[0.04] border border-white/5 text-zinc-300 text-xs font-medium px-3 py-2 pr-8 rounded-xl hover:bg-white/[0.06] cursor-pointer focus:outline-none focus:ring-2 focus:ring-accent-pink/30"
                  title="Sort clips"
                >
                  {SORT_OPTIONS.map((opt) => (
                    <option key={opt.id} value={opt.id} className="bg-[#0f0f13]">
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
                className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-accent-pink to-accent-purple text-white text-xs font-semibold shadow-glow-pink hover:opacity-90 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-pink/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0f0f13] min-h-[44px]"
                title={`Pubblica ${publishableClips.length} clip attive (ignora disattivate e già pubblicate)`}
              >
                <Send size={13} />
                {publishableClips.length === 1
                  ? 'Pubblica 1 clip selezionata'
                  : `Pubblica ${publishableClips.length} clip selezionate`}
              </button>
            )}
          </div>
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

      {clipCount > 0 && sortBy === 'viral_desc' ? (
        // Chunked view: group clips by viral_score tier so the grid is
        // scannable even with 15+ clips (Law of Miller — chunking).
        // Tiers inspired by the NotebookLM brainstorm recommendation.
        (() => {
          const tiers = [
            { id: 'top', label: 'Top virali', hint: 'Score 80+ \u2014 pubblica questi per primi', min: 80, max: 101 },
            { id: 'mid', label: 'Buone candidate', hint: 'Score 50\u201379 \u2014 ottimizzabili con Smart Cut e hook', min: 50, max: 80 },
            { id: 'low', label: 'Menzioni', hint: 'Score <50 \u2014 valuta se scartarle', min: 0, max: 50 },
          ];
          const groups = tiers
            .map((tier) => ({
              ...tier,
              entries: visibleClips.filter(({ clip }) => {
                const s = clip.viral_score || 0;
                return s >= tier.min && s < tier.max;
              }),
            }))
            .filter((g) => g.entries.length > 0);

          return (
            <div className="space-y-8">
              {groups.map((group) => (
                <section key={group.id} aria-labelledby={`tier-${group.id}`}>
                  <header className="flex items-baseline justify-between mb-3 pb-2 border-b border-white/5">
                    <h3
                      id={`tier-${group.id}`}
                      className="text-[11px] font-semibold uppercase tracking-[0.15em] text-zinc-400"
                    >
                      {group.label}
                      <span className="ml-2 text-zinc-600 font-normal normal-case tracking-normal">
                        ({group.entries.length})
                      </span>
                    </h3>
                    <p className="text-[10px] text-zinc-600 hidden sm:block">{group.hint}</p>
                  </header>
                  <div className="grid gap-5 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
                    {group.entries.map(({ clip, originalIndex, rank }) => (
                      <ResultCard
                        key={originalIndex}
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
                    ))}
                  </div>
                </section>
              ))}
            </div>
          );
        })()
      ) : (
        clipCount > 0 && (
          <div className="grid gap-5 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
            {visibleClips.map(({ clip, originalIndex, rank }) => (
              <ResultCard
                key={originalIndex}
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
            ))}
          </div>
        )
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
              Qualcosa è andato storto durante l&apos;elaborazione. Alcune clip potrebbero essere incomplete.
            </p>
          </div>
          {processingMedia && (
            <button
              onClick={() => onRetry(processingMedia)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-pink-500 to-purple-500 text-white text-xs font-semibold hover:opacity-90 transition-all shrink-0 ml-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-pink/60 min-h-[40px]"
            >
              <RotateCcw size={12} /> Riprova
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
