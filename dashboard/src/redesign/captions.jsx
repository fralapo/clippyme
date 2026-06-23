// ClippyMe redesign — EditClipModal: one staged editing surface per clip,
// organised into TABS (Reframe · Captions · Hook · Smart Cut · Trim · Logo) so
// each concern lives in its own section instead of one long scroll.
//
// Reframe mode + Smart Cut + Subtitles + Hook + Logo are edited as *pending*
// state and only committed when the user presses "Apply & reprocess" — no
// auto-reprocessing on every tweak. Apply doesn't block: it hands the staged
// params to the parent (`onApply`) and closes immediately. The actual reframe
// (subprocess) + compose (subtitles → smart-cut → hook → logo) run in the
// BACKGROUND in RedesignApp, so the user can keep editing other clips.
//
// BULK MODE (`bulk` prop): the same surface edits several selected clips at
// once. The "Trim" tab (manual transcript text removal) is per-clip content and
// is hidden; the hook TEXT field is hidden too (each clip keeps its own Gemini
// opener). Only shared config — reframe / smart-cut / subtitles / hook style /
// logo — is applied across the selected clips (see lib/bulkApply.js).
import { useState, useEffect } from 'react';
import { Icon, Btn, Segmented, Switch } from './primitives';
import { SUBTITLE_PRESETS, SUB_COLORS, LOGO_POSITIONS, LOGO_SIZES, GRADE_PRESETS, HOOK_STYLE_DEFAULT } from './data';
import { useModalA11y } from './useModalA11y';
import { clipPreviewSrc, getClipTranscript, editClipAI } from './realApi';
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

export function EditClipModal({ clip, idx, jobId, initial, appliedMode, preselections,
                                bulk = false, targetCount = 0, onClose, onApply }) {
  const t0 = initial?.toggles || {};
  const sp = initial?.subtitleParams || {};
  const pre = preselections || {};
  const preSubs = pre.subtitles || {};

  // Current on-disk reframe mode (what a fresh reframe would diff against).
  const baseMode = appliedMode || initial?.reframeMode || clip.reframe_mode || 'auto';

  const [tab, setTab] = useState('reframe');
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
  // Colour grade (video-use-style). Preset 'none' = grade layer off.
  const gp0 = initial?.gradeParams || { preset: preselections?.grade?.preset || 'none' };
  const [gradePreset, setGradePreset] = useState(gp0.preset || 'none');
  const fonts = useFontList();

  const [mode, setMode] = useState(sp.mode || preSubs.mode || 'karaoke');
  const [preset, setPreset] = useState(sp.preset || preSubs.preset || 'hormozi_bold');
  // Default matches the Create pre-selection + backend ('bottom').
  const [position, setPosition] = useState(sp.position || preSubs.position || 'bottom');
  const [subFont, setSubFont] = useState(sp.font || preSubs.font || 'Montserrat-Black');
  const [subColor, setSubColor] = useState(sp.font_color || preSubs.font_color || '#FFFFFF');
  const [offsetY, setOffsetY] = useState(Number(sp.offset_y ?? preSubs.offset_y ?? 0));
  const [kSize, setKSize] = useState(Number(sp.font_size ?? preSubs.font_size ?? 0));
  const [cOutline, setCOutline] = useState(Number(sp.border_width ?? preSubs.border_width ?? 2));
  const [cBg, setCBg] = useState(Number(sp.bg_opacity ?? preSubs.bg_opacity ?? 0) > 0);
  const [hookText, setHookText] = useState(
    initial?.hookParams?.text || clip.viral_hook_text || clip.hook_text || '',
  );
  // IG-Stories hook style: seed from a prior edit, else the pre-selection.
  const [hookStyle, setHookStyle] = useState(
    () => pickHookStyle(initial?.hookParams || (preselections || {}).hook),
  );

  // Lazy-load transcript segments the first time the Trim tab is opened (and
  // never in bulk mode — manual trim is per-clip). Cheap GET; backend reads
  // metadata.json. Failure → hide the trim list silently.
  useEffect(() => {
    if (bulk || tab !== 'trim' || segments !== null || !jobId) return;
    let alive = true;
    getClipTranscript(jobId, idx)
      .then((d) => { if (!alive) return;
        const segs = d.segments || [];
        setSegments(segs);
        setDropped(dropSetFromRanges(segs, initial?.dropRanges));
      })
      .catch(() => { if (alive) setSegErr(true); });
    return () => { alive = false; };
  }, [bulk, tab, segments, jobId, idx, initial]);

  const toggleDrop = (i) => setDropped((prev) => {
    const next = new Set(prev);
    next.has(i) ? next.delete(i) : next.add(i);
    return next;
  });

  // Conversational trim: ask Gemini which spans to cut, then mark every segment
  // overlapping a returned span as dropped (reuses the tap-to-cut state).
  const [aiText, setAiText] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMsg, setAiMsg] = useState('');
  const askAITrim = async () => {
    const instr = aiText.trim();
    if (!instr || aiBusy || !jobId) return;
    setAiBusy(true); setAiMsg('');
    try {
      const { drop_ranges = [], explanation = '' } = await editClipAI(jobId, idx, instr);
      const segs = segments || [];
      const hit = new Set();
      for (const [ds, de] of drop_ranges) {
        for (const s of segs) {
          // overlap test between [s.start,s.end] and [ds,de]
          if (s.start < de && s.end > ds) hit.add(s.index);
        }
      }
      if (hit.size) {
        setDropped((prev) => new Set([...prev, ...hit]));
        setAiMsg(explanation || `Cut ${hit.size} segment${hit.size === 1 ? '' : 's'}.`);
      } else {
        setAiMsg(explanation || 'Nothing to cut for that instruction.');
      }
    } catch (e) {
      setAiMsg(e.message || 'AI trim failed.');
    } finally {
      setAiBusy(false);
    }
  };

  // Dropped segment indices → merged [start, end] spans for the backend. Never
  // in bulk (per-clip content).
  const dropRanges = bulk ? [] : (segments || [])
    .filter((s) => dropped.has(s.index))
    .map((s) => [s.start, s.end]);
  const hasDrops = dropRanges.length > 0;

  const panelRef = useModalA11y(onClose);

  const TABS = [
    { id: 'reframe', label: 'Reframe', icon: 'scan-face' },
    { id: 'captions', label: 'Captions', icon: 'captions' },
    { id: 'hook', label: 'Hook', icon: 'type' },
    { id: 'smartcut', label: 'Smart Cut', icon: 'scissors' },
    !bulk && { id: 'trim', label: 'Trim', icon: 'baseline' },
    { id: 'logo', label: 'Logo', icon: 'stamp' },
    { id: 'grade', label: 'Grade', icon: 'palette' },
  ].filter(Boolean);

  const gradeOn = gradePreset && gradePreset !== 'none';
  const reframeChanged = reframeMode !== baseMode;
  // Manual trim must run the Smart Cut compose stage (drop_ranges only apply
  // inside _apply_smartcut backend-side), so dropping text implies smartcut.
  const effSmartcut = smartcut || hasDrops;
  const anyCompose = effSmartcut || subsOn || hookOn || logoOn || gradeOn;
  const willReprocess = reframeChanged || anyCompose;

  // Non-blocking apply: seed the full param shape the compose backend expects,
  // layer the user's edits on top, hand it to the parent for BACKGROUND
  // processing, and close immediately.
  const apply = () => {
    // Build from the clean seed + current UI state only (no raw `...sp` spread,
    // which would leak stale style keys into a karaoke re-compose).
    const subtitleParams = { ...seedSubtitleParams(preselections), mode, preset, position,
      offset_y: offsetY,
      ...(mode === 'karaoke'
        ? { font_size: kSize > 0 ? kSize : undefined }
        : { font: subFont, font_color: subColor, border_width: cOutline,
            bg_opacity: cBg ? 0.6 : 0, bg_color: '#000000' }) };
    const hookParams = { ...seedHookParams(clip, preselections), ...(initial?.hookParams || {}), ...hookStyle, text: hookText };
    const logoParams = { position: logoPos, size: logoSize };
    const gradeParams = { preset: gradePreset };
    const toggles = { smartcut: effSmartcut, subtitles: subsOn, hook: hookOn, logo: logoOn, grade: gradeOn };
    onApply({ reframeMode, baseMode, toggles, subtitleParams, hookParams, logoParams, gradeParams,
      dropRanges: effSmartcut ? dropRanges : [] });
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal wide" ref={panelRef} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="edit-modal-title">
        <div className="modal-head">
          <div><h3 id="edit-modal-title">{bulk ? `Edit ${targetCount} clips` : 'Edit clip'}</h3>
            <div className="mh-sub">{bulk
              ? 'Shared settings · trim & hook text stay per-clip'
              : (clip.video_title_for_youtube_short || clip.title || `Clip ${idx + 1}`)}</div></div>
          <button className="x" onClick={onClose} aria-label="Close"><Icon n="x" /></button>
        </div>

        <div className="modal-body edit-grid">
          {/* Live preview of the (representative) clip as it stands on disk. */}
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
            <div className="edit-tabs" role="tablist">
              {TABS.map((t) => (
                <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
                  className={'tab' + (tab === t.id ? ' active' : '')} onClick={() => setTab(t.id)}>
                  <Icon n={t.icon} /><span className="lbl">{t.label}</span>
                </button>
              ))}
            </div>

            {tab === 'reframe' && (
              <div className="field" style={{ marginTop: 4 }}>
                <span className="field-label">Reframe</span>
                <Segmented full value={reframeMode} onChange={setReframeMode} options={REFRAME_OPTS} />
                <div className="eo-d" style={{ marginTop: 6 }}>Auto face-track · Object element-crop · Off letterbox bands</div>
              </div>
            )}

            {tab === 'smartcut' && (
              <>
                <div className="edit-opt">
                  <div className="eo-ico"><Icon n="scissors" /></div>
                  <div className="eo-txt"><div className="eo-t">Smart Cut</div><div className="eo-d">Auto-remove silence &amp; filler words</div></div>
                  <Switch on={smartcut} onChange={setSmartcut} />
                </div>
                <div className="eo-d" style={{ marginTop: 8 }}>
                  Detects and trims dead air + fillers automatically. To cut specific
                  sentences or words, use the {bulk ? 'Trim section on a single clip' : <b>Trim</b>} tab.
                </div>
              </>
            )}

            {tab === 'trim' && !bulk && (
              <div className="cf-row" style={{ marginBottom: 0 }}>
                <span className="field-label" style={{ marginBottom: 9, display: 'flex', justifyContent: 'space-between' }}>
                  <span>Manual trim</span>
                  {hasDrops && <span className="eo-d">{dropRanges.length} dropped</span>}
                </span>
                <div className="eo-d" style={{ marginBottom: 8 }}>
                  Tap any line to cut it, or describe the edit below. Trimming also runs Smart Cut&apos;s auto silence pass.
                </div>
                <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                  <input className="input-field" style={{ flex: 1 }}
                    placeholder="e.g. cut the intro and the part where he stumbles"
                    value={aiText} onChange={(e) => setAiText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') askAITrim(); }}
                    disabled={aiBusy || !segments || segments.length === 0} />
                  <Btn onClick={askAITrim} disabled={aiBusy || !aiText.trim() || !segments || segments.length === 0}>
                    <Icon n={aiBusy ? 'loader' : 'wand-sparkles'} style={{ width: 14, height: 14 }} />
                    {aiBusy ? 'Thinking…' : 'AI trim'}
                  </Btn>
                </div>
                {aiMsg && <div className="eo-d" style={{ marginBottom: 8 }}>{aiMsg}</div>}
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
                          <span className="trim-txt" title={s.text}>
                            {s.text && s.text.length > 140 ? s.text.slice(0, 140) + '…' : s.text}
                          </span>
                          <span className="trim-time">{s.start.toFixed(1)}s</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {tab === 'captions' && (
              <>
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
                      <>
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
                        <div className="cf-row">
                          <span className="field-label" style={{ marginBottom: 9, display: 'flex', justifyContent: 'space-between' }}>
                            <span>Font size</span><span className="eo-d">{kSize > 0 ? kSize : 'Auto'}</span>
                          </span>
                          <input type="range" min="0" max="80" step="1" value={kSize} aria-label="Subtitle font size"
                            onChange={(e) => setKSize(Number(e.target.value))} style={{ width: '100%' }} />
                        </div>
                      </>
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
                        <div className="cf-row">
                          <span className="field-label" style={{ marginBottom: 9, display: 'flex', justifyContent: 'space-between' }}>
                            <span>Outline width</span><span className="eo-d">{cOutline}</span>
                          </span>
                          <input type="range" min="0" max="6" step="1" value={cOutline} aria-label="Subtitle outline width"
                            onChange={(e) => setCOutline(Number(e.target.value))} style={{ width: '100%' }} />
                        </div>
                        <div className="edit-opt" style={{ marginTop: 4 }}>
                          <div className="eo-txt"><div className="eo-t" style={{ fontSize: 13 }}>Background box</div>
                            <div className="eo-d">Solid panel behind the text</div></div>
                          <Switch on={cBg} onChange={setCBg} />
                        </div>
                      </>
                    )}
                    <div className="cf-row">
                      <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Position</span>
                      <Segmented full value={position} onChange={setPosition}
                        options={[{ id: 'top', label: 'Top' }, { id: 'center', label: 'Center' }, { id: 'bottom', label: 'Bottom' }]} />
                    </div>
                    <div className="cf-row">
                      <span className="field-label" style={{ marginBottom: 9, display: 'flex', justifyContent: 'space-between' }}>
                        <span>Vertical nudge</span><span className="eo-d">{offsetY > 0 ? `+${offsetY}` : offsetY}</span>
                      </span>
                      <input type="range" min="-50" max="50" step="1" value={offsetY} aria-label="Subtitle vertical position"
                        onChange={(e) => setOffsetY(Number(e.target.value))} style={{ width: '100%' }} />
                    </div>
                  </div>
                )}
              </>
            )}

            {tab === 'hook' && (
              <>
                <div className="edit-opt">
                  <div className="eo-ico"><Icon n="type" /></div>
                  <div className="eo-txt"><div className="eo-t">Text hook</div><div className="eo-d">A scroll-stopping opener overlaid on the clip</div></div>
                  <Switch on={hookOn} onChange={setHookOn} />
                </div>
                {hookOn && (
                  <div className="cfg-drawer fade-in">
                    {bulk ? (
                      <div className="eo-d" style={{ marginBottom: 10 }}>
                        Applying the hook <b>style</b> to all selected clips. Each clip keeps its own hook text.
                      </div>
                    ) : (
                      <div className="cf-row">
                        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Hook text</span>
                        <textarea className="ta" rows="2" value={hookText} placeholder="e.g. THIS changed everything"
                          onChange={(e) => setHookText(e.target.value)}></textarea>
                      </div>
                    )}
                    <div style={{ marginTop: bulk ? 0 : 10 }}><HookPreview text={bulk ? 'Your hook text' : hookText} style={hookStyle} /></div>
                    <HookStyleControls style={hookStyle}
                      set={(partial) => setHookStyle((s) => ({ ...s, ...partial }))} />
                  </div>
                )}
              </>
            )}

            {tab === 'logo' && (
              <>
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
              </>
            )}

            {tab === 'grade' && (
              <>
                <div className="edit-opt">
                  <div className="eo-ico"><Icon n="palette" /></div>
                  <div className="eo-txt"><div className="eo-t">Colour grade</div><div className="eo-d">Cinematic colour pass burned before overlays</div></div>
                  <Switch on={gradeOn} onChange={(on) => setGradePreset(on ? 'warm_cinematic' : 'none')} />
                </div>
                {gradeOn && (
                  <div className="cfg-drawer fade-in">
                    <div className="cf-row" style={{ marginBottom: 0 }}>
                      <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Look</span>
                      <Segmented full value={gradePreset} onChange={setGradePreset}
                        options={GRADE_PRESETS} />
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        <div className="modal-foot">
          {willReprocess && (
            <span className="edit-dirty">
              {bulk
                ? `Will reprocess ${targetCount} clips in the background`
                : `${reframeChanged ? 'Will re-render framing' : 'Will re-compose layers'} in the background`}
            </span>
          )}
          <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
          <div className="mf-right">
            <Btn variant="primary" icon={willReprocess ? 'wand-sparkles' : 'check'} onClick={apply}>
              {bulk ? `Apply to ${targetCount} clips` : (willReprocess ? 'Apply & reprocess' : 'Save changes')}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}
