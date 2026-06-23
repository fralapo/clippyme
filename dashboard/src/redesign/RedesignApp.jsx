// ClippyMe redesign — wired to the real backend via the production hooks.
// Visual layer is the Claude Design handoff; data layer reuses the same
// useJobSubmission / useJobPolling / useHistory / useClipStates the production
// app uses, so the pipeline behaves identically.
import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import './tokens.css';
import './app.css';
import { Icon, Btn } from './primitives';
import { TopNav } from './chrome';
import { CreateView } from './create';
import { ProcessingView } from './processing';
import { ResultsView } from './results';
import { PublishModal } from './publish';
import { HistoryView, SettingsView, ApiKeyModal } from './views';
import { EditClipModal } from './captions';
import { optsToPreselections, restoreJob, listBackendJobIds, cancelJob, pauseJob, resumeJob, stopJob, reframeClip, composeClip } from './realApi';
import { allPresets, getDefaultPresetOpts, getDefaultPresetId, saveUserPreset, deleteUserPreset, setDefaultPreset } from './presets';
import { HOOK_STYLE_DEFAULT } from './data';
import { clipStateToParams, buildBulkPlan } from '../lib/bulkApply';

import { useJobSubmission } from '../hooks/useJobSubmission';
import { useJobPolling } from '../hooks/useJobPolling';
import { useHistory } from '../hooks/useHistory';
import { useClipStates } from '../hooks/useClipStates';
import { recordTasteEvent } from '../lib/taste';
import { useBackendStatus } from '../hooks/useBackendStatus';
import { useSessionPersistence } from '../hooks/useSessionPersistence';

const DEFAULT_OPTS = {
  mode: 'single', source: 'url', url: '', file: null, fileName: '', batch: '', batchFiles: [], instructions: '',
  clipsAuto: true, clips: 7, aspect: '9:16',
  detect: true, reframeMode: 'auto', smartcut: true, zoom: true, model: '',
  subtitles: true, subMode: 'karaoke', subPreset: 'hormozi_bold', subPosition: 'center',
  subFont: 'Montserrat-Black', subColor: '#FFFFFF',
  hooks: true, hookPos: 'top', hookSize: 'M', hookStyle: { ...HOOK_STYLE_DEFAULT },
  logo: false, logoPos: 'top-right', logoSize: 'M', gradePreset: 'none',
  language: 'multi',
  platforms: { tiktok: true, ig: true, yt: false },
  preset: 'viral',
};

const CONFETTI_COLORS = ['#E6428D', '#9850C3', '#675ADD', '#0A81D9', '#02C5BF', '#F7BC59'];

function Confetti() {
  const pieces = useMemo(() => Array.from({ length: 90 }, (_, i) => ({
    left: Math.random() * 100, delay: Math.random() * 0.6, dur: 2.2 + Math.random() * 1.6,
    color: CONFETTI_COLORS[i % CONFETTI_COLORS.length], rot: Math.random() * 360, w: 6 + Math.random() * 6,
  })), []);
  return (
    <div className="confetti">
      {pieces.map((p, i) => (
        <i key={i} style={{ left: p.left + '%', background: p.color, width: p.w, height: p.w * 1.6,
          transform: `rotate(${p.rot}deg)`, animationDelay: p.delay + 's', animationDuration: p.dur + 's' }} />
      ))}
    </div>
  );
}

function Toasts({ items }) {
  const ic = { success: 'circle-check', warn: 'triangle-alert', info: 'info', error: 'triangle-alert' };
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={'toast ' + (t.type === 'error' ? 'warn' : t.type)}>
          <span className="ti"><Icon n={ic[t.type] || 'info'} /></span>
          <span>{t.msg}</span>
        </div>
      ))}
    </div>
  );
}

export default function RedesignApp() {
  const [apiKey, setApiKey] = useState(localStorage.getItem('gemini_key') || '');
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [tab, setTab] = useState('create');
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | processing | complete | error
  const [results, setResults] = useState(null);
  const [logs, setLogs] = useState([]);
  const [currentStep, setCurrentStep] = useState(null);
  const [processingMedia, setProcessingMedia] = useState(null);
  const [paused, setPaused] = useState(false);
  // Seed Create from the user's default preset (if any) so their preferred
  // settings are already applied on load.
  const [opts, setOpts] = useState(() => ({ ...DEFAULT_OPTS, ...(getDefaultPresetOpts() || {}) }));
  const [presetsVersion, setPresetsVersion] = useState(0);
  const [defaultPresetId, setDefaultPresetId] = useState(getDefaultPresetId());
  // presetsVersion is a manual cache-bust trigger: allPresets() reads from
  // external (localStorage) state, so bumping the version must force a recompute.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const presetList = useMemo(() => allPresets(), [presetsVersion]);
  const [preselections, setPreselectionsRaw] = useState(null);
  const [confetti, setConfetti] = useState(false);
  const [toasts, setToasts] = useState([]);
  // Track all auto-dismiss timer ids so they can be cleared if the component
  // unmounts before any timer fires (prevents setState on an unmounted tree).
  const toastTimerIds = useRef([]);
  useEffect(() => () => { toastTimerIds.current.forEach(clearTimeout); }, []);
  const [publishClips, setPublishClips] = useState(null);
  const [editClip, setEditClip] = useState(null);
  // Multi-select bulk editor: { targets: [{ i, c }] }.
  const [bulkEdit, setBulkEdit] = useState(null);
  const [viewingHistory, setViewingHistory] = useState(false);
  // jobIds that still exist on disk (null = not yet known / backend offline →
  // don't disable anything). Reconciles the localStorage history list against
  // reality so jobs wiped by a rebuild are flagged instead of dead-clicking.
  const [availableJobIds, setAvailableJobIds] = useState(null);

  const { history, saveToHistory, deleteFromHistory, clearHistory } = useHistory();
  const { cookiesConfigured, setCookiesConfigured } = useBackendStatus();
  const { states: clipStates, updateClip: updateClipState } = useClipStates(jobId);

  // Cross-job taste memory (#8): record a kept/discarded signal as the user
  // publishes or removes clips, then wrap updateClipState so every call site
  // feeds the taste profile without extra plumbing.
  const updateClipStateT = (idx, patch) => {
    try {
      const c = clips?.[idx];
      if (c && patch) {
        const metrics = { viralScore: c.viral_score, duration: (c.end || 0) - (c.start || 0) };
        if (patch.deleted === true) recordTasteEvent({ ...metrics, action: 'discarded' });
        if (patch.publishedAt) recordTasteEvent({ ...metrics, action: 'kept' });
      }
    } catch { /* taste memory is best-effort */ }
    updateClipState(idx, patch);
  };

  useEffect(() => { if (apiKey) localStorage.setItem('gemini_key', apiKey); }, [apiKey]);
  // Refresh the on-disk job set whenever the History tab opens, so a job whose
  // files were removed (rebuild/cleanup) shows as unavailable rather than
  // failing silently when clicked.
  useEffect(() => {
    if (tab === 'history' && !viewingHistory) listBackendJobIds().then(setAvailableJobIds);
  }, [tab, viewingHistory]);
  useSessionPersistence({ status, jobId, results, processingMedia, activeTab: tab, preselections });

  const pushToast = useCallback((type, msg) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, type, msg }]);
    const tid = setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3600);
    toastTimerIds.current.push(tid);
  }, []);

  // Background clip reprocess: the Edit modal stages the changes and hands them
  // here, then closes immediately. The reframe (subprocess) + compose
  // (subtitles → smart-cut → hook) run here, OUTSIDE the modal lifecycle, so the
  // user can keep editing other clips while this one renders. The clip's
  // `processing` flag drives the per-card spinner; each clip is an independent
  // async chain → several can render concurrently.
  const reprocessClip = useCallback(async (idx, clip, params) => {
    const { reframeMode, baseMode, toggles, subtitleParams, hookParams, logoParams, gradeParams, dropRanges } = params;
    const reframeChanged = reframeMode !== baseMode;
    const anyCompose = !!(toggles.smartcut || toggles.subtitles || toggles.hook || toggles.logo || toggles.grade);

    // Persist the user's choices + flip the card into its processing state up
    // front (so the badge/preview already reflect the new reframe mode).
    updateClipState(idx, { reframeMode, toggles, subtitleParams, hookParams, logoParams, gradeParams, dropRanges,
      processing: reframeChanged || anyCompose });

    if (!reframeChanged && !anyCompose) {
      pushToast('success', `Clip ${idx + 1} updated`);
      return;
    }

    let reframeApplied = false;
    try {
      if (reframeChanged) {
        await reframeClip(jobId, idx, reframeMode);
        reframeApplied = true;
        // Reframe overwrites the clip on disk → bust the cache + drop any stale
        // composed preview so the card re-fetches the freshly framed clip.
        updateClipState(idx, { reframeBust: Date.now(), previewUrl: undefined });
      }
      if (anyCompose) {
        const { composed_url } = await composeClip(jobId, idx, {
          toggles,
          hook_params: toggles.hook ? hookParams : {},
          subtitle_params: toggles.subtitles ? subtitleParams : {},
          logo_params: toggles.logo ? logoParams : {},
          grade_params: toggles.grade ? gradeParams : {},
          drop_ranges: toggles.smartcut ? (dropRanges || []) : [],
        });
        updateClipState(idx, { previewUrl: composed_url, previewBust: Date.now(), processing: false });
      } else {
        updateClipState(idx, { processing: false });
      }
      pushToast('success', `Clip ${idx + 1} updated`);
    } catch (err) {
      // Partial success: reframe already overwrote the file, so keep its
      // cache-buster even though composing failed — otherwise the card serves
      // the pre-reframe cached URL forever.
      if (reframeApplied) {
        updateClipState(idx, { reframeBust: Date.now(), previewUrl: undefined, processing: false });
        pushToast('error', `Clip ${idx + 1}: reframed, but composing the layers failed.`);
        return;
      }
      updateClipState(idx, { processing: false });
      pushToast('error', err?.status === 409
        ? `Clip ${idx + 1} is too old to reframe — reprocess the video first.`
        : `Clip ${idx + 1} reprocess failed: ` + String(err?.message || err).slice(0, 50));
    }
  }, [jobId, updateClipState, pushToast]);

  const setPreselections = (value) => {
    setPreselectionsRaw(value);
    try { if (jobId && value) localStorage.setItem(`clippyme_preselections_job_${jobId}`, JSON.stringify(value)); } catch { /* */ }
  };

  // recipe / manual-edit handling on opts
  const set = (patch) => setOpts((o) => ({ ...o, ...patch, preset: null }));
  const pickPreset = (p) => setOpts((o) => ({ ...o, ...p.opts, preset: p.id }));

  const onSaveCurrentPreset = () => {
    const name = window.prompt('Name this preset:');
    if (!name || !name.trim()) return;
    saveUserPreset(name.trim(), opts);
    setPresetsVersion((v) => v + 1);
    pushToast('success', `Preset "${name.trim()}" saved`);
  };
  const onSetDefaultPreset = (id) => {
    const next = defaultPresetId === id ? null : id;
    setDefaultPreset(next);
    setDefaultPresetId(next);
    pushToast('info', next ? 'Default preset set' : 'Default cleared');
  };
  const onDeletePreset = (id) => {
    deleteUserPreset(id);
    setPresetsVersion((v) => v + 1);
    if (defaultPresetId === id) setDefaultPresetId(null);
    pushToast('info', 'Preset deleted');
  };

  useJobPolling({
    jobId,
    isActive: status === 'processing',
    onResult: setResults,
    onCompleted: (data) => {
      setStatus('complete');
      setConfetti(true);
      setTimeout(() => setConfetti(false), 3000);
      pushToast('success', `${data.result?.clips?.length || 0} clips ready`);
      saveToHistory({
        jobId,
        status: 'complete',
        timestamp: Date.now(),
        source: processingMedia?.type === 'url' ? processingMedia.payload : processingMedia?.payload?.name || 'Local file',
        sourceType: processingMedia?.type || 'file',
        clipCount: data.result?.clips?.length || 0,
        cost: data.result?.cost_analysis?.total_cost || null,
      });
    },
    onStopped: (data) => {
      // Graceful stop kept the finished clips — route to the editable results
      // view just like a normal completion.
      setStatus('complete');
      setPaused(false);
      pushToast('info', `Stopped — kept ${data.result?.clips?.length || 0} clip(s)`);
      saveToHistory({
        jobId,
        status: 'stopped',
        timestamp: Date.now(),
        source: processingMedia?.type === 'url' ? processingMedia.payload : processingMedia?.payload?.name || 'Local file',
        sourceType: processingMedia?.type || 'file',
        clipCount: data.result?.clips?.length || 0,
        cost: data.result?.cost_analysis?.total_cost || null,
      });
    },
    onCancelled: () => { setStatus('idle'); setJobId(null); setResults(null); setLogs([]); setCurrentStep(null); setPaused(false); },
    onFailed: (errorMsg) => {
      setStatus('error');
      setLogs((prev) => [...prev, 'Error: ' + errorMsg]);
      pushToast('error', 'Job failed: ' + String(errorMsg).slice(0, 80));
    },
    onProgress: (lg, step) => { setLogs(lg); if (step) setCurrentStep(step); },
  });

  const { handleProcess, handleBatchProcess } = useJobSubmission({
    apiKey, setShowKeyModal, setStatus, setLogs, setResults, setProcessingMedia,
    setPreselections, setJobId,
    onBatchFinished: ({ succeeded, failed, total }) => {
      setTab('history');
      pushToast(failed === 0 ? 'success' : 'warn', `Batch: ${succeeded}/${total} ok${failed ? `, ${failed} failed` : ''}`);
    },
  });

  const startJob = () => {
    const pre = optsToPreselections(opts);
    // The backend has no clip-count parameter — Gemini decides how many clips
    // the video is worth. When the user opts out of Auto and sets a target, we
    // pass it as a soft hint in the instructions (Gemini may still return more
    // or fewer based on the content).
    let instructions = opts.instructions || '';
    if (!opts.clipsAuto) {
      instructions = `${instructions} Aim for roughly ${opts.clips} clips.`.trim();
    }
    if (opts.mode === 'single') {
      if (opts.source === 'url') {
        if (!opts.url.trim()) return;
        handleProcess({ type: 'url', payload: opts.url.trim(), instructions, preselections: pre });
      } else {
        if (!opts.file) return;
        handleProcess({ type: 'file', payload: opts.file, instructions, preselections: pre });
      }
    } else {
      const urls = opts.batch.split('\n').map((l) => l.trim()).filter(Boolean);
      handleBatchProcess({ urls, files: opts.batchFiles, instructions, preselections: pre });
    }
  };

  const resetToCreate = () => {
    // If a job is still running, actually cancel it on the backend instead of
    // just dropping our local handle (which would leave it churning).
    if (status === 'processing' && jobId) cancelJob(jobId);
    setStatus('idle'); setJobId(null); setResults(null); setLogs([]); setProcessingMedia(null);
    setCurrentStep(null); setViewingHistory(false); setTab('create'); setPaused(false);
    try { localStorage.removeItem('clippyme_session'); } catch { /* */ }
  };

  // Job controls (backend: /api/pause, /api/resume, /api/stop).
  const pauseCurrent = async () => {
    if (!jobId) return;
    try { await pauseJob(jobId); setPaused(true); pushToast('info', 'Job paused'); }
    catch (e) { pushToast('error', 'Pause failed: ' + String(e.message || e).slice(0, 60)); }
  };
  const resumeCurrent = async () => {
    if (!jobId) return;
    try { await resumeJob(jobId); setPaused(false); pushToast('info', 'Job resumed'); }
    catch (e) { pushToast('error', 'Resume failed: ' + String(e.message || e).slice(0, 60)); }
  };
  const stopCurrent = async () => {
    if (!jobId) return;
    // Graceful stop — the poll loop picks up status 'stopped' and onStopped
    // routes to the results view with the clips finished so far.
    try { await stopJob(jobId); pushToast('info', 'Stopping — keeping finished clips…'); }
    catch (e) { pushToast('error', 'Stop failed: ' + String(e.message || e).slice(0, 60)); }
  };

  const openPublish = (clips) => setPublishClips(Array.isArray(clips) ? clips : [clips]);

  const goTab = (next) => {
    if (next === 'create' && (status === 'complete' || status === 'error')) {
      setStatus('idle'); setJobId(null); setResults(null); setLogs([]); setProcessingMedia(null); setCurrentStep(null);
    }
    setViewingHistory(false);
    setTab(next);
  };

  const openHistoryJob = async (h) => {
    try {
      const data = await restoreJob(h.jobId);
      setJobId(h.jobId);
      setResults(data.result);
      setStatus('complete');
      setProcessingMedia({ type: h.sourceType || 'url', payload: h.source });
      try {
        const saved = localStorage.getItem(`clippyme_preselections_job_${h.jobId}`);
        setPreselectionsRaw(saved ? JSON.parse(saved) : null);
      } catch { setPreselectionsRaw(null); }
      setViewingHistory(true);
    } catch (err) {
      // The clip files are gone from disk (typically a docker rebuild/cleanup
      // wiped output/ while the localStorage entry lingered). Drop the dead
      // entry so the phantom row stops teasing a click that can never open.
      if (err?.status === 404 || err?.status === 400) {
        deleteFromHistory(h.jobId);
        setAvailableJobIds((prev) => { if (!prev) return prev; const n = new Set(prev); n.delete(h.jobId); return n; });
        pushToast('error', 'Clip files were removed (rebuild/cleanup) — entry cleared');
      } else {
        pushToast('error', 'Could not restore this job');
      }
    }
  };

  const clips = results?.clips || [];

  // Visible (non-removed) clips as {i, c} — shared by both bulk paths.
  const visibleClips = () => clips.map((c, i) => ({ i, c })).filter(({ i }) => !clipStates[i]?.deleted);

  // Bounded-concurrency runner for bulk reprocessing. Each reprocessClip spawns
  // heavy backend work (reframe = YOLO/MediaPipe subprocess, compose = ffmpeg)
  // and the server only throttles the MAIN job worker — these endpoints are
  // ungated, so the client is the only throttle. A bare forEach would fire all
  // N at once and thrash/OOM the box. Cap at 2 (matches AE_MAX_PARALLEL); this
  // is the same reason results.jsx:exportMany runs sequentially. reprocessClip
  // swallows its own errors, so a failed clip never breaks the pool.
  const runBulk = async (plan, limit = 2) => {
    let next = 0;
    const worker = async () => {
      while (next < plan.length) {
        const { idx, clip, params } = plan[next++];
        await reprocessClip(idx, clip, params);
      }
    };
    await Promise.all(Array.from({ length: Math.min(limit, plan.length) }, worker));
  };

  // "Apply to all": take one clip's saved settings (or the global seeds if it
  // was never edited) and reprocess every OTHER visible clip with them. Manual
  // trim + per-clip hook text are intentionally not propagated (see bulkApply).
  const applyClipToAll = (srcIdx) => {
    const src = clips[srcIdx];
    if (!src) return;
    const srcParams = clipStateToParams(clipStates[srcIdx], preselections, src);
    const plan = buildBulkPlan(srcParams, visibleClips(), clipStates, srcIdx);
    if (!plan.length) { pushToast('info', 'No other clips to apply to'); return; }
    pushToast('info', `Applying settings to ${plan.length} clip${plan.length === 1 ? '' : 's'}…`);
    runBulk(plan);
  };

  // Bulk editor "Apply": staged params from the modal → every selected clip.
  const applyBulkEdit = (params, targets) => {
    const srcParams = {
      reframeMode: params.reframeMode,
      toggles: params.toggles,
      subtitleParams: params.subtitleParams,
      hookParams: params.hookParams,
      logoParams: params.logoParams,
      gradeParams: params.gradeParams,
    };
    const plan = buildBulkPlan(srcParams, targets, clipStates);
    if (!plan.length) return;
    pushToast('info', `Reprocessing ${plan.length} clip${plan.length === 1 ? '' : 's'}…`);
    runBulk(plan);
  };

  return (
    <div>
      <TopNav tab={tab} setTab={goTab} busy={status === 'processing'} />
      {confetti && <Confetti />}

      {tab === 'create' && status === 'idle' && (
        <CreateView opts={opts} set={set} onPickPreset={pickPreset} onCreate={startJob}
          presets={presetList} defaultId={defaultPresetId}
          onSaveCurrent={onSaveCurrentPreset} onSetDefault={onSetDefaultPreset} onDelete={onDeletePreset} />
      )}
      {tab === 'create' && (status === 'processing' || status === 'error') && (
        <ProcessingView media={processingMedia} status={status} logs={logs} step={currentStep}
          clips={clips} opts={opts} onCancel={resetToCreate} onRetry={startJob}
          paused={paused} onPause={pauseCurrent} onResume={resumeCurrent} onStop={stopCurrent} />
      )}
      {tab === 'create' && status === 'complete' && (
        <ResultsView clips={clips} jobId={jobId} preselections={preselections}
          clipStates={clipStates} onUpdateClipState={updateClipStateT} onBack={resetToCreate}
          onPublish={openPublish} onPublishAll={openPublish} onEdit={(c, i) => setEditClip({ clip: c, idx: i })}
          onApplyToAll={applyClipToAll} onEditSelected={(targets) => setBulkEdit({ targets })}
          pushToast={pushToast} />
      )}

      {tab === 'history' && !viewingHistory && (
        <HistoryView history={history} availableIds={availableJobIds}
          onOpen={openHistoryJob}
          onDelete={(id) => { deleteFromHistory(id); pushToast('info', 'Job deleted'); }}
          onClear={() => { clearHistory(); pushToast('info', 'History cleared'); }} />
      )}
      {tab === 'history' && viewingHistory && (
        <div className="fade-in">
          <div className="container" style={{ paddingTop: 24, paddingBottom: 0 }}>
            <Btn variant="secondary" size="sm" icon="arrow-left" onClick={() => setViewingHistory(false)}>Back to history</Btn>
          </div>
          <ResultsView clips={clips} jobId={jobId} preselections={preselections} embedded
            clipStates={clipStates} onUpdateClipState={updateClipStateT}
            onPublish={openPublish} onPublishAll={openPublish} onEdit={(c, i) => setEditClip({ clip: c, idx: i })}
            onApplyToAll={applyClipToAll} onEditSelected={(targets) => setBulkEdit({ targets })}
            pushToast={pushToast} />
        </div>
      )}

      {tab === 'settings' && <SettingsView apiKey={apiKey} onApiKey={setApiKey} cookiesConfigured={cookiesConfigured} onCookiesChange={setCookiesConfigured} pushToast={pushToast} />}

      {publishClips && (
        <PublishModal clips={publishClips} jobId={jobId} clipStates={clipStates} preselections={preselections}
          onClose={() => setPublishClips(null)}
          onPublished={(idx) => updateClipStateT(idx, { publishedAt: Date.now() })}
          pushToast={pushToast} />
      )}
      {editClip && (
        <EditClipModal clip={editClip.clip} idx={editClip.idx} jobId={jobId}
          initial={clipStates[editClip.idx]}
          appliedMode={clipStates[editClip.idx]?.reframeMode || editClip.clip.reframe_mode || 'auto'}
          preselections={preselections}
          onClose={() => setEditClip(null)}
          onApply={(params) => { reprocessClip(editClip.idx, editClip.clip, params); setEditClip(null); }} />
      )}
      {bulkEdit && bulkEdit.targets.length > 0 && (
        <EditClipModal clip={bulkEdit.targets[0].c} idx={bulkEdit.targets[0].i} jobId={jobId}
          bulk targetCount={bulkEdit.targets.length}
          initial={clipStates[bulkEdit.targets[0].i]}
          appliedMode={clipStates[bulkEdit.targets[0].i]?.reframeMode || bulkEdit.targets[0].c.reframe_mode || 'auto'}
          preselections={preselections}
          onClose={() => setBulkEdit(null)}
          onApply={(params) => { applyBulkEdit(params, bulkEdit.targets); setBulkEdit(null); }} />
      )}
      {showKeyModal && <ApiKeyModal onClose={() => setShowKeyModal(false)} onGoToSettings={() => { setShowKeyModal(false); setTab('settings'); }} />}

      <Toasts items={toasts} />
    </div>
  );
}
