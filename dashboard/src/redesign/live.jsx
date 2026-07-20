// ClippyMe redesign — Live Monitor: start/stop the Kick channel marathon
// monitor and show its capture→process→publish state. Reuses the Zernio
// platform-picker pattern from publish.jsx (same PLAT map + accounts source).
import { useState, useEffect } from 'react';
import { Hero } from './chrome';
import { Panel, Btn, Badge, Switch, PlatPill, PLATFORMS } from './primitives';
import { getZernio, startLiveMonitor, stopLiveMonitor } from './realApi';
import { PLAT } from './publish';
import { validateSlug, buildPlatformTargets } from '../lib/liveMonitorForm';
import { useLiveMonitorStatus } from '../hooks/useLiveMonitorStatus';

const STATE_LABEL = {
  idle: 'Idle',
  waiting_live: 'Waiting for the channel to go live',
  prelive: 'Prelive — letting the stream settle in',
  capturing: 'Capturing segment',
  draining: 'Draining — finishing the last segment',
};

const STATE_TONE = {
  idle: 'out', waiting_live: 'amber', prelive: 'amber', capturing: 'teal', draining: 'amber',
};

export function LiveMonitorView({ pushToast }) {
  const [zernio, setZernio] = useState(null);
  const [slug, setSlug] = useState('');
  const [touched, setTouched] = useState(false);
  const [plats, setPlats] = useState({ tiktok: true, ig: true, yt: false });
  const [captionTemplate, setCaptionTemplate] = useState('');
  const [titleTemplate, setTitleTemplate] = useState('');
  const [loop, setLoop] = useState(false);
  const [segmentMin, setSegmentMin] = useState(30);
  const [preliveMin, setPreliveMin] = useState(30);
  const [minGapMin, setMinGapMin] = useState(15);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);

  const status = useLiveMonitorStatus();

  useEffect(() => { getZernio().then(setZernio).catch(() => setZernio({ configured: false })); }, []);

  const accounts = zernio?.accounts || {};
  const toggle = (k) => setPlats((p) => ({ ...p, [k]: !p[k] }));
  const targets = buildPlatformTargets(plats, accounts, PLAT);
  const slugError = validateSlug(slug);
  const canStart = !slugError && targets.length > 0 && zernio?.configured;

  const onStart = async () => {
    setTouched(true);
    if (!canStart) return;
    setStarting(true);
    try {
      await startLiveMonitor({
        slug: slug.trim().toLowerCase(),
        platforms: targets,
        segment_seconds: Math.round(segmentMin * 60),
        prelive_skip_seconds: Math.round(preliveMin * 60),
        min_gap_seconds: Math.round(minGapMin * 60),
        loop,
        caption_template: captionTemplate,
        title_template: titleTemplate,
      });
      pushToast?.('success', `Monitoring ${slug.trim()}…`);
    } catch (e) {
      pushToast?.('error', 'Start failed: ' + String(e.message || e).slice(0, 80));
    } finally {
      setStarting(false);
    }
  };

  const onStop = async () => {
    setStopping(true);
    try {
      await stopLiveMonitor();
      pushToast?.('info', 'Live monitor stopped');
    } catch (e) {
      pushToast?.('error', 'Stop failed: ' + String(e.message || e).slice(0, 60));
    } finally {
      setStopping(false);
    }
  };

  const running = !!status?.running;

  return (
    <div className="container narrow fade-in">
      <Hero eyebrow="Live Monitor" line1="Auto-clip a Kick marathon." grad="live."
        sub="Skips the first minutes of the stream, captures fixed-length segments, and publishes clips as they're ready — spaced apart on socials." />

      <Panel title="Status" icon="rss" style={{ marginBottom: 18 }}>
        <div className="opt" style={{ borderBottom: 0 }}>
          <div className="otxt">
            <div className="ot">
              <Badge tone={STATE_TONE[status?.state] || 'out'}>{STATE_LABEL[status?.state] || status?.state || 'Unknown'}</Badge>
              {status?.slug && <span style={{ marginLeft: 8, color: 'var(--fg-3)' }}>{status.slug}</span>}
            </div>
            <div className="od">
              {status
                ? `${status.segments_captured || 0} segment(s) captured · ${status.clips_published || 0} clip(s) published`
                : 'Loading…'}
            </div>
            {status?.current_job_id && (
              <div className="od">Current job: {status.current_job_id}</div>
            )}
            {status?.last_error && <div className="od" style={{ color: 'var(--danger)' }}>{status.last_error}</div>}
          </div>
          <div className="r">
            {running && (
              <Btn variant="secondary" size="sm" icon="square" disabled={stopping} onClick={onStop}>
                {stopping ? 'Stopping…' : 'Stop'}
              </Btn>
            )}
          </div>
        </div>
      </Panel>

      {!running && (
        <Panel title="Start monitor" sub="Requires Zernio configured in Settings" icon="wand-sparkles">
          <div className="field">
            <span className="field-label">Kick channel slug</span>
            <input className="key-input" style={{ width: '100%', fontFamily: 'var(--font-sans)' }}
              aria-label="Kick channel slug" placeholder="e.g. xqc"
              value={slug} onChange={(e) => setSlug(e.target.value)} onBlur={() => setTouched(true)} />
            {touched && slugError && <div className="od" style={{ color: 'var(--danger)' }}>{slugError}</div>}
          </div>

          <div className="field">
            <span className="field-label">Platforms</span>
            <div className="plats">
              {PLATFORMS.map((p) => {
                const has = !!accounts[PLAT[p.id].acct];
                return (
                  <PlatPill key={p.id} {...p} on={plats[p.id] && has}
                    onClick={() => (has ? toggle(p.id) : pushToast?.('warn', `No ${PLAT[p.id].label} account saved`))} />
                );
              })}
            </div>
          </div>

          <div className="field">
            <span className="field-label">Title template (optional)</span>
            <input className="key-input" style={{ width: '100%', fontFamily: 'var(--font-sans)' }}
              aria-label="Title template" placeholder="{title}"
              value={titleTemplate} onChange={(e) => setTitleTemplate(e.target.value)} />
          </div>
          <div className="field">
            <span className="field-label">Caption template (optional)</span>
            <textarea className="ta" rows="2" aria-label="Caption template" placeholder="{hook}"
              value={captionTemplate} onChange={(e) => setCaptionTemplate(e.target.value)}></textarea>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 14 }}>
            <label className="field">
              <span className="field-label">Segment (min)</span>
              <input className="key-input" type="number" min="1" max="60" aria-label="Segment minutes"
                value={segmentMin} onChange={(e) => setSegmentMin(Number(e.target.value))} />
            </label>
            <label className="field">
              <span className="field-label">Prelive skip (min)</span>
              <input className="key-input" type="number" min="0" max="120" aria-label="Prelive skip minutes"
                value={preliveMin} onChange={(e) => setPreliveMin(Number(e.target.value))} />
            </label>
            <label className="field">
              <span className="field-label">Min gap (min)</span>
              <input className="key-input" type="number" min="0" max="1440" aria-label="Minimum publish gap minutes"
                value={minGapMin} onChange={(e) => setMinGapMin(Number(e.target.value))} />
            </label>
          </div>

          <div className="opt" style={{ borderBottom: 0 }}>
            <div className="otxt"><div className="ot">Loop</div><div className="od">Keep monitoring for the next live session after this one ends</div></div>
            <div className="r"><Switch on={loop} onChange={setLoop} /></div>
          </div>

          <Btn variant="grad" icon="wand-sparkles" disabled={!canStart || starting} onClick={onStart} block>
            {starting ? 'Starting…' : 'Start monitor'}
          </Btn>
        </Panel>
      )}
    </div>
  );
}
