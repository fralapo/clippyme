import React from 'react';
import { Key } from 'lucide-react';

/**
 * "API Key Required" onboarding modal shown when the user tries to submit a
 * job without a Gemini API key configured.
 *
 * @param {{ onClose: () => void, onGoToSettings: () => void }} props
 */
export default function ApiKeyModal({ onClose, onGoToSettings }) {
  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-md animate-fade-in"
      onClick={onClose}
    >
      <div
        className="rounded-2xl bg-[#16161d] border border-white/10 max-w-md w-full mx-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-8 space-y-6">
          <div className="w-14 h-14 rounded-2xl bg-amber-500/10 text-amber-400 flex items-center justify-center mx-auto">
            <Key size={28} />
          </div>
          <div className="text-center space-y-2">
            <h2 className="text-2xl font-bold text-white">API Key Required</h2>
            <p className="text-sm text-zinc-500">
              You need a Google Gemini API key to use the clip engine.
            </p>
          </div>
          <div className="bg-[#0f0f13] border border-white/5 rounded-xl p-5 space-y-4">
            <p className="text-xs font-medium text-zinc-500">Quick Setup:</p>
            <ol className="text-sm text-zinc-400 space-y-3">
              <li className="flex items-center gap-3">
                <span className="w-6 h-6 rounded-lg bg-white/5 flex items-center justify-center text-xs font-semibold text-blue-400 border border-white/5 shrink-0">
                  1
                </span>
                Visit{' '}
                <a
                  href="https://aistudio.google.com/app/apikey"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-400 hover:underline font-medium"
                >
                  Google AI Studio
                </a>
              </li>
              <li className="flex items-center gap-3">
                <span className="w-6 h-6 rounded-lg bg-white/5 flex items-center justify-center text-xs font-semibold text-blue-400 border border-white/5 shrink-0">
                  2
                </span>
                Sign in and generate a free API key
              </li>
              <li className="flex items-center gap-3">
                <span className="w-6 h-6 rounded-lg bg-white/5 flex items-center justify-center text-xs font-semibold text-blue-400 border border-white/5 shrink-0">
                  3
                </span>
                Configure it in Settings
              </li>
            </ol>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              onClick={onClose}
              className="flex-1 px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-sm font-medium text-zinc-300 hover:bg-white/10 transition-all"
            >
              Dismiss
            </button>
            <button
              onClick={onGoToSettings}
              className="flex-1 px-4 py-3 rounded-xl bg-gradient-to-r from-pink-500 to-purple-500 text-sm font-semibold text-white hover:opacity-90 transition-all"
            >
              Go to Settings
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
