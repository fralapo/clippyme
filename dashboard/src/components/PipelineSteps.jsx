import React from 'react';
import { Check, Zap } from 'lucide-react';

// Human-friendly labels inspired by the NotebookLM UX brainstorm
// (Idleness Aversion / Operational Transparency): describe WHAT the
// system is doing, not its technical function names.
const STEPS = [
  { key: 'downloading', label: 'Scarico il video' },
  { key: 'transcribing', label: 'Ascolto l\u2019audio' },
  { key: 'analyzing', label: 'Cerco i momenti virali' },
  { key: 'processing', label: 'Monto le clip' },
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
      aria-valuetext={currentLabel ? `Fase ${currentIdx + 1} di ${STEPS.length}: ${currentLabel}` : 'In attesa'}
      aria-live="polite"
    >
      {STEPS.map((step, i) => {
        const isDone = i < currentIdx;
        const isActive = i === currentIdx;
        return (
          <React.Fragment key={step.key}>
            <div
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                isDone
                  ? 'text-emerald-400 bg-emerald-500/10'
                  : isActive
                  ? 'text-blue-400 bg-blue-500/10 border border-blue-500/20'
                  : 'text-zinc-600'
              }`}
            >
              {isDone ? <Check size={12} /> : isActive ? <Zap size={12} className="animate-pulse" /> : null}
              {step.label}
            </div>
            {i < STEPS.length - 1 && (
              <div className={`w-6 h-px ${isDone ? 'bg-emerald-500/50' : 'bg-zinc-800'}`} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}
