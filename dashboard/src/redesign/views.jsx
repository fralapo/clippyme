// ClippyMe redesign — HistoryView + SettingsView + ApiKeyModal, wired to the
// real backend (history list/restore/delete; config keys, cookies, Zernio).
import { useState, useEffect } from 'react';
import { Icon, Btn, Badge, Switch, Panel } from './primitives';
import { Hero } from './chrome';
import {
  getConfig, saveConfig, cookiesStatus, uploadCookies, deleteCookies,
  getZernio, saveZernio, discoverZernioAccounts,
} from './realApi';

function relTime(ts) {
  if (!ts) return '';
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function HistoryView({ history, onOpen, onDelete, onClear }) {
  if (!history.length) {
    return (
      <div className="container narrow fade-in">
        <Hero eyebrow="History" line1="Nothing here yet." sub="Every job you run shows up here — ready to reopen, re-export, or publish again." />
        <div className="empty">
          <div className="ei"><Icon n="clock" /></div>
          <h3>No jobs yet</h3>
          <p>Head to Create, paste a link, and your finished clips will land here.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="container narrow fade-in">
      <div className="results-head" style={{ marginBottom: 18 }}>
        <h2>History</h2>
        <Badge tone="out">{history.length} jobs</Badge>
        <div className="rh-right">
          <Btn variant="ghost" size="sm" icon="trash-2" onClick={onClear}>Clear all</Btn>
        </div>
      </div>
      <Panel pad={false} className="hlist">
        {history.map((h) => {
          const ok = h.status === 'complete';
          return (
            <div className="hrow" key={h.jobId} onClick={() => ok && onOpen(h)} style={{ cursor: ok ? 'pointer' : 'default' }}>
              <div className="hthumb" style={{ background: 'var(--grad-viral)' }}>{h.clipCount ?? 0}</div>
              <div style={{ minWidth: 0 }}>
                <div className="ht">{h.source || h.jobId}</div>
                <div className="hm">
                  <Icon n={h.sourceType === 'url' ? 'globe' : 'file-video'} style={{ width: 11, height: 11, verticalAlign: '-1px', marginRight: 5 }} />
                  {h.clipCount || 0} clips{h.cost != null ? ` · $${Number(h.cost).toFixed(2)}` : ''} · {relTime(h.timestamp)}
                </div>
              </div>
              <div className="hr">
                {ok ? <Badge tone="teal" icon="check">complete</Badge>
                  : h.status === 'error' ? <Badge tone="danger" icon="triangle-alert">error</Badge>
                    : <Badge tone="amber" icon="clock">{h.status || 'pending'}</Badge>}
                <span className="mini" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(h.jobId); }}><Icon n="trash-2" /></span>
                {ok && <Icon n="chevron-right" style={{ width: 18, height: 18, color: 'var(--fg-4)' }} />}
              </div>
            </div>
          );
        })}
      </Panel>
    </div>
  );
}

function KeyRow({ icon, name, desc, value, onChange, onSave, placeholder, present }) {
  const [reveal, setReveal] = useState(false);
  return (
    <div className="keyrow">
      <div className="ki"><Icon n={icon} /></div>
      <div style={{ minWidth: 0 }}>
        <div className="kt">{name}</div>
        <div className="kd">{desc}</div>
      </div>
      <div className="kr">
        <input className="key-input" type={reveal ? 'text' : 'password'} value={value}
          placeholder={placeholder} onChange={(e) => onChange(e.target.value)} onBlur={onSave} />
        <span className="mini" title={reveal ? 'Hide' : 'Show'} onClick={() => setReveal(!reveal)}><Icon n={reveal ? 'eye-off' : 'eye'} /></span>
        {value || present ? <Badge tone="teal" icon="check">set</Badge> : <Badge tone="out">empty</Badge>}
      </div>
    </div>
  );
}

export function SettingsView({ apiKey, onApiKey, cookiesConfigured, pushToast }) {
  const [gemini, setGemini] = useState(apiKey || '');
  const [deepgram, setDeepgram] = useState('');
  const [hf, setHf] = useState('');
  const [present, setPresent] = useState({});
  const [zernio, setZernioState] = useState(null);
  const [zKey, setZKey] = useState('');
  const [accts, setAccts] = useState({ tiktok: '', instagram: '', youtube: '' });
  const [cookies, setCookies] = useState(!!cookiesConfigured);

  useEffect(() => {
    getConfig().then((c) => setPresent({
      gemini: !!c.GEMINI_API_KEY, hf: !!c.HF_TOKEN, deepgram: !!c.DEEPGRAM_API_KEY,
    })).catch(() => {});
    getZernio().then((z) => { setZernioState(z); if (z.accounts) setAccts({ tiktok: '', instagram: '', youtube: '', ...z.accounts }); }).catch(() => {});
    cookiesStatus().then((s) => setCookies(!!s.configured)).catch(() => {});
  }, []);

  const saveKeys = async (patch) => {
    try { await saveConfig(patch); pushToast?.('success', 'Saved'); } catch { pushToast?.('error', 'Save failed'); }
  };

  const saveZernioCfg = async () => {
    try {
      const payload = { accounts: accts };
      if (zKey.trim()) payload.api_key = zKey.trim();
      const z = await saveZernio(payload);
      setZernioState(z); setZKey('');
      pushToast?.('success', 'Zernio saved');
    } catch { pushToast?.('error', 'Zernio save failed'); }
  };

  const discover = async () => {
    try {
      const { accounts } = await discoverZernioAccounts();
      const next = { ...accts };
      (accounts || []).forEach((a) => {
        const p = (a.platform || '').toLowerCase();
        const id = a._id || a.id;
        if (p.includes('tiktok')) next.tiktok = id;
        else if (p.includes('insta')) next.instagram = id;
        else if (p.includes('you')) next.youtube = id;
      });
      setAccts(next);
      pushToast?.('success', `Discovered ${(accounts || []).length} accounts`);
    } catch { pushToast?.('error', 'Discover failed — check API key'); }
  };

  const onCookieFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try { await uploadCookies(f); setCookies(true); pushToast?.('success', 'Cookies uploaded'); }
    catch { pushToast?.('error', 'Cookie upload failed'); }
  };
  const removeCookies = async () => {
    try { await deleteCookies(); setCookies(false); pushToast?.('info', 'Cookies removed'); }
    catch { pushToast?.('error', 'Remove failed'); }
  };

  return (
    <div className="container narrow fade-in">
      <Hero eyebrow="Settings" line1="Keys & connections." sub="Everything is stored locally. Your keys never leave your machine." />

      <Panel title="API keys" sub="Required for transcription & moment detection" icon="key-round" style={{ marginBottom: 18 }}>
        <KeyRow icon="sparkles" name="Gemini" desc="Viral-moment detection" value={gemini} present={present.gemini}
          onChange={(v) => { setGemini(v); onApiKey?.(v); }} onSave={() => gemini && saveKeys({ GEMINI_API_KEY: gemini })} placeholder="AIza…" />
        <KeyRow icon="audio-lines" name="Deepgram" desc="Nova-3 transcription" value={deepgram} present={present.deepgram}
          onChange={setDeepgram} onSave={() => deepgram && saveKeys({ DEEPGRAM_API_KEY: deepgram })} placeholder="dg_…" />
        <KeyRow icon="scan-face" name="Hugging Face token" desc="Speaker diarization models" value={hf} present={present.hf}
          onChange={setHf} onSave={() => hf && saveKeys({ HF_TOKEN: hf })} placeholder="hf_…" />
      </Panel>

      <Panel title="Publishing" sub="Push finished clips to socials via Zernio" icon="send" style={{ marginBottom: 18 }}>
        <div className="zernio-card" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <div className="zico"><Icon n="rss" /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="kt">Zernio</div>
              <div className="kd">{zernio?.configured ? `Connected${zernio.api_key_masked ? ' · ' + zernio.api_key_masked : ''}` : 'Add your API key + account IDs to schedule posts'}</div>
            </div>
            {zernio?.configured && <span className="conn"><Icon n="circle-check" />Connected</span>}
          </div>
          <input className="key-input" style={{ width: '100%' }} type="password" value={zKey}
            placeholder={zernio?.configured ? 'Replace API key (optional)' : 'Zernio API key (sk_…)'} onChange={(e) => setZKey(e.target.value)} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8 }}>
            {['tiktok', 'instagram', 'youtube'].map((p) => (
              <input key={p} className="key-input" style={{ width: '100%', fontFamily: 'var(--font-sans)' }}
                value={accts[p] || ''} placeholder={`${p} account id`} onChange={(e) => setAccts((a) => ({ ...a, [p]: e.target.value }))} />
            ))}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <Btn variant="secondary" size="sm" icon="rss" onClick={discover}>Discover from Zernio</Btn>
            <Btn variant="primary" size="sm" icon="check" onClick={saveZernioCfg}>Save</Btn>
          </div>
        </div>
      </Panel>

      <Panel title="Downloads" sub="For age- or region-restricted sources" icon="cookie">
        <div className="opt" style={{ borderBottom: 0 }}>
          <div className="oico"><Icon n="cookie" /></div>
          <div className="otxt"><div className="ot">YouTube cookies</div><div className="od">{cookies ? 'Configured · restricted videos OK' : 'Not set · public videos only'}</div></div>
          <div className="r" style={{ gap: 8 }}>
            <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer' }}>
              <Icon n="upload" />Upload
              <input type="file" accept=".txt" hidden onChange={onCookieFile} />
            </label>
            {cookies && <Btn variant="ghost" size="sm" icon="trash-2" onClick={removeCookies}>Remove</Btn>}
          </div>
        </div>
      </Panel>
    </div>
  );
}

export function ApiKeyModal({ onClose, onGoToSettings }) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head"><h3>Add your Gemini key</h3><button className="x" onClick={onClose}><Icon n="x" /></button></div>
        <div className="modal-body">
          <p style={{ color: 'var(--fg-2)', fontSize: 14, lineHeight: 1.55 }}>
            ClippyMe needs a Gemini key to score the transcript and find viral moments. It's stored locally and never leaves your machine.
          </p>
        </div>
        <div className="modal-foot">
          <Btn variant="ghost" onClick={onClose}>Later</Btn>
          <div className="mf-right"><Btn variant="primary" icon="settings" onClick={onGoToSettings}>Open settings</Btn></div>
        </div>
      </div>
    </div>
  );
}
