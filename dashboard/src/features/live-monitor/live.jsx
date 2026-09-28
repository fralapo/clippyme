// ClippyMe — Live Monitor: start/stop concurrent channel monitors
// (Kick/Twitch live, or YouTube/Kick/Twitch VOD feeds) and show each one's
// capture→process→publish state. Reuses the Zernio platform-picker pattern
// from publish.jsx (same PLAT map + accounts source).
import { useState, useEffect } from 'react';
import { Hero } from '../../components/chrome';
import { Icon, Panel, Btn, Badge, Switch, Segmented, PlatPill, PLATFORMS } from '../../components/primitives';
import { getZernio, startLiveMonitor, stopLiveMonitor, updateMonitorConfig, setMonitorPublishing } from '../../api/client';
import { PLAT } from '../publishing/publish';
import { validateSlug, buildPlatformTargets, classifyStartError, clampMonitorTimings, clipSelectionPayload, zoomToPercent, LETTERBOX_ZOOM_PERCENTS } from './liveMonitorForm';
import { buildMonitorBannerPayload } from './liveMonitorBanner';
import { toComposeSubtitleParams, fromComposeSubtitleParams } from './subtitleComposeParams';
import { BannerControls } from '../../components/controls/bannerControls';
import { SubtitleControls } from '../../components/controls/subtitleControls';
import { useLiveMonitorStatus } from './useLiveMonitorStatus';
import { relTime } from '../../lib/relTime';

// SubtitleControls is fully controlled with no built-in defaults (see
// subtitleControls.jsx) — this is the same default set create.jsx's
// SubConfig seeds new recipes with, reused here for the monitor's optional
// subtitle override drawer.
const SUB_DEFAULTS = {
  mode: 'karaoke', preset: 'hormozi_bold', font: 'Montserrat-Black',
  font_color: '#FFFFFF', outline_color: '#000000', font_size: 0,
  border_width: 2, bg: false, position: 'bottom', align: 'center', offset_y: 0,
};

// Monitors always render letterboxed (reframe disabled): the whole frame sits
// between black bars. The optional fixed zoom trims that % off the width so the
// picture is bigger and the bars smaller.
const ZOOM_OPTIONS = LETTERBOX_ZOOM_PERCENTS.map(
  (p) => ({ id: String(p), label: p ? `${p}%` : 'No zoom' }));

// The start form is long enough that a lone "Min gap" or platform picker reads
// without context. Grouping by what a field steers — what gets captured, how
// the clips look, where they get posted — is the whole point of this wrapper.
function Group({ title, hint, children }) {
  return (
    <div style={{ marginBottom: 22 }}>
      <div className="cm-title" style={{ marginBottom: hint ? 2 : 10 }}>{title}</div>
      {hint && <div className="od" style={{ marginBottom: 12 }}>{hint}</div>}
      {children}
    </div>
  );
}

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

// Seconds → minutes for the drawer's minute inputs; '' (blank) when unset so
// "Apply" still treats an untouched field as untouched.
const secToMin = (s) => (typeof s === 'number' ? String(Math.round(s / 60)) : '');

// Settings-drawer state, seeded from the running monitor's `status().config`
// (the same allow-list snapshot() persists) — the drawer used to always open
// blank because status() didn't echo config back (see task-5-brief); it now
// does. "Apply" still sends only the fields the user actually touches —
// untouched fields stay omitted rather than clobbering server state with
// blanks, even though they're now prefilled for editing.
function MonitorSettings({ monitor, onApply, applying }) {
  const cfg = monitor.config || {};
  const [instructions, setInstructions] = useState(cfg.instructions || '');
  const [captionTemplate, setCaptionTemplate] = useState(cfg.caption_template || '');
  const [titleTemplate, setTitleTemplate] = useState(cfg.title_template || '');
  const [segmentMin, setSegmentMin] = useState(secToMin(cfg.segment_seconds));
  const [preliveMin, setPreliveMin] = useState(secToMin(cfg.prelive_skip_seconds));
  const [minGapMin, setMinGapMin] = useState(secToMin(cfg.min_gap_seconds));
  const [subOn, setSubOn] = useState(!!cfg.compose?.subtitle_params);
  const [sub, setSub] = useState(() => fromComposeSubtitleParams(cfg.compose?.subtitle_params, SUB_DEFAULTS));
  // Default-on (matches the backend default): only an explicit `false` in the
  // persisted config starts the checkbox unchecked.
  const [deleteAfterPublish, setDeleteAfterPublish] = useState(cfg.delete_after_publish !== false);
  const [deleteAfterPublishTouched, setDeleteAfterPublishTouched] = useState(false);
  const [clipSelection, setClipSelection] = useState(cfg.clip_selection === 'auto' ? 'auto' : 'fixed');
  const [clipSelectionTouched, setClipSelectionTouched] = useState(false);
  const [maxClips, setMaxClips] = useState(typeof cfg.max_clips === 'number' ? String(cfg.max_clips) : '');
  const [minScore, setMinScore] = useState(typeof cfg.min_viral_score === 'number' ? String(cfg.min_viral_score) : '');
  const [smartCut, setSmartCut] = useState(!!cfg.smart_cut);
  const [smartCutTouched, setSmartCutTouched] = useState(false);
  const [zoom, setZoom] = useState(zoomToPercent(cfg.letterbox_zoom));
  const [zoomTouched, setZoomTouched] = useState(false);

  const apply = () => {
    const partial = {};
    if (instructions.trim()) partial.instructions = instructions.trim();
    if (captionTemplate.trim()) partial.caption_template = captionTemplate.trim();
    if (titleTemplate.trim()) partial.title_template = titleTemplate.trim();
    if (segmentMin !== '') partial.segment_seconds = clampMonitorTimings(segmentMin, 0, 0).segment_seconds;
    if (preliveMin !== '') partial.prelive_skip_seconds = clampMonitorTimings(0, preliveMin, 0).prelive_skip_seconds;
    if (minGapMin !== '') partial.min_gap_seconds = clampMonitorTimings(0, 0, minGapMin).min_gap_seconds;
    if (subOn) partial.compose = { subtitle_params: toComposeSubtitleParams(sub) };
    if (deleteAfterPublishTouched) partial.delete_after_publish = deleteAfterPublish;
    if (clipSelectionTouched) partial.clip_selection = clipSelection;
    const bounded = clipSelectionPayload(clipSelection, maxClips, minScore);
    if (maxClips !== '') partial.max_clips = bounded.max_clips;
    if (minScore !== '') partial.min_viral_score = bounded.min_viral_score;
    if (smartCutTouched) partial.smart_cut = smartCut;
    if (zoomTouched) partial.letterbox_zoom = zoom;
    onApply(monitor.id, partial);
  };

  return (
    <div className="cfg-drawer fade-in" style={{ marginTop: 10 }}>
      <div className="od" style={{ marginBottom: 8 }}>Changes apply to the next clips only.</div>
      <div className="field">
        <span className="field-label">AI instructions</span>
        <textarea className="ta" rows="2" aria-label={`Settings instructions ${monitor.id}`}
          value={instructions} onChange={(e) => setInstructions(e.target.value)} />
      </div>
      <div className="field">
        <span className="field-label">Title template</span>
        <input className="key-input" style={{ width: '100%' }} aria-label={`Settings title template ${monitor.id}`}
          value={titleTemplate} onChange={(e) => setTitleTemplate(e.target.value)} />
      </div>
      <div className="field">
        <span className="field-label">Caption template</span>
        <input className="key-input" style={{ width: '100%' }} aria-label={`Settings caption template ${monitor.id}`}
          value={captionTemplate} onChange={(e) => setCaptionTemplate(e.target.value)} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 10 }}>
        <label className="field">
          <span className="field-label">Segment (min)</span>
          <input className="key-input" type="number" min="1" max="60" aria-label={`Settings segment minutes ${monitor.id}`}
            value={segmentMin} onChange={(e) => setSegmentMin(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Prelive skip (min)</span>
          <input className="key-input" type="number" min="0" max="120" aria-label={`Settings prelive skip minutes ${monitor.id}`}
            value={preliveMin} onChange={(e) => setPreliveMin(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Min gap (min)</span>
          <input className="key-input" type="number" min="0" max="1440" aria-label={`Settings min gap minutes ${monitor.id}`}
            value={minGapMin} onChange={(e) => setMinGapMin(e.target.value)} />
        </label>
      </div>
      <div className="field">
        <span className="field-label">Clips per segment</span>
        <Segmented full value={clipSelection}
          onChange={(v) => { setClipSelection(v); setClipSelectionTouched(true); }}
          options={[{ id: 'fixed', label: 'Fixed number' }, { id: 'auto', label: 'Automatic' }]} />
        <div style={{ display: 'grid', gridTemplateColumns: clipSelection === 'auto' ? 'repeat(2,1fr)' : '1fr', gap: 8, marginTop: 8 }}>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="field-label">{clipSelection === 'auto' ? 'Max clips' : 'Clips'}</span>
            <input className="key-input" type="number" min="0" max="1000" aria-label={`Settings clips per segment ${monitor.id}`}
              value={maxClips} onChange={(e) => setMaxClips(e.target.value)} />
            <div className="od">0 = no limit.</div>
          </label>
          {clipSelection === 'auto' && (
            <label className="field" style={{ marginBottom: 0 }}>
              <span className="field-label">Min viral score</span>
              <input className="key-input" type="number" min="1" max="100" aria-label={`Settings min viral score ${monitor.id}`}
                value={minScore} onChange={(e) => setMinScore(e.target.value)} />
            </label>
          )}
        </div>
      </div>
      <div className="opt" style={{ borderBottom: 0, paddingLeft: 0, paddingRight: 0 }}>
        <div className="otxt"><div className="ot">Subtitle overrides</div><div className="od">Applies to future clips only</div></div>
        <Switch on={subOn} onChange={setSubOn} />
      </div>
      {subOn && <SubtitleControls variant="create" value={sub} onChange={(p) => setSub((s) => ({ ...s, ...p }))} />}
      <div className="opt" style={{ borderBottom: 0, paddingLeft: 0, paddingRight: 0 }}>
        <div className="otxt"><div className="ot">Smart Cut</div><div className="od">Removes silences and fillers before publishing</div></div>
        <Switch on={smartCut} label={`Smart cut ${monitor.id}`}
          onChange={(on) => { setSmartCut(on); setSmartCutTouched(true); }} />
      </div>
      <div className="field">
        <span className="field-label">Letterbox zoom ({zoom ? `${zoom}%` : 'off'})</span>
        <Segmented full value={String(zoom)}
          onChange={(v) => { setZoom(Number(v)); setZoomTouched(true); }}
          options={ZOOM_OPTIONS} />
      </div>
      <div className="opt" style={{ borderBottom: 0, paddingLeft: 0, paddingRight: 0 }}>
        <div className="otxt"><div className="ot">Delete clip after publish</div><div className="od">Frees disk once a clip is confirmed published</div></div>
        <Switch on={deleteAfterPublish} label={`Delete after publish ${monitor.id}`}
          onChange={(on) => { setDeleteAfterPublish(on); setDeleteAfterPublishTouched(true); }} />
      </div>
      <Btn variant="secondary" size="sm" disabled={applying} onClick={apply} style={{ marginTop: 10 }}>
        {applying ? 'Applying…' : 'Apply'}
      </Btn>
    </div>
  );
}

function MonitorCard({ monitor, onStop, stopping, onApplySettings, applyingSettings, onTogglePublishing, togglingPublishing }) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <div className="opt" style={{ borderBottom: 0, flexDirection: 'column', alignItems: 'stretch' }}>
      <div style={{ display: 'flex', width: '100%' }}>
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
          {monitor.gemini_exhausted_at && (
            <div className="od" style={{ color: 'var(--brand-amber)' }}>
              Gemini rate-limited — last segment skipped ({relTime(monitor.gemini_exhausted_at)})
            </div>
          )}
        </div>
        <div className="r">
          <Btn variant="secondary" size="sm" icon="sliders-horizontal" onClick={() => setSettingsOpen((v) => !v)}>
            Settings
          </Btn>
          <Btn variant="secondary" size="sm" icon="square" disabled={stopping} onClick={() => onStop(monitor.id)}>
            {stopping ? 'Stopping…' : 'Stop'}
          </Btn>
        </div>
      </div>

      <div className="opt" style={{ borderBottom: 0, paddingLeft: 0, paddingRight: 0, marginTop: 6 }}>
        <div className="otxt">
          <div className="ot">Zernio auto-publish</div>
          {!monitor.publishing_enabled && (
            <div className="od">Paused — {monitor.pending_publish || 0} clip(s) waiting</div>
          )}
        </div>
        <Switch on={!!monitor.publishing_enabled} disabled={togglingPublishing} label={`Zernio auto-publish ${monitor.id}`}
          onChange={(on) => onTogglePublishing(monitor.id, on)} />
      </div>

      {settingsOpen && (
        <MonitorSettings monitor={monitor} onApply={onApplySettings} applying={applyingSettings} />
      )}
    </div>
  );
}

export function LiveMonitorView({ pushToast }) {
  const [zernio, setZernio] = useState(null);
  const [platform, setPlatform] = useState('kick');
  const [mode, setMode] = useState('live');
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
  const [catchup, setCatchup] = useState('backfill');
  const [clipSelection, setClipSelection] = useState('fixed');
  const [maxClips, setMaxClips] = useState(5);
  const [minScore, setMinScore] = useState(70);
  const [smartCut, setSmartCut] = useState(false);
  const [zoom, setZoom] = useState(0);
  const [subOn, setSubOn] = useState(false);
  const [sub, setSub] = useState(SUB_DEFAULTS);
  const [starting, setStarting] = useState(false);
  const [stoppingId, setStoppingId] = useState(null);
  const [applyingSettingsId, setApplyingSettingsId] = useState(null);
  const [togglingPublishingId, setTogglingPublishingId] = useState(null);

  const [monitors, refreshMonitors, meta] = useLiveMonitorStatus();

  useEffect(() => { getZernio().then(setZernio).catch(() => setZernio({ configured: false })); }, []);

  // YouTube has no "live" concept for this monitor (clips new uploads only).
  useEffect(() => { if (platform === 'youtube' && mode !== 'vod') setMode('vod'); }, [platform, mode]);

  const accounts = zernio?.accounts || {};
  const toggle = (k) => setPlats((p) => ({ ...p, [k]: !p[k] }));
  const targets = buildPlatformTargets(plats, accounts, PLAT);
  const slugError = validateSlug(slug, platform);
  const canStart = !slugError && targets.length > 0 && zernio?.configured;
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
        platforms: targets,
        ...clampMonitorTimings(segmentMin, preliveMin, minGapMin),
        ...clipSelectionPayload(clipSelection, maxClips, minScore),
        loop,
        catchup,
        smart_cut: smartCut,
        letterbox_zoom: zoom,
        caption_template: captionTemplate,
        title_template: titleTemplate,
        instructions,
        banner: buildMonitorBannerPayload(bannerMode, { platform: bannerPlatform, handle: bannerHandle, y_pct: bannerYPct }),
        ...(subOn ? { compose: { subtitle_params: toComposeSubtitleParams(sub) } } : {}),
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

  const onApplySettings = async (monitorId, partial) => {
    if (Object.keys(partial).length === 0) return;
    setApplyingSettingsId(monitorId);
    try {
      await updateMonitorConfig(monitorId, partial);
      pushToast?.('success', 'Settings applied — will take effect from the next clips.');
      refreshMonitors();
    } catch (e) {
      pushToast?.('error', 'Update failed: ' + String(e.message || e).slice(0, 60));
    } finally {
      setApplyingSettingsId(null);
    }
  };

  const onTogglePublishing = async (monitorId, enabled) => {
    setTogglingPublishingId(monitorId);
    try {
      await setMonitorPublishing(monitorId, enabled);
      refreshMonitors();
    } catch (e) {
      pushToast?.('error', 'Update failed: ' + String(e.message || e).slice(0, 60));
    } finally {
      setTogglingPublishingId(null);
    }
  };

  return (
    <div className="container narrow fade-in">
      <Hero eyebrow="Live Monitor" line1="Auto-clip a channel." grad="live."
        sub="Watches a channel across sessions, captures/processes new content, and publishes clips as they're ready — spaced apart on socials." />

      <Panel title="Monitors" icon="rss" style={{ marginBottom: 18 }}>
        {/* Distinguish "backend unreachable" from a true empty list — the poll
            swallows errors into `meta`, so without this an outage renders the
            same "No monitors running." as a healthy idle. */}
        {meta.error && <div className="od" style={{ color: 'var(--danger)' }}>Can&apos;t reach the backend — monitor status unknown.</div>}
        {!meta.error && monitors.length === 0 && !meta.loading && <div className="od">No monitors running.</div>}
        {monitors.map((m) => (
          <MonitorCard key={m.id} monitor={m} onStop={onStop} stopping={stoppingId === m.id}
            onApplySettings={onApplySettings} applyingSettings={applyingSettingsId === m.id}
            onTogglePublishing={onTogglePublishing} togglingPublishing={togglingPublishingId === m.id} />
        ))}
      </Panel>

      <Panel title="Start monitor" sub="Requires Zernio configured in Settings" icon="wand-sparkles">
        <Group title="Source" hint="What gets watched, and which part of it is worth clipping.">
        <div className="field">
          <span className="field-label">Platform</span>
          <Segmented value={platform} onChange={setPlatform} options={PLATFORM_OPTIONS} />
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

        {/* Catchup only steers the live capture loop (backfill of the windows
            missed before the monitor noticed the stream). VOD mode processes
            whole items from a feed, so the choice is meaningless there. */}
        {mode !== 'vod' && (
          <div className="field">
            <span className="field-label">Catchup</span>
            <Segmented full value={catchup} onChange={setCatchup}
              options={[{ id: 'backfill', label: 'From the start of the live' }, { id: 'live_only', label: 'From now only' }]} />
          </div>
        )}

        {/* Segment length only exists for the live capture loop. Prelive skip
            survives into VOD mode for Kick/Twitch — those recordings start with
            the same waiting screen — but a YouTube upload has no prelive. */}
        <div style={{ display: 'grid', gridTemplateColumns: !isVod && platform !== 'youtube' ? 'repeat(2,1fr)' : '1fr', gap: 8 }}>
          {!isVod && (
            <label className="field">
              <span className="field-label">Segment (min)</span>
              <input className="key-input" type="number" min="1" max="60" aria-label="Segment minutes"
                value={segmentMin} onChange={(e) => setSegmentMin(e.target.value === '' ? '' : Number(e.target.value))} />
            </label>
          )}
          {platform !== 'youtube' && (
            <label className="field">
              <span className="field-label">Prelive skip (min)</span>
              <input className="key-input" type="number" min="0" max="120" aria-label="Prelive skip minutes"
                value={preliveMin} onChange={(e) => setPreliveMin(e.target.value === '' ? '' : Number(e.target.value))} />
              <div className="od">Drops the waiting screen at the head of the {isVod ? 'recording' : 'stream'}.</div>
            </label>
          )}
        </div>

        <div className="opt" style={{ borderBottom: 0 }}>
          <div className="otxt"><div className="ot">Loop</div><div className="od">Keep monitoring for the next session after this one ends</div></div>
          <div className="r"><Switch on={loop} onChange={setLoop} /></div>
        </div>
        </Group>

        <Group title="Clips" hint="How many clips each run yields, and how they look.">
        <div className="field">
          <span className="field-label">Clips per segment</span>
          <Segmented full value={clipSelection} onChange={setClipSelection}
            options={[{ id: 'fixed', label: 'Fixed number' }, { id: 'auto', label: 'Automatic' }]} />
          <div style={{ display: 'grid', gridTemplateColumns: clipSelection === 'auto' ? 'repeat(2,1fr)' : '1fr', gap: 8, marginTop: 8 }}>
            <label className="field" style={{ marginBottom: 0 }}>
              <span className="field-label">{clipSelection === 'auto' ? 'Max clips' : 'Clips'}</span>
              <input className="key-input" type="number" min="0" max="1000" aria-label="Clips per segment"
                value={maxClips} onChange={(e) => setMaxClips(e.target.value === '' ? '' : Number(e.target.value))} />
              <div className="od">0 = no limit — publish every clip the segment yields.</div>
            </label>
            {clipSelection === 'auto' && (
              <label className="field" style={{ marginBottom: 0 }}>
                <span className="field-label">Min viral score</span>
                <input className="key-input" type="number" min="1" max="100" aria-label="Minimum viral score"
                  value={minScore} onChange={(e) => setMinScore(e.target.value === '' ? '' : Number(e.target.value))} />
              </label>
            )}
          </div>
          <div className="od">
            {clipSelection === 'auto'
              ? 'Publishes only the clips scoring above the floor — a weak segment yields fewer, or none.'
              : 'Always publishes the top clips of each segment by viral score.'}
          </div>
        </div>

        <div className="field">
          <span className="field-label">Letterbox zoom</span>
          <Segmented full value={String(zoom)} onChange={(v) => setZoom(Number(v))} options={ZOOM_OPTIONS} />
          <div className="od">
            {zoom
              ? `Crops ${zoom}% off the sides — bigger picture, smaller black bars.`
              : 'Whole frame between the black bars, nothing cropped.'}
          </div>
        </div>

        <div className="opt" style={{ paddingLeft: 0, paddingRight: 0 }}>
          <div className="otxt">
            <div className="ot">Smart Cut</div>
            <div className="od">Removes silences and fillers from every published clip</div>
          </div>
          <Switch on={smartCut} label="Smart cut" onChange={setSmartCut} />
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

        <div className="opt" style={{ borderBottom: 0 }}>
          <div className="otxt"><div className="ot">Subtitles (customize)</div><div className="od">Leave off to use server defaults</div></div>
          <div className="r"><Switch on={subOn} onChange={setSubOn} label="Customize subtitles" /></div>
        </div>
        {subOn && (
          <div style={{ marginBottom: 14 }}>
            <SubtitleControls variant="create" value={sub} onChange={(p) => setSub((s) => ({ ...s, ...p }))} />
          </div>
        )}

        <div className="field">
          <span className="field-label"><Icon n="sparkles" style={{ color: 'var(--brand-blue)' }} /> AI instructions · optional</span>
          <textarea className="ta" rows="2" aria-label="AI instructions" value={instructions}
            placeholder="e.g. “Find the funniest moments” or “Skip the intro, focus on the demo”"
            onChange={(e) => setInstructions(e.target.value)}></textarea>
        </div>
        </Group>

        <Group title="Publishing" hint="Where every finished clip goes on Zernio, and how far apart the posts are scheduled.">
        <div className="field">
          <span className="field-label">Post to</span>
          <div className="plats">
            {PLATFORMS.map((p) => {
              const has = !!accounts[PLAT[p.id].acct];
              return (
                <PlatPill key={p.id} {...p} on={plats[p.id] && has}
                  onClick={() => (has ? toggle(p.id) : pushToast?.('warn', `No ${PLAT[p.id].label} account saved`))} />
              );
            })}
          </div>
          <div className="od">Accounts come from the Zernio section in Settings.</div>
        </div>

        <label className="field">
          <span className="field-label">Min gap (min)</span>
          <input className="key-input" type="number" min="0" max="1440" aria-label="Minimum publish gap minutes"
            value={minGapMin} onChange={(e) => setMinGapMin(e.target.value === '' ? '' : Number(e.target.value))} />
          <div className="od">Minimum spacing between two scheduled posts — shared across every running monitor.</div>
        </label>

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
        </Group>

        <Btn variant="grad" icon="wand-sparkles" disabled={!canStart || starting} onClick={onStart} block>
          {starting ? 'Starting…' : 'Start monitor'}
        </Btn>
      </Panel>
    </div>
  );
}
