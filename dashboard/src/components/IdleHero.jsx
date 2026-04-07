import React from 'react';
import { AlertCircle, Instagram, Key, Youtube } from 'lucide-react';
import MediaInput from './MediaInput';

const TikTokIcon = ({ size = 16, className = '' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

/**
 * Landing / idle state of the Dashboard tab: hero headline, credential
 * warnings, media input, and a platform footer.
 *
 * @param {{
 *   apiKey: string,
 *   hfTokenSet: boolean,
 *   cookiesConfigured: boolean,
 *   isProcessing: boolean,
 *   onOpenSettings: () => void,
 *   onProcess: (data: object) => void,
 *   onBatchProcess: (data: object) => void,
 * }} props
 */
export default function IdleHero({
  apiKey,
  hfTokenSet,
  cookiesConfigured,
  isProcessing,
  onOpenSettings,
  onProcess,
  onBatchProcess,
}) {
  return (
    <div className="flex flex-col items-center text-center space-y-8 pt-6 sm:pt-16">
      <div className="space-y-4">
        <div className="relative inline-block">
          <div className="absolute -inset-6 bg-gradient-to-r from-pink-500/20 to-purple-500/20 blur-3xl rounded-full" />
          <h1 className="text-5xl sm:text-6xl md:text-7xl font-extrabold text-white tracking-tight relative">
            Go{' '}
            <span className="bg-gradient-to-r from-pink-500 to-purple-500 bg-clip-text text-transparent">
              Viral
            </span>
          </h1>
        </div>
        <p className="text-zinc-500 text-base sm:text-lg max-w-md mx-auto leading-relaxed">
          Drop a URL or upload a file to generate viral short clips with AI.
        </p>
      </div>

      {!apiKey && (
        <button
          onClick={onOpenSettings}
          className="max-w-md w-full p-4 bg-amber-500/10 border border-amber-500/20 rounded-2xl flex items-center gap-3 text-left hover:bg-amber-500/15 transition-all"
        >
          <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center shrink-0">
            <Key size={20} className="text-amber-400" />
          </div>
          <div>
            <p className="text-sm font-semibold text-amber-400">API Key Required</p>
            <p className="text-xs text-zinc-400 mt-0.5">
              Set your Gemini API key in Settings to start.
            </p>
          </div>
        </button>
      )}

      {!hfTokenSet && (
        <button
          onClick={onOpenSettings}
          className="max-w-md w-full p-3 bg-blue-500/10 border border-blue-500/20 rounded-2xl flex items-center gap-3 text-left hover:bg-blue-500/15 transition-all"
        >
          <div className="w-9 h-9 rounded-xl bg-blue-500/20 flex items-center justify-center shrink-0">
            <AlertCircle size={18} className="text-blue-400" />
          </div>
          <div>
            <p className="text-xs font-semibold text-blue-400">Hugging Face Token Not Set</p>
            <p className="text-[11px] text-zinc-400 mt-0.5">
              Add a HF token in Settings for faster Whisper model downloads.
            </p>
          </div>
        </button>
      )}

      <div className="max-w-xl w-full">
        <MediaInput
          onProcess={onProcess}
          onBatchProcess={onBatchProcess}
          isProcessing={isProcessing}
          cookiesConfigured={cookiesConfigured}
        />
      </div>

      <div className="flex items-center justify-center gap-8 pt-2">
        <div className="flex items-center gap-2 text-zinc-600 hover:text-white transition-all duration-300">
          <Youtube size={18} />
          <span className="text-xs font-medium">YouTube</span>
        </div>
        <div className="flex items-center gap-2 text-zinc-600 hover:text-white transition-all duration-300">
          <Instagram size={18} />
          <span className="text-xs font-medium">Instagram</span>
        </div>
        <div className="flex items-center gap-2 text-zinc-600 hover:text-white transition-all duration-300">
          <TikTokIcon size={18} />
          <span className="text-xs font-medium">TikTok</span>
        </div>
      </div>
    </div>
  );
}
