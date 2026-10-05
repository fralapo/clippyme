// Shared Instagram-Stories-style hook text controls — used by the Create
// "Clip Options" hook drawer and the per-clip Edit modal. `style` is the flat
// param object (keys match the backend create_hook_image dict); `set(partial)`
// merges updates. A live WYSIWYG preview sits on top so the user sees the
// banner / colours / outline before reprocessing.
import { Segmented, Switch } from '../primitives';
import { SUB_COLORS, HOOK_OUTLINE, HOOK_BACKEND_DEFAULT_FONT, HOOK_UNSUPPORTED_FONTS, bundledPreviewFont, isHookFontSelectable } from '../../lib/uiOptions';

function Swatches({ value, onPick, label }) {
  return (
    <div className="cf-row">
      <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>{label}</span>
      <div className="swatches">
        {SUB_COLORS.map((c) => (
          <button key={c} type="button" aria-label={`${label} ${c}`}
            className={'swatch' + ((value || '').toUpperCase() === c.toUpperCase() ? ' on' : '')}
            style={{ background: c }} onClick={() => onPick(c)} />
        ))}
      </div>
    </div>
  );
}

// Font ID the preview draws. '', a font the hook renderer never loads (Verdana)
// and a name the live font list no longer carries (an uploaded font deleted
// after a preset or clip saved it) all render with the backend default
// (hook_overlay FONT_PATH). Until the list has loaded, an uploaded font's
// availability is unknown and the name is kept. Preview-only.
function previewFontId(font, fontCatalog) {
  if (!font || HOOK_UNSUPPORTED_FONTS.has(font)) return HOOK_BACKEND_DEFAULT_FONT;
  if (fontCatalog?.live && !fontCatalog.fonts.some(([v]) => v === font)) return HOOK_BACKEND_DEFAULT_FONT;
  return font;
}

// `fontCatalog` is the parent's useFontCatalog(), shared with HookStyleControls.
export function HookPreview({ text, style, fontCatalog }) {
  const s = style || {};
  const ow = parseInt(s.outline_width || 0, 10);
  const oc = s.outline_color || '#000';
  // CSS text-shadow approximation of the Pillow stroke (8-way) for the preview.
  const stroke = ow > 0
    ? [[-ow, -ow], [ow, -ow], [-ow, ow], [ow, ow], [0, -ow], [0, ow], [-ow, 0], [ow, 0]]
      .map(([x, y]) => `${x}px ${y}px 0 ${oc}`).join(',')
    : (s.bg_enabled ? 'none' : '0 2px 6px rgba(0,0,0,.6)');
  const bg = s.bg_enabled
    ? hexA(s.bg_color || '#FFFFFF', s.bg_opacity ?? 0.94)
    : 'transparent';
  // Bundled fonts preview with the same TTF the backend burns, at its real
  // weight (a generic 800 would faux-bold 400-only Anton/Bangers). An empty or
  // unavailable font previews the backend default face; s.font is unchanged.
  const fontId = previewFontId(s.font, fontCatalog);
  const face = bundledPreviewFont(fontId) || {
    fontFamily: `"${fontId}", sans-serif`,
    fontWeight: 800,
  };
  // The renderer draws the TTF's default glyphs with no tracking: don't inherit
  // the dashboard's body font-feature-settings (ss01 swaps Montserrat's y/a/t/W…,
  // tnum digits) or letter-spacing (any non-zero value drops fi/fl/ff ligatures).
  return (
    <div style={{ padding: '18px 12px', background: '#0c0c11', borderRadius: 'var(--r-sm)', textAlign: 'center', display: 'flex', justifyContent: 'center' }}>
      <span style={{
        display: 'inline-block', padding: s.bg_enabled ? '8px 16px' : '4px 6px',
        borderRadius: 12, background: bg, color: s.text_color || '#fff',
        ...face, fontFeatureSettings: 'normal', letterSpacing: 'normal', fontSize: 17, lineHeight: 1.15, textShadow: stroke, maxWidth: '100%',
      }}>{text || 'Your hook text'}</span>
    </div>
  );
}

function hexA(hex, a) {
  const h = (hex || '#FFFFFF').replace('#', '');
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

// `fonts` is the parent's useFontCatalog().fonts ([value, label] pairs); only
// isHookFontSelectable() entries are offered (no unsupported font, no duplicate
// of "Default (serif)").
export function HookStyleControls({ style, set, fonts }) {
  const s = style || {};
  const ow = String(s.outline_width ?? 0);
  return (
    <>
      <div className="edit-opt" style={{ padding: '10px 0', border: 0 }}>
        <div className="eo-txt"><div className="eo-t" style={{ fontSize: 13 }}>Banner behind text</div><div className="eo-d">A coloured block (Instagram-style)</div></div>
        <Switch on={!!s.bg_enabled} onChange={(v) => set({ bg_enabled: v })} />
      </div>
      {s.bg_enabled && (
        <>
          <Swatches label="Banner color" value={s.bg_color} onPick={(c) => set({ bg_color: c })} />
          <div className="cf-row">
            <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Banner opacity · {Math.round((s.bg_opacity ?? 0.94) * 100)}%</span>
            <input type="range" min="20" max="100" value={Math.round((s.bg_opacity ?? 0.94) * 100)}
              onChange={(e) => set({ bg_opacity: Number(e.target.value) / 100 })} style={{ width: '100%' }} />
          </div>
        </>
      )}
      <Swatches label="Text color" value={s.text_color} onPick={(c) => set({ text_color: c })} />
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Outline</span>
        <Segmented full value={ow} onChange={(id) => set({ outline_width: Number(id) })}
          options={HOOK_OUTLINE.map(([v, l]) => ({ id: v, label: l }))} />
      </div>
      {ow !== '0' && <Swatches label="Outline color" value={s.outline_color} onPick={(c) => set({ outline_color: c })} />}
      <div className="edit-opt" style={{ padding: '10px 0', border: 0 }}>
        <div className="eo-txt"><div className="eo-t" style={{ fontSize: 13 }}>Animated entrance</div><div className="eo-d">Fade + slide-up when the hook appears</div></div>
        <Switch on={!!s.animate} onChange={(v) => set({ animate: v })} />
      </div>
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Font</span>
        <select className="sel" style={{ width: '100%' }} value={s.font || ''} onChange={(e) => set({ font: e.target.value })}>
          <option value="">Default (serif)</option>
          {fonts.filter(([v]) => isHookFontSelectable(v)).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
    </>
  );
}
