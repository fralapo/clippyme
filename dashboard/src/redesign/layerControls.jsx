// ClippyMe redesign — LogoControls + GradeControls: the logo/grade config
// pieces shared by the Create recipe and the EditClipModal (hookStyle.jsx
// precedent: controlled values + partial-emitting onChange, UI only).
import { Segmented } from './primitives';
import { LOGO_POSITIONS, LOGO_SIZES, GRADE_PRESETS } from './data';

// The two cf-rows of the logo drawer. No wrapper: each surface keeps its own
// .cfg-drawer (Create appends an upload hint under these rows).
// Note: the modal's Size row used to carry style={{marginBottom:0}} — dropped
// as redundant: .cfg-drawer .cf-row:last-child already zeroes the margin when
// the row is last (modal), and in Create the hint follows so the margin must
// stay either way.
export function LogoControls({ position, size, onChange }) {
  return (
    <>
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Position</span>
        <div className="seg-grid">
          {LOGO_POSITIONS.map(([v, l]) => (
            <button key={v} type="button" className={'seg-cell' + (position === v ? ' on' : '')}
              onClick={() => onChange({ position: v })}>{l}</button>
          ))}
        </div>
      </div>
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Size</span>
        <Segmented full value={size} onChange={(id) => onChange({ size: id })}
          options={LOGO_SIZES.map(([v, l]) => ({ id: v, label: l }))} />
      </div>
    </>
  );
}

// Just the preset segmented — the surrounding chrome genuinely differs per
// surface (Create: always-visible row with an explicit 'Off' entry, no
// Switch; modal: an on/off Switch owns the none↔preset transition).
export function GradeControls({ preset, onChange, withOff = false, full = true }) {
  const options = withOff
    ? [{ id: 'none', label: 'Off' }, ...GRADE_PRESETS.map((g) => ({ id: g.id, label: g.label }))]
    : GRADE_PRESETS;
  return (
    <Segmented full={full} value={preset} onChange={(id) => onChange({ preset: id })}
      options={options} />
  );
}
