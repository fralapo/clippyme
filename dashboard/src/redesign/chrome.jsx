
import { useEffect, useState } from 'react';
import { Icon } from './icon';
import logoMark from './logo-mark.png';

const TABS = [
  { id: 'create', label: 'Create', icon: 'wand-sparkles' },
  { id: 'live', label: 'Live Monitor', icon: 'rss' },
  { id: 'history', label: 'History', icon: 'clock' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
];

function useBrowserOnline() {
  const [online, setOnline] = useState(() => typeof navigator === 'undefined' || navigator.onLine !== false);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine !== false);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  return online;
}

export function TopNav({ tab, setTab, busy }) {
  const online = useBrowserOnline();
  const status = !online ? 'Offline' : busy ? 'Working' : 'Local';
  return (
    <header className="topnav">
      <div className="brand" aria-label="ClippyMe home">
        <img src={logoMark} alt="" aria-hidden="true" />
        <span>Clippy<span className="me">Me</span></span>
      </div>
      <nav className="tabs" aria-label="Primary navigation">
        {TABS.map((item) => (
          <button key={item.id} type="button" className={`tab${tab === item.id ? ' active' : ''}`}
            aria-current={tab === item.id ? 'page' : undefined} onClick={() => setTab(item.id)}>
            <Icon n={item.icon} /><span className="lbl">{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="nav-right">
        <span className={`status-dot${online ? '' : ' offline'}`} role="status" aria-live="polite">
          <i aria-hidden="true" style={busy && online ? { background: 'var(--brand-blue)', boxShadow: '0 0 0 3px rgba(10,129,217,.16)' } : null} />
          <span className="sd-lbl">{status}</span>
        </span>
        <div className="avatar" aria-hidden="true">CM</div>
      </div>
    </header>
  );
}

export function Hero({ eyebrow, line1, grad, sub }) {
  return (
    <div className="hero">
      {eyebrow && <div className="eyebrow"><i aria-hidden="true" />{eyebrow}</div>}
      <h1>{line1}{grad && <> <span className="grad">{grad}</span></>}</h1>
      {sub && <p>{sub}</p>}
    </div>
  );
}
