import React, { useState, useRef } from 'react';
import { Youtube, Upload, FileVideo, X, Globe, Link2, FileUp, Loader2, ChevronDown, Sparkles, Layers, Clipboard, Settings } from 'lucide-react';

// Visual previews for subtitle preset selection. Each entry mimics the
// rendered look of the corresponding preset in subtitles.py:SUBTITLE_PRESETS.
const SUBTITLE_PRESETS = [
    {
        id: 'classic_white',
        label: 'Classic',
        highlight: '#FFFF00',
        previewStyle: {
            color: '#FFFFFF',
            fontFamily: 'Verdana, sans-serif',
            textShadow: '-1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000',
        },
    },
    {
        id: 'hormozi_bold',
        label: 'Hormozi',
        highlight: '#00FF00',
        previewStyle: {
            color: '#FFFFFF',
            fontFamily: 'Impact, "Arial Black", sans-serif',
            textShadow: '-1.5px -1.5px 0 #000, 1.5px -1.5px 0 #000, -1.5px 1.5px 0 #000, 1.5px 1.5px 0 #000',
            letterSpacing: '0.02em',
        },
    },
    {
        id: 'neon_glow',
        label: 'Neon',
        highlight: '#00FFFF',
        previewStyle: {
            color: '#FFFFFF',
            fontFamily: '"Helvetica Neue", sans-serif',
            textShadow: '0 0 4px #00FFFF, 0 0 8px #00FFFF',
        },
    },
    {
        id: 'mrbeast_box',
        label: 'MrBeast',
        highlight: '#FFFF00',
        previewStyle: {
            color: '#FFFFFF',
            fontFamily: '"Arial Black", sans-serif',
            backgroundColor: '#000',
            padding: '2px 6px',
            borderRadius: '3px',
        },
    },
    {
        id: 'minimal_clean',
        label: 'Minimal',
        highlight: '#FFFFFF',
        previewStyle: {
            color: '#FFFFFF',
            fontFamily: '"Helvetica Neue", sans-serif',
            fontWeight: 500,
        },
    },
    {
        id: 'fire_impact',
        label: 'Fire',
        highlight: '#FF4444',
        previewStyle: {
            color: '#FFFFFF',
            fontFamily: 'Impact, sans-serif',
            textShadow: '0 0 3px #FF4444, -1px -1px 0 #000, 1px 1px 0 #000',
            letterSpacing: '0.03em',
        },
    },
];

export default function MediaInput({ onProcess, onBatchProcess, isProcessing, cookiesConfigured }) {
    const [mode, setMode] = useState('single'); // 'single' | 'batch'
    const [singleSource, setSingleSource] = useState('url'); // 'url' | 'file'
    const [url, setUrl] = useState('');
    const [file, setFile] = useState(null);
    const [instructions, setInstructions] = useState('');
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [batchUrls, setBatchUrls] = useState('');
    const [batchFiles, setBatchFiles] = useState([]); // File[]
    const [isDragging, setIsDragging] = useState(false);
    const urlInputRef = useRef(null);

    const [showPreselections, setShowPreselections] = useState(false);
    const [reframeMode, setReframeMode] = useState('auto');
    const [preSmartCut, setPreSmartCut] = useState(false);
    const [preSubtitles, setPreSubtitles] = useState(false);
    const [preSubPreset, setPreSubPreset] = useState('classic_white');
    const [preSubMode, setPreSubMode] = useState('karaoke');
    const [showSubConfig, setShowSubConfig] = useState(false);
    const [preHook, setPreHook] = useState(false);
    const [preHookPosition, setPreHookPosition] = useState('top');
    const [preHookSize, setPreHookSize] = useState('S');
    const [showHookConfig, setShowHookConfig] = useState(false);

    const handleSubmit = (e) => {
        e.preventDefault();
        const preselections = {
            reframe_mode: reframeMode,
            smartcut: preSmartCut,
            subtitles: preSubtitles
                ? (preSubMode === 'karaoke'
                    ? { preset: preSubPreset, mode: 'karaoke' }
                    : { mode: 'classic' })
                : null,
            hook: preHook ? { position: preHookPosition, size: preHookSize } : null,
        };
        const opts = { instructions: instructions.trim() || undefined, preselections };
        if (mode === 'batch') {
            const urls = batchUrls.split('\n').map(u => u.trim()).filter(u => u);
            if ((urls.length > 0 || batchFiles.length > 0) && onBatchProcess) {
                onBatchProcess({ urls, files: batchFiles, ...opts });
            }
        } else if (mode === 'single') {
            if (singleSource === 'url' && url) {
                onProcess({ type: 'url', payload: url, ...opts });
            } else if (singleSource === 'file' && file) {
                onProcess({ type: 'file', payload: file, ...opts });
            }
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragging(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            if (mode === 'batch') {
                setBatchFiles((prev) => [...prev, ...Array.from(e.dataTransfer.files)]);
            } else {
                setFile(e.dataTransfer.files[0]);
                setSingleSource('file');
            }
        }
    };

    const handlePaste = async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text) setUrl(text);
            urlInputRef.current?.focus();
        } catch {
            // clipboard access denied
        }
    };

    const batchUrlCount = batchUrls.split('\n').filter(u => u.trim()).length;
    const batchTotal = batchUrlCount + batchFiles.length;

    const tabs = [
        { id: 'single', label: 'Single', icon: FileVideo },
        { id: 'batch', label: 'Batch', icon: Layers },
    ];

    const isDisabled = isProcessing
        || (mode === 'single' && singleSource === 'url' && !url)
        || (mode === 'single' && singleSource === 'file' && !file)
        || (mode === 'batch' && batchTotal === 0);

    return (
        <div className="bg-[#0f0f13] border border-white/5 rounded-xl overflow-hidden animate-fade-in shadow-2xl shadow-black/40">
            {/* Pill Tabs */}
            <div className="px-6 pt-6 pb-2">
                <div className="inline-flex bg-white/[0.04] rounded-full p-1 gap-0.5">
                    {tabs.map(({ id, label, icon: Icon }) => (
                        <button
                            key={id}
                            type="button"
                            onClick={() => setMode(id)}
                            className={`flex items-center gap-2 px-5 py-2 rounded-full text-xs font-semibold tracking-wide transition-all duration-300 ${
                                mode === id
                                    ? 'bg-white/10 text-white shadow-sm'
                                    : 'text-zinc-500 hover:text-zinc-300'
                            }`}
                        >
                            <Icon size={14} />
                            {label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Content */}
            <div className="p-6">
                <form onSubmit={handleSubmit} className="space-y-5">

                    {/* Single Mode — URL or File via inner toggle */}
                    {mode === 'single' && (
                        <div className="space-y-4">
                            {/* Source toggle */}
                            <div className="inline-flex bg-white/[0.04] rounded-full p-1 gap-0.5">
                                <button
                                    type="button"
                                    onClick={() => setSingleSource('url')}
                                    className={`flex items-center gap-1.5 px-4 py-1.5 rounded-full text-[11px] font-semibold tracking-wide transition-all ${
                                        singleSource === 'url'
                                            ? 'bg-white/10 text-white shadow-sm'
                                            : 'text-zinc-500 hover:text-zinc-300'
                                    }`}
                                >
                                    <Globe size={12} />
                                    URL
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setSingleSource('file')}
                                    className={`flex items-center gap-1.5 px-4 py-1.5 rounded-full text-[11px] font-semibold tracking-wide transition-all ${
                                        singleSource === 'file'
                                            ? 'bg-white/10 text-white shadow-sm'
                                            : 'text-zinc-500 hover:text-zinc-300'
                                    }`}
                                >
                                    <FileUp size={12} />
                                    Upload
                                </button>
                            </div>

                            {singleSource === 'url' ? (
                                <>
                                    <div className="relative">
                                        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-zinc-600" aria-hidden="true">
                                            <Youtube size={20} />
                                        </div>
                                        <label htmlFor="video-url" className="sr-only">Video URL</label>
                                        <input
                                            id="video-url"
                                            ref={urlInputRef}
                                            type="url"
                                            value={url}
                                            onChange={(e) => setUrl(e.target.value)}
                                            placeholder="Paste a YouTube or video URL..."
                                            className="w-full bg-white/[0.03] border border-white/5 rounded-xl pl-12 pr-24 py-4 text-[15px] text-white placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-transparent transition-all"
                                        />
                                        <button
                                            type="button"
                                            onClick={handlePaste}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/10 text-zinc-400 hover:text-white text-xs font-medium transition-all"
                                        >
                                            <Clipboard size={13} />
                                            Paste
                                        </button>
                                    </div>

                                    {!cookiesConfigured && (
                                        <div className="flex items-start gap-2 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs">
                                            <span className="mt-0.5">⚠</span>
                                            <span>Cookie non configurati. Senza cookie, il download potrebbe fallire o essere più lento. Configura i cookie nelle <strong>Impostazioni</strong>.</span>
                                        </div>
                                    )}
                                </>
                            ) : (
                                <div
                                    className={`border-2 border-dashed rounded-xl p-10 text-center transition-all duration-300 relative group cursor-pointer ${
                                        file
                                            ? 'border-emerald-500/30 bg-emerald-500/[0.03]'
                                            : isDragging
                                                ? 'border-blue-500/50 bg-blue-500/[0.04] shadow-[0_0_30px_-5px_rgba(59,130,246,0.15)]'
                                                : 'border-white/[0.06] hover:border-white/[0.12] hover:shadow-[0_0_30px_-5px_rgba(255,255,255,0.03)] bg-white/[0.01]'
                                    }`}
                                    onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                                    onDragLeave={() => setIsDragging(false)}
                                    onDrop={handleDrop}
                                >
                                    {file ? (
                                        <div className="flex flex-col items-center gap-3">
                                            <div className="w-14 h-14 rounded-xl bg-emerald-500/10 flex items-center justify-center text-emerald-400 border border-emerald-500/20">
                                                <FileVideo size={28} />
                                            </div>
                                            <div className="text-center">
                                                <p className="text-white font-semibold text-sm truncate max-w-[240px]">{file.name}</p>
                                                <p className="text-[11px] text-zinc-500 mt-0.5">Ready to process</p>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => setFile(null)}
                                                aria-label="Remove selected file"
                                                className="mt-1 p-2.5 hover:bg-white/10 rounded-lg transition-all text-zinc-500 hover:text-white min-h-[44px] min-w-[44px] flex items-center justify-center"
                                            >
                                                <X size={16} />
                                            </button>
                                        </div>
                                    ) : (
                                        <label className="cursor-pointer flex flex-col items-center gap-3">
                                            <input
                                                type="file"
                                                accept="video/*"
                                                onChange={(e) => setFile(e.target.files?.[0] || null)}
                                                className="hidden"
                                            />
                                            <div className="w-14 h-14 rounded-xl bg-white/[0.03] flex items-center justify-center text-zinc-500 group-hover:text-white group-hover:bg-white/[0.06] border border-white/5 transition-all duration-300">
                                                <Upload size={26} />
                                            </div>
                                            <div className="text-center">
                                                <p className="text-zinc-300 font-medium text-sm">Drop your video here or click to browse</p>
                                                <p className="text-[11px] text-zinc-600 mt-1">MP4, MOV, WEBM up to 2GB</p>
                                            </div>
                                        </label>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Batch Mode — URLs textarea + multi-file upload */}
                    {mode === 'batch' && (
                        <div className="space-y-4">
                            {/* URLs textarea */}
                            <div className="space-y-2">
                                <label htmlFor="batch-urls" className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
                                    <Globe size={11} /> URLs
                                </label>
                                <textarea
                                    id="batch-urls"
                                    value={batchUrls}
                                    onChange={(e) => setBatchUrls(e.target.value)}
                                    placeholder={"https://youtube.com/watch?v=abc\nhttps://youtube.com/watch?v=def"}
                                    className="w-full bg-white/[0.03] border border-white/5 rounded-xl px-4 py-3.5 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-transparent resize-none h-24 font-mono leading-relaxed transition-all"
                                    maxLength={5000}
                                />
                                <p className="text-[11px] text-zinc-500 px-1">One URL per line</p>
                            </div>

                            {/* File uploads */}
                            <div className="space-y-2">
                                <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
                                    <FileUp size={11} /> Files
                                </label>
                                <div
                                    className={`border-2 border-dashed rounded-xl p-5 text-center transition-all duration-300 cursor-pointer ${
                                        isDragging
                                            ? 'border-blue-500/50 bg-blue-500/[0.04]'
                                            : 'border-white/[0.06] hover:border-white/[0.12] bg-white/[0.01]'
                                    }`}
                                    onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                                    onDragLeave={() => setIsDragging(false)}
                                    onDrop={handleDrop}
                                >
                                    <label className="cursor-pointer flex flex-col items-center gap-2">
                                        <input
                                            type="file"
                                            accept="video/*"
                                            multiple
                                            onChange={(e) => setBatchFiles((prev) => [...prev, ...Array.from(e.target.files || [])])}
                                            className="hidden"
                                        />
                                        <Upload size={20} className="text-zinc-500" />
                                        <p className="text-xs text-zinc-400">Drop videos or click to add (multiple)</p>
                                    </label>
                                </div>

                                {batchFiles.length > 0 && (
                                    <ul className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                                        {batchFiles.map((f, i) => (
                                            <li key={`${f.name}-${i}`} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/5">
                                                <FileVideo size={13} className="text-emerald-400/70 flex-shrink-0" />
                                                <span className="text-[11px] text-zinc-300 truncate flex-1">{f.name}</span>
                                                <button
                                                    type="button"
                                                    onClick={() => setBatchFiles((prev) => prev.filter((_, j) => j !== i))}
                                                    className="p-1 rounded hover:bg-white/10 text-zinc-500 hover:text-white transition-colors"
                                                    aria-label={`Remove ${f.name}`}
                                                >
                                                    <X size={12} />
                                                </button>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>

                            <div className="flex items-center justify-between px-1 pt-1 border-t border-white/5">
                                <p className="text-[11px] text-zinc-500">
                                    Total items
                                </p>
                                <p className={`text-[11px] font-medium ${batchTotal > 20 ? 'text-red-400' : batchTotal > 0 ? 'text-zinc-300' : 'text-zinc-600'}`}>
                                    {batchTotal} / 20
                                </p>
                            </div>
                        </div>
                    )}

                    {/* AI Instructions (collapsible) */}
                    <div className="rounded-xl border border-white/5 overflow-hidden">
                        <button
                            type="button"
                            onClick={() => setShowAdvanced(!showAdvanced)}
                            className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition-colors"
                        >
                            <span className="flex items-center gap-2 text-[11px] font-medium text-zinc-400">
                                <Sparkles size={13} className="text-purple-400/70" />
                                AI Instructions
                            </span>
                            <ChevronDown size={14} className={`text-zinc-600 transition-transform duration-200 ${showAdvanced ? 'rotate-180' : ''}`} />
                        </button>
                        {showAdvanced && (
                            <div className="px-4 pb-4 space-y-2 animate-fade-in">
                                <textarea
                                    value={instructions}
                                    onChange={(e) => setInstructions(e.target.value)}
                                    placeholder="Guide the AI... e.g. 'Find the funniest moments' or 'Focus on the cooking parts, skip the intro'"
                                    className="w-full bg-white/[0.03] border border-white/5 rounded-lg px-4 py-3 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-transparent resize-none h-20 transition-all"
                                    maxLength={500}
                                />
                                <p className="text-[11px] text-zinc-600 px-0.5">Optional. Helps the AI find specific types of clips.</p>
                            </div>
                        )}
                    </div>

                    {/* Clip Options (collapsible) */}
                    <div className="rounded-xl border border-white/5 overflow-hidden">
                        <button
                            type="button"
                            onClick={() => setShowPreselections(!showPreselections)}
                            className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition-colors"
                        >
                            <span className="flex items-center gap-2 text-[11px] font-medium text-zinc-400">
                                <Settings size={13} className="text-blue-400/70" />
                                Clip Options
                            </span>
                            <ChevronDown size={14} className={`text-zinc-600 transition-transform duration-200 ${showPreselections ? 'rotate-180' : ''}`} />
                        </button>

                        {showPreselections && (
                            <div className="px-4 pb-4 space-y-4 animate-fade-in">

                                {/* Reframe Mode */}
                                <div className="space-y-2">
                                    <p className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">Reframe Mode</p>
                                    <div className="flex gap-2">
                                        {[
                                            { value: 'auto', label: 'Auto Reframe' },
                                            { value: 'disabled', label: 'Disabled (4:3)' },
                                        ].map(({ value, label }) => (
                                            <button
                                                key={value}
                                                type="button"
                                                onClick={() => setReframeMode(value)}
                                                className={`flex-1 py-2 px-3 rounded-lg text-xs font-medium border transition-all ${
                                                    reframeMode === value
                                                        ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                                        : 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300 hover:bg-white/[0.04]'
                                                }`}
                                            >
                                                {label}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                {/* Smart Cut */}
                                <div className="flex items-center justify-between py-1">
                                    <span className="text-[12px] font-medium text-zinc-300">Smart Cut</span>
                                    <button
                                        type="button"
                                        onClick={() => setPreSmartCut(!preSmartCut)}
                                        aria-checked={preSmartCut}
                                        role="switch"
                                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 ${
                                            preSmartCut ? 'bg-accent-pink/60' : 'bg-white/10'
                                        }`}
                                    >
                                        <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform ${preSmartCut ? 'translate-x-4' : 'translate-x-1'}`} />
                                    </button>
                                </div>

                                {/* Subtitles */}
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between py-1">
                                        <div className="flex items-center gap-2">
                                            <span className="text-[12px] font-medium text-zinc-300">Subtitles</span>
                                            {preSubtitles && (
                                                <button
                                                    type="button"
                                                    onClick={() => setShowSubConfig(!showSubConfig)}
                                                    className={`p-1 rounded transition-colors ${showSubConfig ? 'text-accent-pink' : 'text-zinc-500 hover:text-zinc-300'}`}
                                                    aria-label="Configure subtitles"
                                                >
                                                    <Settings size={12} />
                                                </button>
                                            )}
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => setPreSubtitles(!preSubtitles)}
                                            aria-checked={preSubtitles}
                                            role="switch"
                                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 ${
                                                preSubtitles ? 'bg-accent-pink/60' : 'bg-white/10'
                                            }`}
                                        >
                                            <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform ${preSubtitles ? 'translate-x-4' : 'translate-x-1'}`} />
                                        </button>
                                    </div>

                                    {preSubtitles && showSubConfig && (
                                        <div className="bg-white/[0.02] border border-white/5 rounded-lg p-3 space-y-3 animate-fade-in">
                                            {/* Mode (first — drives whether preset picker is shown) */}
                                            <div className="space-y-1.5">
                                                <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">Mode</p>
                                                <div className="flex gap-2">
                                                    {['karaoke', 'classic'].map(m => (
                                                        <button
                                                            key={m}
                                                            type="button"
                                                            onClick={() => setPreSubMode(m)}
                                                            className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium border transition-all ${
                                                                preSubMode === m
                                                                    ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                                                    : 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300 hover:bg-white/[0.04]'
                                                            }`}
                                                        >
                                                            {m.charAt(0).toUpperCase() + m.slice(1)}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>

                                            {/* Preset — only meaningful in karaoke mode (classic uses font/color params) */}
                                            {preSubMode === 'karaoke' ? (
                                                <div className="space-y-1.5">
                                                    <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">Karaoke Preset</p>
                                                    <div className="grid grid-cols-2 gap-1.5">
                                                        {SUBTITLE_PRESETS.map((p) => {
                                                            const isActive = preSubPreset === p.id;
                                                            return (
                                                                <button
                                                                    key={p.id}
                                                                    type="button"
                                                                    onClick={() => setPreSubPreset(p.id)}
                                                                    className={`relative rounded-lg border overflow-hidden transition-all ${
                                                                        isActive
                                                                            ? 'border-accent-pink/50 bg-white/[0.06]'
                                                                            : 'border-white/5 bg-white/[0.02] hover:border-white/10'
                                                                    }`}
                                                                >
                                                                    <div className="px-2 py-2.5 flex items-center justify-center min-h-[44px]">
                                                                        <span style={p.previewStyle} className="text-[11px] font-bold leading-tight text-center">
                                                                            WORD <span style={{ color: p.highlight }}>UP</span>
                                                                        </span>
                                                                    </div>
                                                                    <div className="px-1.5 py-1 bg-black/40 border-t border-white/5">
                                                                        <p className={`text-[9px] uppercase tracking-wider truncate ${isActive ? 'text-accent-pink' : 'text-zinc-500'}`}>{p.label}</p>
                                                                    </div>
                                                                </button>
                                                            );
                                                        })}
                                                    </div>
                                                </div>
                                            ) : (
                                                <div className="rounded-lg bg-white/[0.02] border border-white/5 px-3 py-2.5">
                                                    <p className="text-[10px] text-zinc-500 leading-relaxed">
                                                        Classic mode uses standard SRT subtitles with default styling.
                                                        Font, color and outline are configurable per-clip from the
                                                        captions modal after generation.
                                                    </p>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                {/* Hook */}
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between py-1">
                                        <div className="flex items-center gap-2">
                                            <span className="text-[12px] font-medium text-zinc-300">Hook</span>
                                            {preHook && (
                                                <button
                                                    type="button"
                                                    onClick={() => setShowHookConfig(!showHookConfig)}
                                                    className={`p-1 rounded transition-colors ${showHookConfig ? 'text-accent-pink' : 'text-zinc-500 hover:text-zinc-300'}`}
                                                    aria-label="Configure hook"
                                                >
                                                    <Settings size={12} />
                                                </button>
                                            )}
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => setPreHook(!preHook)}
                                            aria-checked={preHook}
                                            role="switch"
                                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 ${
                                                preHook ? 'bg-accent-pink/60' : 'bg-white/10'
                                            }`}
                                        >
                                            <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform ${preHook ? 'translate-x-4' : 'translate-x-1'}`} />
                                        </button>
                                    </div>

                                    {preHook && showHookConfig && (
                                        <div className="bg-white/[0.02] border border-white/5 rounded-lg p-3 space-y-3 animate-fade-in">
                                            {/* Position */}
                                            <div className="space-y-1.5">
                                                <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">Position</p>
                                                <div className="flex gap-2">
                                                    {['top', 'center', 'bottom'].map(pos => (
                                                        <button
                                                            key={pos}
                                                            type="button"
                                                            onClick={() => setPreHookPosition(pos)}
                                                            className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium border transition-all ${
                                                                preHookPosition === pos
                                                                    ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                                                    : 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300 hover:bg-white/[0.04]'
                                                            }`}
                                                        >
                                                            {pos.charAt(0).toUpperCase() + pos.slice(1)}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>
                                            {/* Size */}
                                            <div className="space-y-1.5">
                                                <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">Size</p>
                                                <div className="flex gap-2">
                                                    {['S', 'M', 'L'].map(sz => (
                                                        <button
                                                            key={sz}
                                                            type="button"
                                                            onClick={() => setPreHookSize(sz)}
                                                            className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium border transition-all ${
                                                                preHookSize === sz
                                                                    ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                                                    : 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300 hover:bg-white/[0.04]'
                                                            }`}
                                                        >
                                                            {sz}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>

                            </div>
                        )}
                    </div>

                    {/* Submit Button */}
                    <button
                        type="submit"
                        disabled={isDisabled}
                        className={`w-full py-4 rounded-xl font-semibold text-[15px] tracking-wide transition-all duration-300 flex items-center justify-center gap-2.5 ${
                            isDisabled
                                ? 'bg-zinc-800/50 text-zinc-600 cursor-not-allowed'
                                : 'bg-gradient-to-r from-pink-500 to-purple-600 hover:from-pink-400 hover:to-purple-500 text-white shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 active:scale-[0.98]'
                        }`}
                    >
                        {isProcessing ? (
                            <>
                                <Loader2 size={20} className="animate-spin" />
                                <span>Processing...</span>
                            </>
                        ) : (
                            <span>{mode === 'batch' ? 'Launch Batch' : 'Start Processing'}</span>
                        )}
                    </button>
                </form>
            </div>
        </div>
    );
}
