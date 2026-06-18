// ClippyMe redesign — Results: real clip cards (video + score + reframe +
// download + publish + captions) and multi-select for batch actions.
import { useState } from 'react';
import { Icon, Btn, Badge } from './primitives';
import { clipPreviewSrc, fmtDuration, downloadClip, exportClip } from './realApi';

const REFRAME_ICON = { auto: 'crop', object: 'layers', disabled: 'square' };
const REFRAME_LABEL = { auto: 'Auto', object: 'Object', disabled: 'Off' };

function ClipCard({ clip, index, jobId, state, preselections, onUpdate, onEdit, selectMode, onPublish, pushToast }) {
  const [downloading, setDownloading] = useState(false);
  const selected = state?.selected !== false;
  const score = Math.round(clip.viral_score || 0);
  // Read-only here — reframe mode is changed (and applied) inside the Edit
  // modal, not by an instant click on the card.
  const mode = state?.reframeMode || clip.reframe_mode || 'auto';
  const title = clip.video_title_for_youtube_short || `Clip ${index + 1}`;

  const doDownload = async (e) => {
    e.stopPropagation();
    if (downloading) return;
    setDownloading(true);
    try {
      const kind = await exportClip(jobId, index, clip, state, preselections);
      pushToast?.('success', kind === 'composed' ? 'Composed clip downloaded' : 'Clip downloaded');
    } catch {
      pushToast?.('warn', 'Compose failed, downloaded the raw clip instead');
      downloadClip(clip, index);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className={'clip' + (score >= 90 ? ' top' : '') + (selectMode && selected ? ' sel' : '')}
      onClick={() => selectMode && onUpdate(index, { selected: !selected })}>
      <div className="clip-media" style={{ padding: 0, background: '#000' }}>
        <video src={clipPreviewSrc(clip, state)} controls={!selectMode} playsInline preload="metadata"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', zIndex: 0 }} />
        <div className="clip-top" style={{ padding: 10 }}>
          <span className="score"><Icon n="flame" style={{ width: 12, height: 12 }} />{score}</span>
          {selectMode
            ? <span className="clip-check"><Icon n="check" /></span>
            : <span className="rf-badge" title={`Reframe: ${REFRAME_LABEL[mode] || mode}`}>
                <Icon n={REFRAME_ICON[mode] || 'crop'} />{REFRAME_LABEL[mode] || 'Auto'}
              </span>}
        </div>
        <div className="clip-bottom" style={{ padding: 10 }}>
          {state?.publishedAt && <span className="clip-pub"><Icon n="check" />published</span>}
          <span className="dur" style={{ marginLeft: state?.publishedAt ? 8 : 0 }}>{fmtDuration(clip.start, clip.end)}</span>
        </div>
      </div>
      {!selectMode && (
        <button className="clip-edit" onClick={(e) => { e.stopPropagation(); onEdit(clip, index); }}
          title="Set reframe, captions, smart cut & hook — then apply">
          <Icon n="sliders-horizontal" />Edit &amp; reprocess
        </button>
      )}
      <div className="clip-foot">
        <span className="ttl" title={title}>{title}</span>
        <button type="button" className="mini" title="Download (applies your edits)" aria-label="Download clip" onClick={doDownload}><Icon n={downloading ? 'loader' : 'download'} /></button>
        <button type="button" className="mini" title="Publish" aria-label="Publish clip" onClick={(e) => { e.stopPropagation(); onPublish({ ...clip, _idx: index }); }}><Icon n="send" /></button>
        <button type="button" className="mini" title="Remove clip from the grid (file stays on disk)" aria-label="Remove clip" onClick={(e) => {
          e.stopPropagation();
          if (window.confirm('Remove this clip from the grid? The file stays on disk.')) {
            onUpdate(index, { deleted: true });
            pushToast?.('info', 'Clip removed');
          }
        }}><Icon n="trash-2" /></button>
      </div>
    </div>
  );
}

export function ResultsView({ clips, jobId, preselections, clipStates = {}, onUpdateClipState,
  doneIn, onBack, onPublish, onPublishAll, onEdit, embedded, pushToast }) {
  const [selectMode, setSelectMode] = useState(false);
  const [exporting, setExporting] = useState(false);

  const visible = clips.map((c, i) => ({ c, i })).filter(({ i }) => !clipStates[i]?.deleted);
  const selectedIdx = visible.filter(({ i }) => clipStates[i]?.selected !== false).map(({ i }) => i);
  const topScore = clips.length ? Math.max(...clips.map((c) => Math.round(c.viral_score || 0))) : 0;

  const publishMany = (list) => onPublishAll(list.map(({ c, i }) => ({ ...c, _idx: i })));
  // Bulk export composes each clip (applying its toggles) just like the single
  // download, sequentially so we don't spawn N ffmpeg jobs at once.
  const exportMany = async (list) => {
    if (exporting || !list.length) return;
    setExporting(true);
    let ok = 0;
    for (const { c, i } of list) {
      try { await exportClip(jobId, i, c, clipStates[i], preselections); ok += 1; }
      catch { downloadClip(c, i); }
      await new Promise((r) => setTimeout(r, 250));
    }
    setExporting(false);
    pushToast?.('success', `Exported ${ok}/${list.length} clips`);
  };

  return (
    <div className="container fade-in">
      <div className="results-head">
        {!embedded && <Btn variant="icon" icon="arrow-left" onClick={onBack} title="Start over" />}
        <h2>{visible.length} clips ready</h2>
        {doneIn && <Badge tone="teal" icon="check">done in {doneIn}</Badge>}
        <div className="rh-right">
          <Btn variant="secondary" size="sm" icon={selectMode ? 'x' : 'check-square'} onClick={() => setSelectMode((v) => !v)}>
            {selectMode ? 'Cancel' : 'Select'}
          </Btn>
          {!selectMode && <Btn variant="secondary" size="sm" icon={exporting ? 'loader' : 'download'} disabled={exporting} onClick={() => exportMany(visible)}>{exporting ? 'Exporting…' : 'Export all'}</Btn>}
          {!selectMode && <Btn variant="grad" size="sm" icon="send" onClick={() => publishMany(visible)}>Publish all</Btn>}
        </div>
      </div>
      <div className="results-sub">Sorted by virality score · top moment {topScore}</div>

      {selectMode && (
        <div className="actionbar">
          <span className="sel-n">{selectedIdx.length} selected</span>
          <div className="ab-right">
            <Btn variant="secondary" size="sm" icon={exporting ? 'loader' : 'download'} disabled={!selectedIdx.length || exporting}
              onClick={() => exportMany(visible.filter(({ i }) => clipStates[i]?.selected !== false))}>{exporting ? 'Exporting…' : 'Export'}</Btn>
            <Btn variant="grad" size="sm" icon="send" disabled={!selectedIdx.length}
              onClick={() => publishMany(visible.filter(({ i }) => clipStates[i]?.selected !== false))}>Publish {selectedIdx.length || ''}</Btn>
          </div>
        </div>
      )}

      <div className="results-grid">
        {visible.map(({ c, i }) => (
          <ClipCard key={c.original_index ?? i} clip={c} index={i} jobId={jobId}
            state={clipStates[i]} preselections={preselections} onUpdate={onUpdateClipState} selectMode={selectMode}
            onPublish={onPublish} onEdit={onEdit} pushToast={pushToast} />
        ))}
      </div>
    </div>
  );
}
