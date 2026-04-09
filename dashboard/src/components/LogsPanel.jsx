import React, { useMemo, useRef, useEffect, useState } from 'react';
import { ChevronDown, Terminal, Copy, Check } from 'lucide-react';

/**
 * Classify a log line into a level based on emoji/keyword prefixes.
 * Returned level drives both the gutter dot color and the text tone.
 *
 * @param {string} line
 * @returns {'ok'|'warn'|'err'|'step'|'info'}
 */
function classify(line) {
  // Structured key=value observability fields like "error=none" /
  // "error=null" / "error=0" / "error=false" are NOT errors — strip them
  // before the keyword scan so a successful parse log doesn't light up
  // the gutter red.
  const scan = line.replace(/\berror=(none|null|0|false)\b/gi, '');
  if (/\b(error|failed|exception|traceback)\b/i.test(scan)) return 'err';
  if (/^\s*(⚠️|warning|⚠)/i.test(line) || /\b(deprecated|warn)\b/i.test(line)) return 'warn';
  if (/^\s*(✅|✔|success|done|complete)/i.test(line)) return 'ok';
  if (/^\s*(🎬|🎙|📥|🔍|🎯|🧠|⚙|🚀|▶|—)/i.test(line)) return 'step';
  return 'info';
}

/**
 * Progress-like lines we want to collapse into a single "live" row whose
 * text keeps mutating as new lines arrive. These patterns are spam-prone:
 * yt-dlp fragment counters, ffmpeg `frame=… fps=…` progress, percentage bars.
 */
const PROGRESS_PATTERNS = [
  /^\s*\[download\]/i,
  /^\s*frame=\s*\d+/i,
  /^\s*size=/i,
  /^\s*\d+(\.\d+)?%\s/,
];

function isProgress(line) {
  return PROGRESS_PATTERNS.some((re) => re.test(line));
}

/**
 * Build a compacted view of the log stream:
 *   1. Collapse runs of contiguous identical lines into `{ text, count }`.
 *   2. Collapse consecutive progress-like lines into one entry whose text
 *      is the latest value (so the UI shows a live-updating counter
 *      instead of 900 identical-looking rows).
 *
 * Returns an array of entries: `{ id, text, level, count, kind }`.
 */
function compactLogs(logs) {
  const out = [];
  let i = 0;
  while (i < logs.length) {
    const line = logs[i];
    // Progress spam: fold the whole contiguous run into one live row.
    if (isProgress(line)) {
      let j = i + 1;
      while (j < logs.length && isProgress(logs[j])) j += 1;
      out.push({
        id: i,
        text: logs[j - 1], // show the most recent progress state
        level: 'info',
        count: j - i,
        kind: 'progress',
      });
      i = j;
      continue;
    }
    // Exact duplicate run: coalesce into one row + ×N badge.
    let j = i + 1;
    while (j < logs.length && logs[j] === line) j += 1;
    out.push({
      id: i,
      text: line,
      level: classify(line),
      count: j - i,
      kind: 'line',
    });
    i = j;
  }
  return out;
}

const LEVEL_STYLES = {
  ok:   { dot: 'bg-[oklch(68%_0.18_145)] shadow-[0_0_5px_oklch(68%_0.18_145/0.7)]', text: 'text-[oklch(78%_0.17_145)]' },
  warn: { dot: 'bg-[oklch(80%_0.17_75)]  shadow-[0_0_5px_oklch(80%_0.17_75/0.7)]',  text: 'text-[oklch(82%_0.15_75)]' },
  err:  { dot: 'bg-[oklch(62%_0.22_25)]  shadow-[0_0_5px_oklch(62%_0.22_25/0.7)]',  text: 'text-[oklch(78%_0.2_25)]' },
  step: { dot: 'bg-[oklch(74%_0.175_62)] shadow-[0_0_5px_oklch(74%_0.175_62/0.7)]', text: 'text-[oklch(86%_0.07_85)]' },
  info: { dot: 'bg-zinc-700', text: 'text-zinc-500' },
};

/**
 * Collapsible live log panel.
 *
 * Visual optimizations:
 *  - Repeated lines are coalesced into a single row with a ×N badge.
 *  - Progress-spam (yt-dlp [download], ffmpeg frame=…, %) collapses into
 *    one live row whose text updates to the latest value.
 *  - Level is inferred from emoji/keyword prefix → colored gutter dot.
 *  - Line numbers replace the fake timestamps from the previous version.
 *  - Auto-scroll follows the tail when the user hasn't scrolled up.
 *
 * @param {{
 *   logs: string[],
 *   visible: boolean,
 *   onToggle: () => void,
 *   maxHeightClass?: string,
 *   showWaiting?: boolean,
 * }} props
 */
export default function LogsPanel({
  logs,
  visible,
  onToggle,
  maxHeightClass = 'max-h-64',
  showWaiting = false,
}) {
  const scrollRef = useRef(null);
  const stuckToBottomRef = useRef(true);
  const [copied, setCopied] = useState(false);

  const compact = useMemo(() => compactLogs(logs || []), [logs]);

  const handleCopy = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText((logs || []).join('\n'));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard API unavailable — silently ignore
    }
  };

  // Auto-scroll follows the tail unless the user scrolled up.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !visible) return;
    if (stuckToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [compact, visible]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stuckToBottomRef.current = distanceFromBottom < 24;
  };

  const totalLines = logs?.length || 0;
  const rowCount = compact.length;

  return (
    <div className="rounded-[3px] bg-[oklch(9%_0.006_260)] border border-white/[0.07] overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-5 py-2.5 flex items-center justify-between hover:bg-white/[0.02] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[oklch(74%_0.175_62)]/50"
      >
        <span className="type-label flex items-center gap-2.5">
          <Terminal size={12} strokeWidth={1.8} />
          Live&nbsp;logs
          {totalLines > 0 && (
            <span className="type-mono text-[10px] text-zinc-700 tabular-nums normal-case tracking-normal">
              {rowCount}&nbsp;rows&nbsp;/&nbsp;{totalLines}&nbsp;lines
            </span>
          )}
        </span>
        <span className="flex items-center gap-2">
          {totalLines > 0 && (
            <span
              role="button"
              tabIndex={0}
              onClick={handleCopy}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleCopy(e); }}
              title="Copy all logs"
              className="flex items-center gap-1 type-mono text-[10px] uppercase tracking-[0.08em] text-zinc-500 hover:text-[oklch(86%_0.07_85)] px-2 py-1 rounded-[2px] hover:bg-white/[0.04] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[oklch(74%_0.175_62)]/50"
            >
              {copied ? <Check size={11} strokeWidth={2} /> : <Copy size={11} strokeWidth={1.8} />}
              {copied ? 'Copied' : 'Copy'}
            </span>
          )}
          <ChevronDown
            size={12}
            className={`text-zinc-600 transition-transform ${visible ? '' : 'rotate-180'}`}
          />
        </span>
      </button>
      {visible && (
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className={`border-t border-white/5 ${maxHeightClass} overflow-y-auto font-mono text-[11px] leading-[1.55]`}
        >
          {rowCount === 0 && !showWaiting && (
            <div className="px-5 py-4 type-label">No output yet</div>
          )}
          {compact.map((row, idx) => {
            const styles = LEVEL_STYLES[row.level] || LEVEL_STYLES.info;
            const isProgressRow = row.kind === 'progress';
            return (
              <div
                key={row.id}
                className="flex items-start gap-3 px-5 py-[3px] hover:bg-white/[0.015] border-l-2 border-transparent hover:border-[oklch(74%_0.175_62)]/25 transition-colors"
              >
                {/* Gutter: line index + level dot */}
                <span className="type-mono text-[9px] text-zinc-700 tabular-nums shrink-0 w-7 text-right select-none pt-[3px]">
                  {String(idx + 1).padStart(3, '0')}
                </span>
                <span
                  aria-hidden
                  className={`w-1.5 h-1.5 rounded-full shrink-0 mt-[7px] ${styles.dot}`}
                />
                <span className={`break-words flex-1 min-w-0 ${styles.text}`}>
                  {row.text}
                  {isProgressRow && row.count > 1 && (
                    <span className="ml-2 type-mono text-[9px] text-zinc-700 tabular-nums">
                      live&nbsp;·&nbsp;{row.count}&nbsp;frames
                    </span>
                  )}
                </span>
                {!isProgressRow && row.count > 1 && (
                  <span
                    className="type-mono text-[9px] font-semibold tabular-nums shrink-0 px-1.5 py-0.5 rounded-[2px] bg-white/[0.04] border border-white/[0.08] text-zinc-400 mt-[2px]"
                    title={`${row.count} identical lines coalesced`}
                  >
                    ×{row.count}
                  </span>
                )}
              </div>
            );
          })}
          {showWaiting && (
            <div className="px-5 py-2 flex items-center gap-2 type-label !text-[oklch(74%_0.175_62)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[oklch(74%_0.175_62)] animate-pulse shadow-[0_0_6px_oklch(74%_0.175_62/0.8)]" />
              Waiting for output
            </div>
          )}
        </div>
      )}
    </div>
  );
}
