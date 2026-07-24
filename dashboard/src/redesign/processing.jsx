// ClippyMe processing view: live logs, durable pipeline progress, operational
// metrics and clips streamed as soon as each checkpointed render is verified.
import { useEffect, useMemo, useRef } from 'react';
import { Icon, Btn, Badge, Panel } from './primitives';
import { Hero } from './chrome';
import { PIPE } from './data';
import { pipelineStepMeta } from '../lib/pipelineStep';
import { clipVideoSrc, fmtDuration } from './realApi';
import { latestRuntimeTelemetry, formatEta, formatMetric } from '../lib/runtimeTelemetry';

const STEP_INFO = {
  queued: { pct: 5, idx: 0 },
  acquiring: { pct: 12, idx: 0 },
  downloading: { pct: 18, idx: 0 },
  preflight: { pct: 22, idx: 0 },
  transcribing: { pct: 38, idx: 1 },
  analyzing: { pct: 58, idx: 2 },
  cutting: { pct: 68, idx: 3 },
  reframing: { pct: 82, idx: 3 },
  quality: { pct: 93, idx: 4 },
  finalizing: { pct: 97, idx: 4 },
  processing: { pct: 80, idx: 3 },
};

function MiniClip({ clip }) {
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

function Metric({ label, value, hint }) {
  return (
    <div style={{ minWidth: 112, flex: '1 1 112px', border: '1px solid var(--line)', borderRadius: 10,
      padding: '10px 12px', background: 'var(--bg-2)' }}>
      <div className="label" style={{ fontSize: 10, marginBottom: 4 }}>{label}</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, color: 'var(--fg-1)' }}>{value}</div>
      {hint && <div style={{ fontSize: 11, color: 'var(--fg-4)', marginTop: 2 }}>{hint}</div>}
    </div>
  );
}

function Operations({ runtime, preflight }) {
  if (!runtime && !preflight) return null;
  const attempt = runtime?.attempt || '—';
  const clips = runtime?.clips || '0/0';
  return (
    <div style={{ marginBottom: 16 }}>
      <div className="stream-head" style={{ marginTop: 0, marginBottom: 8 }}>
        <h3 style={{ fontSize: 14 }}>Operations</h3>
        {runtime?.stage && <Badge tone="out">{runtime.stage}</Badge>}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        <Metric label="attempt" value={attempt} hint="bounded retry" />
        <Metric label="verified clips" value={clips} hint="QA passed" />
        <Metric label="ETA" value={formatEta(runtime?.eta_s)} hint="live estimate" />
        <Metric label="CPU" value={formatMetric(runtime?.cpu, '%')} />
        <Metric label="job RAM" value={formatMetric(runtime?.rss_mb, ' MB')} />
        <Metric label="disk free" value={formatMetric(runtime?.disk_free_gb, ' GB')} />
      </div>
      {preflight && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
          <Metric label="planned clips" value={formatMetric(preflight.clips)} />
          <Metric label="estimated time" value={formatEta(Number(preflight.runtime_min) * 60)} />
          <Metric label="peak disk" value={formatMetric(preflight.disk_gb, ' GB')} />
          <Metric label="Gemini estimate" value={Number.isFinite(Number(preflight.cost_usd))
            ? `$${Number(preflight.cost_usd).toFixed(4)}` : '—'} hint="upper-bound estimate" />
        </div>
      )}
    </div>
  );
}

export function ProcessingView({ media, status, logs = [], step, clips = [], onCancel, onRetry,
                                 paused = false, onPause, onResume, onStop, opts = {} }) {
  const logRef = useRef(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; });

  const { runtime, preflight } = useMemo(() => latestRuntimeTelemetry(logs), [logs]);
  const visibleLogs = useMemo(
    () => logs.filter((line) => !String(line).startsWith('[runtime]') && !String(line).startsWith('[preflight]')),
    [logs],
  );
  const failed = status === 'error';
  const effectiveStep = runtime?.stage || step;
  const info = STEP_INFO[effectiveStep] || STEP_INFO.queued;
  const clipBoost = clips.length > 0 ? Math.min(18, clips.length * 3) : 0;
  const reportedProgress = Number(runtime?.progress);
  const pct = failed ? 100 : Number.isFinite(reportedProgress)
    ? Math.min(100, Math.max(0, reportedProgress))
    : Math.min(96, info.pct + clipBoost);
  const activeIdx = clips.length > 0 ? Math.max(info.idx, 4) : info.idx;
  const sourceLabel = media?.type === 'url' ? media.payload : (media?.payload?.name || media?.payload || 'your video');
  const STEP_WORD = {
    queued: 'queued', acquiring: 'fetching', downloading: 'fetching', preflight: 'checking capacity',
    transcribing: 'transcribing', analyzing: 'scoring', cutting: 'cutting', reframing: 'rendering',
    quality: 'verifying', finalizing: 'finalizing', processing: 'rendering', completed: 'complete',
  };
  const phase = failed ? 'failed' : (STEP_WORD[effectiveStep] || (clips.length > 0 ? 'rendering' : 'working'));
  const metaOverride = pipelineStepMeta(logs, { ...opts, mediaType: media?.type });
  const nameOverride = { reframe: `Reframe ${opts.aspect || '9:16'}` };

  return (
    <div className="container fade-in">
      <Hero eyebrow={failed ? 'Pipeline error' : 'Pipeline running'}
        line1={failed ? 'Something broke.' : 'Cutting your clips.'}
        sub={failed ? 'The job failed. Check the log below, then retry or start over.'
          : 'Every phase is checkpointed. Verified clips appear immediately, and a retry resumes from durable work instead of starting over.'} />
      <div className="proc">
        <aside className="proc-aside">
          <Panel pad={true}>
            <div className="pipe">
              {PIPE.map((pipelineStep, index) => {
                const done = !failed && index < activeIdx;
                const active = !failed && index === activeIdx;
                const meta = metaOverride[pipelineStep.id] || pipelineStep.meta;
                const name = nameOverride[pipelineStep.id] || pipelineStep.name;
                return (
                  <div key={pipelineStep.id} className={'pstep' + (done ? ' done' : active ? ' active' : '')}>
                    <div className="rail">
                      <div className="pdot"><Icon n={done ? 'check' : pipelineStep.icon} /></div>
                      {index < PIPE.length - 1 && <div className="pseg-v"></div>}
                    </div>
                    <div className="pbody">
                      <div className="pname">{name}</div>
                      <div className="pmeta">{active ? meta + ' …' : done ? 'done' : meta}</div>
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
                {!failed && onPause && (paused
                  ? <Btn variant="secondary" size="sm" icon="play" onClick={onResume}>Resume</Btn>
                  : <Btn variant="ghost" size="sm" icon="clock" onClick={onPause}>Pause</Btn>)}
                {!failed && onStop && clips.length > 0 && (
                  <Btn variant="secondary" size="sm" icon="check-square" onClick={onStop}>Stop &amp; keep</Btn>
                )}
                <Btn variant="ghost" size="sm" icon="x" onClick={onCancel}>{failed ? 'Start over' : 'Discard'}</Btn>
              </span>
            </div>

            <Operations runtime={runtime} preflight={preflight} />

            <div className="log" ref={logRef}>
              {visibleLogs.length === 0 && <div className="ln"><span className="ts">··</span> <span>waiting for the worker…</span></div>}
              {visibleLogs.map((line, index) => (
                <div key={index} className="ln">
                  <span className={/error/i.test(line) ? '' : /✓|done|complete|found/i.test(line) ? 'ok' : ''}
                    style={/error/i.test(line) ? { color: 'var(--danger)' } : undefined}>{line}</span>
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
            {clips.slice(0, 8).map((clip, index) => <MiniClip key={clip.original_index ?? index} clip={clip} />)}
            {!failed && clips.length < 4 && Array.from({ length: 4 - clips.length }).map((_, index) => (
              <div key={'slot' + index} className="slot">{index === 0 ? <div className="sk"></div> : null}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
