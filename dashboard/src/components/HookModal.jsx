import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Sparkles, Loader2, Maximize, MoveVertical } from 'lucide-react';

export default function HookModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl, initialText }) {
    const [text, setText] = useState(initialText || '');
    const [position, setPosition] = useState('top');
    const [size, setSize] = useState('M');

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
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-md animate-fade-in" onClick={onClose}>
            <div className="glass-panel p-1 w-full max-w-5xl shadow-2xl relative flex flex-col md:flex-row gap-0 overflow-hidden max-h-[90vh]" onClick={(e) => e.stopPropagation()}>
                {/* Left: Preview */}
                <div className="flex-1 bg-black relative flex items-center justify-center min-h-[400px]">
                    <video src={videoUrl} className="w-full h-full object-contain opacity-40 grayscale" muted playsInline />

                    <div className={`absolute inset-0 flex flex-col items-center p-8 pointer-events-none ${getPositionClass()}`}>
                        <div
                            className="text-black font-bold rounded-2xl shadow-2xl text-center whitespace-pre-wrap transition-all duration-300"
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

                    <div className="absolute top-6 left-6 flex items-center gap-3">
                        <div className="w-2 h-2 rounded-full bg-warning animate-pulse" />
                        <span className="text-[10px] font-black text-white uppercase tracking-[0.3em]">Live_Preview</span>
                    </div>
                </div>

                {/* Right: Controls */}
                <div className="w-full md:w-[380px] bg-surface-darker/80 backdrop-blur-xl border-l border-white/5 flex flex-col overflow-hidden">
                    <div className="p-8 border-b border-white/5 flex items-center justify-between">
                        <div>
                            <h3 className="text-xl font-black text-white uppercase tracking-tighter italic">Viral Hook</h3>
                            <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mt-1">Text Overlay Engine</p>
                        </div>
                        <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-xl transition-all">
                            <X size={20} className="text-zinc-500 hover:text-white" />
                        </button>
                    </div>

                    <div className="flex-1 overflow-y-auto custom-scrollbar p-8 space-y-8">
                        {/* Text Input */}
                        <div className="space-y-3">
                            <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                <Sparkles size={14} className="text-warning" /> Hook Text
                            </label>
                            <textarea
                                value={text}
                                onChange={(e) => setText(e.target.value)}
                                rows={3}
                                className="input-field !bg-black/40 !border-white/5 focus:!border-warning/30 resize-none font-serif"
                                placeholder="POV: You just discovered..."
                            />
                        </div>

                        {/* Position */}
                        <div className="space-y-4">
                            <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                <MoveVertical size={14} /> Position
                            </label>
                            <div className="grid grid-cols-3 gap-3">
                                {['top', 'center', 'bottom'].map((pos) => (
                                    <button
                                        key={pos}
                                        onClick={() => setPosition(pos)}
                                        className={`flex flex-col items-center gap-1 p-3 rounded-2xl border transition-all duration-300 ${position === pos ? 'bg-warning border-warning text-black shadow-lg shadow-warning/10' : 'bg-white/[0.02] border-white/5 text-zinc-500 hover:bg-white/5'}`}
                                    >
                                        <span className="text-[9px] font-black uppercase tracking-widest">{pos}</span>
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Size */}
                        <div className="space-y-4">
                            <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                <Maximize size={14} /> Text Size
                            </label>
                            <div className="grid grid-cols-3 gap-3">
                                {[
                                    { id: 'S', label: 'Small' },
                                    { id: 'M', label: 'Medium' },
                                    { id: 'L', label: 'Large' },
                                ].map((sz) => (
                                    <button
                                        key={sz.id}
                                        onClick={() => setSize(sz.id)}
                                        className={`flex flex-col items-center gap-1 p-3 rounded-2xl border transition-all duration-300 ${size === sz.id ? 'bg-warning border-warning text-black shadow-lg shadow-warning/10' : 'bg-white/[0.02] border-white/5 text-zinc-500 hover:bg-white/5'}`}
                                    >
                                        <span className="text-[9px] font-black uppercase tracking-widest">{sz.label}</span>
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="p-4 bg-white/[0.02] rounded-2xl border border-white/5 text-[10px] text-zinc-500">
                            <strong className="text-zinc-400">Tip:</strong> Keep it short and punchy. "POV:", "Did you know?", or questions work best for scroll-stopping retention.
                        </div>
                    </div>

                    <div className="p-8 bg-black/20 border-t border-white/5">
                        <button
                            onClick={() => onGenerate({ text, position, size })}
                            disabled={isProcessing || !text.trim()}
                            className="w-full py-5 bg-warning hover:bg-warning/90 text-black rounded-xl font-black uppercase tracking-[0.2em] italic shadow-lg shadow-warning/10 transition-all active:scale-[0.98] flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isProcessing ? <Loader2 size={20} className="animate-spin" /> : <Sparkles size={20} />}
                            {isProcessing ? 'Rendering...' : 'Add Hook'}
                        </button>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
}
