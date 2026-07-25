
import { useEffect, useMemo, useRef } from 'react';
import { Icon, Btn, Badge, Panel } from './primitives';
import { LazyVideo } from './LazyVideo';
import { Hero } from './chrome';
import { PIPE } from './data';
import { pipelineStepMeta } from '../lib/pipelineStep';
import { clipVideoSrc, fmtDuration } from './realApi';
import { latestRuntimeTelemetry, formatEta, formatMetric } from '../lib/runtimeTelemetry';

const STEP_INFO = {
  queued: { pct: 5, idx: 0 }, acquiring: { pct: 12, idx: 0 }, downloading: { pct: 18, idx: 0 },
  preflight: { pct: 22, idx: 0 }, transcribing: { pct: 38, idx: 1 }, analyzing: { pct: 58, idx: 2 },
  cutting: { pct: 68, idx: 3 }, reframing: { pct: 82, idx: 3 }, quality: { pct: 93, idx: 4 },
  finalizing: { pct: 97, idx: 4 }, processing: { pct: 80, idx: 3 },
};

function MiniClip({ clip }) {
  return <div className="clip fade-in" style={{ cursor: 'default' }}><div className="clip-media" style={{ padding: 0, background: '#000' }}>
    <LazyVideo src={clipVideoSrc(clip)} muted playsInline aria-label="Verified clip preview"
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
    <div className="clip-top" style={{ padding: 8 }}><span className="score">{Math.round(clip.viral_score || 0)}</span></div>
    <div className="clip-bottom" style={{ padding: 8 }}><span className="dur">{fmtDuration(clip.start, clip.end)}</span></div>
  </div></div>;
}

function Metric({ label, value, hint }) {
  return <div className="operation-metric"><div className="label">{label}</div><div className="operation-value">{value}</div>{hint && <div className="operation-hint">{hint}</div>}</div>;
}

function Operations({ runtime, preflight }) {
  if (!runtime && !preflight) return null;
  return <section className="operations" aria-labelledby="operations-title">
    <div className="stream-head"><h3 id="operations-title" aria-level="2">Operations</h3>{runtime?.stage && <Badge tone="out">{runtime.stage}</Badge>}</div>
    <div className="operation-grid">
      <Metric label="attempt" value={runtime?.attempt || '—'} hint="bounded retry" />
      <Metric label="verified clips" value={runtime?.clips || '0/0'} hint="QA passed" />
      <Metric label="ETA" value={formatEta(runtime?.eta_s)} hint="live estimate" />
      <Metric label="CPU" value={formatMetric(runtime?.cpu, '%')} />
      <Metric label="job RAM" value={formatMetric(runtime?.rss_mb, ' MB')} />
      <Metric label="disk free" value={formatMetric(runtime?.disk_free_gb, ' GB')} />
    </div>
    {preflight && <div className="operation-grid operation-grid-secondary">
      <Metric label="planned clips" value={formatMetric(preflight.clips)} />
      <Metric label="estimated time" value={formatEta(Number(preflight.runtime_min) * 60)} />
      <Metric label="peak disk" value={formatMetric(preflight.disk_gb, ' GB')} />
      <Metric label="Gemini estimate" value={Number.isFinite(Number(preflight.cost_usd)) ? `$${Number(preflight.cost_usd).toFixed(4)}` : '—'} hint="upper-bound estimate" />
    </div>}
  </section>;
}

export function ProcessingView({ media, status, logs = [], step, clips = [], onCancel, onRetry,
  paused = false, onPause, onResume, onStop, opts = {} }) {
  const logRef = useRef(null);
  const followTail = useRef(true);
  useEffect(() => {
    const node = logRef.current;
    if (node && followTail.current) node.scrollTop = node.scrollHeight;
  }, [logs]);

  const { runtime, preflight } = useMemo(() => latestRuntimeTelemetry(logs), [logs]);
  const visibleLogs = useMemo(() => logs.filter((line) => !String(line).startsWith('[runtime]') && !String(line).startsWith('[preflight]')), [logs]);
  const failed = status === 'error';
  const effectiveStep = runtime?.stage || step;
  const info = STEP_INFO[effectiveStep] || STEP_INFO.queued;
  const reportedProgress = Number(runtime?.progress);
  const pct = failed ? 100 : Number.isFinite(reportedProgress) ? Math.min(100, Math.max(0, reportedProgress)) : Math.min(96, info.pct + Math.min(18, clips.length * 3));
  const activeIdx = clips.length > 0 ? Math.max(info.idx, 4) : info.idx;
  const sourceLabel = media?.type === 'url' ? media.payload : (media?.payload?.name || media?.payload || 'your video');
  const words = { queued: 'queued', acquiring: 'fetching', downloading: 'fetching', preflight: 'checking capacity', transcribing: 'transcribing', analyzing: 'scoring', cutting: 'cutting', reframing: 'rendering', quality: 'verifying', finalizing: 'finalizing', processing: 'rendering', completed: 'complete' };
  const phase = failed ? 'failed' : paused ? 'paused' : (words[effectiveStep] || (clips.length > 0 ? 'rendering' : 'working'));
  const metaOverride = pipelineStepMeta(logs, { ...opts, mediaType: media?.type });

  return <main className="container fade-in">
    <Hero eyebrow={failed ? 'Pipeline error' : paused ? 'Pipeline paused' : 'Pipeline running'} line1={failed ? 'Something broke.' : paused ? 'Work is paused.' : 'Cutting your clips.'}
      sub={failed ? 'Check the log below, then retry or start over.' : 'Every phase is checkpointed. Verified clips appear immediately, and retries resume from durable work.'} />
    <div className="proc">
      <aside className="proc-aside"><Panel><div className="pipe">
        {PIPE.map((pipelineStep, index) => {
          const done = !failed && index < activeIdx;
          const active = !failed && index === activeIdx;
          return <div key={pipelineStep.id} className={`pstep${done ? ' done' : active ? ' active' : ''}`} aria-current={active ? 'step' : undefined}>
            <div className="rail"><div className="pdot"><Icon n={done ? 'check' : pipelineStep.icon} /></div>{index < PIPE.length - 1 && <div className="pseg-v" />}</div>
            <div className="pbody"><div className="pname">{pipelineStep.id === 'reframe' ? `Reframe ${opts.aspect || '9:16'}` : pipelineStep.name}</div>
              <div className="pmeta">{active ? `${metaOverride[pipelineStep.id] || pipelineStep.meta} …` : done ? 'done' : (metaOverride[pipelineStep.id] || pipelineStep.meta)}</div></div>
          </div>;
        })}
      </div></Panel></aside>
      <div><Panel>
        <div className="pbar-wrap" role="progressbar" aria-label={`Pipeline ${phase}`} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(pct)}>
          <div className="pbar"><i style={{ width: `${pct}%`, background: failed ? 'var(--danger)' : undefined }} /></div><div className="pbar-pct">{phase}</div>
        </div>
        <div className="processing-toolbar"><span className="label"><span className="mono">src ·</span> {String(sourceLabel).slice(0, 46)}</span>
          <span className="processing-actions">
            {failed && <Btn variant="secondary" size="sm" icon="wand-sparkles" onClick={onRetry}>Retry</Btn>}
            {!failed && onPause && (paused ? <Btn variant="secondary" size="sm" icon="play" onClick={onResume}>Resume</Btn> : <Btn variant="ghost" size="sm" icon="clock" onClick={onPause}>Pause</Btn>)}
            {!failed && onStop && clips.length > 0 && <Btn variant="secondary" size="sm" icon="check-square" onClick={onStop}>Stop & keep</Btn>}
            <Btn variant="ghost" size="sm" icon="x" onClick={onCancel}>{failed ? 'Start over' : 'Discard'}</Btn>
          </span>
        </div>
        <Operations runtime={runtime} preflight={preflight} />
        <div className="log" ref={logRef} role="log" aria-live="polite" aria-relevant="additions"
          onScroll={(event) => { const node = event.currentTarget; followTail.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48; }}>
          {visibleLogs.length === 0 && <div className="ln"><span>waiting for the worker…</span></div>}
          {visibleLogs.map((line, index) => <div key={`${index}-${line}`} className="ln"><span className={/✓|done|complete|found/i.test(line) ? 'ok' : ''} style={/error/i.test(line) ? { color: 'var(--danger)' } : undefined}>{line}</span></div>)}
          {!failed && <div aria-hidden="true"><span className="cursor" /></div>}
        </div>
      </Panel>
      <section aria-labelledby="clips-title">
        <div className="stream-head"><h3 id="clips-title" aria-level="2">Clips</h3>{clips.length > 0 ? <Badge tone="teal" icon="check">{clips.length} ready</Badge> : <Badge tone="out">{failed ? 'no clips' : 'finding moments…'}</Badge>}</div>
        <div className="stream">{clips.slice(0, 8).map((clip, index) => <MiniClip key={clip.original_index ?? index} clip={clip} />)}
          {!failed && clips.length < 4 && Array.from({ length: 4 - clips.length }).map((_, index) => <div key={`slot${index}`} className="slot">{index === 0 ? <div className="sk" /> : null}</div>)}</div>
      </section>
      </div>
    </div>
  </main>;
}
