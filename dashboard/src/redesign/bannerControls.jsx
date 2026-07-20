// ClippyMe redesign — BannerControls: the per-clip attribution banner (platform
// logo + channel handle burned bottom-of-clip), shared by the Create recipe
// and the EditClipModal (hookStyle.jsx / layerControls.jsx precedent: fully
// controlled `value` + `onChange(partial)`, no defaults applied here — the
// caller's adapter/seed resolves those). The enable Switch stays on each
// surface (matches Captions/Hook/Logo tabs) — this component only renders the
// platform/handle/position fields once the caller has already decided "on".
import { Segmented } from './primitives';
import { bannerText } from '../lib/bannerText';

export const BANNER_PLATFORMS = [
  { id: 'kick', label: 'Kick' },
  { id: 'youtube', label: 'YouTube' },
  { id: 'twitch', label: 'Twitch' },
];

const HANDLE_PLACEHOLDER = { kick: 'grenbaud', youtube: '@GrenBaudLounge', twitch: 'grenbaud' };

export function BannerControls({ value: v, onChange }) {
  const platform = v?.platform || 'kick';
  const handle = v?.handle || '';
  const yPct = Math.round((v?.y_pct ?? 0.85) * 100);
  const preview = bannerText(platform, handle);
  return (
    <>
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Platform</span>
        <Segmented full value={platform} onChange={(id) => onChange({ platform: id })} options={BANNER_PLATFORMS} />
      </div>
      <div className="cf-row">
        <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Channel handle</span>
        <input className="input-field" style={{ width: '100%' }} aria-label="Banner handle"
          placeholder={HANDLE_PLACEHOLDER[platform]} value={handle}
          onChange={(e) => onChange({ handle: e.target.value })} />
      </div>
      <div className="cf-row" style={{ marginBottom: 0 }}>
        <span className="field-label" style={{ marginBottom: 9, display: 'flex', justifyContent: 'space-between' }}>
          <span>Vertical position</span><span className="eo-d">{yPct}%</span>
        </span>
        <input type="range" min="60" max="87" step="1" value={yPct} aria-label="Banner vertical position"
          onChange={(e) => onChange({ y_pct: Number(e.target.value) / 100 })} style={{ width: '100%' }} />
      </div>
      <div className="eo-d" style={{ marginTop: 8 }}>
        {preview ? `Preview: ${preview}` : 'Enter a handle to preview the banner text'}
      </div>
    </>
  );
}
