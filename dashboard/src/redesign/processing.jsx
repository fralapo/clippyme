// ClippyMe redesign — ProcessingView wired to real polling: live logs, a
// vertical pipeline driven by the detected step, and real clips streaming in
// as partial results arrive.
import { useEffect, useRef } from 'react';
import { Icon, Btn, Badge, Panel } from './primitives';
import { Hero } from './chrome';
import { PIPE } from './data';
import { clipVideoSrc, fmtDuration } from './realApi';

// Map the backend's detected pipeline step to an approximate % + pipe index.
// (The backend streams logs, not a numeric %, so this is a visual estimate.)
const STEP_INFO = {
  queued: { pct: 5, idx: 0 },
  downloading: { pct: 18, idx: 0 },
  transcribing: { pct: 38, idx: 1 },
  analyzing: { pct: 58, idx: 2 },
  processing: { pct: 80, idx: 3 },
};

function MiniClip({ clip, idx }) {
  return (
    <div className="clip fade-in" style={{ cursor: 'default' }}>
      <div className="clip-media" style={{ padding: 0, background: '#000' }}>
        <video src={clipVideoSrc(clip)} muted playsInline preload="metadata"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
        <div className="clip-top" style={{ padding: 8 }}>
          <span className="score" style={{ fontSize: 12, padding: '3px 7px' }}>{Math.round(clip.viral_score || 0)}</span>
        </div>
        <div className="clip-bottom" style={{ padding: 8 }}><span className="dur">{fmtDuration(clip.start, clip.end)}</span></div>
      </div>
    </div>
  );
}

export function ProcessingView({ media, status, logs = [], step, clips = [], onCancel, onRetry }) {
  const logRef = useRef(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; });

  const failed = status === 'error';
  const info = STEP_INFO[step] || STEP_INFO.queued;
  // Once clips start arriving, push the bar toward the finish.
  const clipBoost = clips.length > 0 ? Math.min(18, clips.length * 3) : 0;
  const pct = failed ? 100 : Math.min(96, info.pct + clipBoost);
  const activeIdx = clips.length > 0 ? Math.max(info.idx, 4) : info.idx;
  const sourceLabel = media?.type === 'url' ? media.payload : (media?.payload?.name || media?.payload || 'your video');
  // Honest phase word instead of a fabricated percentage (the backend streams
  // logs, not a number — the bar below is a coarse estimate, the word is the
  // ground truth from the detected step).
  const STEP_WORD = { queued: 'queued', downloading: 'fetching', transcribing: 'transcribing', analyzing: 'scoring', processing: 'rendering' };
  const phase = failed ? 'failed' : clips.length > 0 ? 'rendering' : (STEP_WORD[step] || 'working');

  return (
    <div className="container fade-in">
      <Hero eyebrow={failed ? 'Pipeline error' : 'Pipeline running'}
        line1={failed ? 'Something broke.' : 'Cutting your clips.'}
        sub={failed ? 'The job failed. Check the log below, then retry or start over.'
          : "ClippyMe is working through the pipeline. Clips show up below the moment each one is rendered, so you don't have to wait for the whole batch."} />
      <div className="proc">
        <aside className="proc-aside">
          <Panel pad={true}>
            <div className="pipe">
              {PIPE.map((s, i) => {
                const done = !failed && (i < activeIdx);
                const active = !failed && i === activeIdx;
                return (
                  <div key={s.id} className={'pstep' + (done ? ' done' : active ? ' active' : '')}>
                    <div className="rail">
                      <div className="pdot"><Icon n={done ? 'check' : s.icon} /></div>
                      {i < PIPE.length - 1 && <div className="pseg-v"></div>}
                    </div>
                    <div className="pbody">
                      <div className="pname">{s.name}</div>
                      <div className="pmeta">{active ? s.meta + ' …' : done ? 'done' : s.meta}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </aside>

        <div>
          <Panel pad={true}>
            <div className="pbar-wrap">
              <div className="pbar"><i style={{ width: pct + '%', background: failed ? 'var(--danger)' : undefined }}></i></div>
              <div className="pbar-pct" style={{ fontFamily: 'var(--font-mono)', fontSize: 13, letterSpacing: '.04em', minWidth: 110, color: failed ? 'var(--danger)' : 'var(--blue-300)' }}>{phase}</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16, gap: 10 }}>
              <span className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
                <span className="mono" style={{ color: 'var(--fg-4)' }}>src ·</span> {String(sourceLabel).slice(0, 46)}
              </span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                {failed && <Btn variant="secondary" size="sm" icon="wand-sparkles" onClick={onRetry}>Retry</Btn>}
                <Btn variant="ghost" size="sm" icon="x" onClick={onCancel}>{failed ? 'Start over' : 'Cancel'}</Btn>
              </span>
            </div>
            <div className="log" ref={logRef}>
              {logs.length === 0 && <div className="ln"><span className="ts">··</span> <span>waiting for the worker…</span></div>}
              {logs.map((l, i) => (
                <div key={i} className="ln">
                  <span className={/error/i.test(l) ? '' : /✓|done|complete|found/i.test(l) ? 'ok' : ''}
                    style={/error/i.test(l) ? { color: 'var(--danger)' } : undefined}>{l}</span>
                </div>
              ))}
              {!failed && <div><span className="cursor"></span></div>}
            </div>
          </Panel>

          <div className="stream-head">
            <h3>Clips</h3>
            {clips.length > 0
              ? <Badge tone="teal" icon="check">{clips.length} ready</Badge>
              : <Badge tone="out">{failed ? 'no clips' : 'finding moments…'}</Badge>}
          </div>
          <div className="stream">
            {clips.slice(0, 8).map((c, i) => <MiniClip key={c.original_index ?? i} clip={c} idx={i} />)}
            {!failed && clips.length < 4 && Array.from({ length: 4 - clips.length }).map((_, i) => (
              <div key={'slot' + i} className="slot">{i === 0 && clips.length > 0 ? <div className="sk"></div> : (clips.length === 0 && i === 0 ? <div className="sk"></div> : null)}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
