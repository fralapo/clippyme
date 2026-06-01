// ClippyMe redesign — CaptionEditModal: live 9:16 preview that updates as you edit.
import { useState } from 'react';
import { Icon, Btn, Segmented } from './primitives';
import { CLIP_GRADS, SUBTITLE_PRESETS } from './data';

export function CaptionEditModal({ clip, idx, initial, preselections, onClose, onSave }) {
  const sp = initial?.subtitleParams || {};
  const pre = preselections?.subtitles || {};
  const [mode, setMode] = useState(sp.mode || pre.mode || 'karaoke');
  const [preset, setPreset] = useState(sp.preset || pre.preset || 'hormozi_bold');
  const [position, setPosition] = useState(sp.position || pre.position || 'center');
  const [hookText, setHookText] = useState(
    initial?.hookParams?.text || clip.viral_hook_text || clip.hook_text || '',
  );

  const save = () => onSave({
    toggles: { ...(initial?.toggles || {}), subtitles: true, hook: !!hookText.trim() },
    subtitleParams: { ...(initial?.subtitleParams || {}), mode, preset, position },
    hookParams: { ...(initial?.hookParams || {}), text: hookText },
  });
  const ps = SUBTITLE_PRESETS.find((p) => p.id === preset) || SUBTITLE_PRESETS[0];
  const posStyle = position === 'top' ? { justifyContent: 'flex-start', paddingTop: 28 }
    : position === 'bottom' ? { justifyContent: 'flex-end', paddingBottom: 28 }
      : { justifyContent: 'center' };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div><h3>Edit captions</h3><div className="mh-sub">{clip.title}</div></div>
          <button className="x" onClick={onClose}><Icon n="x" /></button>
        </div>
        <div className="modal-body" style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 20 }}>
          <div className="clip" style={{ cursor: 'default' }}>
            <div className="clip-media" style={{ background: CLIP_GRADS[idx % CLIP_GRADS.length], ...posStyle }}>
              <div className="clip-top" style={{ position: 'absolute', top: 12, left: 12, right: 12 }}>
                <span className="score" style={{ fontSize: 12 }}>{Math.round(clip.viral_score || 0)}</span>
              </div>
              <div style={{ position: 'relative', zIndex: 3, textAlign: 'center', padding: '0 8px' }}>
                <span style={{ ...ps.style, fontSize: 15, fontWeight: 800, lineHeight: 1.1 }}>
                  {hookText.split(' ').slice(0, 2).join(' ')} <span style={{ color: ps.hi }}>{hookText.split(' ').slice(2).join(' ') || 'NOW'}</span>
                </span>
              </div>
            </div>
          </div>
          <div>
            <div className="field">
              <span className="field-label">Hook text</span>
              <textarea className="ta" rows="2" value={hookText} onChange={(e) => setHookText(e.target.value)}></textarea>
            </div>
            <div className="field">
              <span className="field-label">Mode</span>
              <Segmented full value={mode} onChange={setMode}
                options={[{ id: 'karaoke', label: 'Karaoke' }, { id: 'classic', label: 'Classic' }]} />
            </div>
            {mode === 'karaoke' && (
              <div className="field">
                <span className="field-label">Style preset</span>
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
            <div className="field" style={{ marginBottom: 0 }}>
              <span className="field-label">Position</span>
              <Segmented full value={position} onChange={setPosition}
                options={[{ id: 'top', label: 'Top' }, { id: 'center', label: 'Center' }, { id: 'bottom', label: 'Bottom' }]} />
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
          <div className="mf-right"><Btn variant="primary" icon="check" onClick={save}>Save captions</Btn></div>
        </div>
      </div>
    </div>
  );
}
