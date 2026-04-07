import React, { useEffect, useState } from 'react';
import { Github, Globe, Shield, Send, Check, Circle } from 'lucide-react';
import KeyInput from './KeyInput';
import ZernioSettings from './ZernioSettings';
import { getApiUrl } from '../config';

/**
 * Settings tab: API key + credential management plus a few shortcut links.
 *
 * @param {{
 *   onKeySet: (key: string) => void,
 *   onHfTokenSet: () => void,
 *   onCookiesChange?: (configured: boolean) => void,
 * }} props
 */
export default function SettingsTab({ onKeySet, onHfTokenSet, onCookiesChange }) {
  const [status, setStatus] = useState({
    gemini: false,
    hf: false,
    cookies: false,
    zernio: false,
  });

  useEffect(() => {
    Promise.all([
      fetch(getApiUrl('/api/config')).then((r) => (r.ok ? r.json() : {})),
      fetch(getApiUrl('/api/config/cookies/status')).then((r) => (r.ok ? r.json() : {})),
      fetch(getApiUrl('/api/config/zernio')).then((r) => (r.ok ? r.json() : {})),
    ])
      .then(([cfg, cookies, zernio]) => {
        setStatus({
          gemini: !!cfg.GEMINI_API_KEY,
          hf: !!cfg.HF_TOKEN,
          cookies: !!cookies.configured,
          zernio: !!zernio.configured,
        });
      })
      .catch(() => {});
  }, []);

  const setupItems = [
    { key: 'gemini', label: 'Gemini API key', required: true, ok: status.gemini },
    { key: 'cookies', label: 'YouTube cookies', required: false, ok: status.cookies },
    { key: 'hf', label: 'HuggingFace token', required: false, ok: status.hf },
    { key: 'zernio', label: 'Zernio publishing', required: false, ok: status.zernio },
  ];
  const missingRequired = setupItems.filter((s) => s.required && !s.ok).length;
  const totalOk = setupItems.filter((s) => s.ok).length;

  const goToLanding = (e) => {
    e.preventDefault();
    localStorage.removeItem('clippyme_skip_landing');
    window.location.hash = '';
    window.location.reload();
  };

  return (
    <div className="animate-fade-in space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white">Settings</h2>
        <p className="text-zinc-500 text-sm mt-1">
          Manage your API keys and model configuration.
        </p>
      </div>

      {/* Setup status card */}
      <div
        className={`rounded-2xl border p-4 ${
          missingRequired > 0
            ? 'bg-amber-500/5 border-amber-500/20'
            : 'bg-emerald-500/5 border-emerald-500/20'
        }`}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p
              className={`text-sm font-semibold ${
                missingRequired > 0 ? 'text-amber-300' : 'text-emerald-300'
              }`}
            >
              {missingRequired > 0
                ? `Setup incomplete — ${missingRequired} required item${missingRequired === 1 ? '' : 's'} missing`
                : `All systems ready (${totalOk}/${setupItems.length} configured)`}
            </p>
            <p className="text-[11px] text-zinc-500 mt-0.5">
              {missingRequired > 0
                ? "You won't be able to process clips until the required items are configured."
                : "ClippyMe is ready to go. Optional integrations expand what you can do at the edges."}
            </p>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
          {setupItems.map((item) => (
            <div
              key={item.key}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[11px] ${
                item.ok
                  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
                  : item.required
                    ? 'bg-amber-500/10 border-amber-500/20 text-amber-300'
                    : 'bg-white/[0.02] border-white/5 text-zinc-500'
              }`}
            >
              {item.ok ? <Check size={10} /> : <Circle size={10} />}
              <span className="truncate">{item.label}</span>
              {!item.ok && item.required && (
                <span className="text-[8px] uppercase font-bold tracking-wider ml-auto">req</span>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-2xl bg-[#0f0f13] border border-white/5 overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5 flex items-center gap-2.5">
          <Shield size={16} className="text-emerald-400" />
          <span className="text-sm font-medium text-zinc-300">API Keys &amp; Security</span>
        </div>
        <div className="p-6">
          <KeyInput onKeySet={onKeySet} onHfTokenSet={onHfTokenSet} onCookiesChange={onCookiesChange} />
        </div>
      </div>

      <div className="rounded-2xl bg-[#0f0f13] border border-white/5 overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5 flex items-center gap-2.5">
          <Send size={16} className="text-accent-pink" />
          <span className="text-sm font-medium text-zinc-300">Social Publishing (Zernio)</span>
        </div>
        <div className="p-6">
          <ZernioSettings />
        </div>
      </div>

      <div className="flex items-center gap-4 pt-2">
        <a
          href="#"
          onClick={goToLanding}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/5 border border-white/5 hover:border-white/10 text-sm text-zinc-400 hover:text-white transition-all"
        >
          <Globe size={16} />
          Landing Page
        </a>
        <a
          href="https://github.com/fralapo/clippyme"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/5 border border-white/5 hover:border-white/10 text-sm text-zinc-400 hover:text-white transition-all"
        >
          <Github size={16} />
          Repository
        </a>
      </div>
    </div>
  );
}
