import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Sparkles, Loader2 } from 'lucide-react';

export default function HookModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl, initialText }) {
    const [text, setText] = useState(initialText || '');
    const [position, setPosition] = useState('top');
    const [size, setSize] = useState('S');
    const [offsetY, setOffsetY] = useState(0);

    if (!isOpen) return null;

    const getPositionClass = () => {
        switch (position) {
            case 'center': return 'justify-center';
            case 'bottom': return 'justify-end pb-[20%]';
            default: return 'justify-start pt-[20%]';
        }
    };

    const getSizeStyle = () => {
        switch (size) {
            case 'S': return { fontSize: '12px', maxWidth: '80%' };
            case 'L': return { fontSize: '22px', maxWidth: '95%' };
            default: return { fontSize: '16px', maxWidth: '90%' };
        }
    };

    return createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in" onClick={onClose}>
            <div
                className="bg-[#0f0f13] border border-white/10 rounded-2xl w-full max-w-4xl shadow-elevated relative flex flex-col md:flex-row overflow-hidden max-h-[90vh]"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Close button */}
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 z-30 p-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
                >
                    <X size={18} className="text-zinc-400" />
                </button>

                {/* Left column: Controls */}
                <div className="flex-1 flex flex-col overflow-hidden border-r border-white/10 md:max-w-[380px]">
                    <div className="px-6 pt-6 pb-4">
                        <h3 className="text-lg font-display font-bold text-white">Viral Hook</h3>
                        <p className="text-xs text-zinc-500 mt-0.5">Add a scroll-stopping text overlay</p>
                    </div>

                    <div className="flex-1 overflow-y-auto px-6 pb-6 space-y-6">
                        {/* Text input */}
                        <div className="space-y-2">
                            <label className="text-xs font-medium text-zinc-400 flex items-center gap-1.5">
                                <Sparkles size={13} className="text-warning" /> Hook Text
                            </label>
                            <textarea
                                value={text}
                                onChange={(e) => setText(e.target.value)}
                                rows={3}
                                className="w-full bg-[#0f0f13] border border-white/10 rounded-lg px-4 py-3 text-white text-sm focus:outline-none focus:border-accent-pink/50 resize-none placeholder:text-zinc-600"
                                placeholder="POV: You just discovered..."
                            />
                        </div>

                        {/* Position */}
                        <div className="space-y-2">
                            <label className="text-xs font-medium text-zinc-400">Position</label>
                            <div className="flex gap-2">
                                {['top', 'center', 'bottom'].map((pos) => (
                                    <button
                                        key={pos}
                                        onClick={() => setPosition(pos)}
                                        className={`flex-1 py-2 rounded-lg border text-xs font-medium capitalize transition-all ${
                                            position === pos
                                                ? 'bg-white/[0.06] border-accent-pink/40 text-white'
                                                : 'bg-white/[0.02] border-white/[0.06] text-zinc-500 hover:border-white/10'
                                        }`}
                                    >
                                        {pos}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Vertical Offset */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-xs font-medium text-zinc-400">Vertical Offset</label>
                                <span className="text-xs text-zinc-500">{offsetY}%</span>
                            </div>
                            <input
                                type="range"
                                min="-50"
                                max="50"
                                value={offsetY}
                                onChange={(e) => setOffsetY(Number(e.target.value))}
                                className="w-full h-1 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-pink"
                            />
                        </div>

                        {/* Size */}
                        <div className="space-y-2">
                            <label className="text-xs font-medium text-zinc-400">Text Size</label>
                            <div className="flex gap-2">
                                {[
                                    { id: 'S', label: 'Small' },
                                    { id: 'M', label: 'Medium' },
                                    { id: 'L', label: 'Large' },
                                ].map((sz) => (
                                    <button
                                        key={sz.id}
                                        onClick={() => setSize(sz.id)}
                                        className={`flex-1 py-2 rounded-lg border text-xs font-medium transition-all ${
                                            size === sz.id
                                                ? 'bg-white/[0.06] border-accent-pink/40 text-white'
                                                : 'bg-white/[0.02] border-white/[0.06] text-zinc-500 hover:border-white/10'
                                        }`}
                                    >
                                        {sz.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Tip */}
                        <div className="p-3 bg-white/[0.02] rounded-xl border border-white/[0.06] text-[11px] text-zinc-500 leading-relaxed">
                            <span className="text-zinc-400 font-medium">Tip:</span> Keep it short and punchy. "POV:", "Did you know?", or questions work best for scroll-stopping retention.
                        </div>
                    </div>

                    {/* Apply button */}
                    <div className="px-6 py-4 border-t border-white/10">
                        <button
                            onClick={() => onGenerate({ text, position, size, offset_y: offsetY })}
                            disabled={isProcessing || !text.trim()}
                            className="w-full py-3 rounded-xl font-semibold text-sm text-white transition-all active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                            style={{ background: 'linear-gradient(135deg, #e6428d, #9850c3)' }}
                        >
                            {isProcessing ? (
                                <>
                                    <Loader2 size={16} className="animate-spin" />
                                    Rendering...
                                </>
                            ) : (
                                <>
                                    <Sparkles size={16} />
                                    Add Hook
                                </>
                            )}
                        </button>
                    </div>
                </div>

                {/* Right column: Preview */}
                <div className="flex-1 bg-black relative flex items-center justify-center min-h-[350px]">
                    <video src={videoUrl} className="w-full h-full object-contain opacity-30 grayscale" muted playsInline />

                    <div className={`absolute inset-0 flex flex-col items-center p-8 pointer-events-none ${getPositionClass()}`}>
                        <div
                            className="text-black font-bold rounded-2xl text-center whitespace-pre-wrap transition-all duration-300"
                            style={{
                                ...getSizeStyle(),
                                backgroundColor: 'rgba(255, 255, 255, 0.92)',
                                fontFamily: 'Noto Serif, Georgia, serif',
                                padding: '12px 20px',
                                boxShadow: '0 8px 30px rgba(0,0,0,0.4)',
                                transform: `translateY(${offsetY}%)`,
                            }}
                        >
                            {text || 'Enter your hook text...'}
                        </div>
                    </div>

                    <div className="absolute top-4 left-4 flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse" />
                        <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">Preview</span>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
}
