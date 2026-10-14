
import { memo, useCallback, useMemo, useState } from 'react';
import { Icon, Btn, Badge } from '../../components/primitives';
import { LazyVideo } from '../../components/LazyVideo';
import { clipPreviewSrc, fmtDuration, downloadClip, exportClip } from '../../api/client';
import { REVIEW_APPROVAL_REASONS, REVIEW_FEEDBACK_REASONS } from '../../lib/taste';

const REFRAME_ICON = { auto: 'crop', subject: 'scan-face', object: 'scan-face', disabled: 'square' };
const REFRAME_LABEL = { auto: 'Auto', subject: 'Subject', object: 'Subject', disabled: 'Off' };
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function acceptedPublicationStatus(clip, state) {
  const records = Array.isArray(clip?.published)
    ? clip.published.filter((r) => r && typeof r === 'object' && (r.at || r.post_id))
    : [];
  const latest = records.at(-1);
  const providerTime = latest ? Date.parse(latest.at || '') : NaN;
  const localTime = Number(state?.publishedAt);
  if (latest && (!Number.isFinite(localTime) || !Number.isFinite(providerTime) || providerTime >= localTime)) {
    return latest.scheduled_for ? 'scheduled' : 'submitted';
  }
  if (Number.isFinite(localTime) && localTime > 0) {
    return state?.publicationStatus === 'scheduled' ? 'scheduled'
      : state?.publicationStatus === 'submitted' ? 'submitted' : 'published';
  }
  return null;
}

const REVIEW_LABELS = {
  pending: 'Pending review',
  approved: 'Approved for manual publishing',
  changes_requested: 'Changes requested',
  discarded: 'Discarded from manual publishing',
};

function ReviewControls({ clip, index, onReviewClip, disabled }) {
  const title = clip.video_title_for_youtube_short || `Clip ${index + 1}`;
  const status = clip.review_status || 'pending';
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [showRequest, setShowRequest] = useState(false);
  const [note, setNote] = useState(clip.review_note || '');
  const [reason, setReason] = useState('');
  const [approvalReason, setApprovalReason] = useState('');
  const [showDiscard, setShowDiscard] = useState(false);

  const save = async (nextStatus, noteText = '', feedbackReason = '') => {
    if (saving || disabled) return;
    setSaving(true);
    setError('');
    try {
      await onReviewClip(index, nextStatus, noteText, feedbackReason);
      setShowRequest(false);
      setShowDiscard(false);
      setReason('');
      setApprovalReason('');
      if (nextStatus !== 'changes_requested') setNote('');
    } catch (failure) {
      setError(failure?.message || 'Could not save review decision. Try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="clip-review" aria-label={`Review ${title}`}>
      <p className={`clip-review-status status-${status}`} role="status">{REVIEW_LABELS[status] || REVIEW_LABELS.pending}</p>
      {status === 'changes_requested' && clip.review_note && !showRequest && (
        <p className="clip-review-note">{clip.review_note}</p>
      )}
      {status === 'discarded' ? (
        <Btn size="sm" disabled={saving || disabled} loading={saving}
          onClick={() => save('pending')}>Restore for review</Btn>
      ) : <div className="clip-review-actions">
        {status !== 'approved' && <Btn size="sm" variant="grad" disabled={saving || disabled} loading={saving}
          onClick={() => save('approved', '', approvalReason)} aria-label={`Approve ${title}`}>Approve</Btn>}
        {status !== 'changes_requested' ? (
          <Btn size="sm" disabled={saving || disabled} onClick={() => setShowRequest((value) => !value)}>
            Request changes
          </Btn>
        ) : (
          <Btn size="sm" disabled={saving || disabled} onClick={() => setShowRequest((value) => !value)}>
            Edit request
          </Btn>
        )}
        <Btn size="sm" variant="ghost" disabled={saving || disabled} onClick={() => setShowDiscard((value) => !value)}>
          Discard
        </Btn>
      </div>}
      {status !== 'discarded' && status !== 'approved' && (
        <details className="clip-review-optional">
          <summary>Optional approval feedback</summary>
          <label htmlFor={`approval-reason-${index}`}>Why is this clip worth keeping?</label>
          <select id={`approval-reason-${index}`} value={approvalReason}
            onChange={(event) => setApprovalReason(event.target.value)}>
            <option value="">Do not save a reason</option>
            {Object.entries(REVIEW_APPROVAL_REASONS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </details>
      )}
      {showRequest && status !== 'discarded' && (
        <div className="clip-review-request">
          <label htmlFor={`review-note-${index}`}>What should change?</label>
          <textarea id={`review-note-${index}`} maxLength={500} value={note}
            onChange={(event) => setNote(event.target.value)} />
          <label htmlFor={`review-reason-${index}`}>Optional feedback reason</label>
          <select id={`review-reason-${index}`} value={reason} onChange={(event) => setReason(event.target.value)}>
            <option value="">Do not save a reason</option>
            {Object.entries(REVIEW_FEEDBACK_REASONS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <Btn size="sm" variant="secondary" disabled={saving || disabled || !note.trim()} loading={saving}
            onClick={() => save('changes_requested', note.trim(), reason)}>Save change request</Btn>
        </div>
      )}
      {showDiscard && status !== 'discarded' && (
        <div className="clip-review-request">
          <label htmlFor={`discard-reason-${index}`}>Optional feedback reason</label>
          <select id={`discard-reason-${index}`} value={reason} onChange={(event) => setReason(event.target.value)}>
            <option value="">Do not save a reason</option>
            {Object.entries(REVIEW_FEEDBACK_REASONS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <Btn size="sm" variant="secondary" disabled={saving || disabled} loading={saving}
            onClick={() => save('discarded', '', reason)}>Confirm discard</Btn>
        </div>
      )}
      {error && <p className="clip-review-error" role="alert">{error} <span>You can retry.</span></p>}
      {disabled && <p className="clip-review-hint">Review is available after reprocessing finishes.</p>}
    </section>
  );
}

const ClipCard = memo(function ClipCard({ clip, index, jobId, state, preselections, onUpdate, onEdit, onApplyToAll, selectMode, onPublish, onReviewClip, pushToast }) {
  const [downloading, setDownloading] = useState(false);
  const selected = state?.selected !== false;
  const score = Math.round(clip.viral_score || 0);
  const mode = state?.reframeMode || clip.reframe_mode || 'auto';
  const title = clip.video_title_for_youtube_short || `Clip ${index + 1}`;
  const processing = !!state?.processing;
  const publicationStatus = acceptedPublicationStatus(clip, state);
  const selectionProps = selectMode ? {
    role: 'checkbox',
    tabIndex: 0,
    'aria-checked': selected,
    onClick: () => onUpdate(index, { selected: !selected }),
    onKeyDown: (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onUpdate(index, { selected: !selected });
      }
    },
  } : {};

  const doDownload = async (event) => {
    event.stopPropagation();
    if (downloading || processing) return;
    setDownloading(true);
    try {
      const kind = await exportClip(jobId, index, clip, state, preselections);
      pushToast?.('success', kind === 'composed' ? 'Composed clip downloaded' : 'Clip downloaded');
    } catch (error) {
      // A raw fallback silently discards the user's edits. Require explicit
      // consent and keep the original compose failure visible.
      const reason = error?.message || 'Unknown error';
      const useRaw = window.confirm(
        `Edited export failed for "${title}": ${reason}. Download the unedited original instead?`
      );
      if (useRaw) {
        try {
          downloadClip(clip, index);
          pushToast?.('warn', 'Edited export failed; unedited download started');
        } catch {
          pushToast?.('warn', 'Edited export failed; unedited download also failed');
        }
      } else {
        pushToast?.('warn', `Edited export failed for "${title}": ${reason}`);
      }
    } finally {
      setDownloading(false);
    }
  };

  return (
    <article {...selectionProps} className={`clip${score >= 90 ? ' top' : ''}${selectMode && selected ? ' sel' : ''}`}>
      <div className="clip-media" style={{ padding: 0, background: '#000' }}>
        <LazyVideo src={clipPreviewSrc(clip, state)} controls={!selectMode} playsInline muted={selectMode}
          aria-label={`Preview ${title}`} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', zIndex: 0 }} />
        <div className="clip-top" style={{ padding: 10 }}>
          <span className="score"><Icon n="flame" />{score}</span>
          {selectMode ? <span className="clip-check" aria-hidden="true"><Icon n="check" /></span>
            : <span className="rf-badge" title={`Reframe: ${REFRAME_LABEL[mode] || mode}`}><Icon n={REFRAME_ICON[mode] || 'crop'} />{REFRAME_LABEL[mode] || 'Auto'}</span>}
        </div>
        <div className="clip-bottom" style={{ padding: 10 }}>
          {publicationStatus && <span className="clip-pub"><Icon n="check" />{publicationStatus}</span>}
          <span className="dur" style={{ marginLeft: publicationStatus ? 8 : 0 }}>{fmtDuration(clip.start, clip.end)}</span>
        </div>
        {processing && <div className="clip-busy" role="status"><Icon n="loader" /><span>Reprocessing…</span></div>}
      </div>
      {!selectMode && (
        <button type="button" className="clip-edit" disabled={processing} onClick={(event) => { event.stopPropagation(); onEdit(clip, index); }}
          aria-label={`Edit and reprocess ${title}`}><Icon n={processing ? 'loader' : 'sliders-horizontal'} />{processing ? 'Reprocessing…' : 'Edit & reprocess'}</button>
      )}
      <div className="clip-foot">
        <span className="ttl" title={title}>{title}</span>
        {/* In selectMode the whole card is a role="checkbox" — nested buttons
            inside a checkbox role are invalid for assistive tech, so the
            action cluster only renders in the normal (non-select) mode. */}
        {!selectMode && <>
        <button type="button" className="mini" title="Apply these settings to all clips" aria-label="Apply settings to all clips" disabled={processing}
          onClick={(event) => { event.stopPropagation(); if (!processing && window.confirm("Apply this clip's settings to every other clip? Manual trim and per-clip hook text are not copied.")) onApplyToAll(index); }}><Icon n="copy" /></button>
        <button type="button" className="mini" title="Download with edits" aria-label={`Download ${title}`} disabled={downloading || processing} onClick={doDownload}><Icon n={downloading ? 'loader' : 'download'} /></button>
        <button type="button" className="mini" title={clip.review_status === 'approved' ? 'Publish' : 'Approve this clip before publishing'} aria-label={`Publish ${title}`} disabled={processing || clip.review_status !== 'approved'} onClick={(event) => { event.stopPropagation(); onPublish({ ...clip, _idx: index, _apiIdx: clip.original_index ?? index }); }}><Icon n="send" /></button>
        <button type="button" className="mini" title="Remove from grid" aria-label={`Remove ${title}`} onClick={(event) => {
          event.stopPropagation();
          if (window.confirm('Remove this clip from the grid? The file stays on disk.')) { onUpdate(index, { deleted: true }); pushToast?.('info', 'Clip removed'); }
        }}><Icon n="trash-2" /></button>
        </>}
      </div>
      {!selectMode && <ReviewControls clip={clip} index={index} onReviewClip={onReviewClip} disabled={processing} />}
    </article>
  );
});

export function ResultsView({ clips, jobId, preselections, clipStates = {}, onUpdateClipState,
  doneIn, onBack, onPublish, onPublishAll, onEdit, onApplyToAll, onEditSelected, onReviewClip = async () => {}, embedded, pushToast }) {
  const [selectMode, setSelectMode] = useState(false);
  const [exporting, setExporting] = useState(false);
  const visible = useMemo(() => clips.map((clip, index) => ({ c: clip, i: index })).filter(({ i }) => !clipStates[i]?.deleted), [clips, clipStates]);
  const selected = useMemo(() => visible.filter(({ i }) => clipStates[i]?.selected !== false), [visible, clipStates]);
  // Manual publishing requires an explicit durable operator approval.
  const ready = useMemo(() => visible.filter(({ c, i }) =>
    !clipStates[i]?.processing && c.review_status === 'approved'), [visible, clipStates]);
  const selectedReady = useMemo(() => selected.filter(({ c, i }) =>
    !clipStates[i]?.processing && c.review_status === 'approved'), [selected, clipStates]);
  const processingCount = visible.filter(({ i }) => clipStates[i]?.processing).length;
  const awaitingReviewCount = visible.filter(({ c }) =>
    c.review_status !== 'approved' && c.review_status !== 'discarded').length;
  const topScore = useMemo(() => visible.length ? Math.max(...visible.map(({ c }) => Math.round(c.viral_score || 0))) : 0, [visible]);
  const allSelected = visible.length > 0 && selected.length === visible.length;

  const setSelectedAll = useCallback((value) => visible.forEach(({ i }) => onUpdateClipState(i, { selected: value })), [visible, onUpdateClipState]);
  const publishMany = useCallback((list) => {
    const publishable = list.filter(({ i }) => !clipStates[i]?.processing);
    if (!publishable.length) return;
    onPublishAll(publishable.map(({ c, i }) => ({ ...c, _idx: i, _apiIdx: c.original_index ?? i })));
  }, [onPublishAll, clipStates]);
  const exportMany = async (list) => {
    if (exporting || !list.length) return;
    setExporting(true);
    let edited = 0;
    let raw = 0;
    const failures = [];
    try {
      for (const { c, i } of list) {
        try {
          const kind = await exportClip(jobId, i, c, clipStates[i], preselections);
          if (kind === 'composed') edited += 1;
          else raw += 1;
        } catch (error) {
          failures.push({ clip: c, index: i, error });
        }
        await delay(150);
      }
      // One decision for the batch instead of silently replacing edited clips
      // or repeatedly opening confirmation dialogs for individual failures.
      if (failures.length && window.confirm(
        `Edited export failed for ${failures.length} clip(s). Download unedited originals for those clips instead?`
      )) {
        for (const { clip, index } of failures) {
          try { downloadClip(clip, index); raw += 1; }
          catch { /* count as failed, not downloaded */ }
        }
      }
      const started = edited + raw;
      const notDownloaded = list.length - started;
      pushToast?.(notDownloaded ? 'warn' : failures.length ? 'warn' : 'success',
        `Started ${started}/${list.length} clip downloads (${edited} edited, ${raw} unedited)${notDownloaded ? `; ${notDownloaded} failed or skipped` : ''}`);
    } finally { setExporting(false); }
  };

  return (
    <main className="container fade-in">
      <div className="results-head">
        {!embedded && <Btn variant="icon" icon="arrow-left" onClick={onBack} title="Start over" aria-label="Start over" />}
        <h2>{visible.length} clips ready</h2>
        {doneIn && <Badge tone="teal" icon="check">done in {doneIn}</Badge>}
        <div className="rh-right">
          <Btn variant="secondary" size="sm" icon={selectMode ? 'x' : 'check-square'} onClick={() => setSelectMode((current) => {
            if (!current) visible.forEach(({ i }) => onUpdateClipState(i, { selected: false }));
            return !current;
          })}>{selectMode ? 'Cancel' : 'Select'}</Btn>
          {!selectMode && <Btn variant="secondary" size="sm" icon="download" loading={exporting} disabled={!visible.length} onClick={() => exportMany(visible)}>{exporting ? 'Exporting…' : 'Export all'}</Btn>}
          {!selectMode && <Btn variant="grad" size="sm" icon="send" disabled={!ready.length} onClick={() => publishMany(ready)}>{`Publish approved ${ready.length}`}</Btn>}
        </div>
      </div>
      <div className="results-sub">Sorted by virality score · top moment {topScore}
        {awaitingReviewCount > 0 && <span role="status"> · {awaitingReviewCount} clip{awaitingReviewCount === 1 ? '' : 's'} need operator review before manual publishing</span>}
        {processingCount > 0 && <span role="status"> · {processingCount} clip{processingCount === 1 ? '' : 's'} still reprocessing — excluded from publishing until ready</span>}
      </div>

      {selectMode && <div className="actionbar" role="toolbar" aria-label="Selected clip actions">
        <span className="sel-n" aria-live="polite">{selected.length} selected</span>
        <Btn variant="ghost" size="sm" icon="check-check" onClick={() => setSelectedAll(!allSelected)}>{allSelected ? 'Deselect all' : 'Select all'}</Btn>
        <div className="ab-right">
          <Btn variant="secondary" size="sm" icon="sliders-horizontal" disabled={!selected.length} onClick={() => onEditSelected(selected)}>Edit {selected.length || ''}</Btn>
          <Btn variant="secondary" size="sm" icon="download" loading={exporting} disabled={!selected.length} onClick={() => exportMany(selected)}>{exporting ? 'Exporting…' : 'Export'}</Btn>
          <Btn variant="grad" size="sm" icon="send" disabled={!selectedReady.length} onClick={() => publishMany(selectedReady)}>{`Publish approved ${selectedReady.length}`}</Btn>
        </div>
      </div>}

      {visible.length ? <div className="results-grid" role="group" aria-label="Generated clips">
        {visible.map(({ c, i }) => <ClipCard key={c.original_index ?? i} clip={c} index={i} jobId={jobId} state={clipStates[i]}
          preselections={preselections} onUpdate={onUpdateClipState} selectMode={selectMode} onPublish={onPublish}
          onReviewClip={onReviewClip}
          onEdit={onEdit} onApplyToAll={onApplyToAll} pushToast={pushToast} />)}
      </div> : <div className="empty" role="status"><div className="ei"><Icon n="film" /></div><h3>No visible clips</h3><p>All clips were removed from this view. Start over to generate a new set.</p></div>}
    </main>
  );
}
