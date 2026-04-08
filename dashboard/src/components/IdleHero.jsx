import React, { useState } from 'react';
import { AlertCircle, Cookie, Instagram, Key, X, Youtube } from 'lucide-react';
import MediaInput from './MediaInput';

const TikTokIcon = ({ size = 16, className = '' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

/**
 * Idle state of the Dashboard tab: hero headline, credential
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
  const [dismissedWarnings, setDismissedWarnings] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('clippyme_dismissed_warnings') || '{}');
    } catch {
      return {};
    }
  });

  const dismiss = (key) => {
    const next = { ...dismissedWarnings, [key]: true };
    setDismissedWarnings(next);
    try {
      localStorage.setItem('clippyme_dismissed_warnings', JSON.stringify(next));
    } catch {
      /* quota */
    }
  };

  return (
    <div className="flex flex-col items-center text-center pt-6 sm:pt-14 w-full space-y-6">
      {/* Masthead */}
      <div className="w-full max-w-3xl space-y-5 mb-10">
        <div className="flex items-center gap-3 justify-center type-label">
          <span aria-hidden className="inline-block w-6 h-px bg-[oklch(74%_0.175_62)]" />
          <span>AI&nbsp;viral&nbsp;clip&nbsp;generator</span>
          <span aria-hidden className="inline-block w-6 h-px bg-[oklch(74%_0.175_62)]" />
        </div>
        <h1 className="type-display text-[clamp(3rem,9vw,6.5rem)] text-white leading-[0.92] relative">
          <span className="block">Long videos</span>
          <span className="block italic text-[oklch(74%_0.175_62)] relative">
            into shorts.
            <span
              aria-hidden
              className="absolute left-1/2 -translate-x-1/2 -bottom-2 w-[55%] h-px bg-[oklch(74%_0.175_62)]/50"
            />
          </span>
        </h1>
        <p className="type-label !normal-case !tracking-[0.02em] !text-zinc-400 !text-[14px] !font-sans max-w-md mx-auto leading-relaxed">
          Paste a YouTube URL or drop a file. ClippyMe finds the viral moments,
          reframes them 9:16, and burns subtitles — automatically.
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

      {!hfTokenSet && !dismissedWarnings.hf && (
        <div className="max-w-md w-full p-3 bg-blue-500/10 border border-blue-500/20 rounded-2xl flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-500/20 flex items-center justify-center shrink-0">
            <AlertCircle size={18} className="text-blue-400" />
          </div>
          <button
            type="button"
            onClick={onOpenSettings}
            className="flex-1 text-left hover:opacity-80 transition-opacity"
          >
            <p className="text-xs font-semibold text-blue-400">Hugging Face Token Not Set</p>
            <p className="text-[11px] text-zinc-400 mt-0.5">
              Optional. Speeds up Whisper model downloads.
            </p>
          </button>
          <button
            type="button"
            onClick={() => dismiss('hf')}
            aria-label="Dismiss"
            className="p-1.5 rounded-lg text-zinc-500 hover:text-white hover:bg-white/5 transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {apiKey && !cookiesConfigured && !dismissedWarnings.cookies && (
        <div className="max-w-md w-full p-3 bg-amber-500/10 border border-amber-500/20 rounded-2xl flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-amber-500/20 flex items-center justify-center shrink-0">
            <Cookie size={18} className="text-amber-400" />
          </div>
          <button
            type="button"
            onClick={onOpenSettings}
            className="flex-1 text-left hover:opacity-80 transition-opacity"
          >
            <p className="text-xs font-semibold text-amber-400">YouTube Cookies Not Configured</p>
            <p className="text-[11px] text-zinc-400 mt-0.5">
              Recommended. Avoids rate limits on YouTube downloads.
            </p>
          </button>
          <button
            type="button"
            onClick={() => dismiss('cookies')}
            aria-label="Dismiss"
            className="p-1.5 rounded-lg text-zinc-500 hover:text-white hover:bg-white/5 transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <div className="max-w-xl w-full">
        <MediaInput
          onProcess={onProcess}
          onBatchProcess={onBatchProcess}
          isProcessing={isProcessing}
          cookiesConfigured={cookiesConfigured}
        />
      </div>

      <div className="flex items-center justify-center gap-5 pt-4 type-label">
        <span className="text-zinc-600">Ships&nbsp;to</span>
        <div className="flex items-center gap-1.5 text-zinc-500 hover:text-[oklch(74%_0.175_62)] transition-colors duration-300">
          <Youtube size={14} strokeWidth={1.6} />
          <span>YouTube</span>
        </div>
        <span aria-hidden className="w-3 h-px bg-white/10" />
        <div className="flex items-center gap-1.5 text-zinc-500 hover:text-[oklch(74%_0.175_62)] transition-colors duration-300">
          <Instagram size={14} strokeWidth={1.6} />
          <span>Instagram</span>
        </div>
        <span aria-hidden className="w-3 h-px bg-white/10" />
        <div className="flex items-center gap-1.5 text-zinc-500 hover:text-[oklch(74%_0.175_62)] transition-colors duration-300">
          <TikTokIcon size={13} />
          <span>TikTok</span>
        </div>
      </div>
    </div>
  );
}
