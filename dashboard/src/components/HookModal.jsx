import React, { useState, useEffect, useRef, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Sparkles, Loader2 } from 'lucide-react';
import { scaleFontToPreview } from '@/lib/subtitlePresets';

export default function HookModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl, initialText, initialValues }) {
    const iv = initialValues || {};
    const [text, setText] = useState(iv.text || initialText || '');
    const [size, setSize] = useState(iv.size || 'S');
    // Single vertical slider -50 (top) → +50 (bottom).
    const [offsetY, setOffsetY] = useState(iv.offset_y ?? -35);
    const position = 'center';

    // Re-seed state when the modal opens so subsequent opens reflect the
    // parent's latest hookParams (including pre-selection defaults).
    useEffect(() => {
        if (!isOpen) return;
        const v = initialValues || {};
        setText(v.text || initialText || '');
        setSize(v.size || 'S');
        setOffsetY(v.offset_y ?? -35);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen]);

    // Preview video ref — used to scale the hook font faithfully to the
    // backend `hooks.py:add_hook_to_video` math (font = video_width * 0.9 *
    // 0.05 * font_scale). We scale using the rendered video height so the
    // preview matches the final burned-in overlay.
    const previewVideoRef = useRef(null);
    const [renderedVideoHeight, setRenderedVideoHeight] = useState(0);
    useLayoutEffect(() => {
        if (!isOpen) return undefined;
        const update = () => {
            const el = previewVideoRef.current;
            if (!el) return;
            setRenderedVideoHeight(el.clientHeight || 0);
        };
        update();
        const ro = new ResizeObserver(update);
        if (previewVideoRef.current) ro.observe(previewVideoRef.current);
        window.addEventListener('resize', update);
        return () => {
            ro.disconnect();
            window.removeEventListener('resize', update);
        };
    }, [isOpen]);

    if (!isOpen) return null;

    // Backend math for 9:16 @ 1080x1920:
    //   target_box_width = 1080 * 0.9 = 972
    //   base_font_size   = 972 * 0.05 = 48.6
    //   S=0.8 → 38.88, M=1.0 → 48.6, L=1.3 → 63.18
    // These are pixel heights at the 1920 px reference → scale via
    // scaleFontToPreview(backendSize, renderedHeight).
    const HOOK_BACKEND_SIZES = { S: 38.88, M: 48.6, L: 63.18 };
    const backendFontSize = HOOK_BACKEND_SIZES[size] || HOOK_BACKEND_SIZES.M;
    const previewFontSize = scaleFontToPreview(backendFontSize, renderedVideoHeight);

    const getSizeStyle = () => ({
        fontSize: `${previewFontSize}px`,
        maxWidth: '90%',
    });

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

                        {/* Vertical Position (single slider) */}
                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <label className="text-xs font-medium text-zinc-400">Vertical Position</label>
                                <span className="text-xs text-zinc-500">
                                    {offsetY < -15 ? 'Top' : offsetY > 15 ? 'Bottom' : 'Center'}
                                </span>
                            </div>
                            <input
                                type="range"
                                min="-50"
                                max="50"
                                value={offsetY}
                                onChange={(e) => setOffsetY(Number(e.target.value))}
                                className="w-full h-1 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-pink"
                            />
                            <div className="flex justify-between text-[9px] text-zinc-600">
                                <span>Top</span>
                                <span>Center</span>
                                <span>Bottom</span>
                            </div>
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
                                    Apply Hook
                                </>
                            )}
                        </button>
                    </div>
                </div>

                {/* Right column: Preview */}
                <div className="flex-1 bg-black relative flex items-center justify-center min-h-[350px]">
                    <video
                        ref={previewVideoRef}
                        src={videoUrl}
                        className="w-full h-full object-contain opacity-30 grayscale"
                        muted
                        playsInline
                    />

                    <div className="absolute inset-0 pointer-events-none">
                        <div
                            className="absolute left-0 right-0 flex justify-center px-8 transition-all duration-200"
                            style={{ top: `${50 + offsetY}%`, transform: 'translateY(-50%)' }}
                        >
                            <div
                                className="text-black font-bold rounded-2xl text-center whitespace-pre-wrap"
                                style={{
                                    ...getSizeStyle(),
                                    backgroundColor: 'rgba(255, 255, 255, 0.92)',
                                    fontFamily: 'Noto Serif, Georgia, serif',
                                    padding: '12px 20px',
                                    boxShadow: '0 8px 30px rgba(0,0,0,0.4)',
                                }}
                            >
                                {text || 'Enter your hook text...'}
                            </div>
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
