import React, { useState, useEffect, useRef, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Loader2, Zap, Type, Palette, Layers } from 'lucide-react';
import { SUBTITLE_PRESETS, scaleFontToPreview, outlineToTextShadow } from '@/lib/subtitlePresets';

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

export default function SubtitleModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl, initialValues }) {
    // Normalize initial values from the parent. The parent already stores
    // subtitleParams in the backend snake_case shape (font, font_color,
    // border_color, bg_opacity, …), so we map them 1:1 into the modal's
    // local state when the modal opens.
    const iv = initialValues || {};
    const initialMode = iv.mode === 'classic' ? 'classic' : 'viral';

    const [mode, setMode] = useState(initialMode);
    // Single vertical position slider: -50 = top, 0 = center, +50 = bottom.
    const [offsetY, setOffsetY] = useState(iv.offset_y ?? 35);
    const position = 'center';

    // Viral mode state
    const [selectedPreset, setSelectedPreset] = useState(iv.preset || 'classic_white');
    const [karaokeMode, setKaraokeMode] = useState(iv.display_mode || 'word_group');
    const [wordsPerGroup, setWordsPerGroup] = useState(iv.words_per_group ?? 3);
    const [uppercase, setUppercase] = useState(iv.uppercase ?? true);
    const [highlightColor, setHighlightColor] = useState(iv.highlight_color || '#FFFF00');
    const [fontName, setFontName] = useState(
        iv.mode === 'karaoke' || iv.mode === 'viral' ? (iv.font || 'Montserrat-Black') : 'Montserrat-Black'
    );

    // Preview video ref + measured rendered height for faithful font scaling.
    // The backend burns subtitles at libass fontsize values (px @ 1920 video
    // height). We mirror the same math on the DOM preview so what the user
    // sees here matches the final render 1:1.
    const previewVideoRef = useRef(null);
    const [renderedVideoHeight, setRenderedVideoHeight] = useState(0);
    useLayoutEffect(() => {
        if (!isOpen) return undefined;
        const update = () => {
            const el = previewVideoRef.current;
            if (!el) return;
            // Video is `object-contain`, so the actual rendered picture
            // height may be smaller than the <video> element. For 9:16 in a
            // wider container, the picture height === element height. For a
            // narrower container the picture is letterboxed. Using
            // `clientHeight` as an upper bound is close enough for a preview.
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

    // Classic mode state — seeded from initialValues when the parent passes
    // per-clip subtitleParams (from pre-selection or an earlier apply).
    const [fontSize, setFontSize] = useState(iv.font_size ?? 42);
    const [classicFontName, setClassicFontName] = useState(
        iv.mode === 'classic' ? (iv.font || 'Verdana') : 'Verdana'
    );
    const [fontColor, setFontColor] = useState(iv.font_color || '#FFFFFF');
    const [borderColor, setBorderColor] = useState(iv.border_color || '#000000');
    const [borderWidth, setBorderWidth] = useState(iv.border_width ?? 2);
    const [bgColor, setBgColor] = useState(iv.bg_color || '#000000');
    const [bgOpacity, setBgOpacity] = useState(iv.bg_opacity ?? 0.0);

    // Re-seed state every time the modal transitions closed → open so
    // subsequent opens reflect the parent's latest subtitleParams.
    useEffect(() => {
        if (!isOpen) return;
        const v = initialValues || {};
        setMode(v.mode === 'classic' ? 'classic' : 'viral');
        setOffsetY(v.offset_y ?? 35);
        setSelectedPreset(v.preset || 'classic_white');
        setKaraokeMode(v.display_mode || 'word_group');
        setWordsPerGroup(v.words_per_group ?? 3);
        setUppercase(v.uppercase ?? true);
        setHighlightColor(v.highlight_color || '#FFFF00');
        setFontName(
            v.mode === 'karaoke' || v.mode === 'viral' ? (v.font || 'Montserrat-Black') : 'Montserrat-Black'
        );
        setFontSize(v.font_size ?? 42);
        setClassicFontName(v.mode === 'classic' ? (v.font || 'Verdana') : 'Verdana');
        setFontColor(v.font_color || '#FFFFFF');
        setBorderColor(v.border_color || '#000000');
        setBorderWidth(v.border_width ?? 2);
        setBgColor(v.bg_color || '#000000');
        setBgOpacity(v.bg_opacity ?? 0.0);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen]);

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
                mode: 'karaoke',
                position,
                offset_y: offsetY,
                // Viral karaoke uses preset fontsize on the backend — this
                // field is ignored for the preset path but kept for schema
                // compatibility. The actual rendered size comes from
                // subtitles.py:SUBTITLE_PRESETS[preset].fontsize.
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
            onGenerate({
                mode: 'classic',
                position,
                offset_y: offsetY,
                fontSize,
                fontName: classicFontName,
                fontColor,
                borderColor,
                borderWidth,
                bgColor,
                bgOpacity,
            });
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

                                {/* Classic: Font size (matches backend 1:1 — value is the
                                    libass fontsize at 1920 px reference height, rendered
                                    after a 0.85 scale inside burn_subtitles) */}
                                <div className="space-y-2">
                                    <div className="flex justify-between items-center">
                                        <label className="text-xs font-medium text-zinc-400">Font size</label>
                                        <span className="text-xs font-mono text-accent-pink">{fontSize}px</span>
                                    </div>
                                    <input
                                        type="range" min="20" max="80" step="1"
                                        value={fontSize}
                                        onChange={(e) => setFontSize(parseInt(e.target.value))}
                                        className="w-full accent-accent-pink h-1 bg-white/5 rounded-full appearance-none cursor-pointer"
                                    />
                                </div>

                                {/* Classic: Stroke (outline) — color + width */}
                                <div className="space-y-2">
                                    <div className="flex justify-between items-center">
                                        <label className="text-xs font-medium text-zinc-400">Stroke</label>
                                        <span className="text-xs font-mono text-accent-pink">{borderWidth}px</span>
                                    </div>
                                    <div className="flex items-center gap-3">
                                        <label
                                            className="relative w-9 h-9 rounded-[3px] border-2 border-white/15 hover:border-accent-pink/60 cursor-pointer shrink-0 transition-colors"
                                            style={{ backgroundColor: borderColor }}
                                            title="Stroke color"
                                        >
                                            <input
                                                type="color"
                                                value={borderColor}
                                                onChange={(e) => setBorderColor(e.target.value)}
                                                className="absolute inset-0 opacity-0 cursor-pointer"
                                            />
                                        </label>
                                        <input
                                            type="range" min="0" max="10" step="1"
                                            value={borderWidth}
                                            onChange={(e) => setBorderWidth(parseInt(e.target.value))}
                                            aria-label="Stroke width"
                                            className="flex-1 accent-accent-pink h-1 bg-white/5 rounded-full appearance-none cursor-pointer"
                                        />
                                    </div>
                                </div>

                                {/* Classic: Background box — toggle + color + opacity */}
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <label className="text-xs font-medium text-zinc-400 flex items-center gap-1.5">
                                            <Layers size={13} /> Background box
                                        </label>
                                        <button
                                            type="button"
                                            onClick={() => setBgOpacity(bgOpacity > 0 ? 0 : 0.6)}
                                            role="switch"
                                            aria-checked={bgOpacity > 0}
                                            className={`w-10 h-5 rounded-full transition-all duration-300 relative p-0.5 ${
                                                bgOpacity > 0 ? 'bg-accent-pink' : 'bg-white/10'
                                            }`}
                                        >
                                            <div className={`w-4 h-4 rounded-full bg-white transition-all duration-300 ${bgOpacity > 0 ? 'translate-x-5' : 'translate-x-0'}`} />
                                        </button>
                                    </div>

                                    {bgOpacity > 0 && (
                                        <div className="flex items-center gap-3 animate-fade-in">
                                            <label
                                                className="relative w-9 h-9 rounded-[3px] border-2 border-white/15 hover:border-accent-pink/60 cursor-pointer shrink-0 transition-colors"
                                                style={{ backgroundColor: bgColor }}
                                                title="Background color"
                                            >
                                                <input
                                                    type="color"
                                                    value={bgColor}
                                                    onChange={(e) => setBgColor(e.target.value)}
                                                    className="absolute inset-0 opacity-0 cursor-pointer"
                                                />
                                            </label>
                                            <div className="flex-1 space-y-1">
                                                <div className="flex items-center justify-between">
                                                    <span className="text-[10px] text-zinc-500 uppercase tracking-wider">Opacity</span>
                                                    <span className="text-xs font-mono text-accent-pink">{Math.round(bgOpacity * 100)}%</span>
                                                </div>
                                                <input
                                                    type="range" min="10" max="100" step="5"
                                                    value={Math.round(bgOpacity * 100)}
                                                    onChange={(e) => setBgOpacity(parseInt(e.target.value) / 100)}
                                                    aria-label="Background opacity"
                                                    className="w-full accent-accent-pink h-1 bg-white/5 rounded-full appearance-none cursor-pointer"
                                                />
                                            </div>
                                        </div>
                                    )}
                                </div>
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
                    <video
                        ref={previewVideoRef}
                        src={videoUrl}
                        className="w-full h-full object-contain opacity-30 grayscale"
                        muted
                        playsInline
                    />

                    <div className="absolute inset-0 flex flex-col items-center justify-center p-10">
                        <div
                            className="w-full flex items-center justify-center transition-all duration-200 absolute left-0 right-0"
                            style={{
                                // offsetY -50 → 0% from top, 0 → 50% (center), +50 → 100%
                                top: `${50 + offsetY}%`,
                                transform: 'translateY(-50%)',
                            }}
                        >
                            {mode === 'viral' ? (() => {
                                // Faithful scaling: use the real backend preset values
                                // (from the shared subtitlePresets spec) and project the
                                // fontsize into the preview video element's rendered height.
                                const preset = SUBTITLE_PRESETS[selectedPreset] || SUBTITLE_PRESETS.classic_white;
                                const scaledFont = scaleFontToPreview(preset.fontsize, renderedVideoHeight);
                                const scaledOutline = scaleFontToPreview(preset.outlineWidth, renderedVideoHeight);
                                const textShadow = outlineToTextShadow(scaledOutline, preset.outlineColor);
                                const isBoxStyle = preset.borderStyle === 3;
                                const neonGlow = preset.neonGlow
                                    ? `, 0 0 ${scaledOutline * 2}px ${preset.highlightColor}, 0 0 ${scaledOutline * 4}px ${preset.highlightColor}`
                                    : '';
                                const shouldUppercase = uppercase;
                                return (
                                    <div className="text-center px-4" style={{ maxWidth: '85%' }}>
                                        <span
                                            style={{
                                                fontFamily: fontName || preset.font,
                                                color: preset.textColor,
                                                fontSize: `${scaledFont}px`,
                                                lineHeight: 1.15,
                                                fontWeight: 900,
                                                textShadow: `${textShadow}${neonGlow}`,
                                                textTransform: shouldUppercase ? 'uppercase' : 'none',
                                                ...(isBoxStyle ? {
                                                    backgroundColor: '#000000',
                                                    padding: `${scaledFont * 0.15}px ${scaledFont * 0.35}px`,
                                                    borderRadius: `${scaledFont * 0.08}px`,
                                                    boxDecorationBreak: 'clone',
                                                    WebkitBoxDecorationBreak: 'clone',
                                                } : {}),
                                            }}
                                        >
                                            AI GENERATED{' '}
                                            <span style={{ color: highlightColor || preset.highlightColor }}>VIRAL</span>
                                            {' '}CAPTIONS
                                        </span>
                                    </div>
                                );
                            })() : (() => {
                                // Classic mode: burn_subtitles applies fontsize * 0.85
                                // at 1920 reference. Mirror that here.
                                const effectiveBackendSize = Math.max(10, fontSize * 0.85);
                                const scaledFont = scaleFontToPreview(effectiveBackendSize, renderedVideoHeight);
                                const scaledBorder = scaleFontToPreview(borderWidth, renderedVideoHeight);
                                const shadow = scaledBorder > 0
                                    ? outlineToTextShadow(scaledBorder, borderColor)
                                    : 'none';
                                return (
                                    <span
                                        style={{
                                            fontFamily: classicFontName,
                                            color: fontColor,
                                            fontSize: `${scaledFont}px`,
                                            lineHeight: 1.2,
                                            fontWeight: 'bold',
                                            textShadow: shadow,
                                            ...(bgOpacity > 0 ? {
                                                backgroundColor: `${bgColor}${Math.round(bgOpacity * 255).toString(16).padStart(2, '0')}`,
                                                padding: `${scaledFont * 0.2}px ${scaledFont * 0.4}px`,
                                                borderRadius: `${scaledFont * 0.15}px`,
                                            } : {}),
                                        }}
                                    >
                                        AI Generated<br/>Viral Captions
                                    </span>
                                );
                            })()}
                        </div>
                    </div>

                    <div className="absolute top-4 left-4 flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-accent-pink animate-pulse" />
                        <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
                            1:1 Preview
                        </span>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
}
