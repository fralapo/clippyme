// ClippyMe redesign — SubtitleControls: the subtitle config drawer shared by
// BOTH editing surfaces (the Create recipe's SubConfig adapter and the
// EditClipModal Captions tab), following the hookStyle.jsx precedent.
//
// Fully controlled: `value` uses the lib/seedClipParams key vocabulary
// ({ mode, preset, font, font_color, outline_color, font_size, border_width,
// bg, position, align, offset_y }) with every default already resolved by the
// caller's adapter — this component never applies its own. `onChange(partial)`
// has merge semantics. Payload assembly stays on each surface (apply() in the
// modal, RedesignApp's opts→backend mapping for Create) — this is UI only.
//
// The two surfaces had drifted subtly before the dedup; `variant` preserves
// their original chrome byte-for-byte instead of silently unifying it:
//   D1 hint/value spans: 'od' (create) vs 'eo-d' (edit). Both are visually
//      inert inside .cfg-drawer (their CSS is ancestor-scoped), but the DOM
//      stays identical to what each surface rendered.
//   D2 the classic "Background box" row chrome: .opt (create) vs .edit-opt
//      (edit) — a real visual difference between the surfaces.
//   D3 the alignment hint copy differs by a few words.
import { Segmented, Switch } from './primitives';
import { SUBTITLE_PRESETS, SUB_COLORS } from './data';
import { useFontList } from '../hooks/useFontList';

const ALIGN_HINT = {
  create: 'Left = ragged (a bandiera), margin from edge · no right (social buttons)',
  edit: 'Left = ragged (a bandiera) with a margin from the edge · no right (social buttons there)',
};

function BackgroundBoxRow({ variant, on, onToggle }) {
  if (variant === 'create') {
    return (
      <div className="opt" style={{ paddingLeft: 0, paddingRight: 0 }}>
        <div className="otxt"><div className="ot" style={{ fontSize: 13 }}>Background box</div>
          <div className="od">Solid panel behind the text</div></div>
        <Switch on={on} onChange={onToggle} />
      </div>
    );
  }
  return (
    <div className="edit-opt" style={{ marginTop: 4 }}>
      <div className="eo-txt"><div className="eo-t" style={{ fontSize: 13 }}>Background box</div>
        <div className="eo-d">Solid panel behind the text</div></div>
      <Switch on={on} onChange={onToggle} />
    </div>
  );
}

export function SubtitleControls({ value: v, onChange, variant = 'edit' }) {
  const fonts = useFontList();
  const desc = variant === 'create' ? 'od' : 'eo-d';
  return (
    <div className="cfg-drawer fade-in">
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Mode</span>
        <Segmented full value={v.mode} onChange={(id) => onChange({ mode: id })}
          options={[{ id: 'karaoke', label: 'Karaoke' }, { id: 'classic', label: 'Classic' }]} />
      </div>
      {v.mode === 'karaoke' && (
        <>
          <div className="cf-row">
            <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Style preset</span>
            <div className="subgrid">
              {SUBTITLE_PRESETS.map((p) => (
                <button key={p.id} type="button" className={'subpre' + (v.preset === p.id ? ' on' : '')}
                  onClick={() => onChange({ preset: p.id })}>
                  <div className="prev"><span style={p.style}>WORD <span style={{ color: p.hi }}>UP</span></span></div>
                  <div className="nm">{p.label}</div>
                </button>
              ))}
            </div>
          </div>
          <div className="cf-row">
            <span className="field-label" style={{ marginBottom: 9, display: 'flex', justifyContent: 'space-between' }}>
              <span>Font size</span><span className={desc}>{v.font_size > 0 ? v.font_size : 'Auto'}</span>
            </span>
            <input type="range" min="0" max="80" step="1" value={v.font_size} aria-label="Subtitle font size"
              onChange={(e) => onChange({ font_size: Number(e.target.value) })} style={{ width: '100%' }} />
          </div>
          <div className="cf-row" style={{ display: 'flex', gap: 12 }}>
            <label style={{ flex: 1 }}>
              <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Text color</span>
              <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input type="color" aria-label="Subtitle text color" value={v.font_color}
                  onChange={(e) => onChange({ font_color: e.target.value })}
                  style={{ width: 40, height: 30, padding: 0, border: 'none', background: 'none', cursor: 'pointer' }} />
                <span className={desc}>{v.font_color.toUpperCase()}</span>
              </span>
            </label>
            <label style={{ flex: 1 }}>
              <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Stroke color</span>
              <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input type="color" aria-label="Subtitle stroke color" value={v.outline_color}
                  onChange={(e) => onChange({ outline_color: e.target.value })}
                  style={{ width: 40, height: 30, padding: 0, border: 'none', background: 'none', cursor: 'pointer' }} />
                <span className={desc}>{v.outline_color.toUpperCase()}</span>
              </span>
            </label>
          </div>
        </>
      )}
      {v.mode === 'classic' && (
        <>
          <div className="cf-row">
            <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Font</span>
            <select className="sel" style={{ width: '100%' }} value={v.font}
              onChange={(e) => onChange({ font: e.target.value })}>
              {fonts.map(([val, l]) => <option key={val} value={val}>{l}</option>)}
            </select>
          </div>
          <div className="cf-row">
            <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Color</span>
            <div className="swatches">
              {SUB_COLORS.map((c) => (
                <button key={c} type="button" aria-label={`Font color ${c}`}
                  className={'swatch' + (v.font_color.toUpperCase() === c.toUpperCase() ? ' on' : '')}
                  style={{ background: c }} onClick={() => onChange({ font_color: c })} />
              ))}
            </div>
          </div>
          <div className="cf-row">
            <span className="field-label" style={{ marginBottom: 9, display: 'flex', justifyContent: 'space-between' }}>
              <span>Outline width</span><span className={desc}>{v.border_width}</span>
            </span>
            <input type="range" min="0" max="6" step="1" value={v.border_width} aria-label="Subtitle outline width"
              onChange={(e) => onChange({ border_width: Number(e.target.value) })} style={{ width: '100%' }} />
          </div>
          <BackgroundBoxRow variant={variant} on={!!v.bg} onToggle={(on) => onChange({ bg: on })} />
        </>
      )}
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Position</span>
        <Segmented full value={v.position} onChange={(id) => onChange({ position: id })}
          options={[{ id: 'top', label: 'Top' }, { id: 'center', label: 'Center' }, { id: 'bottom', label: 'Bottom' }]} />
      </div>
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Alignment</span>
        <Segmented full value={v.align} onChange={(id) => onChange({ align: id })}
          options={[{ id: 'left', label: 'Left' }, { id: 'center', label: 'Center' }]} />
        <div className={desc} style={{ marginTop: 6 }}>{ALIGN_HINT[variant]}</div>
      </div>
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex', justifyContent: 'space-between' }}>
          <span>Vertical nudge</span><span className={desc}>{v.offset_y > 0 ? `+${v.offset_y}` : v.offset_y}</span>
        </span>
        <input type="range" min="-50" max="50" step="1" value={v.offset_y} aria-label="Subtitle vertical position"
          onChange={(e) => onChange({ offset_y: Number(e.target.value) })} style={{ width: '100%' }} />
      </div>
    </div>
  );
}
