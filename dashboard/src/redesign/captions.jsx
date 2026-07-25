// ClippyMe redesign — EditClipModal: one staged editing surface per clip,
// organised into TABS (Reframe · Captions · Hook · Smart Cut · Trim · Logo ·
// Grade). This file is the modal SHELL — header, live preview, tab bar,
// footer and the staged state + apply() payload seam. The tab bodies live in
// editTabs.jsx; the manual-trim state machine in hooks/useManualTrim.
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
import { useState } from 'react';
import { Icon, Btn } from './primitives';
import { HOOK_STYLE_DEFAULT } from './data';
import { useModalA11y } from './useModalA11y';
import { clipPreviewSrc } from './realApi';
import { useManualTrim } from '../hooks/useManualTrim';
import {
  ReframeTab, SmartCutTab, TrimTab, CaptionsTab, HookTab, LogoTab, GradeTab, BannerTab,
} from './editTabs';
import {
  seedSubtitleParams, seedHookParams, seedLogoParams, seedGradeParams, seedBannerParams,
} from '../lib/seedClipParams';

// Pull the IG-style hook style keys out of a flat hookParams object.
const HOOK_STYLE_KEYS = ['bg_enabled', 'bg_color', 'bg_opacity', 'text_color', 'outline_width', 'outline_color', 'font'];
function pickHookStyle(src) {
  const out = { ...HOOK_STYLE_DEFAULT };
  for (const k of HOOK_STYLE_KEYS) if (src && src[k] !== undefined) out[k] = src[k];
  return out;
}

// 'object' is the legacy name for the FrameShift 'subject' mode — normalize a
// value persisted under the old name so the segmented control highlights right.
const canonReframe = (m) => (m === 'object' ? 'subject' : (m || 'auto'));

export function EditClipModal({ clip, idx, jobId, initial, appliedMode, preselections, sourceBanner,
                                bulk = false, targetCount = 0, onClose, onApply }) {
  const t0 = initial?.toggles || {};
  const sp = initial?.subtitleParams || {};
  const pre = preselections || {};
  const preSubs = pre.subtitles || {};

  // Current on-disk reframe mode (what a fresh reframe would diff against).
  const baseMode = canonReframe(appliedMode || initial?.reframeMode || clip.reframe_mode || 'auto');

  const [tab, setTab] = useState('reframe');
  const [reframeMode, setReframeMode] = useState(baseMode);
  const [smartcut, setSmartcut] = useState(t0.smartcut ?? !!pre.smartcut);
  const [subsOn, setSubsOn] = useState(t0.subtitles ?? !!pre.subtitles);
  const [hookOn, setHookOn] = useState(t0.hook ?? !!pre.hook);
  const [logoOn, setLogoOn] = useState(t0.logo ?? !!pre.logo);
  const [bannerOn, setBannerOn] = useState(t0.banner ?? !!(pre.banner || sourceBanner));

  const lp0 = initial?.logoParams || seedLogoParams(preselections);
  const [logo, setLogo] = useState(() => ({
    position: lp0.position || 'top-right',
    size: lp0.size || 'M',
  }));
  // Colour grade (video-use-style). Preset 'none' = grade layer off.
  const gp0 = initial?.gradeParams || seedGradeParams(preselections);
  const [gradePreset, setGradePreset] = useState(gp0.preset || 'none');

  // Attribution banner (platform logo + handle). Seeded prior-edit → Create
  // pre-selection → the job's own source_info auto-suggestion → off.
  const bp0 = initial?.bannerParams || seedBannerParams(preselections, sourceBanner);
  const [banner, setBanner] = useState(() => ({
    platform: bp0.platform || 'kick',
    handle: bp0.handle || '',
    y_pct: bp0.y_pct ?? 0.85,
  }));

  // Staged subtitle state, one object in the seedClipParams key vocabulary
  // (plus the UI-only boolean `bg`). Seeded prior-edit → pre-selection →
  // default, exactly like the former per-key useStates.
  const [subs, setSubs] = useState(() => ({
    mode: sp.mode || preSubs.mode || 'karaoke',
    preset: sp.preset || preSubs.preset || 'hormozi_bold',
    // Default matches the Create pre-selection + backend ('bottom').
    position: sp.position || preSubs.position || 'bottom',
    font: sp.font || preSubs.font || 'Montserrat-Black',
    font_color: sp.font_color || preSubs.font_color || '#FFFFFF',
    // Karaoke stroke (outline) colour — defaults to black; the user can
    // recolour it per preset, but the default stays black.
    outline_color: sp.outline_color || preSubs.outline_color || '#000000',
    // Horizontal alignment: 'center' or 'left' (a bandiera). No 'right' — the
    // social UI (like/comment/share) lives down the right edge.
    align: sp.align || preSubs.align || 'center',
    offset_y: Number(sp.offset_y ?? preSubs.offset_y ?? 0),
    font_size: Number(sp.font_size ?? preSubs.font_size ?? 0),
    border_width: Number(sp.border_width ?? preSubs.border_width ?? 2),
    bg: Number(sp.bg_opacity ?? preSubs.bg_opacity ?? 0) > 0,
  }));

  const [hookText, setHookText] = useState(
    initial?.hookParams?.text || clip.viral_hook_text || clip.hook_text || '',
  );
  // IG-Stories hook style: seed from a prior edit, else the pre-selection.
  const [hookStyle, setHookStyle] = useState(
    () => pickHookStyle(initial?.hookParams || (preselections || {}).hook),
  );

  // Manual trim (flycut-style) — transcript load + dropped set + AI trim.
  // Resolve to the backend's ABSOLUTE `shorts` position, not the array
  // position `idx` — they diverge once a manual-publish gap skips a
  // deleted_after_publish clip (see job_results._build_clips).
  const trim = useManualTrim({
    jobId, idx: clip.original_index ?? idx,
    active: !bulk && tab === 'trim',
    initialDropRanges: initial?.dropRanges,
  });
  // Dropped spans for the backend. Never in bulk (per-clip content).
  const dropRanges = bulk ? [] : trim.dropRanges;
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
    { id: 'banner', label: 'Banner', icon: 'rss' },
  ].filter(Boolean);

  const gradeOn = gradePreset && gradePreset !== 'none';
  const reframeChanged = reframeMode !== baseMode;
  // Manual trim must run the Smart Cut compose stage (drop_ranges only apply
  // inside _apply_smartcut backend-side), so dropping text implies smartcut.
  const effSmartcut = smartcut || hasDrops;
  const anyCompose = effSmartcut || subsOn || hookOn || logoOn || gradeOn || bannerOn;
  const willReprocess = reframeChanged || anyCompose;

  // Non-blocking apply: seed the full param shape the compose backend expects,
  // layer the user's edits on top, hand it to the parent for BACKGROUND
  // processing, and close immediately.
  const apply = () => {
    // Build from the clean seed + current UI state only (no raw `...sp` spread,
    // which would leak stale style keys into a karaoke re-compose).
    const subtitleParams = { ...seedSubtitleParams(preselections),
      mode: subs.mode, preset: subs.preset, position: subs.position, align: subs.align,
      offset_y: subs.offset_y,
      ...(subs.mode === 'karaoke'
        ? { font_size: subs.font_size > 0 ? subs.font_size : undefined,
            font_color: subs.font_color, outline_color: subs.outline_color }
        : { font: subs.font, font_color: subs.font_color, border_width: subs.border_width,
            bg_opacity: subs.bg ? 0.6 : 0, bg_color: '#000000' }) };
    const hookParams = { ...seedHookParams(clip, preselections), ...(initial?.hookParams || {}), ...hookStyle, text: hookText };
    const logoParams = { position: logo.position, size: logo.size };
    const gradeParams = { preset: gradePreset };
    const bannerParams = { enabled: bannerOn, platform: banner.platform, handle: banner.handle, y_pct: banner.y_pct };
    const toggles = { smartcut: effSmartcut, subtitles: subsOn, hook: hookOn, logo: logoOn, grade: gradeOn, banner: bannerOn };
    onApply({ reframeMode, baseMode, toggles, subtitleParams, hookParams, logoParams, gradeParams, bannerParams,
      dropRanges: effSmartcut ? dropRanges : [] });
  };

  return (
    // Backdrop click is a mouse-only convenience; keyboard users close via
    // Esc (useModalA11y). currentTarget guard replaces stopPropagation.
    <div className="overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal wide" ref={panelRef}
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
              {/* Captions are burned into the pixels by the subtitle layer — no separate text track exists. */}
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

            {tab === 'reframe' && <ReframeTab mode={reframeMode} onChange={setReframeMode} />}
            {tab === 'smartcut' && <SmartCutTab on={smartcut} onChange={setSmartcut} bulk={bulk} />}
            {tab === 'trim' && !bulk && <TrimTab trim={trim} />}
            {tab === 'captions' && (
              <CaptionsTab on={subsOn} onToggle={setSubsOn} subs={subs}
                onSubsChange={(partial) => setSubs((s) => ({ ...s, ...partial }))} />
            )}
            {tab === 'hook' && (
              <HookTab on={hookOn} onToggle={setHookOn} bulk={bulk}
                text={hookText} onText={setHookText} style={hookStyle}
                onStyle={(partial) => setHookStyle((s) => ({ ...s, ...partial }))} />
            )}
            {tab === 'logo' && (
              <LogoTab on={logoOn} onToggle={setLogoOn} logo={logo}
                onChange={(partial) => setLogo((l) => ({ ...l, ...partial }))} />
            )}
            {tab === 'grade' && <GradeTab preset={gradePreset} onChange={setGradePreset} />}
            {tab === 'banner' && (
              <BannerTab on={bannerOn} onToggle={setBannerOn} banner={banner}
                onChange={(partial) => setBanner((b) => ({ ...b, ...partial }))} />
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
