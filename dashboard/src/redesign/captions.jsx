// ClippyMe redesign — EditClipModal: one staged editing surface per clip.
// Reframe mode + Smart Cut + Subtitles + Hook are all edited here as *pending*
// state and only committed when the user presses "Apply & reprocess" — no more
// auto-reprocessing on every single tweak. Apply doesn't block: it hands the
// staged params to the parent (`onApply`) and closes immediately. The actual
// reframe (subprocess) + compose (subtitles → smart-cut → hook) run in the
// BACKGROUND in RedesignApp, so the user can keep editing other clips while
// this one renders. The clip card shows a per-clip "processing" spinner.
import { useState, useEffect } from 'react';
import { Icon, Btn, Segmented, Switch } from './primitives';
import { SUBTITLE_PRESETS, SUB_COLORS, LOGO_POSITIONS, LOGO_SIZES, HOOK_STYLE_DEFAULT } from './data';
import { useModalA11y } from './useModalA11y';
import { clipPreviewSrc, getClipTranscript } from './realApi';
import { useFontList } from '../hooks/useFontList';
import { HookStyleControls, HookPreview } from './hookStyle';
import { seedSubtitleParams, seedHookParams, seedLogoParams } from '../lib/seedClipParams';

// Pull the IG-style hook style keys out of a flat hookParams object.
const HOOK_STYLE_KEYS = ['bg_enabled', 'bg_color', 'bg_opacity', 'text_color', 'outline_width', 'outline_color', 'font'];
function pickHookStyle(src) {
  const out = { ...HOOK_STYLE_DEFAULT };
  for (const k of HOOK_STYLE_KEYS) if (src && src[k] !== undefined) out[k] = src[k];
  return out;
}

const REFRAME_OPTS = [
  { id: 'auto', label: 'Auto' },
  { id: 'object', label: 'Object' },
  { id: 'disabled', label: 'Off' },
];

// Reconstruct which transcript segments were marked dropped from previously
// saved drop_ranges: a segment is "dropped" if a saved span covers its
// midpoint. Lets the manual-trim checklist restore state on modal reopen.
function dropSetFromRanges(segments, ranges) {
  const set = new Set();
  if (!ranges?.length) return set;
  segments.forEach((s) => {
    const mid = (s.start + s.end) / 2;
    if (ranges.some(([a, b]) => mid >= a && mid <= b)) set.add(s.index);
  });
  return set;
}

export function EditClipModal({ clip, idx, jobId, initial, appliedMode, preselections, onClose, onApply }) {
  const t0 = initial?.toggles || {};
  const sp = initial?.subtitleParams || {};
  const pre = preselections || {};
  const preSubs = pre.subtitles || {};

  // Current on-disk reframe mode (what a fresh reframe would diff against).
  const baseMode = appliedMode || initial?.reframeMode || clip.reframe_mode || 'auto';

  const [reframeMode, setReframeMode] = useState(baseMode);
  const [smartcut, setSmartcut] = useState(t0.smartcut ?? !!pre.smartcut);
  // Manual trim (flycut-style): transcript segments + the set the user dropped.
  const [segments, setSegments] = useState(null); // null = not loaded
  const [segErr, setSegErr] = useState(false);
  const [dropped, setDropped] = useState(() => new Set());
  const [subsOn, setSubsOn] = useState(t0.subtitles ?? !!pre.subtitles);
  const [hookOn, setHookOn] = useState(t0.hook ?? !!pre.hook);
  const [logoOn, setLogoOn] = useState(t0.logo ?? !!pre.logo);

  const lp0 = initial?.logoParams || seedLogoParams(preselections);
  const [logoPos, setLogoPos] = useState(lp0.position || 'top-right');
  const [logoSize, setLogoSize] = useState(lp0.size || 'M');
  const fonts = useFontList();

  const [mode, setMode] = useState(sp.mode || preSubs.mode || 'karaoke');
  const [preset, setPreset] = useState(sp.preset || preSubs.preset || 'hormozi_bold');
  const [position, setPosition] = useState(sp.position || preSubs.position || 'center');
  const [subFont, setSubFont] = useState(sp.font || preSubs.font || 'Montserrat-Black');
  const [subColor, setSubColor] = useState(sp.font_color || preSubs.font_color || '#FFFFFF');
  const [hookText, setHookText] = useState(
    initial?.hookParams?.text || clip.viral_hook_text || clip.hook_text || '',
  );
  // IG-Stories hook style: seed from a prior edit, else the pre-selection.
  const [hookStyle, setHookStyle] = useState(
    () => pickHookStyle(initial?.hookParams || (preselections || {}).hook),
  );

  // Lazy-load transcript segments the first time Smart Cut is enabled. Cheap
  // GET; backend reads metadata.json. Failure → hide the trim list silently
  // (auto Smart Cut still works).
  useEffect(() => {
    if (!smartcut || segments !== null || !jobId) return;
    let alive = true;
    getClipTranscript(jobId, idx)
      .then((d) => { if (!alive) return;
        const segs = d.segments || [];
        setSegments(segs);
        setDropped(dropSetFromRanges(segs, initial?.dropRanges));
      })
      .catch(() => { if (alive) setSegErr(true); });
    return () => { alive = false; };
  }, [smartcut, segments, jobId, idx, initial]);

  const toggleDrop = (i) => setDropped((prev) => {
    const next = new Set(prev);
    next.has(i) ? next.delete(i) : next.add(i);
    return next;
  });

  // Dropped segment indices → merged [start, end] spans for the backend.
  const dropRanges = (segments || [])
    .filter((s) => dropped.has(s.index))
    .map((s) => [s.start, s.end]);

  const panelRef = useModalA11y(onClose);

  const reframeChanged = reframeMode !== baseMode;
  const anyCompose = smartcut || subsOn || hookOn || logoOn;
  const willReprocess = reframeChanged || anyCompose;

  // Non-blocking apply: seed the full param shape (font, size, offset_y, …) the
  // compose backend expects, layer the user's edits on top, hand it to the
  // parent for BACKGROUND processing, and close immediately. No await here →
  // the modal never traps the user while a clip renders.
  const apply = () => {
    const subtitleParams = { ...seedSubtitleParams(preselections), ...sp, mode, preset, position,
      ...(mode === 'classic' ? { font: subFont, font_color: subColor } : {}) };
    const hookParams = { ...seedHookParams(clip, preselections), ...(initial?.hookParams || {}), ...hookStyle, text: hookText };
    const logoParams = { position: logoPos, size: logoSize };
    const toggles = { smartcut, subtitles: subsOn, hook: hookOn, logo: logoOn };
    onApply({ reframeMode, baseMode, toggles, subtitleParams, hookParams, logoParams,
      dropRanges: smartcut ? dropRanges : [] });
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal wide" ref={panelRef} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="edit-modal-title">
        <div className="modal-head">
          <div><h3 id="edit-modal-title">Edit clip</h3>
            <div className="mh-sub">{clip.video_title_for_youtube_short || clip.title || `Clip ${idx + 1}`}</div></div>
          <button className="x" onClick={onClose} aria-label="Close"><Icon n="x" /></button>
        </div>

        <div className="modal-body edit-grid">
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
            {smartcut && (
              <div className="cfg-drawer fade-in">
                <div className="cf-row" style={{ marginBottom: 0 }}>
                  <span className="field-label" style={{ marginBottom: 9, display: 'flex', justifyContent: 'space-between' }}>
                    <span>Manual trim</span>
                    {dropRanges.length > 0 && <span className="eo-d">{dropRanges.length} dropped</span>}
                  </span>
                  <div className="eo-d" style={{ marginBottom: 8 }}>
                    Auto removes silence &amp; fillers. Tap any line below to also cut it.
                  </div>
                  {segments === null && !segErr && <div className="eo-d">Loading transcript…</div>}
                  {segErr && <div className="eo-d">Transcript unavailable — auto Smart Cut still applies.</div>}
                  {segments && segments.length === 0 && <div className="eo-d">No transcript segments for this clip.</div>}
                  {segments && segments.length > 0 && (
                    <div className="trim-list">
                      {segments.map((s) => {
                        const off = dropped.has(s.index);
                        return (
                          <button key={s.index} type="button"
                            className={'trim-seg' + (off ? ' cut' : '')}
                            onClick={() => toggleDrop(s.index)}
                            title={off ? 'Will be cut — tap to keep' : 'Kept — tap to cut'}>
                            <Icon n={off ? 'scissors' : 'check'} style={{ width: 13, height: 13, flexShrink: 0 }} />
                            <span className="trim-txt">{s.text}</span>
                            <span className="trim-time">{s.start.toFixed(1)}s</span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}

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
                {mode === 'classic' && (
                  <>
                    <div className="cf-row">
                      <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Font</span>
                      <select className="sel" style={{ width: '100%' }} value={subFont} onChange={(e) => setSubFont(e.target.value)}>
                        {fonts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                    </div>
                    <div className="cf-row">
                      <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Color</span>
                      <div className="swatches">
                        {SUB_COLORS.map((c) => (
                          <button key={c} type="button" aria-label={`Font color ${c}`}
                            className={'swatch' + (subColor.toUpperCase() === c.toUpperCase() ? ' on' : '')}
                            style={{ background: c }} onClick={() => setSubColor(c)} />
                        ))}
                      </div>
                    </div>
                  </>
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
                <div className="cf-row">
                  <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Hook text</span>
                  <textarea className="ta" rows="2" value={hookText} placeholder="e.g. THIS changed everything"
                    onChange={(e) => setHookText(e.target.value)}></textarea>
                  <div style={{ marginTop: 10 }}><HookPreview text={hookText} style={hookStyle} /></div>
                </div>
                <HookStyleControls style={hookStyle}
                  set={(partial) => setHookStyle((s) => ({ ...s, ...partial }))} />
              </div>
            )}

            <div className="edit-opt">
              <div className="eo-ico"><Icon n="stamp" /></div>
              <div className="eo-txt"><div className="eo-t">Brand logo</div><div className="eo-d">Burn your uploaded logo onto the clip</div></div>
              <Switch on={logoOn} onChange={setLogoOn} />
            </div>
            {logoOn && (
              <div className="cfg-drawer fade-in">
                <div className="cf-row">
                  <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Position</span>
                  <div className="seg-grid">
                    {LOGO_POSITIONS.map(([v, l]) => (
                      <button key={v} type="button" className={'seg-cell' + (logoPos === v ? ' on' : '')}
                        onClick={() => setLogoPos(v)}>{l}</button>
                    ))}
                  </div>
                </div>
                <div className="cf-row" style={{ marginBottom: 0 }}>
                  <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Size</span>
                  <Segmented full value={logoSize} onChange={setLogoSize}
                    options={LOGO_SIZES.map(([v, l]) => ({ id: v, label: l }))} />
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="modal-foot">
          {willReprocess && (
            <span className="edit-dirty">
              {reframeChanged ? 'Will re-render framing' : 'Will re-compose layers'} in the background
            </span>
          )}
          <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
          <div className="mf-right">
            <Btn variant="primary" icon={willReprocess ? 'wand-sparkles' : 'check'} onClick={apply}>
              {willReprocess ? 'Apply & reprocess' : 'Save changes'}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}
