// ClippyMe redesign — Live Monitor: start/stop concurrent channel monitors
// (Kick/Twitch live, or YouTube/Kick/Twitch VOD feeds) and show each one's
// capture→process→publish state. Reuses the Zernio platform-picker pattern
// from publish.jsx (same PLAT map + accounts source).
import { useState, useEffect } from 'react';
import { Hero } from './chrome';
import { Icon, Panel, Btn, Badge, Switch, Segmented, PlatPill, PLATFORMS } from './primitives';
import { getZernio, startLiveMonitor, stopLiveMonitor } from './realApi';
import { PLAT } from './publish';
import { validateSlug, buildPlatformTargets, classifyStartError, clampMonitorTimings } from '../lib/liveMonitorForm';
import { buildMonitorBannerPayload } from '../lib/liveMonitorBanner';
import { BannerControls } from './bannerControls';
import { useLiveMonitorStatus } from '../hooks/useLiveMonitorStatus';

const STATE_LABEL = {
  idle: 'Idle',
  waiting_live: 'Waiting for the channel to go live',
  prelive: 'Prelive — letting the stream settle in',
  capturing: 'Capturing segment',
  draining: 'Draining — finishing the last segment',
  watching: 'Watching for new uploads',
};

const STATE_TONE = {
  idle: 'out', waiting_live: 'amber', prelive: 'amber', capturing: 'teal', draining: 'amber', watching: 'teal',
};

const PLATFORM_OPTIONS = [
  { id: 'kick', label: 'Kick' },
  { id: 'twitch', label: 'Twitch' },
  { id: 'youtube', label: 'YouTube' },
];

const PLATFORM_LABEL = { kick: 'Kick', twitch: 'Twitch', youtube: 'YouTube' };

const SLUG_PLACEHOLDER = {
  kick: 'e.g. xqc',
  twitch: 'e.g. xqc',
  youtube: '@handle or https://youtube.com/@handle',
};

function MonitorCard({ monitor, onStop, stopping }) {
  return (
    <div className="opt" style={{ borderBottom: 0 }}>
      <div className="otxt">
        <div className="ot">
          <Badge tone="out">{PLATFORM_LABEL[monitor.platform] || monitor.platform}</Badge>{' '}
          <Badge tone={STATE_TONE[monitor.state] || 'out'}>{STATE_LABEL[monitor.state] || monitor.state || 'Unknown'}</Badge>
          <span style={{ marginLeft: 8, color: 'var(--fg-3)' }}>{monitor.channel || monitor.slug}</span>
          {monitor.mode === 'vod' && <span style={{ marginLeft: 8, color: 'var(--fg-4)' }}>VOD</span>}
        </div>
        <div className="od">
          {monitor.mode === 'vod'
            ? `${monitor.segments_captured || 0} item(s) processed · ${monitor.clips_published || 0} clip(s) published`
            : `${monitor.segments_captured || 0} segment(s) captured · ${monitor.clips_published || 0} clip(s) published`}
        </div>
        {monitor.current_job_id && <div className="od">Current job: {monitor.current_job_id}</div>}
        {monitor.last_error && <div className="od" style={{ color: 'var(--danger)' }}>{monitor.last_error}</div>}
      </div>
      <div className="r">
        <Btn variant="secondary" size="sm" icon="square" disabled={stopping} onClick={() => onStop(monitor.id)}>
          {stopping ? 'Stopping…' : 'Stop'}
        </Btn>
      </div>
    </div>
  );
}

export function LiveMonitorView({ pushToast }) {
  const [zernio, setZernio] = useState(null);
  const [platform, setPlatform] = useState('kick');
  const [mode, setMode] = useState('live');
  // Manual queue is the safe default (no Zernio required); Zernio automatic
  // reveals + requires the account-targets picker below.
  const [publisherMode, setPublisherMode] = useState('manual_queue');
  const [slug, setSlug] = useState('');
  const [touched, setTouched] = useState(false);
  const [plats, setPlats] = useState({ tiktok: true, ig: true, yt: false });
  const [captionTemplate, setCaptionTemplate] = useState('');
  const [titleTemplate, setTitleTemplate] = useState('');
  const [instructions, setInstructions] = useState('');
  const [loop, setLoop] = useState(false);
  const [bannerMode, setBannerMode] = useState('auto'); // auto | off | custom
  const [bannerPlatform, setBannerPlatform] = useState('kick');
  const [bannerHandle, setBannerHandle] = useState('');
  const [bannerYPct, setBannerYPct] = useState(0.85);
  const [segmentMin, setSegmentMin] = useState(30);
  const [preliveMin, setPreliveMin] = useState(30);
  const [minGapMin, setMinGapMin] = useState(15);
  const [starting, setStarting] = useState(false);
  const [stoppingId, setStoppingId] = useState(null);

  const monitors = useLiveMonitorStatus();

  useEffect(() => { getZernio().then(setZernio).catch(() => setZernio({ configured: false })); }, []);

  // YouTube has no "live" concept for this monitor (clips new uploads only).
  useEffect(() => { if (platform === 'youtube' && mode !== 'vod') setMode('vod'); }, [platform, mode]);

  const accounts = zernio?.accounts || {};
  const toggle = (k) => setPlats((p) => ({ ...p, [k]: !p[k] }));
  const targets = buildPlatformTargets(plats, accounts, PLAT);
  const slugError = validateSlug(slug, platform);
  const isManual = publisherMode === 'manual_queue';
  const canStart = !slugError && (isManual || (targets.length > 0 && zernio?.configured));
  const isVod = mode === 'vod';

  const onStart = async () => {
    setTouched(true);
    if (!canStart) return;
    setStarting(true);
    try {
      await startLiveMonitor({
        slug: platform === 'youtube' ? slug.trim() : slug.trim().toLowerCase(),
        platform,
        mode,
        publisher_mode: publisherMode,
        ...(isManual ? {} : { platforms: targets }),
        ...clampMonitorTimings(segmentMin, preliveMin, minGapMin),
        loop,
        caption_template: captionTemplate,
        title_template: titleTemplate,
        instructions,
        banner: buildMonitorBannerPayload(bannerMode, { platform: bannerPlatform, handle: bannerHandle, y_pct: bannerYPct }),
      });
      pushToast?.('success', `Monitoring ${slug.trim()}…`);
      setSlug('');
      setTouched(false);
    } catch (e) {
      const kind = classifyStartError(e.message);
      if (kind === 'duplicate') pushToast?.('warn', 'Already monitoring that channel.');
      else if (kind === 'twitch_creds') pushToast?.('error', 'Twitch not configured — add TWITCH_CLIENT_ID/SECRET in Settings.');
      else pushToast?.('error', 'Start failed: ' + String(e.message || e).slice(0, 80));
    } finally {
      setStarting(false);
    }
  };

  const onStop = async (monitorId) => {
    setStoppingId(monitorId);
    try {
      await stopLiveMonitor(monitorId);
      pushToast?.('info', 'Monitor stopped');
    } catch (e) {
      pushToast?.('error', 'Stop failed: ' + String(e.message || e).slice(0, 60));
    } finally {
      setStoppingId(null);
    }
  };

  return (
    <div className="container narrow fade-in">
      <Hero eyebrow="Live Monitor" line1="Auto-clip a channel." grad="live."
        sub="Watches a channel across sessions, captures/processes new content, and publishes clips as they're ready — spaced apart on socials." />

      <Panel title="Monitors" icon="rss" style={{ marginBottom: 18 }}>
        {monitors.length === 0 && <div className="od">No monitors running.</div>}
        {monitors.map((m) => (
          <MonitorCard key={m.id} monitor={m} onStop={onStop} stopping={stoppingId === m.id} />
        ))}
      </Panel>

      <Panel title="Start monitor" sub="Requires Zernio configured in Settings" icon="wand-sparkles">
        <div className="field">
          <span className="field-label">Platform</span>
          <Segmented value={platform} onChange={setPlatform} options={PLATFORM_OPTIONS} />
        </div>

        <div className="field">
          <span className="field-label">Publish destination</span>
          <Segmented full value={publisherMode} onChange={setPublisherMode}
            options={[{ id: 'manual_queue', label: 'Manual queue' }, { id: 'zernio', label: 'Zernio automatic' }]} />
          <div className="od">{isManual ? 'Finished clips wait in the manual publish queue for you to grab & post.' : 'Finished clips auto-post to the Zernio targets below.'}</div>
        </div>

        <div className="field">
          <span className="field-label">Mode</span>
          <Segmented value={mode} onChange={setMode}
            options={[{ id: 'live', label: 'Live' }, { id: 'vod', label: 'VOD' }]} full />
          {platform === 'youtube' && (
            <div className="od">YouTube: clips every new long-form upload; Shorts excluded</div>
          )}
        </div>

        <div className="field">
          <span className="field-label">{PLATFORM_LABEL[platform]} channel</span>
          <input className="key-input" style={{ width: '100%', fontFamily: 'var(--font-sans)' }}
            aria-label="Channel" placeholder={SLUG_PLACEHOLDER[platform]}
            value={slug} onChange={(e) => setSlug(e.target.value)} onBlur={() => setTouched(true)} />
          {touched && slugError && <div className="od" style={{ color: 'var(--danger)' }}>{slugError}</div>}
        </div>

        {!isManual && (
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
        )}

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
        <div className="field">
          <span className="field-label"><Icon n="sparkles" style={{ color: 'var(--brand-blue)' }} /> AI instructions · optional</span>
          <textarea className="ta" rows="2" aria-label="AI instructions" value={instructions}
            placeholder="e.g. “Find the funniest moments” or “Skip the intro, focus on the demo”"
            onChange={(e) => setInstructions(e.target.value)}></textarea>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: isVod ? '1fr' : 'repeat(3,1fr)', gap: 8, marginBottom: 14 }}>
          {!isVod && (
            <label className="field">
              <span className="field-label">Segment (min)</span>
              <input className="key-input" type="number" min="1" max="60" aria-label="Segment minutes"
                value={segmentMin} onChange={(e) => setSegmentMin(Number(e.target.value))} />
            </label>
          )}
          {!isVod && (
            <label className="field">
              <span className="field-label">Prelive skip (min)</span>
              <input className="key-input" type="number" min="0" max="120" aria-label="Prelive skip minutes"
                value={preliveMin} onChange={(e) => setPreliveMin(Number(e.target.value))} />
            </label>
          )}
          <label className="field">
            <span className="field-label">Min gap (min)</span>
            <input className="key-input" type="number" min="0" max="1440" aria-label="Minimum publish gap minutes"
              value={minGapMin} onChange={(e) => setMinGapMin(Number(e.target.value))} />
          </label>
        </div>

        <div className="opt" style={{ borderBottom: 0 }}>
          <div className="otxt"><div className="ot">Loop</div><div className="od">Keep monitoring for the next session after this one ends</div></div>
          <div className="r"><Switch on={loop} onChange={setLoop} /></div>
        </div>

        <div className="field">
          <span className="field-label">Attribution banner</span>
          <Segmented full value={bannerMode} onChange={setBannerMode}
            options={[
              { id: 'auto', label: `Auto (${PLATFORM_LABEL[platform]} + channel)` },
              { id: 'off', label: 'Off' },
              { id: 'custom', label: 'Custom' },
            ]} />
          {bannerMode === 'custom' && (
            <div className="cfg-drawer fade-in" style={{ marginTop: 10 }}>
              <BannerControls value={{ platform: bannerPlatform, handle: bannerHandle, y_pct: bannerYPct }}
                onChange={(partial) => {
                  if (partial.platform !== undefined) setBannerPlatform(partial.platform);
                  if (partial.handle !== undefined) setBannerHandle(partial.handle);
                  if (partial.y_pct !== undefined) setBannerYPct(partial.y_pct);
                }} />
            </div>
          )}
        </div>

        <Btn variant="grad" icon="wand-sparkles" disabled={!canStart || starting} onClick={onStart} block>
          {starting ? 'Starting…' : 'Start monitor'}
        </Btn>
      </Panel>
    </div>
  );
}
