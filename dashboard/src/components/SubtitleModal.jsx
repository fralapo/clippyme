import React, { useState } from 'react';
import { X, Type, Loader2, AlignCenter, AlignVerticalJustifyStart, AlignVerticalJustifyEnd, Palette, Type as TypeIcon, Layers } from 'lucide-react';

const FONT_OPTIONS = [
    { value: 'Verdana', label: 'Verdana' },
    { value: 'Arial', label: 'Arial' },
    { value: 'Impact', label: 'Impact' },
    { value: 'Helvetica', label: 'Helvetica' },
    { value: 'Georgia', label: 'Georgia' },
    { value: 'Courier New', label: 'Courier New' },
];

const COLOR_PRESETS = [
    { color: '#FFFFFF', label: 'White' },
    { color: '#FFFF00', label: 'Yellow' },
    { color: '#00FFFF', label: 'Cyan' },
    { color: '#00FF00', label: 'Green' },
    { color: '#FF0000', label: 'Red' },
    { color: '#FF69B4', label: 'Pink' },
];

export default function SubtitleModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl }) {
    const [position, setPosition] = useState('bottom');
    const fontSize = 24;
    const [fontName, setFontName] = useState('Verdana');
    const [fontColor, setFontColor] = useState('#FFFFFF');
    const borderColor = '#000000';
    const [borderWidth, setBorderWidth] = useState(2);
    const bgColor = '#000000';
    const [bgOpacity, setBgOpacity] = useState(0.0);

    if (!isOpen) return null;

    const bw = Math.max(borderWidth, 0);
    const bc = borderColor;
    const outlineShadow = bw > 0 ? [
        `-${bw}px -${bw}px 0 ${bc}`, `${bw}px -${bw}px 0 ${bc}`,
        `-${bw}px ${bw}px 0 ${bc}`, `${bw}px ${bw}px 0 ${bc}`,
        `0 -${bw}px 0 ${bc}`, `0 ${bw}px 0 ${bc}`,
        `-${bw}px 0 0 ${bc}`, `${bw}px 0 0 ${bc}`,
    ].join(', ') : 'none';

    const previewStyle = {
        fontFamily: fontName,
        color: fontColor,
        fontSize: '20px',
        fontWeight: 'bold',
        maxWidth: '85%',
        padding: '8px 16px',
        borderRadius: '8px',
        textAlign: 'center',
        lineHeight: '1.2',
        ...(bgOpacity > 0
            ? {
                backgroundColor: `${bgColor}${Math.round(bgOpacity * 255).toString(16).padStart(2, '0')}`,
                textShadow: 'none',
            }
            : { textShadow: outlineShadow }
        ),
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-md animate-fade-in">
            <div className="glass-panel p-1 w-full max-w-5xl shadow-2xl relative flex flex-col md:flex-row gap-0 overflow-hidden max-h-[90vh]">
                {/* Left: Preview Area */}
                <div className="flex-1 bg-black relative flex items-center justify-center min-h-[400px]">
                     <video src={videoUrl} className="w-full h-full object-contain opacity-40 grayscale" muted playsInline />
                     
                     <div className="absolute inset-0 flex flex-col items-center justify-center p-12">
                        <div className={`w-full flex items-center justify-center transition-all duration-500 
                            ${position === 'top' ? 'mb-auto mt-4' : ''}
                            ${position === 'middle' ? 'my-auto' : ''}
                            ${position === 'bottom' ? 'mt-auto mb-4' : ''}
                        `}>
                            <span style={previewStyle} className="shadow-2xl">
                                AI Generated<br/>Viral Captions
                            </span>
                        </div>
                     </div>

                     <div className="absolute top-6 left-6 flex items-center gap-3">
                        <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                        <span className="text-[10px] font-black text-white uppercase tracking-[0.3em]">Live_Preview_Render</span>
                     </div>
                </div>

                {/* Right: Controls Panel */}
                <div className="w-full md:w-[380px] bg-surface-darker/80 backdrop-blur-xl border-l border-white/5 flex flex-col overflow-hidden">
                    <div className="p-8 border-b border-white/5 flex items-center justify-between">
                        <div>
                            <h3 className="text-xl font-black text-white uppercase tracking-tighter italic">Typography</h3>
                            <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mt-1">Subtitle Engine v2</p>
                        </div>
                        <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-xl transition-all">
                            <X size={20} className="text-zinc-500 hover:text-white" />
                        </button>
                    </div>

                    <div className="flex-1 overflow-y-auto custom-scrollbar p-8 space-y-10">
                        {/* Position */}
                        <div className="space-y-4">
                            <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                <AlignCenter size={14} /> Anchor Position
                            </label>
                            <div className="grid grid-cols-3 gap-3">
                                {[
                                    { id: 'top', icon: AlignVerticalJustifyStart },
                                    { id: 'middle', icon: AlignCenter },
                                    { id: 'bottom', icon: AlignVerticalJustifyEnd }
                                ].map((pos) => (
                                    <button
                                        key={pos.id}
                                        onClick={() => setPosition(pos.id)}
                                        className={`flex flex-col items-center gap-2 p-4 rounded-2xl border transition-all duration-300 ${position === pos.id ? 'bg-primary border-primary text-white shadow-glow-primary' : 'bg-white/[0.02] border-white/5 text-zinc-500 hover:bg-white/5'}`}
                                    >
                                        <pos.icon size={18} />
                                        <span className="text-[9px] font-black uppercase tracking-widest">{pos.id}</span>
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Font Selection */}
                        <div className="space-y-4">
                            <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                <TypeIcon size={14} /> Font Family
                            </label>
                            <div className="grid grid-cols-1 gap-2">
                                <select
                                    value={fontName}
                                    onChange={(e) => setFontName(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-primary/50 appearance-none cursor-pointer"
                                >
                                    {FONT_OPTIONS.map((f) => (
                                        <option key={f.value} value={f.value} className="bg-zinc-900">{f.label}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        {/* Visual Style */}
                        <div className="space-y-6">
                            <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                <Palette size={14} /> Color & Border
                            </label>
                            
                            <div className="flex flex-wrap gap-3">
                                {COLOR_PRESETS.map((c) => (
                                    <button
                                        key={c.color}
                                        onClick={() => setFontColor(c.color)}
                                        className={`w-8 h-8 rounded-full border-2 transition-all duration-300 ${fontColor === c.color ? 'border-white scale-110 shadow-lg' : 'border-transparent hover:border-white/20'}`}
                                        style={{ backgroundColor: c.color }}
                                    />
                                ))}
                                <label className="w-8 h-8 rounded-full border-2 border-dashed border-white/20 cursor-pointer flex items-center justify-center hover:border-white/50 transition-all relative">
                                    <span className="text-xs text-zinc-500 font-black">+</span>
                                    <input type="color" value={fontColor} onChange={(e) => setFontColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                </label>
                            </div>

                            <div className="space-y-3">
                                <div className="flex justify-between items-center">
                                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Outline Weight</span>
                                    <span className="text-[10px] font-mono text-primary">{borderWidth}px</span>
                                </div>
                                <input
                                    type="range" min="0" max="5" step="1"
                                    value={borderWidth}
                                    onChange={(e) => setBorderWidth(parseInt(e.target.value))}
                                    className="w-full accent-primary h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer"
                                />
                            </div>
                        </div>

                        {/* Background Container */}
                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                    <Layers size={14} /> Background Box
                                </label>
                                <button 
                                    onClick={() => setBgOpacity(bgOpacity > 0 ? 0 : 0.6)}
                                    className={`w-10 h-5 rounded-full transition-all duration-500 relative p-1 ${bgOpacity > 0 ? 'bg-primary' : 'bg-zinc-800'}`}
                                >
                                    <div className={`w-3 h-3 rounded-full bg-white transition-all duration-500 ${bgOpacity > 0 ? 'translate-x-5' : 'translate-x-0'}`} />
                                </button>
                            </div>
                            
                            {bgOpacity > 0 && (
                                <div className="p-4 rounded-2xl bg-white/[0.02] border border-white/5 space-y-4 animate-fade-in">
                                    <div className="space-y-3">
                                        <div className="flex justify-between items-center">
                                            <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Opacity</span>
                                            <span className="text-[10px] font-mono text-primary">{Math.round(bgOpacity * 100)}%</span>
                                        </div>
                                        <input
                                            type="range" min="10" max="100" step="10"
                                            value={Math.round(bgOpacity * 100)}
                                            onChange={(e) => setBgOpacity(parseInt(e.target.value) / 100)}
                                            className="w-full accent-primary h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer"
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="p-8 bg-black/20 border-t border-white/5">
                        <button
                            onClick={() => onGenerate({ position, fontSize, fontName, fontColor, borderColor, borderWidth, bgColor, bgOpacity })}
                            disabled={isProcessing}
                            className="w-full btn-primary-glow !py-5 font-black uppercase tracking-[0.2em] italic"
                        >
                            {isProcessing ? (
                                <>
                                    <Loader2 size={20} className="animate-spin" />
                                    <span>Rendering...</span>
                                </>
                            ) : (
                                <>
                                    <span>Sync Subtitles</span>
                                </>
                            )}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
