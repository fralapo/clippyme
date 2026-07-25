
import { memo, useCallback, useMemo, useState } from 'react';
import { Icon, Btn, Badge } from './primitives';
import { LazyVideo } from './LazyVideo';
import { clipPreviewSrc, fmtDuration, downloadClip, exportClip } from './realApi';

const REFRAME_ICON = { auto: 'crop', subject: 'scan-face', object: 'scan-face', disabled: 'square' };
const REFRAME_LABEL = { auto: 'Auto', subject: 'Subject', object: 'Subject', disabled: 'Off' };
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const ClipCard = memo(function ClipCard({ clip, index, jobId, state, preselections, onUpdate, onEdit, onApplyToAll, selectMode, onPublish, pushToast }) {
  const [downloading, setDownloading] = useState(false);
  const selected = state?.selected !== false;
  const score = Math.round(clip.viral_score || 0);
  const mode = state?.reframeMode || clip.reframe_mode || 'auto';
  const title = clip.video_title_for_youtube_short || `Clip ${index + 1}`;
  const processing = !!state?.processing;
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
    } catch {
      pushToast?.('warn', 'Compose failed; downloading the raw clip instead');
      downloadClip(clip, index);
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
          {state?.publishedAt && <span className="clip-pub"><Icon n="check" />published</span>}
          <span className="dur" style={{ marginLeft: state?.publishedAt ? 8 : 0 }}>{fmtDuration(clip.start, clip.end)}</span>
        </div>
        {processing && <div className="clip-busy" role="status"><Icon n="loader" /><span>Reprocessing…</span></div>}
      </div>
      {!selectMode && (
        <button type="button" className="clip-edit" disabled={processing} onClick={(event) => { event.stopPropagation(); onEdit(clip, index); }}
          aria-label={`Edit and reprocess ${title}`}><Icon n={processing ? 'loader' : 'sliders-horizontal'} />{processing ? 'Reprocessing…' : 'Edit & reprocess'}</button>
      )}
      <div className="clip-foot">
        <span className="ttl" title={title}>{title}</span>
        {!selectMode && <button type="button" className="mini" title="Apply these settings to all clips" aria-label="Apply settings to all clips" disabled={processing}
          onClick={(event) => { event.stopPropagation(); if (!processing && window.confirm("Apply this clip's settings to every other clip? Manual trim and per-clip hook text are not copied.")) onApplyToAll(index); }}><Icon n="copy" /></button>}
        <button type="button" className="mini" title="Download with edits" aria-label={`Download ${title}`} disabled={downloading || processing} onClick={doDownload}><Icon n={downloading ? 'loader' : 'download'} /></button>
        <button type="button" className="mini" title="Publish" aria-label={`Publish ${title}`} disabled={processing} onClick={(event) => { event.stopPropagation(); onPublish({ ...clip, _idx: index, _apiIdx: clip.original_index ?? index }); }}><Icon n="send" /></button>
        <button type="button" className="mini" title="Remove from grid" aria-label={`Remove ${title}`} onClick={(event) => {
          event.stopPropagation();
          if (window.confirm('Remove this clip from the grid? The file stays on disk.')) { onUpdate(index, { deleted: true }); pushToast?.('info', 'Clip removed'); }
        }}><Icon n="trash-2" /></button>
      </div>
    </article>
  );
});

export function ResultsView({ clips, jobId, preselections, clipStates = {}, onUpdateClipState,
  doneIn, onBack, onPublish, onPublishAll, onEdit, onApplyToAll, onEditSelected, embedded, pushToast }) {
  const [selectMode, setSelectMode] = useState(false);
  const [exporting, setExporting] = useState(false);
  const visible = useMemo(() => clips.map((clip, index) => ({ c: clip, i: index })).filter(({ i }) => !clipStates[i]?.deleted), [clips, clipStates]);
  const selected = useMemo(() => visible.filter(({ i }) => clipStates[i]?.selected !== false), [visible, clipStates]);
  const topScore = useMemo(() => visible.length ? Math.max(...visible.map(({ c }) => Math.round(c.viral_score || 0))) : 0, [visible]);
  const allSelected = visible.length > 0 && selected.length === visible.length;

  const setSelectedAll = useCallback((value) => visible.forEach(({ i }) => onUpdateClipState(i, { selected: value })), [visible, onUpdateClipState]);
  const publishMany = useCallback((list) => onPublishAll(list.map(({ c, i }) => ({ ...c, _idx: i, _apiIdx: c.original_index ?? i }))), [onPublishAll]);
  const exportMany = async (list) => {
    if (exporting || !list.length) return;
    setExporting(true);
    let composed = 0;
    let rawFallback = 0;
    try {
      for (const { c, i } of list) {
        try { await exportClip(jobId, i, c, clipStates[i], preselections); composed += 1; }
        catch { downloadClip(c, i); rawFallback += 1; }
        await delay(150);
      }
      pushToast?.(rawFallback ? 'warn' : 'success', rawFallback
        ? `Exported ${list.length} clips; ${rawFallback} used the raw fallback`
        : `Exported ${composed}/${list.length} clips`);
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
          {!selectMode && <Btn variant="grad" size="sm" icon="send" disabled={!visible.length} onClick={() => publishMany(visible)}>Publish all</Btn>}
        </div>
      </div>
      <div className="results-sub">Sorted by virality score · top moment {topScore}</div>

      {selectMode && <div className="actionbar" role="toolbar" aria-label="Selected clip actions">
        <span className="sel-n" aria-live="polite">{selected.length} selected</span>
        <Btn variant="ghost" size="sm" icon="check-check" onClick={() => setSelectedAll(!allSelected)}>{allSelected ? 'Deselect all' : 'Select all'}</Btn>
        <div className="ab-right">
          <Btn variant="secondary" size="sm" icon="sliders-horizontal" disabled={!selected.length} onClick={() => onEditSelected(selected)}>Edit {selected.length || ''}</Btn>
          <Btn variant="secondary" size="sm" icon="download" loading={exporting} disabled={!selected.length} onClick={() => exportMany(selected)}>{exporting ? 'Exporting…' : 'Export'}</Btn>
          <Btn variant="grad" size="sm" icon="send" disabled={!selected.length} onClick={() => publishMany(selected)}>Publish {selected.length || ''}</Btn>
        </div>
      </div>}

      {visible.length ? <div className="results-grid" role="list" aria-label="Generated clips">
        {visible.map(({ c, i }) => <ClipCard key={c.original_index ?? i} clip={c} index={i} jobId={jobId} state={clipStates[i]}
          preselections={preselections} onUpdate={onUpdateClipState} selectMode={selectMode} onPublish={onPublish}
          onEdit={onEdit} onApplyToAll={onApplyToAll} pushToast={pushToast} />)}
      </div> : <div className="empty" role="status"><div className="ei"><Icon n="film" /></div><h3>No visible clips</h3><p>All clips were removed from this view. Start over to generate a new set.</p></div>}
    </main>
  );
}
