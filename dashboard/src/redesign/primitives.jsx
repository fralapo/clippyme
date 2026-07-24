
import { useId, useRef } from 'react';
import { Icon, Social } from './icon';

export { Icon, Social };

export function Btn({ variant = 'secondary', size, block, icon, iconRight, children, loading = false, disabled, type = 'button', className = '', ...props }) {
  const classes = ['btn', `btn-${variant}`, size && `btn-${size}`, block && 'btn-block', className].filter(Boolean).join(' ');
  return (
    <button {...props} type={type} className={classes} disabled={disabled || loading} aria-busy={loading || undefined}>
      {(loading || icon) && <Icon n={loading ? 'loader' : icon} />}
      <span>{children}</span>
      {!loading && iconRight && <Icon n={iconRight} />}
    </button>
  );
}

export function Badge({ tone = 'out', icon, children, className = '', ...props }) {
  return <span {...props} className={`badge badge-${tone}${className ? ` ${className}` : ''}`}>{icon && <Icon n={icon} />}{children}</span>;
}

export function Switch({ on, onChange, disabled, label = 'Toggle option', ...props }) {
  return (
    <button {...props} type="button" role="switch" aria-checked={!!on} aria-label={label} disabled={disabled}
      className={`sw${on ? ' on' : ''}`} onClick={(event) => { event.stopPropagation(); onChange?.(!on); }}>
      <i aria-hidden="true" />
    </button>
  );
}

export function Segmented({ options, value, onChange, full, blue, label = 'Choose an option' }) {
  const refs = useRef([]);
  const move = (event, index) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const direction = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1;
    const next = (index + direction + options.length) % options.length;
    onChange(options[next].id);
    refs.current[next]?.focus();
  };
  return (
    <div className={`seg${full ? ' full' : ''}${blue ? ' blue' : ''}`} role="group" aria-label={label}>
      {options.map((option, index) => (
        <button key={option.id} ref={(node) => { refs.current[index] = node; }} type="button"
          aria-pressed={value === option.id}
          className={value === option.id ? 'on' : ''} onClick={() => onChange(option.id)} onKeyDown={(event) => move(event, index)}>
          {option.icon && <Icon n={option.icon} />}{option.label}
        </button>
      ))}
    </div>
  );
}

export function Stepper({ value, set, min = 1, max = 12, label = 'Value' }) {
  return (
    <div className="stepper" role="group" aria-label={label}>
      <button type="button" disabled={value <= min} onClick={() => set(Math.max(min, value - 1))} aria-label={`Decrease ${label}`}>–</button>
      <output aria-live="polite">{value}</output>
      <button type="button" disabled={value >= max} onClick={() => set(Math.min(max, value + 1))} aria-label={`Increase ${label}`}>+</button>
    </div>
  );
}

export function Panel({ title, sub, icon, headRight, pad = true, children, className, style, as: Tag = 'section' }) {
  const titleId = useId();
  return (
    <Tag className={`panel${className ? ` ${className}` : ''}`} style={style} aria-labelledby={title ? titleId : undefined}>
      {title && (
        <div className="panel-head">
          {icon && <div className="ico" aria-hidden="true"><Icon n={icon} /></div>}
          <div><h3 id={titleId}>{title}</h3>{sub && <div className="sub">{sub}</div>}</div>
          {headRight && <div className="right">{headRight}</div>}
        </div>
      )}
      <div className={pad ? 'panel-pad' : ''}>{children}</div>
    </Tag>
  );
}

export const PLATFORMS = [
  { id: 'tiktok', icon: 'tiktok', label: 'TikTok' },
  { id: 'ig', icon: 'instagram', label: 'Reels' },
  { id: 'yt', icon: 'youtube', label: 'Shorts' },
];

export function PlatPill({ id, icon, label, on, onClick }) {
  return (
    <button type="button" className={`plat${on ? ` on ${id}` : ''}`} aria-pressed={!!on} onClick={onClick}>
      <Social n={icon} color={on ? 'white' : '7E7E8F'} />{label}
    </button>
  );
}
