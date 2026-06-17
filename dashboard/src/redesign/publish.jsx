// ClippyMe redesign — PublishModal: real concurrent publish to Zernio.
// Every selected clip is published in parallel (Promise.allSettled) — the fix
// for the old sequential stall — each row showing live queued→uploading→
// live/error status. Per-clip compose_first honours the clip's toggles.
import { useState, useEffect } from 'react';
import { Icon, Social, Btn, Switch, PlatPill, PLATFORMS } from './primitives';
import { clipVideoSrc } from './realApi';
import { publishClip, getZernio } from './realApi';
import { seedToggles, seedHookParams, seedSubtitleParams } from '../lib/seedClipParams';

// redesign plat id → backend platform + account key
const PLAT = {
  tiktok: { platform: 'tiktok', acct: 'tiktok', icon: 'tiktok', label: 'TikTok' },
  ig: { platform: 'instagram', acct: 'instagram', icon: 'instagram', label: 'Reels' },
  yt: { platform: 'youtube', acct: 'youtube', icon: 'youtube', label: 'Shorts' },
};

// Local YYYY-MM-DD for `start_date`, offset by `addDays`. Used to give each
// clip in a batch its own day so a per-platform daily posting cap (e.g.
// YouTube's 5/day) doesn't reject the tail of the batch.
function localDatePlus(addDays) {
  const d = new Date();
  d.setDate(d.getDate() + addDays);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function PubRow({ clip, idx, st, plats }) {
  // `st` is either a status string or { state, error } so we can surface the
  // real failure reason instead of a bare "failed".
  const status = typeof st === 'object' && st ? st.state : st;
  const errMsg = typeof st === 'object' && st ? st.error : null;
  const tasks = Object.keys(plats).filter((k) => plats[k]);
  const done = status === 'done';
  const error = status === 'error';
  return (
    <div className={'pubrow' + (done ? ' done' : '')}>
      <div className="pthumb" style={{ background: '#000', overflow: 'hidden' }}>
        <video src={clipVideoSrc(clip)} muted playsInline preload="metadata"
          style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      </div>
      <div className="pinfo">
        <div className="pttl">{clip.video_title_for_youtube_short || `Clip ${idx + 1}`}</div>
        <div className="pplats">
          {tasks.map((p) => (
            <div className="pp" key={p}>
              <Social n={PLAT[p].icon} color={done ? '02C5BF' : '7E7E8F'} size={13} />
              <div className="ptrack"><i className={p} style={{ width: done ? '100%' : status === 'uploading' ? '70%' : '0%', transition: 'width .4s' }}></i></div>
            </div>
          ))}
          <span className={'pstat' + (done ? ' done' : status === 'uploading' ? '' : ' wait')}
            style={error ? { color: 'var(--danger)' } : undefined}
            title={error && errMsg ? errMsg : undefined}>
            {error ? (errMsg ? `failed: ${errMsg.slice(0, 60)}` : 'failed') : done ? 'live' : status === 'uploading' ? 'uploading' : 'queued'}
          </span>
        </div>
      </div>
      <div className="pcheck"><Icon n={done ? 'check' : error ? 'x' : 'loader'} /></div>
    </div>
  );
}

export function PublishModal({ clips, jobId, clipStates = {}, preselections, onClose, onPublished, pushToast }) {
  const all = clips.length > 1;
  const [zernio, setZernio] = useState(null);
  const [plats, setPlats] = useState({ tiktok: true, ig: true, yt: false });
  const [schedule, setSchedule] = useState(true);
  const [caption, setCaption] = useState(clips[0]?.tiktok_caption || clips[0]?.video_title_for_youtube_short || '');
  const [stage, setStage] = useState('setup'); // setup | uploading | done
  const [progress, setProgress] = useState({});

  useEffect(() => { getZernio().then(setZernio).catch(() => setZernio({ configured: false })); }, []);

  // Accessibility: close on Escape so keyboard users aren't trapped.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const accounts = zernio?.accounts || {};
  const toggle = (k) => setPlats((p) => ({ ...p, [k]: !p[k] }));
  const platTargets = () => Object.keys(plats)
    .filter((k) => plats[k] && accounts[PLAT[k].acct])
    .map((k) => ({ platform: PLAT[k].platform, accountId: accounts[PLAT[k].acct] }));
  const targets = platTargets();
  const ready = zernio?.configured && targets.length > 0;

  // `batchPos` is the clip's position within this batch (0-based). When
  // scheduling, each clip gets its own day (start_date = today + batchPos) so
  // a per-platform daily cap doesn't reject the tail of the batch — replicates
  // the one-clip-per-day spacing from the original publisher.
  const buildBody = (clip, idx, batchPos = 0) => {
    const cs = clipStates[idx] || {};
    const toggles = cs.toggles ?? seedToggles(preselections);
    const any = Object.values(toggles).some(Boolean);
    const hookParams = cs.hookParams ?? seedHookParams(clip, preselections);
    const subtitleParams = cs.subtitleParams ?? seedSubtitleParams(preselections);
    const title = (clip.video_title_for_youtube_short || `Clip ${idx + 1}`).slice(0, 100);
    return {
      title,
      caption: (caption && caption.trim()) || title,
      platforms: targets,
      schedule_mode: schedule ? 'auto' : 'now',
      ...(schedule ? { start_date: localDatePlus(batchPos) } : {}),
      timezone: zernio?.timezone || 'Europe/Rome',
      tiktok_settings: plats.tiktok && accounts.tiktok ? {
        privacy_level: 'PUBLIC_TO_EVERYONE', allow_comment: true, allow_duet: true,
        allow_stitch: true, content_preview_confirmed: true, express_consent_given: true,
      } : undefined,
      ...(any ? { compose_first: true, toggles, hook_params: toggles.hook ? hookParams : {}, subtitle_params: toggles.subtitles ? subtitleParams : {} } : {}),
    };
  };

  const run = async () => {
    setStage('uploading');
    const init = {};
    clips.forEach((c) => { init[c._idx] = { state: 'uploading' }; });
    setProgress(init);
    const results = await Promise.allSettled(clips.map(async (clip, batchPos) => {
      const idx = clip._idx;
      try {
        await publishClip(jobId, idx, buildBody(clip, idx, batchPos));
        setProgress((p) => ({ ...p, [idx]: { state: 'done' } }));
        onPublished?.(idx);
        return true;
      } catch (e) {
        // Surface the real reason (e.g. a Zernio daily-limit 429) instead of a
        // bare "failed", so the user knows to retry that platform tomorrow.
        setProgress((p) => ({ ...p, [idx]: { state: 'error', error: e?.message || 'Publish failed' } }));
        return false;
      }
    }));
    const ok = results.filter((r) => r.status === 'fulfilled' && r.value).length;
    const fail = clips.length - ok;
    setTimeout(() => {
      setStage('done');
      pushToast?.(fail === 0 ? 'success' : 'warn', `Published ${ok}/${clips.length}${fail ? `, ${fail} failed` : ''}`);
    }, 500);
  };

  const title = stage === 'done' ? (schedule ? 'Scheduled' : 'Published')
    : all ? `Publish ${clips.length} clips` : `Publish · ${clips[0]?.video_title_for_youtube_short || ''}`;

  return (
    <div className="overlay" onClick={onClose}>
      <div className={'modal' + (all ? ' wide' : '')} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="publish-modal-title">
        <div className="modal-head">
          <div>
            <h3 id="publish-modal-title">{title}</h3>
            {stage === 'uploading' && <div className="mh-sub">uploading concurrently · daily-limit checks server-side</div>}
          </div>
          <button className="x" onClick={onClose} aria-label="Close"><Icon n="x" /></button>
        </div>

        {stage === 'setup' && (
          <>
            <div className="modal-body">
              {!zernio ? <div className="cm-small">Loading Zernio…</div> : !zernio.configured ? (
                <div className="empty" style={{ padding: '24px 12px' }}>
                  <div className="ei"><Icon n="rss" /></div>
                  <h3>Zernio not connected</h3>
                  <p>Add your Zernio API key + account IDs in Settings to publish.</p>
                </div>
              ) : (
                <>
                  <div className="field">
                    <span className="field-label">Platforms</span>
                    <div className="plats">
                      {PLATFORMS.map((p) => {
                        const has = !!accounts[PLAT[p.id].acct];
                        return <PlatPill key={p.id} {...p} on={plats[p.id] && has}
                          onClick={() => has ? toggle(p.id) : pushToast?.('warn', `No ${PLAT[p.id].label} account saved`)} />;
                      })}
                    </div>
                  </div>
                  <div className="field">
                    <span className="field-label">Caption</span>
                    <textarea className="ta" rows="3" value={caption} onChange={(e) => setCaption(e.target.value)}></textarea>
                  </div>
                  <div className="opt" style={{ borderBottom: 0 }}>
                    <div className="oico"><Icon n="calendar-clock" /></div>
                    <div className="otxt"><div className="ot">Schedule for prime time</div><div className="od">SmartScheduler picks the slot · off = publish now</div></div>
                    <div className="r"><Switch on={schedule} onChange={setSchedule} /></div>
                  </div>
                </>
              )}
            </div>
            <div className="modal-foot">
              <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
              <div className="mf-right">
                <Btn variant="secondary" icon="send" disabled={!ready} onClick={() => { setSchedule(false); run(); }}>Publish now</Btn>
                <Btn variant="grad" icon="calendar-clock" disabled={!ready} onClick={run}>{schedule ? 'Schedule' : 'Queue'}</Btn>
              </div>
            </div>
          </>
        )}

        {stage === 'uploading' && (
          <div className="modal-body">
            <div className="pubgrid">
              {clips.map((c) => <PubRow key={c._idx} clip={c} idx={c._idx} st={progress[c._idx]} plats={plats} />)}
            </div>
          </div>
        )}

        {stage === 'done' && (
          <div className="modal-body" style={{ textAlign: 'center', padding: '36px 24px' }}>
            <div style={{ width: 60, height: 60, borderRadius: '50%', background: 'var(--success-bg)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 18px' }}>
              <Icon n={schedule ? 'calendar-check' : 'party-popper'} style={{ width: 28, height: 28, color: 'var(--brand-teal)' }} />
            </div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{all ? `${clips.length} clips ` : 'Clip '}{schedule ? 'scheduled' : 'published'}</div>
            <p style={{ color: 'var(--fg-3)', fontSize: 13.5, marginTop: 8, lineHeight: 1.5 }}>
              {schedule ? 'Queued via Zernio for the next prime-time slot.' : 'Sent to Zernio for immediate publish.'}
            </p>
            <div style={{ marginTop: 22 }}><Btn variant="secondary" onClick={onClose}>Done</Btn></div>
          </div>
        )}
      </div>
    </div>
  );
}
