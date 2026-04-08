import React from 'react';
import { Check, Zap } from 'lucide-react';

// Human-friendly labels inspired by the NotebookLM UX brainstorm
// (Idleness Aversion / Operational Transparency): describe WHAT the
// system is doing, not its technical function names.
const STEPS = [
  { key: 'downloading', label: 'Downloading video' },
  { key: 'transcribing', label: 'Listening to audio' },
  { key: 'analyzing', label: 'Finding viral moments' },
  { key: 'processing', label: 'Editing clips' },
];

const STEP_KEYS = STEPS.map((s) => s.key);

/**
 * Horizontal pipeline progress indicator. Shows which step of the
 * download → transcribe → analyze → render flow is currently active.
 *
 * @param {{ currentStep: string | null }} props
 */
export default function PipelineSteps({ currentStep }) {
  const currentIdx = STEP_KEYS.indexOf(currentStep);
  const currentLabel = currentIdx >= 0 ? STEPS[currentIdx].label : '';
  return (
    <div
      className="flex items-center gap-2 flex-wrap"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={STEPS.length}
      aria-valuenow={Math.max(0, currentIdx + 1)}
      aria-valuetext={currentLabel ? `Step ${currentIdx + 1} of ${STEPS.length}: ${currentLabel}` : 'Waiting'}
      aria-live="polite"
    >
      {STEPS.map((step, i) => {
        const isDone = i < currentIdx;
        const isActive = i === currentIdx;
        return (
          <React.Fragment key={step.key}>
            <div
              className={`flex items-center gap-2 px-3 h-8 rounded-[2px] border font-mono text-[11px] uppercase tracking-[0.12em] transition-all ${
                isDone
                  ? 'text-[oklch(78%_0.17_145)] border-[oklch(68%_0.18_145)]/35 bg-[oklch(68%_0.18_145)]/[0.08]'
                  : isActive
                  ? 'text-[oklch(82%_0.16_68)] border-[oklch(74%_0.175_62)]/50 bg-[oklch(74%_0.175_62)]/[0.1] shadow-[0_0_12px_-4px_oklch(74%_0.175_62/0.6)]'
                  : 'text-zinc-600 border-white/[0.06] bg-transparent'
              }`}
            >
              <span className="type-mono text-[9px] tabular-nums opacity-70">
                {String(i + 1).padStart(2, '0')}
              </span>
              {isDone ? (
                <Check size={11} strokeWidth={2.4} />
              ) : isActive ? (
                <Zap size={11} strokeWidth={2.2} className="animate-pulse" />
              ) : null}
              <span>{step.label}</span>
            </div>
            {i < STEPS.length - 1 && (
              <div
                className={`w-6 h-px ${
                  isDone ? 'bg-[oklch(68%_0.18_145)]/60' : isActive ? 'bg-[oklch(74%_0.175_62)]/40' : 'bg-zinc-800'
                }`}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}
