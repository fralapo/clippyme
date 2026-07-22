// ClippyMe redesign — mobile-first manual publishing companion: a queue of
// frozen MP4s from Live Monitor (publisher_mode='manual_queue') waiting to be
// grabbed and posted by hand, plus a per-clip History browser and an embed of
// the existing Live Monitor manager. Four tabs: Da pubblicare (default) /
// Pubblicate / History / Monitor.
import { useState, useEffect, useCallback } from 'react';
import { Hero } from './chrome';
import { Icon, Btn, Panel } from './primitives';
import {
  getManualQueue, completeManualEntry, restoreManualEntry, manualEntryVideoUrl,
  deleteHistoryClip, listHistoryJobs, fmtDuration,
} from './realApi';
import { relTime } from './views';
import { LiveMonitorView } from './live';
import { shareClip } from '../lib/manualShare';

const TABS = [
  { id: 'pending', label: 'Da pubblicare' },
  { id: 'completed', label: 'Pubblicate' },
  { id: 'history', label: 'History' },
  { id: 'monitor', label: 'Monitor' },
];

// Group order: source platform -> channel -> project/stream/video -> clip
// order (clip_index ascending within a project).
function groupEntries(entries) {
  const map = new Map();
  for (const e of entries) {
    const key = [e.source_platform, e.source_channel, e.project_title].join('||');
    if (!map.has(key)) {
      map.set(key, {
        platform: e.source_platform, channel: e.source_channel, project: e.project_title, entries: [],
      });
    }
    map.get(key).entries.push(e);
  }
  const groups = Array.from(map.values());
  for (const g of groups) g.entries.sort((a, b) => (a.clip_index ?? 0) - (b.clip_index ?? 0));
  groups.sort((a, b) =>
    a.platform.localeCompare(b.platform) || a.channel.localeCompare(b.channel) || a.project.localeCompare(b.project));
  return groups;
}

function QueueCard({ entry, onComplete, onRestore, pushToast }) {
  const [sharing, setSharing] = useState(false);
  const videoUrl = manualEntryVideoUrl(entry.id);
  const filename = `${entry.title || 'clip'}.mp4`;

  const copyCaption = async () => {
    try {
      await navigator.clipboard.writeText(entry.caption || '');
      pushToast?.('success', 'Caption copied');
    } catch {
      pushToast?.('error', 'Copy failed');
    }
  };

  const download = () => {
    const a = document.createElement('a');
    a.href = videoUrl; a.download = filename; a.style.display = 'none';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  };

  const share = async () => {
    setSharing(true);
    try {
      const result = await shareClip({ videoUrl, filename, caption: entry.caption || '' });
      // Never auto-check "published" here — cancelled/fallback both keep the
      // entry pending; the user marks it themselves once actually posted.
      if (result.fallback) pushToast?.('info', 'Sharing not available on this device — use Copy or Download.');
    } finally {
      setSharing(false);
    }
  };

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', gap: 14, padding: 16, flexWrap: 'wrap' }}>
        {/* Lazy: no network fetch happens until the user presses play. */}
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video src={videoUrl} preload="none" controls
          style={{ width: 108, aspectRatio: '9 / 16', borderRadius: 8, background: '#000', flex: 'none' }} />
        <div style={{ minWidth: 0, flex: '1 1 220px' }}>
          <div className="hm">{entry.source_platform} / {entry.source_channel} / {entry.project_title}</div>
          <div className="ht" style={{ whiteSpace: 'normal' }}>{entry.title}</div>
          {entry.caption && <div className="od" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>{entry.caption}</div>}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
            <Btn variant="secondary" icon="clipboard" onClick={copyCaption}>Copia caption</Btn>
            <Btn variant="secondary" icon="send" onClick={share} disabled={sharing}>Condividi</Btn>
            <Btn variant="secondary" icon="download" onClick={download}>Scarica MP4</Btn>
            {entry.status === 'pending' ? (
              <Btn variant="primary" icon="check" onClick={() => onComplete(entry.id)}>Segna pubblicata</Btn>
            ) : (
              <Btn variant="ghost" icon="refresh-cw" onClick={() => onRestore(entry.id)}>Ripristina nella coda</Btn>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function QueuePanel({ status, pushToast }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { entries: es } = await getManualQueue(status);
      setEntries(es || []);
    } catch {
      setError('Could not load the queue.');
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { load(); }, [load]);

  const onComplete = async (id) => {
    try { await completeManualEntry(id); pushToast?.('success', 'Marked as published'); }
    catch { pushToast?.('error', 'That failed — try again'); }
    load();
  };
  const onRestore = async (id) => {
    try { await restoreManualEntry(id); pushToast?.('info', 'Back in the queue'); }
    catch { pushToast?.('error', 'That failed — try again'); }
    load();
  };

  if (loading) return <div className="od">Loading…</div>;
  if (error) return <div className="od" style={{ color: 'var(--danger)' }}>{error}</div>;

  const groups = groupEntries(entries);
  if (groups.length === 0) {
    return (
      <div className="empty">
        <div className="ei"><Icon n="send" /></div>
        <h3>{status === 'pending' ? 'Nothing to publish yet' : 'Nothing published yet'}</h3>
        <p>{status === 'pending'
          ? 'Clips from Live Monitor land here, ready to grab and post by hand.'
          : 'Clips you mark as published show up here — restore any of them back to the queue.'}</p>
      </div>
    );
  }

  return (
    <div>
      {!window.isSecureContext && (
        <div className="od" style={{ color: 'var(--warn, #f5a623)', marginBottom: 16 }}>
          Condividi (native share) needs HTTPS or a Tailscale address — Copia/Scarica still work here.
        </div>
      )}
      {groups.map((g) => (
        <div key={`${g.platform}||${g.channel}||${g.project}`} style={{ marginBottom: 22 }}>
          <div className="results-head" style={{ marginBottom: 10 }}>
            <h2 style={{ fontSize: 'var(--text-base)' }}>{g.platform} / {g.channel} / {g.project}</h2>
          </div>
          {g.entries.map((e) => (
            <QueueCard key={e.id} entry={e} onComplete={onComplete} onRestore={onRestore} pushToast={pushToast} />
          ))}
        </div>
      ))}
    </div>
  );
}

function HistoryPanel({ pushToast }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setJobs(await listHistoryJobs()); }
    catch { setError('Could not load History.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onDeleteClip = async (jobId, clipIndex) => {
    if (!window.confirm('Delete this clip? This cannot be undone.')) return;
    try {
      await deleteHistoryClip(jobId, clipIndex);
      pushToast?.('info', 'Clip deleted');
    } catch {
      pushToast?.('error', 'Delete failed — try again');
    }
    load();
  };

  if (loading) return <div className="od">Loading…</div>;
  if (error) return <div className="od" style={{ color: 'var(--danger)' }}>{error}</div>;
  if (jobs.length === 0) {
    return (
      <div className="empty">
        <div className="ei"><Icon n="clock" /></div>
        <h3>No jobs yet</h3>
        <p>Finished clips will show up here, one row per clip.</p>
      </div>
    );
  }

  return (
    <div>
      {jobs.map((job) => (
        <Panel key={job.jobId} title={job.title || job.source || job.jobId}
          sub={`${job.clipCount ?? (job.clips || []).length} clip(s)${job.timestamp ? ' · ' + relTime(job.timestamp) : ''}`}
          style={{ marginBottom: 16 }}>
          {(job.clips || []).map((clip, idx) => (
            <div className="opt" key={idx}>
              <div className="otxt">
                <div className="ot">{clip.title || `Clip ${idx + 1}`}</div>
                <div className="od">
                  {fmtDuration(clip.start, clip.end)}
                  {clip.published && clip.published.length > 0 ? ' · published' : ''}
                </div>
              </div>
              <div className="r">
                <button type="button" className="mini mp-mini" title="Delete clip" aria-label={`Delete clip ${idx + 1}`}
                  onClick={() => onDeleteClip(job.jobId, idx)}>
                  <Icon n="trash-2" />
                </button>
              </div>
            </div>
          ))}
        </Panel>
      ))}
    </div>
  );
}

export function ManualPublishView({ pushToast }) {
  const [activeTab, setActiveTab] = useState('pending');

  return (
    <div className="container narrow fade-in">
      <Hero eyebrow="Manual publish" line1="Grab it," grad="post it."
        sub="Clips waiting for you to post by hand, grouped by source — plus History and Live Monitor in one place." />

      {/* Reuses the existing sticky secondary-bar look (`.actionbar`) and the
          TopNav tab styling (`.tabs`/`.tab`) — no new CSS. */}
      <div className="actionbar" style={{ marginBottom: 18 }}>
        <div className="tabs">
          {TABS.map((t) => (
            <button key={t.id} type="button" className={'tab mp-tab' + (activeTab === t.id ? ' active' : '')}
              onClick={() => setActiveTab(t.id)}>
              <span className="lbl">{t.label}</span>
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'pending' && <QueuePanel status="pending" pushToast={pushToast} />}
      {activeTab === 'completed' && <QueuePanel status="completed" pushToast={pushToast} />}
      {activeTab === 'history' && <HistoryPanel pushToast={pushToast} />}
      {activeTab === 'monitor' && <LiveMonitorView pushToast={pushToast} />}
    </div>
  );
}
