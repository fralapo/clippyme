// ClippyMe redesign — Results: real clip cards (video + score + reframe +
// download + publish + captions) and multi-select for batch actions.
import { useState } from 'react';
import { Icon, Btn, Badge } from './primitives';
import { clipVideoSrc, fmtDuration, downloadClip, reframeClip } from './realApi';

function scoreTone(s) {
  if (s >= 80) return 'teal';
  if (s >= 50) return 'amber';
  return 'danger';
}

function ClipCard({ clip, index, jobId, state, onUpdate, selectMode, onPublish, onCaptions, pushToast }) {
  const [reframing, setReframing] = useState(false);
  const selected = state?.selected !== false;
  const score = Math.round(clip.viral_score || 0);
  const mode = state?.reframeMode || clip.reframe_mode || 'auto';
  const title = clip.video_title_for_youtube_short || `Clip ${index + 1}`;

  const cycleReframe = async (e) => {
    e.stopPropagation();
    if (reframing) return;
    const next = mode === 'auto' ? 'disabled' : 'auto';
    setReframing(true);
    try {
      await reframeClip(jobId, index, next);
      onUpdate(index, { reframeMode: next, reframeBust: Date.now() });
      pushToast?.('success', `Reframe → ${next}`);
    } catch (err) {
      pushToast?.('error', err.status === 409 ? 'Clip too old to reframe — reprocess it' : 'Reframe failed');
    } finally {
      setReframing(false);
    }
  };

  return (
    <div className={'clip' + (score >= 90 ? ' top' : '') + (selectMode && selected ? ' sel' : '')}
      onClick={() => selectMode && onUpdate(index, { selected: !selected })}>
      <div className="clip-media" style={{ padding: 0, background: '#000' }}>
        <video src={clipVideoSrc(clip, state?.reframeBust)} controls={!selectMode} playsInline preload="metadata"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', zIndex: 0 }} />
        <div className="clip-top" style={{ padding: 10 }}>
          <span className="score"><Icon n="flame" style={{ width: 12, height: 12 }} />{score}</span>
          {selectMode
            ? <span className="clip-check"><Icon n="check" /></span>
            : <button className={'cfg' + (mode === 'auto' ? ' active' : '')} title={`Reframe: ${mode}`} onClick={cycleReframe}
                style={{ position: 'relative', zIndex: 4, width: 30, height: 30, borderRadius: 'var(--r-sm)' }}>
                <Icon n={reframing ? 'loader' : (mode === 'auto' ? 'crop' : 'square')} />
              </button>}
        </div>
        <div className="clip-bottom" style={{ padding: 10 }}>
          {state?.publishedAt && <span className="clip-pub"><Icon n="check" />published</span>}
          <span className="dur" style={{ marginLeft: state?.publishedAt ? 8 : 0 }}>{fmtDuration(clip.start, clip.end)}</span>
        </div>
      </div>
      <div className="clip-foot">
        <span className="ttl" title={title}>{title}</span>
        <span className="mini" title="Edit captions" onClick={(e) => { e.stopPropagation(); onCaptions(clip, index); }}><Icon n="captions" /></span>
        <span className="mini" title="Download" onClick={(e) => { e.stopPropagation(); downloadClip(clip, index); }}><Icon n="download" /></span>
        <span className="mini" title="Publish" onClick={(e) => { e.stopPropagation(); onPublish({ ...clip, _idx: index }); }}><Icon n="send" /></span>
      </div>
    </div>
  );
}

export function ResultsView({ clips, jobId, preselections, clipStates = {}, onUpdateClipState,
  doneIn, onBack, onPublish, onPublishAll, onCaptions, embedded, pushToast }) {
  const [selectMode, setSelectMode] = useState(false);

  const visible = clips.map((c, i) => ({ c, i })).filter(({ i }) => !clipStates[i]?.deleted);
  const selectedIdx = visible.filter(({ i }) => clipStates[i]?.selected !== false).map(({ i }) => i);
  const topScore = clips.length ? Math.max(...clips.map((c) => Math.round(c.viral_score || 0))) : 0;

  const publishMany = (list) => onPublishAll(list.map(({ c, i }) => ({ ...c, _idx: i })));
  const exportMany = (list) => list.forEach(({ c, i }) => downloadClip(c, i));

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
          {!selectMode && <Btn variant="secondary" size="sm" icon="download" onClick={() => exportMany(visible)}>Export all</Btn>}
          {!selectMode && <Btn variant="grad" size="sm" icon="send" onClick={() => publishMany(visible)}>Publish all</Btn>}
        </div>
      </div>
      <div className="results-sub">Sorted by virality score · top moment {topScore}</div>

      {selectMode && (
        <div className="actionbar">
          <span className="sel-n">{selectedIdx.length} selected</span>
          <div className="ab-right">
            <Btn variant="secondary" size="sm" icon="download" disabled={!selectedIdx.length}
              onClick={() => exportMany(visible.filter(({ i }) => clipStates[i]?.selected !== false))}>Export</Btn>
            <Btn variant="grad" size="sm" icon="send" disabled={!selectedIdx.length}
              onClick={() => publishMany(visible.filter(({ i }) => clipStates[i]?.selected !== false))}>Publish {selectedIdx.length || ''}</Btn>
          </div>
        </div>
      )}

      <div className="results-grid">
        {visible.map(({ c, i }) => (
          <ClipCard key={c.original_index ?? i} clip={c} index={i} jobId={jobId}
            state={clipStates[i]} onUpdate={onUpdateClipState} selectMode={selectMode}
            onPublish={onPublish} onCaptions={onCaptions} pushToast={pushToast} />
        ))}
      </div>
    </div>
  );
}
