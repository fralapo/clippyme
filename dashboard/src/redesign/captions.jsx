// ClippyMe redesign — EditClipModal: one staged editing surface per clip.
// Reframe mode + Smart Cut + Subtitles + Hook are all edited here as *pending*
// state and only committed when the user presses "Apply & reprocess" — no more
// auto-reprocessing on every single tweak. Apply runs the real work in order:
//   1. reframe (subprocess) only if the mode actually changed, then
//   2. compose (subtitles → smart-cut → hook) if any layer toggle is on,
// then updates the clip's preview to whatever the pipeline produced.
import { useState } from 'react';
import { Icon, Btn, Segmented, Switch } from './primitives';
import { SUBTITLE_PRESETS } from './data';
import { useModalA11y } from './useModalA11y';
import { reframeClip, composeClip, clipPreviewSrc } from './realApi';
import { seedSubtitleParams, seedHookParams } from '../lib/seedClipParams';

const REFRAME_OPTS = [
  { id: 'auto', label: 'Auto' },
  { id: 'object', label: 'Object' },
  { id: 'disabled', label: 'Off' },
];

export function EditClipModal({ clip, idx, jobId, initial, appliedMode, preselections, onClose, onSave, pushToast }) {
  const t0 = initial?.toggles || {};
  const sp = initial?.subtitleParams || {};
  const pre = preselections || {};
  const preSubs = pre.subtitles || {};

  // Current on-disk reframe mode (what a fresh reframe would diff against).
  const baseMode = appliedMode || initial?.reframeMode || clip.reframe_mode || 'auto';

  const [reframeMode, setReframeMode] = useState(baseMode);
  const [smartcut, setSmartcut] = useState(t0.smartcut ?? !!pre.smartcut);
  const [subsOn, setSubsOn] = useState(t0.subtitles ?? !!pre.subtitles);
  const [hookOn, setHookOn] = useState(t0.hook ?? !!pre.hook);

  const [mode, setMode] = useState(sp.mode || preSubs.mode || 'karaoke');
  const [preset, setPreset] = useState(sp.preset || preSubs.preset || 'hormozi_bold');
  const [position, setPosition] = useState(sp.position || preSubs.position || 'center');
  const [hookText, setHookText] = useState(
    initial?.hookParams?.text || clip.viral_hook_text || clip.hook_text || '',
  );
  const [busy, setBusy] = useState(false);

  const panelRef = useModalA11y(onClose);

  const reframeChanged = reframeMode !== baseMode;
  const anyCompose = smartcut || subsOn || hookOn;
  const willReprocess = reframeChanged || anyCompose;

  const apply = async () => {
    if (busy) return;
    setBusy(true);
    // Seed the full param shape (font, size, offset_y, …) the compose backend
    // expects, then layer the user's edits on top — keeps Apply byte-compatible
    // with the download/export path (which also seeds).
    const subtitleParams = { ...seedSubtitleParams(preselections), ...sp, mode, preset, position };
    const hookParams = { ...seedHookParams(clip, preselections), ...(initial?.hookParams || {}), text: hookText };
    const toggles = { smartcut, subtitles: subsOn, hook: hookOn };
    const patch = { reframeMode, toggles, subtitleParams, hookParams };
    let reframeApplied = false; // reframe overwrites the file on disk — track it
    const commit = (p) => { try { onSave(p); } catch { /* parent state bug — don't freeze the modal */ } };
    try {
      // 1) Reframe first — it overwrites the clip file in place, so a later
      //    compose picks up the new framing automatically.
      if (reframeChanged) {
        await reframeClip(jobId, idx, reframeMode);
        reframeApplied = true;
        patch.reframeBust = Date.now();
        patch.previewUrl = undefined; // a stale composed preview no longer matches
      }
      // 2) Compose the active layers and point the preview at the result.
      if (anyCompose) {
        const { composed_url } = await composeClip(jobId, idx, {
          toggles,
          hook_params: hookOn ? hookParams : {},
          subtitle_params: subsOn ? subtitleParams : {},
        });
        patch.previewUrl = composed_url;
        patch.previewBust = Date.now();
      } else if (reframeChanged) {
        patch.previewUrl = undefined; // show the freshly reframed raw clip
      }
      commit(patch); // parent persists state, closes the modal, toasts success
    } catch (err) {
      const tooOld = err?.status === 409;
      // Partial success: the reframe already overwrote the file on disk, so we
      // MUST persist its cache-buster — otherwise the card keeps serving the
      // pre-reframe cached URL forever. Commit the reframe-only patch (which
      // also closes the modal), then surface the compose failure.
      if (reframeApplied) {
        commit({ reframeMode, reframeBust: Date.now(), previewUrl: undefined });
        pushToast?.('error', 'Reframed, but composing the layers failed: ' + String(err?.message || err).slice(0, 50));
        return;
      }
      pushToast?.('error', tooOld
        ? 'This clip is too old to reframe — reprocess the video first.'
        : 'Reprocess failed: ' + String(err?.message || err).slice(0, 60));
      setBusy(false); // nothing applied — keep the modal open so edits aren't lost
    }
  };

  const ps = SUBTITLE_PRESETS.find((p) => p.id === preset) || SUBTITLE_PRESETS[0];

  return (
    <div className="overlay" onClick={busy ? undefined : onClose}>
      <div className="modal wide" ref={panelRef} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="edit-modal-title">
        <div className="modal-head">
          <div><h3 id="edit-modal-title">Edit clip</h3>
            <div className="mh-sub">{clip.video_title_for_youtube_short || clip.title || `Clip ${idx + 1}`}</div></div>
          <button className="x" onClick={onClose} aria-label="Close" disabled={busy}><Icon n="x" /></button>
        </div>

        <div className="modal-body" style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 20 }}>
          {/* Live preview of the clip as it currently stands on disk. */}
          <div className="clip" style={{ cursor: 'default' }}>
            <div className="clip-media" style={{ padding: 0, background: '#000' }}>
              <video src={clipPreviewSrc(clip, initial)} controls playsInline preload="metadata"
                style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', zIndex: 0 }} />
              <div className="clip-top" style={{ padding: 10 }}>
                <span className="score"><Icon n="flame" style={{ width: 12, height: 12 }} />{Math.round(clip.viral_score || 0)}</span>
              </div>
            </div>
          </div>

          <div>
            <div className="field">
              <span className="field-label">Reframe</span>
              <Segmented full value={reframeMode} onChange={setReframeMode} options={REFRAME_OPTS} />
              <div className="eo-d" style={{ marginTop: 6 }}>Auto face-track · Object element-crop · Off letterbox bands</div>
            </div>

            <div className="edit-opt">
              <div className="eo-ico"><Icon n="scissors" /></div>
              <div className="eo-txt"><div className="eo-t">Smart Cut</div><div className="eo-d">Remove silence &amp; filler words</div></div>
              <Switch on={smartcut} onChange={setSmartcut} />
            </div>

            <div className="edit-opt">
              <div className="eo-ico"><Icon n="captions" /></div>
              <div className="eo-txt"><div className="eo-t">Subtitles</div><div className="eo-d">Burn karaoke or classic captions</div></div>
              <Switch on={subsOn} onChange={setSubsOn} />
            </div>
            {subsOn && (
              <div className="cfg-drawer fade-in">
                <div className="cf-row">
                  <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Mode</span>
                  <Segmented full value={mode} onChange={setMode}
                    options={[{ id: 'karaoke', label: 'Karaoke' }, { id: 'classic', label: 'Classic' }]} />
                </div>
                {mode === 'karaoke' && (
                  <div className="cf-row">
                    <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Style preset</span>
                    <div className="subgrid">
                      {SUBTITLE_PRESETS.map((p) => (
                        <button key={p.id} type="button" className={'subpre' + (preset === p.id ? ' on' : '')} onClick={() => setPreset(p.id)}>
                          <div className="prev"><span style={p.style}>WORD <span style={{ color: p.hi }}>UP</span></span></div>
                          <div className="nm">{p.label}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className="cf-row">
                  <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Position</span>
                  <Segmented full value={position} onChange={setPosition}
                    options={[{ id: 'top', label: 'Top' }, { id: 'center', label: 'Center' }, { id: 'bottom', label: 'Bottom' }]} />
                </div>
              </div>
            )}

            <div className="edit-opt">
              <div className="eo-ico"><Icon n="type" /></div>
              <div className="eo-txt"><div className="eo-t">Text hook</div><div className="eo-d">A scroll-stopping opener overlaid on the clip</div></div>
              <Switch on={hookOn} onChange={setHookOn} />
            </div>
            {hookOn && (
              <div className="cfg-drawer fade-in">
                <div className="cf-row" style={{ marginBottom: 0 }}>
                  <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Hook text</span>
                  <textarea className="ta" rows="2" value={hookText} placeholder="e.g. THIS changed everything"
                    onChange={(e) => setHookText(e.target.value)}></textarea>
                  <div className="prev" style={{ marginTop: 10, padding: '14px 10px', background: '#0c0c11', borderRadius: 'var(--r-sm)', textAlign: 'center' }}>
                    <span style={{ ...ps.style, fontSize: 15, fontWeight: 800, lineHeight: 1.1 }}>
                      {hookText.split(' ').slice(0, 2).join(' ')} <span style={{ color: ps.hi }}>{hookText.split(' ').slice(2).join(' ') || 'NOW'}</span>
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="modal-foot">
          {willReprocess && !busy && (
            <span className="edit-dirty">
              {reframeChanged ? 'Will re-render framing' : 'Will re-compose layers'} on apply
            </span>
          )}
          <Btn variant="ghost" onClick={onClose} disabled={busy}>Cancel</Btn>
          <div className="mf-right">
            <Btn variant="primary" icon={busy ? 'loader' : (willReprocess ? 'wand-sparkles' : 'check')} onClick={apply} disabled={busy}>
              {busy ? 'Reprocessing…' : (willReprocess ? 'Apply & reprocess' : 'Save changes')}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}
