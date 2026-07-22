// ClippyMe redesign — shared primitives (ported to ES modules + lucide-react).
import { Icon, Social } from './icon';

export { Icon, Social };

export function Btn({ variant = 'secondary', size, block, icon, iconRight, children, onClick, disabled, type, style, title }) {
  const cls = ['btn', 'btn-' + variant];
  if (size) cls.push('btn-' + size);
  if (block) cls.push('btn-block');
  return (
    <button type={type || 'button'} className={cls.join(' ')} onClick={onClick} disabled={disabled} style={style} title={title}>
      {icon && <Icon n={icon} />}{children}{iconRight && <Icon n={iconRight} />}
    </button>
  );
}

export function Badge({ tone = 'out', icon, children }) {
  return <span className={'badge badge-' + tone}>{icon && <Icon n={icon} />}{children}</span>;
}

export function Switch({ on, onChange, disabled, label }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} className={'sw' + (on ? ' on' : '')}
      onClick={(e) => { e.stopPropagation(); onChange && onChange(!on); }}><i></i></button>
  );
}

export function Segmented({ options, value, onChange, full, blue }) {
  return (
    <div className={'seg' + (full ? ' full' : '') + (blue ? ' blue' : '')}>
      {options.map((o) => (
        <button key={o.id} type="button" className={value === o.id ? 'on' : ''} onClick={() => onChange(o.id)}>
          {o.icon && <Icon n={o.icon} />}{o.label}
        </button>
      ))}
    </div>
  );
}

export function Stepper({ value, set, min = 1, max = 12 }) {
  return (
    <div className="stepper">
      <button type="button" onClick={() => set(Math.max(min, value - 1))} aria-label="Decrease">–</button>
      <span>{value}</span>
      <button type="button" onClick={() => set(Math.min(max, value + 1))} aria-label="Increase">+</button>
    </div>
  );
}

export function Panel({ title, sub, icon, headRight, pad = true, children, className, style }) {
  return (
    <div className={'panel' + (className ? ' ' + className : '')} style={style}>
      {title && (
        <div className="panel-head">
          {icon && <div className="ico"><Icon n={icon} /></div>}
          <div>
            <h3>{title}</h3>
            {sub && <div className="sub">{sub}</div>}
          </div>
          {headRight && <div className="right">{headRight}</div>}
        </div>
      )}
      <div className={pad ? 'panel-pad' : ''}>{children}</div>
    </div>
  );
}

export const PLATFORMS = [
  { id: 'tiktok', icon: 'tiktok', label: 'TikTok' },
  { id: 'ig', icon: 'instagram', label: 'Reels' },
  { id: 'yt', icon: 'youtube', label: 'Shorts' },
];

export function PlatPill({ id, icon, label, on, onClick }) {
  return (
    <button type="button" className={'plat' + (on ? ' on ' + id : '')} onClick={onClick}>
      <Social n={icon} color={on ? 'white' : '7E7E8F'} />{label}
    </button>
  );
}
