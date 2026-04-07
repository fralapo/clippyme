import React from 'react';
import { Github, Globe, Shield } from 'lucide-react';
import KeyInput from './KeyInput';

/**
 * Settings tab: API key + credential management plus a few shortcut links.
 *
 * @param {{
 *   onKeySet: (key: string) => void,
 *   onHfTokenSet: () => void,
 * }} props
 */
export default function SettingsTab({ onKeySet, onHfTokenSet }) {
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

      <div className="rounded-2xl bg-[#0f0f13] border border-white/5 overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5 flex items-center gap-2.5">
          <Shield size={16} className="text-emerald-400" />
          <span className="text-sm font-medium text-zinc-300">API Keys &amp; Security</span>
        </div>
        <div className="p-6">
          <KeyInput onKeySet={onKeySet} onHfTokenSet={onHfTokenSet} />
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
