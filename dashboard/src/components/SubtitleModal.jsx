import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Type, Loader2, AlignCenter, AlignVerticalJustifyStart, AlignVerticalJustifyEnd, Palette, Type as TypeIcon, Layers, Sparkles, Zap } from 'lucide-react';

const VIRAL_PRESETS = [
    { id: 'classic_white', label: 'Classic White', desc: 'TikTok standard', colors: ['#FFFFFF', '#FFFF00'] },
    { id: 'hormozi_bold', label: 'Hormozi Bold', desc: 'Motivational', colors: ['#FFFFFF', '#00FF00'] },
    { id: 'neon_glow', label: 'Neon Glow', desc: 'Gaming/Tech', colors: ['#FFFFFF', '#00FFFF'] },
    { id: 'mrbeast_box', label: 'MrBeast Box', desc: 'Box style', colors: ['#FFFFFF', '#FFFF00'] },
    { id: 'minimal_clean', label: 'Minimal', desc: 'Elegant', colors: ['#FFFFFF', '#FFFFFF'] },
    { id: 'fire_impact', label: 'Fire Impact', desc: 'Drama', colors: ['#FFFFFF', '#FF4444'] },
];

const FONT_OPTIONS = [
    { value: 'Montserrat-Black', label: 'Montserrat Black' },
    { value: 'Bangers-Regular', label: 'Bangers' },
    { value: 'Poppins-Black', label: 'Poppins Black' },
    { value: 'Poppins-Medium', label: 'Poppins Medium' },
    { value: 'Anton-Regular', label: 'Anton' },
    { value: 'Verdana', label: 'Verdana (Legacy)' },
];

const HIGHLIGHT_COLORS = [
    { color: '#FFFF00', label: 'Yellow' },
    { color: '#00FF00', label: 'Green' },
    { color: '#00FFFF', label: 'Cyan' },
    { color: '#FF4444', label: 'Red' },
    { color: '#FF69B4', label: 'Pink' },
    { color: '#FFFFFF', label: 'White' },
];

export default function SubtitleModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl }) {
    const [mode, setMode] = useState('viral'); // 'viral' (karaoke presets) | 'classic' (legacy SRT)
    const [position, setPosition] = useState('bottom');

    // Viral mode state
    const [selectedPreset, setSelectedPreset] = useState('classic_white');
    const [karaokeMode, setKaraokeMode] = useState('word_group');
    const [wordsPerGroup, setWordsPerGroup] = useState(3);
    const [uppercase, setUppercase] = useState(true);
    const [highlightColor, setHighlightColor] = useState('#FFFF00');
    const [fontName, setFontName] = useState('Montserrat-Black');

    // Classic mode state
    const fontSize = 24;
    const [classicFontName, setClassicFontName] = useState('Verdana');
    const [fontColor, setFontColor] = useState('#FFFFFF');
    const borderColor = '#000000';
    const [borderWidth, setBorderWidth] = useState(2);
    const bgColor = '#000000';
    const [bgOpacity, setBgOpacity] = useState(0.0);

    if (!isOpen) return null;

    const handleGenerate = () => {
        if (mode === 'viral') {
            onGenerate({
                position,
                fontSize: 16,
                fontName,
                fontColor: '#FFFFFF',
                borderColor: '#000000',
                borderWidth: 4,
                bgColor: '#000000',
                bgOpacity: 0,
                preset: selectedPreset,
                karaoke_mode: karaokeMode,
                words_per_group: wordsPerGroup,
                uppercase,
                highlight_color: highlightColor,
            });
        } else {
            onGenerate({ position, fontSize, fontName: classicFontName, fontColor, borderColor, borderWidth, bgColor, bgOpacity });
        }
    };

    const activePreset = VIRAL_PRESETS.find(p => p.id === selectedPreset);

    // Preview text style
    const previewFont = mode === 'viral' ? fontName.replace('-', ' ').split(' ')[0] : classicFontName;
    const previewHighlight = mode === 'viral' ? highlightColor : fontColor;

    return createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-md animate-fade-in" onClick={onClose}>
            <div className="glass-panel p-1 w-full max-w-5xl shadow-2xl relative flex flex-col md:flex-row gap-0 overflow-hidden max-h-[90vh]" onClick={(e) => e.stopPropagation()}>
                {/* Left: Preview Area */}
                <div className="flex-1 bg-black relative flex items-center justify-center min-h-[400px]">
                     <video src={videoUrl} className="w-full h-full object-contain opacity-40 grayscale" muted playsInline />

                     <div className="absolute inset-0 flex flex-col items-center justify-center p-12">
                        <div className={`w-full flex items-center justify-center transition-all duration-500
                            ${position === 'top' ? 'mb-auto mt-16' : ''}
                            ${position === 'middle' ? 'my-auto' : ''}
                            ${position === 'bottom' ? 'mt-auto mb-16' : ''}
                        `}>
                            {mode === 'viral' ? (
                                <div className="text-center">
                                    <span style={{
                                        fontFamily: previewFont,
                                        color: '#FFFFFF',
                                        fontSize: '22px',
                                        fontWeight: 900,
                                        textShadow: '-3px -3px 0 #000, 3px -3px 0 #000, -3px 3px 0 #000, 3px 3px 0 #000',
                                        textTransform: uppercase ? 'uppercase' : 'none',
                                    }}>
                                        AI GENERATED{' '}
                                        <span style={{ color: previewHighlight }}>VIRAL</span>
                                        {' '}CAPTIONS
                                    </span>
                                </div>
                            ) : (
                                <span style={{
                                    fontFamily: classicFontName,
                                    color: fontColor,
                                    fontSize: '20px',
                                    fontWeight: 'bold',
                                    textShadow: borderWidth > 0 ? `-${borderWidth}px -${borderWidth}px 0 ${borderColor}, ${borderWidth}px ${borderWidth}px 0 ${borderColor}` : 'none',
                                    ...(bgOpacity > 0 ? { backgroundColor: `${bgColor}${Math.round(bgOpacity * 255).toString(16).padStart(2, '0')}`, padding: '8px 16px', borderRadius: '8px' } : {}),
                                }} className="shadow-2xl">
                                    AI Generated<br/>Viral Captions
                                </span>
                            )}
                        </div>
                     </div>

                     <div className="absolute top-6 left-6 flex items-center gap-3">
                        <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                        <span className="text-[10px] font-black text-white uppercase tracking-[0.3em]">Live_Preview</span>
                     </div>
                </div>

                {/* Right: Controls Panel */}
                <div className="w-full md:w-[400px] bg-surface-darker/80 backdrop-blur-xl border-l border-white/5 flex flex-col overflow-hidden">
                    <div className="p-6 border-b border-white/5 flex items-center justify-between">
                        <div>
                            <h3 className="text-xl font-black text-white uppercase tracking-tighter italic">Captions</h3>
                            <p className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mt-1">Subtitle Engine v3</p>
                        </div>
                        <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-xl transition-all">
                            <X size={20} className="text-zinc-500 hover:text-white" />
                        </button>
                    </div>

                    {/* Mode Toggle */}
                    <div className="p-4 border-b border-white/5">
                        <div className="flex bg-black/30 p-1 rounded-xl">
                            <button
                                onClick={() => setMode('viral')}
                                className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${mode === 'viral' ? 'bg-primary text-white shadow-glow-primary' : 'text-zinc-500 hover:text-white'}`}
                            >
                                <Zap size={12} /> Viral Karaoke
                            </button>
                            <button
                                onClick={() => setMode('classic')}
                                className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${mode === 'classic' ? 'bg-primary text-white shadow-glow-primary' : 'text-zinc-500 hover:text-white'}`}
                            >
                                <Type size={12} /> Classic
                            </button>
                        </div>
                    </div>

                    <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-8">
                        {mode === 'viral' ? (
                            <>
                                {/* Preset Grid */}
                                <div className="space-y-3">
                                    <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                        <Sparkles size={12} /> Style Preset
                                    </label>
                                    <div className="grid grid-cols-2 gap-2">
                                        {VIRAL_PRESETS.map((p) => (
                                            <button
                                                key={p.id}
                                                onClick={() => {
                                                    setSelectedPreset(p.id);
                                                    setHighlightColor(p.colors[1]);
                                                }}
                                                className={`p-3 rounded-xl border text-left transition-all ${selectedPreset === p.id ? 'bg-primary/10 border-primary/40 shadow-lg' : 'bg-white/[0.02] border-white/5 hover:border-white/15'}`}
                                            >
                                                <div className="flex items-center gap-2 mb-1">
                                                    <div className="flex gap-0.5">
                                                        {p.colors.map((c, i) => (
                                                            <div key={i} className="w-3 h-3 rounded-full border border-white/20" style={{ backgroundColor: c }} />
                                                        ))}
                                                    </div>
                                                </div>
                                                <p className="text-[10px] font-black text-white uppercase tracking-wider">{p.label}</p>
                                                <p className="text-[9px] text-zinc-500">{p.desc}</p>
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                {/* Karaoke Mode */}
                                <div className="space-y-3">
                                    <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em]">Display Mode</label>
                                    <div className="grid grid-cols-2 gap-2">
                                        <button
                                            onClick={() => setKaraokeMode('word_group')}
                                            className={`p-3 rounded-xl border text-center transition-all ${karaokeMode === 'word_group' ? 'bg-primary/10 border-primary/40' : 'bg-white/[0.02] border-white/5 hover:border-white/15'}`}
                                        >
                                            <p className="text-[10px] font-black text-white uppercase">Word Group</p>
                                            <p className="text-[9px] text-zinc-500">2-3 words at a time</p>
                                        </button>
                                        <button
                                            onClick={() => setKaraokeMode('full_line')}
                                            className={`p-3 rounded-xl border text-center transition-all ${karaokeMode === 'full_line' ? 'bg-primary/10 border-primary/40' : 'bg-white/[0.02] border-white/5 hover:border-white/15'}`}
                                        >
                                            <p className="text-[10px] font-black text-white uppercase">Full Line</p>
                                            <p className="text-[9px] text-zinc-500">Karaoke sweep</p>
                                        </button>
                                    </div>
                                </div>

                                {/* Words Per Group */}
                                {karaokeMode === 'word_group' && (
                                    <div className="space-y-3">
                                        <div className="flex justify-between items-center">
                                            <span className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em]">Words Per Group</span>
                                            <span className="text-[10px] font-mono text-primary">{wordsPerGroup}</span>
                                        </div>
                                        <input
                                            type="range" min="1" max="5" step="1"
                                            value={wordsPerGroup}
                                            onChange={(e) => setWordsPerGroup(parseInt(e.target.value))}
                                            className="w-full accent-primary h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer"
                                        />
                                    </div>
                                )}

                                {/* Highlight Color */}
                                <div className="space-y-3">
                                    <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em]">Highlight Color</label>
                                    <div className="flex flex-wrap gap-2">
                                        {HIGHLIGHT_COLORS.map((c) => (
                                            <button
                                                key={c.color}
                                                onClick={() => setHighlightColor(c.color)}
                                                className={`w-7 h-7 rounded-full border-2 transition-all ${highlightColor === c.color ? 'border-white scale-110 shadow-lg' : 'border-transparent hover:border-white/20'}`}
                                                style={{ backgroundColor: c.color }}
                                            />
                                        ))}
                                        <label className="w-7 h-7 rounded-full border-2 border-dashed border-white/20 cursor-pointer flex items-center justify-center hover:border-white/50 transition-all relative">
                                            <span className="text-[9px] text-zinc-500 font-black">+</span>
                                            <input type="color" value={highlightColor} onChange={(e) => setHighlightColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                        </label>
                                    </div>
                                </div>

                                {/* Font + Uppercase */}
                                <div className="space-y-3">
                                    <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em]">Font</label>
                                    <select
                                        value={fontName}
                                        onChange={(e) => setFontName(e.target.value)}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:border-primary/50 appearance-none cursor-pointer"
                                    >
                                        {FONT_OPTIONS.filter(f => f.value !== 'Verdana').map((f) => (
                                            <option key={f.value} value={f.value} className="bg-zinc-900">{f.label}</option>
                                        ))}
                                    </select>
                                </div>

                                <div className="flex items-center justify-between">
                                    <span className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em]">Uppercase</span>
                                    <button
                                        onClick={() => setUppercase(!uppercase)}
                                        className={`w-10 h-5 rounded-full transition-all duration-300 relative p-1 ${uppercase ? 'bg-primary' : 'bg-zinc-800'}`}
                                    >
                                        <div className={`w-3 h-3 rounded-full bg-white transition-all duration-300 ${uppercase ? 'translate-x-5' : 'translate-x-0'}`} />
                                    </button>
                                </div>
                            </>
                        ) : (
                            <>
                                {/* Classic mode controls (legacy) */}
                                <div className="space-y-3">
                                    <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                        <TypeIcon size={14} /> Font Family
                                    </label>
                                    <select
                                        value={classicFontName}
                                        onChange={(e) => setClassicFontName(e.target.value)}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-primary/50 appearance-none cursor-pointer"
                                    >
                                        {FONT_OPTIONS.map((f) => (
                                            <option key={f.value} value={f.value} className="bg-zinc-900">{f.label}</option>
                                        ))}
                                    </select>
                                </div>

                                <div className="space-y-3">
                                    <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                        <Palette size={14} /> Text Color
                                    </label>
                                    <div className="flex flex-wrap gap-2">
                                        {[{ color: '#FFFFFF' }, { color: '#FFFF00' }, { color: '#00FFFF' }, { color: '#00FF00' }, { color: '#FF0000' }, { color: '#FF69B4' }].map((c) => (
                                            <button
                                                key={c.color}
                                                onClick={() => setFontColor(c.color)}
                                                className={`w-7 h-7 rounded-full border-2 transition-all ${fontColor === c.color ? 'border-white scale-110 shadow-lg' : 'border-transparent hover:border-white/20'}`}
                                                style={{ backgroundColor: c.color }}
                                            />
                                        ))}
                                    </div>
                                </div>

                                <div className="space-y-3">
                                    <div className="flex justify-between items-center">
                                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Outline</span>
                                        <span className="text-[10px] font-mono text-primary">{borderWidth}px</span>
                                    </div>
                                    <input
                                        type="range" min="0" max="5" step="1"
                                        value={borderWidth}
                                        onChange={(e) => setBorderWidth(parseInt(e.target.value))}
                                        className="w-full accent-primary h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer"
                                    />
                                </div>

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
                                    <div className="space-y-3">
                                        <div className="flex justify-between items-center">
                                            <span className="text-[10px] font-bold text-zinc-500 uppercase">Opacity</span>
                                            <span className="text-[10px] font-mono text-primary">{Math.round(bgOpacity * 100)}%</span>
                                        </div>
                                        <input
                                            type="range" min="10" max="100" step="10"
                                            value={Math.round(bgOpacity * 100)}
                                            onChange={(e) => setBgOpacity(parseInt(e.target.value) / 100)}
                                            className="w-full accent-primary h-1.5 bg-white/5 rounded-full appearance-none cursor-pointer"
                                        />
                                    </div>
                                )}
                            </>
                        )}

                        {/* Position (shared) */}
                        <div className="space-y-3">
                            <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                <AlignCenter size={12} /> Position
                            </label>
                            <div className="grid grid-cols-3 gap-2">
                                {[
                                    { id: 'top', icon: AlignVerticalJustifyStart },
                                    { id: 'middle', icon: AlignCenter },
                                    { id: 'bottom', icon: AlignVerticalJustifyEnd }
                                ].map((pos) => (
                                    <button
                                        key={pos.id}
                                        onClick={() => setPosition(pos.id)}
                                        className={`flex flex-col items-center gap-1.5 p-3 rounded-xl border transition-all ${position === pos.id ? 'bg-primary border-primary text-white' : 'bg-white/[0.02] border-white/5 text-zinc-500 hover:bg-white/5'}`}
                                    >
                                        <pos.icon size={16} />
                                        <span className="text-[9px] font-black uppercase">{pos.id}</span>
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className="p-6 bg-black/20 border-t border-white/5">
                        <button
                            onClick={handleGenerate}
                            disabled={isProcessing}
                            className="w-full btn-primary-glow !py-4 font-black uppercase tracking-[0.2em] italic"
                        >
                            {isProcessing ? (
                                <>
                                    <Loader2 size={20} className="animate-spin" />
                                    <span>Rendering...</span>
                                </>
                            ) : (
                                <span>{mode === 'viral' ? 'Generate Karaoke Subs' : 'Sync Subtitles'}</span>
                            )}
                        </button>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
}
