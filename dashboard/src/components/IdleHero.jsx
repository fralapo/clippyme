import React, { useState } from 'react';
import { AlertCircle, Cookie, Instagram, Key, X, Youtube } from 'lucide-react';
import MediaInput from './MediaInput';

const TikTokIcon = ({ size = 16, className = '' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

/**
 * Editorial notice banner used for setup warnings above the create box.
 * Three tones matching the system's semantic oklch colors.
 *
 * @param {{
 *   tone: 'critical' | 'warning' | 'info',
 *   icon: React.ComponentType<{ size?: number, strokeWidth?: number, className?: string }>,
 *   label: string,
 *   title: string,
 *   description: string,
 *   onClick?: () => void,
 *   onDismiss?: () => void,
 * }} props
 */
function NoticeBanner({ tone, icon: Icon, label, title, description, onClick, onDismiss }) {
  const palette = {
    critical: {
      accent: 'oklch(70% 0.2 25)',
      accentBg: 'oklch(62% 0.22 25 / 0.08)',
      accentBorder: 'oklch(62% 0.22 25 / 0.35)',
      accentText: 'oklch(78% 0.2 25)',
      iconBg: 'oklch(62% 0.22 25 / 0.12)',
    },
    warning: {
      accent: 'oklch(74% 0.175 62)',
      accentBg: 'oklch(74% 0.175 62 / 0.06)',
      accentBorder: 'oklch(74% 0.175 62 / 0.35)',
      accentText: 'oklch(82% 0.16 68)',
      iconBg: 'oklch(74% 0.175 62 / 0.1)',
    },
    info: {
      accent: 'oklch(68% 0.1 230)',
      accentBg: 'oklch(68% 0.1 230 / 0.05)',
      accentBorder: 'oklch(68% 0.1 230 / 0.3)',
      accentText: 'oklch(78% 0.1 230)',
      iconBg: 'oklch(68% 0.1 230 / 0.1)',
    },
  }[tone];

  const body = (
    <div className="flex items-start gap-3 text-left">
      <div
        className="w-10 h-10 rounded-[3px] flex items-center justify-center shrink-0 border"
        style={{ backgroundColor: palette.iconBg, borderColor: palette.accentBorder }}
      >
        <Icon size={18} strokeWidth={1.6} style={{ color: palette.accentText }} />
      </div>
      <div className="flex-1 min-w-0 pt-0.5">
        <div className="flex items-center gap-2 mb-0.5">
          <span
            className="font-mono text-[9px] uppercase tracking-[0.16em] px-1.5 py-0.5 rounded-[2px]"
            style={{
              color: palette.accentText,
              backgroundColor: palette.accentBg,
              border: `1px solid ${palette.accentBorder}`,
            }}
          >
            {label}
          </span>
        </div>
        <p className="text-[13px] font-medium text-white leading-snug">{title}</p>
        <p className="text-[11px] text-zinc-500 mt-0.5 leading-relaxed">{description}</p>
      </div>
    </div>
  );

  const baseClass = `relative w-full p-4 rounded-[3px] border transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-background`;
  const baseStyle = {
    backgroundColor: palette.accentBg,
    borderColor: palette.accentBorder,
  };

  return (
    <div className="relative w-full">
      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          className={`${baseClass} w-full hover:brightness-110`}
          style={baseStyle}
        >
          {body}
        </button>
      ) : (
        <div className={baseClass} style={baseStyle}>
          {body}
        </div>
      )}
      {onDismiss && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDismiss();
          }}
          aria-label="Dismiss"
          className="absolute top-2 right-2 w-7 h-7 flex items-center justify-center rounded-[2px] text-zinc-500 hover:text-white hover:bg-white/10 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/30"
        >
          <X size={12} strokeWidth={2} />
        </button>
      )}
    </div>
  );
}

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

      <div className="max-w-xl w-full">
        <MediaInput
          onProcess={onProcess}
          onBatchProcess={onBatchProcess}
          isProcessing={isProcessing}
          cookiesConfigured={cookiesConfigured}
        />
      </div>

      {/* Setup notices — rendered below the create card so they don't
          push the main workflow down the fold. Critical items still
          visible, optional ones are dismissible. */}
      {(!apiKey || (!hfTokenSet && !dismissedWarnings.hf) || (apiKey && !cookiesConfigured && !dismissedWarnings.cookies)) && (
        <div className="w-full max-w-xl flex flex-col gap-3 pt-2">
          <div className="flex items-center gap-3 type-label">
            <span className="text-zinc-600">Setup</span>
            <hr className="hairline flex-1" />
          </div>
          {!apiKey && (
            <NoticeBanner
              tone="critical"
              icon={Key}
              label="Required"
              title="Gemini API key required"
              description="Set your Gemini API key in Settings to start processing videos."
              onClick={onOpenSettings}
            />
          )}
          {apiKey && !cookiesConfigured && !dismissedWarnings.cookies && (
            <NoticeBanner
              tone="warning"
              icon={Cookie}
              label="Recommended"
              title="YouTube cookies not configured"
              description="Recommended. Avoids rate limits and age-gate failures on YouTube downloads."
              onClick={onOpenSettings}
              onDismiss={() => dismiss('cookies')}
            />
          )}
          {!hfTokenSet && !dismissedWarnings.hf && (
            <NoticeBanner
              tone="info"
              icon={AlertCircle}
              label="Optional"
              title="Hugging Face token not set"
              description="Optional. Speeds up Whisper model downloads and removes rate limits."
              onClick={onOpenSettings}
              onDismiss={() => dismiss('hf')}
            />
          )}
        </div>
      )}

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
