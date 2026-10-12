// ClippyMe — PublishModal: real concurrent publish to Zernio.
// Every selected clip is published in parallel (Promise.allSettled) — the fix
// for the old sequential stall — each row showing live queued→uploading→
// live/error status. Per-clip compose_first honours the clip's toggles.
import { useState, useEffect, useRef } from 'react';
import { Icon, Social, Btn, Switch, PlatPill, PLATFORMS } from '../../components/primitives';
import { LazyVideo } from '../../components/LazyVideo';
import { clipVideoSrc } from '../../api/client';
import { publishClip, getZernio } from '../../api/client';
import { seedToggles, seedHookParams, seedSubtitleParams, seedLogoParams, seedBannerParams } from '../../lib/seedClipParams';
import { localDatePlus, manualScheduleIso } from './scheduleDates';
import { clearPublishIntent, publishIntent } from './publishIntent';
import { useModalA11y } from '../../hooks/useModalA11y';

// UI platform id → backend platform + account key. Exported so other
// surfaces publishing to Zernio (live.jsx) don't re-derive this mapping.
export const PLAT = {
  tiktok: { platform: 'tiktok', acct: 'tiktok', icon: 'tiktok', label: 'TikTok' },
  ig: { platform: 'instagram', acct: 'instagram', icon: 'instagram', label: 'Reels' },
  yt: { platform: 'youtube', acct: 'youtube', icon: 'youtube', label: 'Shorts' },
};

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
        {/* LazyVideo, not a bare <video>: a 20-clip batch publish must not fire
            20 concurrent video fetches the moment the modal opens. */}
        <LazyVideo src={clipVideoSrc(clip)} muted playsInline rootMargin="120px"
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
  const [exactSchedule, setExactSchedule] = useState(false);
  const [publishTime, setPublishTime] = useState('');
  // Snapshot the mode the user actually submitted; React state updates are async.
  const [submittedMode, setSubmittedMode] = useState(null);
  const [caption, setCaption] = useState(clips[0]?.tiktok_caption || clips[0]?.video_title_for_youtube_short || '');
  const [stage, setStage] = useState('setup'); // setup | uploading | done
  const [progress, setProgress] = useState({});
  const [outcome, setOutcome] = useState(null); // actual confirmed/failed requests

  useEffect(() => { getZernio().then(setZernio).catch(() => setZernio({ configured: false })); }, []);

  // Accessibility: focus trap + Escape-to-close + focus restore.
  const panelRef = useModalA11y(onClose);

  // Guard the post-publish setTimeout so it never calls setState after the
  // modal has been unmounted (e.g. parent closes it while the delay is in flight).
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

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
  const buildBody = (clip, idx, batchPos = 0, mode, scheduledFor) => {
    const cs = clipStates[idx] || {};
    const toggles = cs.toggles ?? seedToggles(preselections);
    const any = Object.values(toggles).some(Boolean);
    const hookParams = cs.hookParams ?? seedHookParams(clip, preselections);
    const subtitleParams = cs.subtitleParams ?? seedSubtitleParams(preselections);
    const logoParams = cs.logoParams ?? seedLogoParams(preselections);
    const gradeParams = cs.gradeParams ?? { preset: preselections?.grade?.preset || 'none' };
    const bannerParams = cs.bannerParams ?? seedBannerParams(preselections);
    const title = (clip.video_title_for_youtube_short || `Clip ${idx + 1}`).slice(0, 100);
    return {
      title,
      caption: (caption && caption.trim()) || title,
      platforms: targets,
      // Always send the operator's edit intent. All-off must select the raw
      // clip even if an earlier composed artifact remains on disk.
      toggles,
      schedule_mode: mode,
      ...(mode === 'auto' ? { start_date: localDatePlus(batchPos) } : {}),
      ...(mode === 'manual' ? { scheduled_for: scheduledFor } : {}),
      timezone: zernio?.timezone || 'Europe/Rome',
      tiktok_settings: plats.tiktok && accounts.tiktok ? {
        privacy_level: 'PUBLIC_TO_EVERYONE', allow_comment: true, allow_duet: true,
        allow_stitch: true, content_preview_confirmed: true, express_consent_given: true,
      } : undefined,
      ...(any ? { compose_first: true, hook_params: toggles.hook ? hookParams : {}, subtitle_params: toggles.subtitles ? subtitleParams : {}, logo_params: toggles.logo ? logoParams : {}, grade_params: toggles.grade ? gradeParams : {}, banner_params: toggles.banner ? bannerParams : {}, drop_ranges: toggles.smartcut ? (cs.dropRanges || []) : [] } : {}),
    };
  };

  const run = async (mode) => {
    const scheduledFor = mode === 'manual' ? manualScheduleIso(publishTime) : null;
    if (mode === 'manual' && (!scheduledFor || all)) {
      pushToast?.('warn', 'Choose a future date and time for one clip.');
      return;
    }
    setSubmittedMode(mode);
    setStage('uploading');
    const init = {};
    clips.forEach((c) => { init[c._idx] = { state: 'uploading' }; });
    setProgress(init);
    const results = await Promise.allSettled(clips.map(async (clip, batchPos) => {
      const idx = clip._idx;
      // Resolve to the backend's ABSOLUTE `shorts` position for the actual
      // publish call — `idx` (array position) stays the key into local
      // clipStates/progress, which are unaffected by a manual-publish gap.
      const apiIdx = clip._apiIdx ?? idx;
      try {
        // Same intent for every retry of this Publish; a new one only after
        // the server confirmed it (then publishing again is a re-publish).
        const intent_id = publishIntent(jobId, apiIdx);
        await publishClip(jobId, apiIdx, { ...buildBody(clip, idx, batchPos, mode, scheduledFor), intent_id });
        clearPublishIntent(jobId, apiIdx);
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
    setOutcome({ ok, fail });
    setTimeout(() => {
      if (!mountedRef.current) return;
      setStage('done');
      pushToast?.(fail === 0 ? 'success' : 'warn', `${mode === 'now' ? 'Published' : 'Scheduled'} ${ok}/${clips.length}${fail ? `, ${fail} failed` : ''}`);
    }, 500);
  };

  const wasScheduled = submittedMode !== 'now';
  const manualReady = !exactSchedule || !schedule || (!!manualScheduleIso(publishTime) && !all);
  const title = stage === 'done' ? (outcome?.fail ? 'Publishing incomplete' : wasScheduled ? 'Scheduled' : 'Published')
    : all ? `Publish ${clips.length} clips` : `Publish · ${clips[0]?.video_title_for_youtube_short || ''}`;

  return (
    // Backdrop click is a mouse-only convenience; keyboard users close via
    // Esc (useModalA11y). currentTarget guard replaces stopPropagation.
    <div className="overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={'modal' + (all ? ' wide' : '')} ref={panelRef}
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
                  {schedule && !all && <div className="field">
                    <label className="field-label">
                      <input type="checkbox" checked={exactSchedule}
                        onChange={(e) => setExactSchedule(e.target.checked)} /> Choose exact publication time
                    </label>
                    {exactSchedule && <>
                      <label className="field-label" htmlFor="publish-exact-datetime">Publication date and time (your local time)</label>
                      <input id="publish-exact-datetime" type="datetime-local" value={publishTime}
                        onChange={(e) => setPublishTime(e.target.value)} />
                      {!manualScheduleIso(publishTime) && <div className="cm-small" role="status">Select a future date and time to continue.</div>}
                    </>}
                  </div>}
                </>
              )}
            </div>
            <div className="modal-foot">
              <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
              <div className="mf-right">
                <Btn variant="secondary" icon="send" disabled={!ready} onClick={() => run('now')}>Publish now</Btn>
                <Btn variant="grad" icon="calendar-clock" disabled={!ready || !manualReady} onClick={() => run(schedule ? (exactSchedule ? 'manual' : 'auto') : 'now')}>{schedule ? (exactSchedule ? 'Schedule exact time' : 'Schedule') : 'Queue'}</Btn>
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
              <Icon n={outcome?.ok === 0 ? 'x' : wasScheduled ? 'calendar-check' : 'party-popper'} style={{ width: 28, height: 28, color: outcome?.fail ? 'var(--danger)' : 'var(--brand-teal)' }} />
            </div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{outcome?.fail ? `${outcome.ok}/${clips.length} clips ${wasScheduled ? 'scheduled' : 'published'}` : <>{all ? `${clips.length} clips ` : 'Clip '}{wasScheduled ? 'scheduled' : 'published'}</>}</div>
            <p style={{ color: 'var(--fg-3)', fontSize: 13.5, marginTop: 8, lineHeight: 1.5 }}>
              {outcome?.fail ? `${outcome.fail} clip${outcome.fail === 1 ? '' : 's'} failed. Review the error below and retry from Results.` : submittedMode === 'manual' ? 'Scheduled via Zernio for your selected date and time.' : wasScheduled ? 'Queued via Zernio for the next prime-time slot.' : 'Sent to Zernio for immediate publish.'}
            </p>
            {outcome?.fail > 0 && <div className="pubgrid" style={{ marginTop: 18, textAlign: 'left' }}>
              {clips.filter((c) => progress[c._idx]?.state === 'error').map((c) =>
                <PubRow key={c._idx} clip={c} idx={c._idx} st={progress[c._idx]} plats={plats} />)}
            </div>}
            <div style={{ marginTop: 22 }}><Btn variant="secondary" onClick={onClose}>Done</Btn></div>
          </div>
        )}
      </div>
    </div>
  );
}
