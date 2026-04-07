import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Loader2, Zap, Type, Palette, Layers } from 'lucide-react';

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

const FONT_FACE_MAP = {
    'Montserrat-Black': '/fonts/Montserrat-Black.ttf',
    'Bangers-Regular': '/fonts/Bangers-Regular.ttf',
    'Poppins-Black': '/fonts/Poppins-Black.ttf',
    'Poppins-Medium': '/fonts/Poppins-Medium.ttf',
    'Anton-Regular': '/fonts/Anton-Regular.ttf',
};

const HIGHLIGHT_COLORS = [
    { color: '#FFFF00', label: 'Yellow' },
    { color: '#00FF00', label: 'Green' },
    { color: '#00FFFF', label: 'Cyan' },
    { color: '#FF4444', label: 'Red' },
    { color: '#FF69B4', label: 'Pink' },
    { color: '#FFFFFF', label: 'White' },
];

export default function SubtitleModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl }) {
    const [mode, setMode] = useState('viral');
    // Single vertical position slider: -50 = top, 0 = center, +50 = bottom.
    // Backend always receives position='center' so MarginV is centered on the
    // video and offset_y drives the actual Y in percentage of video height.
    const [offsetY, setOffsetY] = useState(35);  // default slightly below center
    const position = 'center';

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

    useEffect(() => {
        Object.entries(FONT_FACE_MAP).forEach(([name, url]) => {
            const font = new FontFace(name, `url(${url})`);
            font.load().then((loaded) => {
                document.fonts.add(loaded);
            }).catch(err => console.warn(`Font ${name} failed to load:`, err));
        });
    }, []);

    if (!isOpen) return null;

    const handleGenerate = () => {
        if (mode === 'viral') {
            onGenerate({
                position,
                offset_y: offsetY,
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
            onGenerate({ position, offset_y: offsetY, fontSize, fontName: classicFontName, fontColor, borderColor, borderWidth, bgColor, bgOpacity });
        }
    };

    const previewFont = mode === 'viral' ? fontName : classicFontName;
    const previewHighlight = mode === 'viral' ? highlightColor : fontColor;

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

                {/* Left column: Settings */}
                <div className="flex-1 flex flex-col overflow-hidden border-r border-white/10 md:max-w-[380px]">
                    <div className="px-6 pt-6 pb-4">
                        <h3 className="text-lg font-display font-bold text-white">Captions</h3>
                        <p className="text-xs text-zinc-500 mt-0.5">Configure subtitle style and placement</p>
                    </div>

                    {/* Karaoke / Classic toggle */}
                    <div className="px-6 pb-4">
                        <div className="flex bg-black/40 p-1 rounded-xl">
                            <button
                                onClick={() => setMode('viral')}
                                className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition-all ${
                                    mode === 'viral'
                                        ? 'bg-gradient-to-r from-accent-pink to-accent-purple text-white shadow-glow-pink'
                                        : 'text-zinc-500 hover:text-zinc-300'
                                }`}
                            >
                                <Zap size={13} /> Karaoke
                            </button>
                            <button
                                onClick={() => setMode('classic')}
                                className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition-all ${
                                    mode === 'classic'
                                        ? 'bg-gradient-to-r from-accent-pink to-accent-purple text-white shadow-glow-pink'
                                        : 'text-zinc-500 hover:text-zinc-300'
                                }`}
                            >
                                <Type size={13} /> Classic
                            </button>
                        </div>
                    </div>

                    <div className="flex-1 overflow-y-auto px-6 pb-6 space-y-6">
                        {mode === 'viral' ? (
                            <>
                                {/* Preset grid - 2x3 */}
                                <div className="space-y-2">
                                    <label className="text-xs font-medium text-zinc-400">Style Preset</label>
                                    <div className="grid grid-cols-2 gap-2">
                                        {VIRAL_PRESETS.map((p) => (
                                            <button
                                                key={p.id}
                                                onClick={() => {
                                                    setSelectedPreset(p.id);
                                                    setHighlightColor(p.colors[1]);
                                                }}
                                                className={`p-3 rounded-xl border text-left transition-all ${
                                                    selectedPreset === p.id
                                                        ? 'bg-white/[0.06] border-accent-pink/40'
                                                        : 'bg-white/[0.02] border-white/[0.06] hover:border-white/10'
                                                }`}
                                            >
                                                <div className="flex items-center gap-1.5 mb-1.5">
                                                    {p.colors.map((c, i) => (
                                                        <div
                                                            key={i}
                                                            className="w-3 h-3 rounded-full border border-white/20"
                                                            style={{ backgroundColor: c }}
                                                        />
                                                    ))}
                                                </div>
                                                <p className="text-xs font-semibold text-white">{p.label}</p>
                                                <p className="text-[10px] text-zinc-500">{p.desc}</p>
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                {/* Display mode */}
                                <div className="space-y-2">
                                    <label className="text-xs font-medium text-zinc-400">Display Mode</label>
                                    <div className="grid grid-cols-2 gap-2">
                                        <button
                                            onClick={() => setKaraokeMode('word_group')}
                                            className={`p-2.5 rounded-xl border text-center transition-all ${
                                                karaokeMode === 'word_group'
                                                    ? 'bg-white/[0.06] border-accent-pink/40'
                                                    : 'bg-white/[0.02] border-white/[0.06] hover:border-white/10'
                                            }`}
                                        >
                                            <p className="text-xs font-semibold text-white">Word Group</p>
                                            <p className="text-[10px] text-zinc-500">2-3 words at a time</p>
                                        </button>
                                        <button
                                            onClick={() => setKaraokeMode('full_line')}
                                            className={`p-2.5 rounded-xl border text-center transition-all ${
                                                karaokeMode === 'full_line'
                                                    ? 'bg-white/[0.06] border-accent-pink/40'
                                                    : 'bg-white/[0.02] border-white/[0.06] hover:border-white/10'
                                            }`}
                                        >
                                            <p className="text-xs font-semibold text-white">Full Line</p>
                                            <p className="text-[10px] text-zinc-500">Karaoke sweep</p>
                                        </button>
                                    </div>
                                </div>

                                {/* Words per group slider */}
                                {karaokeMode === 'word_group' && (
                                    <div className="space-y-2">
                                        <div className="flex justify-between items-center">
                                            <label className="text-xs font-medium text-zinc-400">Words Per Group</label>
                                            <span className="text-xs font-mono text-accent-pink">{wordsPerGroup}</span>
                                        </div>
                                        <input
                                            type="range" min="1" max="5" step="1"
                                            value={wordsPerGroup}
                                            onChange={(e) => setWordsPerGroup(parseInt(e.target.value))}
                                            className="w-full accent-accent-pink h-1 bg-white/5 rounded-full appearance-none cursor-pointer"
                                        />
                                    </div>
                                )}

                                {/* Highlight color */}
                                <div className="space-y-2">
                                    <label className="text-xs font-medium text-zinc-400">Highlight Color</label>
                                    <div className="flex flex-wrap gap-2">
                                        {HIGHLIGHT_COLORS.map((c) => (
                                            <button
                                                key={c.color}
                                                onClick={() => setHighlightColor(c.color)}
                                                className={`w-7 h-7 rounded-full border-2 transition-all ${
                                                    highlightColor === c.color
                                                        ? 'border-white scale-110'
                                                        : 'border-transparent hover:border-white/20'
                                                }`}
                                                style={{ backgroundColor: c.color }}
                                            />
                                        ))}
                                        <label className="w-7 h-7 rounded-full border-2 border-dashed border-white/20 cursor-pointer flex items-center justify-center hover:border-white/40 transition-all relative">
                                            <span className="text-[10px] text-zinc-500">+</span>
                                            <input type="color" value={highlightColor} onChange={(e) => setHighlightColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                        </label>
                                    </div>
                                </div>

                                {/* Font */}
                                <div className="space-y-2">
                                    <label className="text-xs font-medium text-zinc-400">Font</label>
                                    <select
                                        value={fontName}
                                        onChange={(e) => setFontName(e.target.value)}
                                        className="w-full bg-[#0f0f13] border border-white/10 rounded-lg px-4 py-3 text-sm text-white focus:outline-none focus:border-accent-pink/50 appearance-none cursor-pointer"
                                    >
                                        {FONT_OPTIONS.filter(f => f.value !== 'Verdana').map((f) => (
                                            <option key={f.value} value={f.value} className="bg-[#0f0f13]">{f.label}</option>
                                        ))}
                                    </select>
                                </div>

                                {/* Uppercase toggle */}
                                <div className="flex items-center justify-between">
                                    <span className="text-xs font-medium text-zinc-400">Uppercase</span>
                                    <button
                                        onClick={() => setUppercase(!uppercase)}
                                        className={`w-10 h-5 rounded-full transition-all duration-300 relative p-0.5 ${
                                            uppercase ? 'bg-accent-pink' : 'bg-white/10'
                                        }`}
                                    >
                                        <div className={`w-4 h-4 rounded-full bg-white transition-all duration-300 ${uppercase ? 'translate-x-5' : 'translate-x-0'}`} />
                                    </button>
                                </div>
                            </>
                        ) : (
                            <>
                                {/* Classic: Font family */}
                                <div className="space-y-2">
                                    <label className="text-xs font-medium text-zinc-400 flex items-center gap-1.5">
                                        <Type size={13} /> Font Family
                                    </label>
                                    <select
                                        value={classicFontName}
                                        onChange={(e) => setClassicFontName(e.target.value)}
                                        className="w-full bg-[#0f0f13] border border-white/10 rounded-lg px-4 py-3 text-sm text-white focus:outline-none focus:border-accent-pink/50 appearance-none cursor-pointer"
                                    >
                                        {FONT_OPTIONS.map((f) => (
                                            <option key={f.value} value={f.value} className="bg-[#0f0f13]">{f.label}</option>
                                        ))}
                                    </select>
                                </div>

                                {/* Classic: Text color */}
                                <div className="space-y-2">
                                    <label className="text-xs font-medium text-zinc-400 flex items-center gap-1.5">
                                        <Palette size={13} /> Text Color
                                    </label>
                                    <div className="flex flex-wrap gap-2">
                                        {[{ color: '#FFFFFF' }, { color: '#FFFF00' }, { color: '#00FFFF' }, { color: '#00FF00' }, { color: '#FF0000' }, { color: '#FF69B4' }].map((c) => (
                                            <button
                                                key={c.color}
                                                onClick={() => setFontColor(c.color)}
                                                className={`w-7 h-7 rounded-full border-2 transition-all ${
                                                    fontColor === c.color
                                                        ? 'border-white scale-110'
                                                        : 'border-transparent hover:border-white/20'
                                                }`}
                                                style={{ backgroundColor: c.color }}
                                            />
                                        ))}
                                    </div>
                                </div>

                                {/* Classic: Outline */}
                                <div className="space-y-2">
                                    <div className="flex justify-between items-center">
                                        <label className="text-xs font-medium text-zinc-400">Outline</label>
                                        <span className="text-xs font-mono text-accent-pink">{borderWidth}px</span>
                                    </div>
                                    <input
                                        type="range" min="0" max="5" step="1"
                                        value={borderWidth}
                                        onChange={(e) => setBorderWidth(parseInt(e.target.value))}
                                        className="w-full accent-accent-pink h-1 bg-white/5 rounded-full appearance-none cursor-pointer"
                                    />
                                </div>

                                {/* Classic: Background box toggle */}
                                <div className="flex items-center justify-between">
                                    <label className="text-xs font-medium text-zinc-400 flex items-center gap-1.5">
                                        <Layers size={13} /> Background Box
                                    </label>
                                    <button
                                        onClick={() => setBgOpacity(bgOpacity > 0 ? 0 : 0.6)}
                                        className={`w-10 h-5 rounded-full transition-all duration-300 relative p-0.5 ${
                                            bgOpacity > 0 ? 'bg-accent-pink' : 'bg-white/10'
                                        }`}
                                    >
                                        <div className={`w-4 h-4 rounded-full bg-white transition-all duration-300 ${bgOpacity > 0 ? 'translate-x-5' : 'translate-x-0'}`} />
                                    </button>
                                </div>

                                {bgOpacity > 0 && (
                                    <div className="space-y-2">
                                        <div className="flex justify-between items-center">
                                            <label className="text-xs font-medium text-zinc-400">Opacity</label>
                                            <span className="text-xs font-mono text-accent-pink">{Math.round(bgOpacity * 100)}%</span>
                                        </div>
                                        <input
                                            type="range" min="10" max="100" step="10"
                                            value={Math.round(bgOpacity * 100)}
                                            onChange={(e) => setBgOpacity(parseInt(e.target.value) / 100)}
                                            className="w-full accent-accent-pink h-1 bg-white/5 rounded-full appearance-none cursor-pointer"
                                        />
                                    </div>
                                )}
                            </>
                        )}

                        {/* Vertical Position (single unified slider) */}
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
                    </div>

                    {/* Apply button */}
                    <div className="px-6 py-4 border-t border-white/10">
                        <button
                            onClick={handleGenerate}
                            disabled={isProcessing}
                            className="w-full py-3 rounded-xl font-semibold text-sm text-white transition-all active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                            style={{ background: 'linear-gradient(135deg, #e6428d, #9850c3)' }}
                        >
                            {isProcessing ? (
                                <>
                                    <Loader2 size={16} className="animate-spin" />
                                    Rendering...
                                </>
                            ) : (
                                <span>{mode === 'viral' ? 'Apply Karaoke Subtitles' : 'Apply Classic Subtitles'}</span>
                            )}
                        </button>
                    </div>
                </div>

                {/* Right column: Preview */}
                <div className="flex-1 bg-black relative flex items-center justify-center min-h-[350px]">
                    <video src={videoUrl} className="w-full h-full object-contain opacity-30 grayscale" muted playsInline />

                    <div className="absolute inset-0 flex flex-col items-center justify-center p-10">
                        <div
                            className="w-full flex items-center justify-center transition-all duration-200 absolute left-0 right-0"
                            style={{
                                // offsetY -50 → 0% from top, 0 → 50% (center), +50 → 100%
                                top: `${50 + offsetY}%`,
                                transform: 'translateY(-50%)',
                            }}
                        >
                            {mode === 'viral' ? (
                                <div className="text-center">
                                    <span style={{
                                        fontFamily: previewFont,
                                        color: '#FFFFFF',
                                        fontSize: '20px',
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
                                    fontSize: '18px',
                                    fontWeight: 'bold',
                                    textShadow: borderWidth > 0 ? `-${borderWidth}px -${borderWidth}px 0 ${borderColor}, ${borderWidth}px ${borderWidth}px 0 ${borderColor}` : 'none',
                                    ...(bgOpacity > 0 ? { backgroundColor: `${bgColor}${Math.round(bgOpacity * 255).toString(16).padStart(2, '0')}`, padding: '8px 16px', borderRadius: '8px' } : {}),
                                }}>
                                    AI Generated<br/>Viral Captions
                                </span>
                            )}
                        </div>
                    </div>

                    <div className="absolute top-4 left-4 flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-accent-pink animate-pulse" />
                        <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">Preview</span>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
}
