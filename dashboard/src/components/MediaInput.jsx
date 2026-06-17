import React, { useState, useRef, useEffect } from 'react';
import { Youtube, Upload, FileVideo, X, Globe, FileUp, Loader2, ChevronDown, Sparkles, Layers, Clipboard, Settings } from 'lucide-react';

/**
 * Segmented button group — used for tabs (Single/Batch), source
 * picker (URL/Upload), mode picker (Karaoke/Classic), size/position
 * pickers. Single consistent style across the whole create box.
 *
 * @param {{
 *   options: Array<{ id: string, label: string, icon?: React.ComponentType<{ size?: number }> }>,
 *   value: string,
 *   onChange: (id: string) => void,
 *   size?: 'sm' | 'md',
 *   fullWidth?: boolean,
 * }} props
 */
function Segmented({ options, value, onChange, size = 'md', fullWidth = false }) {
    const height = size === 'sm' ? 'h-8' : 'h-10';
    const px = size === 'sm' ? 'px-3' : 'px-4';
    return (
        <div
            className={`inline-flex border border-white/[0.08] rounded-[3px] bg-white/[0.02] p-0.5 ${
                fullWidth ? 'w-full' : ''
            }`}
            role="tablist"
        >
            {options.map(({ id, label, icon: Icon }) => {
                const active = value === id;
                return (
                    <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        onClick={() => onChange(id)}
                        className={`${fullWidth ? 'flex-1' : ''} ${height} ${px} flex items-center justify-center gap-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/60 ${
                            active
                                ? 'bg-[oklch(74%_0.175_62)] text-[oklch(14%_0.01_260)] font-semibold'
                                : 'text-zinc-500 hover:text-zinc-200'
                        }`}
                    >
                        {Icon && <Icon size={13} strokeWidth={active ? 2.2 : 1.8} />}
                        {label}
                    </button>
                );
            })}
        </div>
    );
}

/**
 * Editorial-styled iOS-style toggle switch. Whole row is clickable,
 * 44px minimum touch target, amber accent when on, aria-compliant.
 *
 * @param {{
 *   label: string,
 *   description?: string,
 *   checked: boolean,
 *   onChange: (next: boolean) => void,
 *   onConfigure?: () => void,
 *   configureActive?: boolean,
 * }} props
 */
function SwitchRow({ label, description, checked, onChange, onConfigure, configureActive }) {
    // A single <button role="switch"> would be ideal for a11y, but we
    // want the label + description to also be clickable. We render the
    // label block as a plain clickable div (aria-hidden from the a11y
    // tree) and put the real role="switch" only on the thumb element
    // below, so screen readers see exactly one switch per row.
    return (
        <div className="flex items-center justify-between gap-3 min-h-[44px]">
            <div
                onClick={() => onChange(!checked)}
                className="flex-1 flex items-center gap-2.5 text-left rounded-[3px] py-1 px-1 -mx-1 hover:bg-white/[0.02] cursor-pointer"
                aria-hidden
            >
                <span
                    aria-hidden
                    className={`w-1.5 h-1.5 rounded-full shrink-0 transition-all ${
                        checked
                            ? 'bg-[oklch(74%_0.175_62)] shadow-[0_0_6px_oklch(74%_0.175_62/0.85)]'
                            : 'bg-zinc-700'
                    }`}
                />
                <div className="flex flex-col min-w-0">
                    <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-zinc-200 leading-tight">
                        {label}
                    </span>
                    {description && (
                        <span className="text-[10px] text-zinc-500 leading-tight mt-0.5 truncate">
                            {description}
                        </span>
                    )}
                </div>
            </div>
            {onConfigure && checked && (
                <button
                    type="button"
                    onClick={onConfigure}
                    aria-label={`Configure ${label}`}
                    className={`w-9 h-9 flex items-center justify-center rounded-[3px] border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/60 ${
                        configureActive
                            ? 'bg-[oklch(74%_0.175_62)]/[0.14] border-[oklch(74%_0.175_62)]/50 text-[oklch(82%_0.16_68)]'
                            : 'bg-white/[0.02] border-white/[0.08] text-zinc-400 hover:text-white hover:border-white/[0.2]'
                    }`}
                >
                    <Settings size={13} strokeWidth={1.8} />
                </button>
            )}
            <button
                type="button"
                onClick={() => onChange(!checked)}
                role="switch"
                aria-checked={checked}
                aria-label={label}
                className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background ${
                    checked
                        ? 'bg-[oklch(74%_0.175_62)] shadow-[inset_0_1px_2px_oklch(60%_0.18_55/0.5),0_0_10px_-2px_oklch(74%_0.175_62/0.5)]'
                        : 'bg-white/[0.08] border border-white/[0.06]'
                }`}
            >
                <span
                    aria-hidden
                    className={`inline-block h-4 w-4 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.4)] transition-transform duration-200 ${
                        checked ? 'translate-x-6' : 'translate-x-1'
                    }`}
                />
            </button>
        </div>
    );
}

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

export default function MediaInput({ onProcess, onBatchProcess, isProcessing }) {
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

    // Pre-selection state persisted to localStorage so users don't lose their
    // Advanced Options choices when they refocus the window / navigate tabs.
    const PRESELECT_LS_KEY = 'clippyme_preselections_v3';
    const loadPersisted = () => {
        try {
            const raw = localStorage.getItem(PRESELECT_LS_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch {
            return {};
        }
    };
    const persisted = loadPersisted();

    // Auto Reframe default is 'auto' (ON) to match the backend argparse
    // default AND the name of the feature itself — a toggle labeled
    // "Auto Reframe" should start enabled, or users wonder why the
    // flagship AI feature is off by default.
    const [reframeMode, setReframeMode] = useState(persisted.reframeMode ?? 'auto');
    const [preSmartCut, setPreSmartCut] = useState(persisted.preSmartCut ?? false);
    const [preSubtitles, setPreSubtitles] = useState(persisted.preSubtitles ?? false);
    const [preSubPreset, setPreSubPreset] = useState(persisted.preSubPreset ?? 'classic_white');
    const [preSubMode, setPreSubMode] = useState(persisted.preSubMode ?? 'karaoke');
    const [showSubConfig, setShowSubConfig] = useState(false);
    // Classic-mode pre-selection controls
    const [preSubClassicFont, setPreSubClassicFont] = useState(persisted.preSubClassicFont ?? 'Verdana');
    const [preSubClassicFontColor, setPreSubClassicFontColor] = useState(persisted.preSubClassicFontColor ?? '#FFFFFF');
    // Subtitle position default is 'bottom' (standard caption placement).
    // We DO restore it from localStorage v3+ so user choices persist across
    // sessions — earlier versions force-overrode on mount to flush stale
    // data that leaked from an obsolete LS schema.
    const [preSubClassicPosition, setPreSubClassicPosition] = useState(persisted.preSubClassicPosition ?? 'bottom');
    // Classic subtitles stroke + background (matches backend burn_subtitles params)
    const [preSubClassicBorderColor, setPreSubClassicBorderColor] = useState(persisted.preSubClassicBorderColor ?? '#000000');
    const [preSubClassicBorderWidth, setPreSubClassicBorderWidth] = useState(persisted.preSubClassicBorderWidth ?? 2);
    const [preSubClassicBgColor, setPreSubClassicBgColor] = useState(persisted.preSubClassicBgColor ?? '#000000');
    const [preSubClassicBgOpacity, setPreSubClassicBgOpacity] = useState(persisted.preSubClassicBgOpacity ?? 0);
    const [preHook, setPreHook] = useState(persisted.preHook ?? false);
    // Hook position default is 'top' (the teaser sits above the action).
    const [preHookPosition, setPreHookPosition] = useState(persisted.preHookPosition ?? 'top');
    const [preHookSize, setPreHookSize] = useState(persisted.preHookSize ?? 'S');
    const [showHookConfig, setShowHookConfig] = useState(false);
    // Per-job ASR language override. Default 'multi' uses Deepgram Nova-3
    // code-switching. When the user knows the video is single-language,
    // picking an explicit code boosts accuracy AND makes diarization
    // reliable — 'multi' has known edge cases on speaker counting.
    // Language default is 'multi' (Deepgram Nova-3 code-switching) for
    // global audiences. Restored from localStorage v3+ so a user who picks
    // 'en' or 'it' explicitly doesn't have to re-select on every mount.
    const [preLanguage, setPreLanguage] = useState(persisted.preLanguage ?? 'multi');
    // Per-job Gemini model override. '' = use the global Settings model
    // (default gemini-2.5-flash). Lets the user pick a stronger/cheaper model
    // for THIS run without touching Settings.
    const [preModel, setPreModel] = useState(persisted.preModel ?? '');

    // Subtle Ken Burns zoom (1.0→1.05x) applied to each clip. Default ON
    // because it noticeably improves retention on static-shot content.
    // The UI toggles the positive sense; the backend receives `no_zoom`
    // (negated) via the `preselections.no_zoom` field.
    const [preSubtleZoom, setPreSubtleZoom] = useState(persisted.preSubtleZoom ?? true);
    // AI viral-clip detection (Gemini). Default ON. When OFF the pipeline
    // skips analysis and converts the whole input video to 9:16
    // (main.py --skip-analysis). Useful when the user already has a
    // pre-trimmed clip and just wants the reframe + post-processing.
    const [preAiDetection, setPreAiDetection] = useState(persisted.preAiDetection ?? true);

    // Persist whenever any pre-selection changes.
    useEffect(() => {
        try {
            localStorage.setItem(
                PRESELECT_LS_KEY,
                JSON.stringify({
                    reframeMode,
                    preSmartCut,
                    preSubtitles,
                    preSubPreset,
                    preSubMode,
                    preSubClassicFont,
                    preSubClassicFontColor,
                    preSubClassicPosition,
                    preSubClassicBorderColor,
                    preSubClassicBorderWidth,
                    preSubClassicBgColor,
                    preSubClassicBgOpacity,
                    preHook,
                    preHookPosition,
                    preHookSize,
                    preLanguage,
                    preModel,
                    preSubtleZoom,
                    preAiDetection,
                })
            );
        } catch {
            // localStorage full / disabled — silent fail
        }
    }, [
        reframeMode,
        preSmartCut,
        preSubtitles,
        preSubPreset,
        preSubMode,
        preSubClassicFont,
        preSubClassicFontColor,
        preSubClassicPosition,
        preSubClassicBorderColor,
        preSubClassicBorderWidth,
        preSubClassicBgColor,
        preSubClassicBgOpacity,
        preHook,
        preHookPosition,
        preHookSize,
        preLanguage,
        preModel,
        preSubtleZoom,
        preAiDetection,
    ]);

    const handleSubmit = (e) => {
        e.preventDefault();
        const preselections = {
            reframe_mode: reframeMode,
            smartcut: preSmartCut,
            subtitles: preSubtitles
                ? (preSubMode === 'karaoke'
                    ? {
                        mode: 'karaoke',
                        preset: preSubPreset,
                        position: preSubClassicPosition,
                      }
                    : {
                        mode: 'classic',
                        font: preSubClassicFont,
                        font_color: preSubClassicFontColor,
                        position: preSubClassicPosition,
                        border_color: preSubClassicBorderColor,
                        border_width: preSubClassicBorderWidth,
                        bg_color: preSubClassicBgColor,
                        bg_opacity: preSubClassicBgOpacity,
                      })
                : null,
            hook: preHook ? { position: preHookPosition, size: preHookSize } : null,
            language: preLanguage && preLanguage !== 'multi' ? preLanguage : undefined,
            // Per-job LLM override ('' → backend uses the global Settings model).
            model: preModel || undefined,
            // Backend flags — inverted from the positive UI labels.
            no_zoom: !preSubtleZoom,
            skip_analysis: !preAiDetection,
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
        <div className="relative bg-[oklch(14%_0.009_260)] border border-white/[0.08] rounded-[3px] overflow-hidden animate-fade-in shadow-[0_32px_80px_-40px_oklch(0%_0_0/0.9),0_0_0_1px_oklch(100%_0_0/0.02)]">
            {/* Slate header */}
            <div className="flex items-center justify-between px-5 h-9 border-b border-white/[0.06] bg-white/[0.015]">
                <div className="flex items-center gap-2 type-mono text-[10px] text-zinc-500 uppercase tracking-[0.16em]">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-[oklch(74%_0.175_62)] shadow-[0_0_6px_oklch(74%_0.175_62/0.6)]" />
                    New&nbsp;job
                </div>
                <Segmented
                    options={tabs}
                    value={mode}
                    onChange={setMode}
                    size="sm"
                />
            </div>

            {/* Content */}
            <div className="p-6">
                <form onSubmit={handleSubmit} className="space-y-5">

                    {/* Single Mode — URL or File via inner toggle */}
                    {mode === 'single' && (
                        <div className="space-y-4">
                            {/* Source toggle */}
                            <Segmented
                                options={[
                                    { id: 'url', label: 'URL', icon: Globe },
                                    { id: 'file', label: 'Upload', icon: FileUp },
                                ]}
                                value={singleSource}
                                onChange={setSingleSource}
                                size="sm"
                            />

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
                                            placeholder="Paste a YouTube or video URL…"
                                            className="w-full bg-white/[0.03] border border-white/[0.09] rounded-[3px] pl-12 pr-24 py-4 text-[15px] text-white placeholder:text-zinc-600 placeholder:italic focus:outline-none focus:border-[oklch(74%_0.175_62)]/60 focus:ring-[3px] focus:ring-[oklch(74%_0.175_62)]/15 transition-all"
                                        />
                                        <button
                                            type="button"
                                            onClick={handlePaste}
                                            className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1.5 px-3 h-8 rounded-[3px] bg-white/[0.04] border border-white/[0.08] hover:bg-white/[0.08] hover:border-white/[0.15] text-zinc-300 hover:text-white font-mono text-[10px] uppercase tracking-[0.12em] transition-all"
                                        >
                                            <Clipboard size={12} strokeWidth={1.8} />
                                            Paste
                                        </button>
                                    </div>

                                </>
                            ) : (
                                <div
                                    className={`border-2 border-dashed rounded-[3px] p-10 text-center transition-all duration-300 relative group cursor-pointer ${
                                        file
                                            ? 'border-[oklch(68%_0.18_145)]/40 bg-[oklch(68%_0.18_145)]/[0.05]'
                                            : isDragging
                                                ? 'border-[oklch(74%_0.175_62)]/60 bg-[oklch(74%_0.175_62)]/[0.06] shadow-[0_0_40px_-10px_oklch(74%_0.175_62/0.3)]'
                                                : 'border-white/[0.1] hover:border-[oklch(74%_0.175_62)]/40 bg-white/[0.015]'
                                    }`}
                                    onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                                    onDragLeave={() => setIsDragging(false)}
                                    onDrop={handleDrop}
                                >
                                    {file ? (
                                        <div className="flex flex-col items-center gap-3">
                                            <div className="w-14 h-14 rounded-[3px] bg-[oklch(68%_0.18_145)]/[0.1] flex items-center justify-center text-[oklch(78%_0.17_145)] border border-[oklch(68%_0.18_145)]/30">
                                                <FileVideo size={26} strokeWidth={1.6} />
                                            </div>
                                            <div className="text-center">
                                                <p className="text-white font-medium text-sm truncate max-w-[260px]">{file.name}</p>
                                                <p className="type-label mt-1">Ready</p>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => setFile(null)}
                                                aria-label="Remove selected file"
                                                className="mt-1 flex items-center gap-1.5 h-9 px-3 rounded-[3px] border border-white/[0.1] hover:border-white/[0.2] hover:bg-white/[0.04] text-zinc-400 hover:text-white font-mono text-[10px] uppercase tracking-[0.12em] transition-all"
                                            >
                                                <X size={12} strokeWidth={2} />
                                                Remove
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
                                            <div className="w-14 h-14 rounded-[3px] bg-white/[0.03] flex items-center justify-center text-zinc-500 group-hover:text-[oklch(82%_0.16_68)] group-hover:bg-[oklch(74%_0.175_62)]/[0.08] border border-white/[0.1] group-hover:border-[oklch(74%_0.175_62)]/40 transition-all duration-300">
                                                <Upload size={24} strokeWidth={1.6} />
                                            </div>
                                            <div className="text-center">
                                                <p className="text-zinc-200 font-medium text-sm">Drop your video here or click to browse</p>
                                                <p className="type-label mt-1.5">MP4 · MOV · WEBM · up to 2GB</p>
                                            </div>
                                        </label>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Batch Mode — URLs textarea + multi-file upload */}
                    {mode === 'batch' && (
                        <div className="space-y-5">
                            {/* URLs textarea */}
                            <div className="space-y-2">
                                <label htmlFor="batch-urls" className="type-label flex items-center gap-1.5">
                                    <Globe size={10} strokeWidth={1.8} /> URLs
                                </label>
                                <textarea
                                    id="batch-urls"
                                    value={batchUrls}
                                    onChange={(e) => setBatchUrls(e.target.value)}
                                    placeholder={"https://youtube.com/watch?v=abc\nhttps://youtube.com/watch?v=def"}
                                    className="w-full bg-white/[0.03] border border-white/[0.09] rounded-[3px] px-4 py-3.5 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-[oklch(74%_0.175_62)]/60 focus:ring-[3px] focus:ring-[oklch(74%_0.175_62)]/15 resize-none h-24 font-mono leading-relaxed transition-all"
                                    maxLength={5000}
                                />
                                <p className="type-label !normal-case !tracking-normal !text-zinc-600 !font-sans px-1">One URL per line</p>
                            </div>

                            {/* File uploads */}
                            <div className="space-y-2">
                                <label className="type-label flex items-center gap-1.5">
                                    <FileUp size={10} strokeWidth={1.8} /> Files
                                </label>
                                <div
                                    className={`border-2 border-dashed rounded-[3px] p-5 text-center transition-all duration-300 cursor-pointer ${
                                        isDragging
                                            ? 'border-[oklch(74%_0.175_62)]/60 bg-[oklch(74%_0.175_62)]/[0.06]'
                                            : 'border-white/[0.1] hover:border-[oklch(74%_0.175_62)]/40 bg-white/[0.015]'
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
                                        <Upload size={18} strokeWidth={1.6} className="text-zinc-500" />
                                        <p className="text-xs text-zinc-400">Drop videos or click to add (multiple)</p>
                                    </label>
                                </div>

                                {batchFiles.length > 0 && (
                                    <ul className="space-y-1 max-h-40 overflow-y-auto pr-1">
                                        {batchFiles.map((f, i) => (
                                            <li key={`${f.name}-${i}`} className="flex items-center gap-2.5 px-3 h-9 rounded-[3px] bg-white/[0.025] border border-white/[0.06]">
                                                <FileVideo size={12} strokeWidth={1.8} className="text-[oklch(78%_0.17_145)] flex-shrink-0" />
                                                <span className="text-[11px] text-zinc-300 truncate flex-1 font-mono">{f.name}</span>
                                                <button
                                                    type="button"
                                                    onClick={() => setBatchFiles((prev) => prev.filter((_, j) => j !== i))}
                                                    className="w-6 h-6 flex items-center justify-center rounded-[2px] hover:bg-white/10 text-zinc-500 hover:text-white transition-colors"
                                                    aria-label={`Remove ${f.name}`}
                                                >
                                                    <X size={11} strokeWidth={2} />
                                                </button>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>

                            <div className="flex items-center justify-between pt-2 border-t border-white/[0.06] type-label">
                                <span>Total items</span>
                                <span className={`tabular-nums ${batchTotal > 20 ? 'text-[oklch(70%_0.22_25)]' : batchTotal > 0 ? 'text-[oklch(82%_0.16_68)]' : 'text-zinc-600'}`}>
                                    {String(batchTotal).padStart(2, '0')}&nbsp;/&nbsp;20
                                </span>
                            </div>
                        </div>
                    )}

                    {/* Advanced options drawer — AI Instructions + Clip Options */}
                    <div className="rounded-[3px] border border-white/[0.08] overflow-hidden">
                        <button
                            type="button"
                            onClick={() => setShowAdvanced(!showAdvanced)}
                            aria-expanded={showAdvanced}
                            className="w-full flex items-center justify-between px-4 h-11 hover:bg-white/[0.025] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/50 focus-visible:ring-inset"
                        >
                            <span className="flex items-center gap-2.5">
                                <Settings size={12} strokeWidth={1.8} className="text-zinc-500" />
                                <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-zinc-300">
                                    Advanced options
                                </span>
                                {(instructions.trim() || preSmartCut || preSubtitles || preHook || reframeMode !== 'disabled') && (
                                    <span className="inline-flex items-center gap-1 font-mono text-[9px] px-1.5 py-0.5 rounded-[2px] border border-[oklch(74%_0.175_62)]/40 text-[oklch(82%_0.16_68)] uppercase tracking-[0.14em]">
                                        <span className="w-1 h-1 rounded-full bg-[oklch(74%_0.175_62)] shadow-[0_0_4px_oklch(74%_0.175_62/0.8)]" />
                                        Custom
                                    </span>
                                )}
                            </span>
                            <ChevronDown size={14} strokeWidth={1.8} className={`text-zinc-500 transition-transform duration-200 ${showAdvanced ? 'rotate-180' : ''}`} />
                        </button>
                        {showAdvanced && (
                            <div className="px-5 pb-5 space-y-6 animate-fade-in border-t border-white/[0.06] pt-5">
                                {/* Section: AI Instructions */}
                                <div className="space-y-2">
                                    <div className="flex items-center gap-2 type-label">
                                        <Sparkles size={10} strokeWidth={1.8} className="text-[oklch(74%_0.175_62)]" />
                                        AI Instructions
                                    </div>
                                    <textarea
                                        value={instructions}
                                        onChange={(e) => setInstructions(e.target.value)}
                                        placeholder="Guide the AI… e.g. 'Find the funniest moments' or 'Focus on the cooking parts, skip the intro'"
                                        className="w-full bg-white/[0.03] border border-white/[0.09] rounded-[3px] px-4 py-3 text-sm text-white placeholder:text-zinc-600 placeholder:italic focus:outline-none focus:border-[oklch(74%_0.175_62)]/60 focus:ring-[3px] focus:ring-[oklch(74%_0.175_62)]/15 resize-none h-20 transition-all"
                                        maxLength={500}
                                    />
                                    <p className="text-[11px] text-zinc-600 px-0.5">Optional. Helps the AI find specific types of clips.</p>
                                </div>

                                {/* Section: Clip Options */}
                                <div className="space-y-3">
                                    <div className="flex items-center gap-3 type-label">
                                        <span className="text-[oklch(74%_0.175_62)]">§</span>
                                        Clip options
                                        <hr className="hairline flex-1" />
                                    </div>

                                {/* Auto Reframe — single toggle. ON = face tracking in
                                    a 9:16 vertical frame. OFF = original footage
                                    placed inside a 9:16 frame with black letterbox
                                    bars top & bottom (NOT a crop). Terminology is
                                    kept consistent with ResultCard so users never
                                    see '4:3' language that made them think the
                                    output was a crop. */}
                                <SwitchRow
                                    label="Auto Reframe"
                                    description={
                                        reframeMode === 'auto'
                                            ? 'ON · face tracking in a 9:16 frame'
                                            : 'OFF · letterbox (black bars top & bottom)'
                                    }
                                    checked={reframeMode === 'auto'}
                                    onChange={(next) => setReframeMode(next ? 'auto' : 'disabled')}
                                />

                                {/* AI clip detection (Gemini). OFF → --skip-analysis
                                    turns the whole video into a single 9:16 clip. */}
                                <SwitchRow
                                    label="AI clip detection"
                                    description={
                                        preAiDetection
                                            ? 'ON · Gemini picks the viral moments'
                                            : 'OFF · convert the entire video (skip analysis)'
                                    }
                                    checked={preAiDetection}
                                    onChange={setPreAiDetection}
                                />

                                {/* Subtle Ken Burns zoom (1.0→1.05x). OFF → --no-zoom. */}
                                <SwitchRow
                                    label="Subtle zoom"
                                    description={
                                        preSubtleZoom
                                            ? 'ON · gentle Ken Burns (1.0→1.05x)'
                                            : 'OFF · static frames, no motion added'
                                    }
                                    checked={preSubtleZoom}
                                    onChange={setPreSubtleZoom}
                                />

                                {/* Spoken language override — default 'multi' uses Nova-3
                                    code-switching (EN+IT native). Pick a single language
                                    for better accuracy AND reliable speaker diarization. */}
                                <div className="space-y-1.5">
                                    <div className="flex items-center justify-between gap-3">
                                        <label
                                            htmlFor="clip-language"
                                            className="type-label !text-zinc-300"
                                        >
                                            Spoken language
                                        </label>
                                        <span className="type-mono text-[9px] text-zinc-600 normal-case tracking-normal">
                                            {preLanguage === 'multi'
                                                ? 'Auto (code-switching)'
                                                : `Forced · ${preLanguage}`}
                                        </span>
                                    </div>
                                    <select
                                        id="clip-language"
                                        value={preLanguage}
                                        onChange={(e) => setPreLanguage(e.target.value)}
                                        className="w-full bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.16] focus:border-[oklch(74%_0.175_62)]/55 text-zinc-200 text-[12px] font-mono uppercase tracking-[0.1em] px-3 h-9 rounded-[3px] cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/45 appearance-none"
                                    >
                                        <option value="multi" className="bg-[oklch(9%_0.006_260)]">
                                            Multi-language
                                        </option>
                                        <option value="en" className="bg-[oklch(9%_0.006_260)]">English (en)</option>
                                        <option value="it" className="bg-[oklch(9%_0.006_260)]">Italiano (it)</option>
                                        <option value="es" className="bg-[oklch(9%_0.006_260)]">Español (es)</option>
                                        <option value="fr" className="bg-[oklch(9%_0.006_260)]">Français (fr)</option>
                                        <option value="de" className="bg-[oklch(9%_0.006_260)]">Deutsch (de)</option>
                                        <option value="pt" className="bg-[oklch(9%_0.006_260)]">Português (pt)</option>
                                        <option value="nl" className="bg-[oklch(9%_0.006_260)]">Nederlands (nl)</option>
                                        <option value="pl" className="bg-[oklch(9%_0.006_260)]">Polski (pl)</option>
                                        <option value="tr" className="bg-[oklch(9%_0.006_260)]">Türkçe (tr)</option>
                                        <option value="ru" className="bg-[oklch(9%_0.006_260)]">Русский (ru)</option>
                                        <option value="ja" className="bg-[oklch(9%_0.006_260)]">日本語 (ja)</option>
                                        <option value="ko" className="bg-[oklch(9%_0.006_260)]">한국어 (ko)</option>
                                        <option value="zh" className="bg-[oklch(9%_0.006_260)]">中文 (zh)</option>
                                        <option value="hi" className="bg-[oklch(9%_0.006_260)]">हिन्दी (hi)</option>
                                        <option value="uk" className="bg-[oklch(9%_0.006_260)]">Українська (uk)</option>
                                        <option value="sv" className="bg-[oklch(9%_0.006_260)]">Svenska (sv)</option>
                                        <option value="da" className="bg-[oklch(9%_0.006_260)]">Dansk (da)</option>
                                        <option value="nb" className="bg-[oklch(9%_0.006_260)]">Norsk (nb)</option>
                                        <option value="fi" className="bg-[oklch(9%_0.006_260)]">Suomi (fi)</option>
                                        <option value="el" className="bg-[oklch(9%_0.006_260)]">Ελληνικά (el)</option>
                                    </select>
                                    <p className="text-[10px] text-zinc-600 leading-snug">
                                        Leave on <span className="text-zinc-400">Multi</span> for mixed-language videos.
                                        Pick a single language when you know the video is only in one —
                                        it improves transcription accuracy and speaker diarization.
                                    </p>
                                </div>

                                {/* AI model override — which Gemini model detects the
                                    viral moments. Default uses the global Settings model;
                                    pick Pro for sharper picks or Flash-Lite for cheapest.
                                    The full live model list lives in Settings. */}
                                <div className="space-y-1.5">
                                    <div className="flex items-center justify-between gap-3">
                                        <label htmlFor="clip-model" className="type-label !text-zinc-300">
                                            AI model
                                        </label>
                                        <span className="type-mono text-[9px] text-zinc-600 normal-case tracking-normal">
                                            {preModel ? `This job · ${preModel}` : 'Default (Settings)'}
                                        </span>
                                    </div>
                                    <select
                                        id="clip-model"
                                        value={preModel}
                                        onChange={(e) => setPreModel(e.target.value)}
                                        className="w-full bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.16] focus:border-[oklch(74%_0.175_62)]/55 text-zinc-200 text-[12px] font-mono uppercase tracking-[0.1em] px-3 h-9 rounded-[3px] cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/45 appearance-none"
                                    >
                                        <option value="" className="bg-[oklch(9%_0.006_260)]">Default (use Settings)</option>
                                        <option value="gemini-2.5-flash" className="bg-[oklch(9%_0.006_260)]">Gemini 2.5 Flash · balanced</option>
                                        <option value="gemini-2.5-pro" className="bg-[oklch(9%_0.006_260)]">Gemini 2.5 Pro · sharpest</option>
                                        <option value="gemini-2.5-flash-lite" className="bg-[oklch(9%_0.006_260)]">Gemini 2.5 Flash-Lite · cheapest</option>
                                    </select>
                                    <p className="text-[10px] text-zinc-600 leading-snug">
                                        Overrides the model for <span className="text-zinc-400">this run only</span>.
                                        Newer models (Gemini 3+) appear automatically under
                                        <span className="text-zinc-400"> Settings → AI model</span> once your key has access.
                                    </p>
                                </div>

                                {/* Smart Cut */}
                                <SwitchRow
                                    label="Smart Cut"
                                    description="Remove silences and filler words"
                                    checked={preSmartCut}
                                    onChange={setPreSmartCut}
                                />

                                {/* Subtitles */}
                                <div className="space-y-2">
                                    <SwitchRow
                                        label="Subtitles"
                                        description="Burn karaoke or classic captions"
                                        checked={preSubtitles}
                                        onChange={setPreSubtitles}
                                        onConfigure={() => setShowSubConfig(!showSubConfig)}
                                        configureActive={showSubConfig}
                                    />

                                    {preSubtitles && showSubConfig && (
                                        <div className="bg-white/[0.02] border border-white/[0.07] rounded-[3px] p-4 space-y-4 animate-fade-in">
                                            {/* Mode (first — drives whether preset picker is shown) */}
                                            <div className="space-y-2">
                                                <p className="type-label">Mode</p>
                                                <Segmented
                                                    options={[
                                                        { id: 'karaoke', label: 'Karaoke' },
                                                        { id: 'classic', label: 'Classic' },
                                                    ]}
                                                    value={preSubMode}
                                                    onChange={setPreSubMode}
                                                    size="sm"
                                                    fullWidth
                                                />
                                            </div>

                                            {/* Preset — only meaningful in karaoke mode */}
                                            {preSubMode === 'karaoke' ? (
                                                <div className="space-y-3">
                                                    <div className="space-y-2">
                                                        <p className="type-label">Karaoke preset</p>
                                                        <div className="grid grid-cols-2 gap-2">
                                                            {SUBTITLE_PRESETS.map((p) => {
                                                            const isActive = preSubPreset === p.id;
                                                            return (
                                                                <button
                                                                    key={p.id}
                                                                    type="button"
                                                                    onClick={() => setPreSubPreset(p.id)}
                                                                    aria-pressed={isActive}
                                                                    className={`relative rounded-[3px] border overflow-hidden transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/60 ${
                                                                        isActive
                                                                            ? 'border-[oklch(74%_0.175_62)]/60 bg-[oklch(74%_0.175_62)]/[0.08] shadow-[0_0_0_1px_oklch(74%_0.175_62/0.25)_inset]'
                                                                            : 'border-white/[0.08] bg-white/[0.02] hover:border-white/[0.18]'
                                                                    }`}
                                                                >
                                                                    <div className="px-2 py-2.5 flex items-center justify-center min-h-[44px]">
                                                                        <span style={p.previewStyle} className="text-[11px] font-bold leading-tight text-center">
                                                                            WORD <span style={{ color: p.highlight }}>UP</span>
                                                                        </span>
                                                                    </div>
                                                                    <div className="px-1.5 py-1 bg-black/50 border-t border-white/[0.06] flex items-center gap-1.5">
                                                                        {isActive && (
                                                                            <span className="w-1 h-1 rounded-full bg-[oklch(74%_0.175_62)] shadow-[0_0_4px_oklch(74%_0.175_62/0.8)]" />
                                                                        )}
                                                                        <p className={`type-mono text-[9px] uppercase tracking-[0.14em] truncate ${isActive ? 'text-[oklch(82%_0.16_68)]' : 'text-zinc-500'}`}>{p.label}</p>
                                                                    </div>
                                                                </button>
                                                            );
                                                        })}
                                                        </div>
                                                    </div>
                                                    {/* Position (shared between karaoke and classic) */}
                                                    <div className="space-y-2">
                                                        <p className="type-label">Position</p>
                                                        <Segmented
                                                            options={[
                                                                { id: 'top', label: 'Top' },
                                                                { id: 'middle', label: 'Middle' },
                                                                { id: 'bottom', label: 'Bottom' },
                                                            ]}
                                                            value={preSubClassicPosition}
                                                            onChange={setPreSubClassicPosition}
                                                            size="sm"
                                                            fullWidth
                                                        />
                                                    </div>
                                                </div>
                                            ) : (
                                                <div className="space-y-3">
                                                    {/* Font */}
                                                    <div className="space-y-2">
                                                        <p className="type-label">Font</p>
                                                        <select
                                                            value={preSubClassicFont}
                                                            onChange={(e) => setPreSubClassicFont(e.target.value)}
                                                            className="w-full bg-white/[0.03] border border-white/[0.09] rounded-[3px] px-3 h-10 text-xs text-white font-mono uppercase tracking-[0.06em] focus:outline-none focus:border-[oklch(74%_0.175_62)]/60 focus:ring-[3px] focus:ring-[oklch(74%_0.175_62)]/15 transition-all"
                                                        >
                                                            {['Verdana', 'Montserrat-Black', 'Anton-Regular', 'Bangers-Regular', 'Poppins-Black', 'Poppins-Medium'].map(f => (
                                                                <option key={f} value={f} className="bg-[oklch(15%_0.01_260)]">{f.replace(/-/g, ' ')}</option>
                                                            ))}
                                                        </select>
                                                    </div>
                                                    {/* Font color */}
                                                    <div className="space-y-2">
                                                        <p className="type-label">Font color</p>
                                                        <div className="flex flex-wrap gap-2">
                                                            {['#FFFFFF', '#FFFF00', '#00FFFF', '#00FF00', '#FF4444', '#FF69B4'].map(c => (
                                                                <button
                                                                    key={c}
                                                                    type="button"
                                                                    onClick={() => setPreSubClassicFontColor(c)}
                                                                    aria-label={`Color ${c}`}
                                                                    aria-pressed={preSubClassicFontColor === c}
                                                                    className={`w-8 h-8 rounded-[2px] border-2 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)] focus-visible:ring-offset-2 focus-visible:ring-offset-background ${
                                                                        preSubClassicFontColor === c
                                                                            ? 'border-[oklch(74%_0.175_62)] shadow-[0_0_0_2px_oklch(74%_0.175_62/0.3)]'
                                                                            : 'border-white/20 hover:border-white/40'
                                                                    }`}
                                                                    style={{ backgroundColor: c }}
                                                                />
                                                            ))}
                                                            <label className="w-8 h-8 rounded-[2px] border-2 border-dashed border-white/20 cursor-pointer flex items-center justify-center hover:border-[oklch(74%_0.175_62)]/50 relative transition-colors">
                                                                <span className="text-[11px] text-zinc-500">+</span>
                                                                <input type="color" value={preSubClassicFontColor} onChange={(e) => setPreSubClassicFontColor(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
                                                            </label>
                                                        </div>
                                                    </div>
                                                    {/* Stroke (outline) — color + width */}
                                                    <div className="space-y-2">
                                                        <div className="flex items-center justify-between">
                                                            <p className="type-label">Stroke</p>
                                                            <span className="type-mono text-[10px] text-[oklch(82%_0.16_68)] tabular-nums">
                                                                {preSubClassicBorderWidth}&nbsp;px
                                                            </span>
                                                        </div>
                                                        <div className="flex items-center gap-3">
                                                            {/* Color swatch + picker */}
                                                            <label
                                                                className="relative w-10 h-10 rounded-[3px] border-2 border-white/[0.15] hover:border-[oklch(74%_0.175_62)]/60 cursor-pointer shrink-0 transition-colors shadow-[0_0_0_1px_oklch(0%_0_0/0.4)_inset]"
                                                                style={{ backgroundColor: preSubClassicBorderColor }}
                                                                title="Stroke color"
                                                            >
                                                                <input
                                                                    type="color"
                                                                    value={preSubClassicBorderColor}
                                                                    onChange={(e) => setPreSubClassicBorderColor(e.target.value)}
                                                                    className="absolute inset-0 opacity-0 cursor-pointer"
                                                                />
                                                            </label>
                                                            {/* Width slider */}
                                                            <input
                                                                type="range"
                                                                min={0}
                                                                max={10}
                                                                step={1}
                                                                value={preSubClassicBorderWidth}
                                                                onChange={(e) => setPreSubClassicBorderWidth(Number(e.target.value))}
                                                                aria-label="Stroke width"
                                                                className="flex-1 accent-[oklch(74%_0.175_62)]"
                                                            />
                                                        </div>
                                                        <p className="type-label !normal-case !tracking-normal !text-zinc-600 !text-[10px] !font-sans">
                                                            Outline around each character. Set to 0 to disable.
                                                        </p>
                                                    </div>
                                                    {/* Background box — toggle + color + opacity */}
                                                    <div className="space-y-2">
                                                        <div className="flex items-center justify-between">
                                                            <p className="type-label">Background</p>
                                                            <button
                                                                type="button"
                                                                onClick={() => setPreSubClassicBgOpacity(preSubClassicBgOpacity > 0 ? 0 : 0.6)}
                                                                role="switch"
                                                                aria-checked={preSubClassicBgOpacity > 0}
                                                                aria-label="Toggle background box"
                                                                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/60 ${
                                                                    preSubClassicBgOpacity > 0
                                                                        ? 'bg-[oklch(74%_0.175_62)]'
                                                                        : 'bg-white/[0.1] border border-white/[0.08]'
                                                                }`}
                                                            >
                                                                <span
                                                                    aria-hidden
                                                                    className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.4)] transition-transform ${preSubClassicBgOpacity > 0 ? 'translate-x-5' : 'translate-x-1'}`}
                                                                />
                                                            </button>
                                                        </div>
                                                        {preSubClassicBgOpacity > 0 && (
                                                            <div className="flex items-center gap-3 animate-fade-in">
                                                                <label
                                                                    className="relative w-10 h-10 rounded-[3px] border-2 border-white/[0.15] hover:border-[oklch(74%_0.175_62)]/60 cursor-pointer shrink-0 transition-colors"
                                                                    style={{ backgroundColor: preSubClassicBgColor }}
                                                                    title="Background color"
                                                                >
                                                                    <input
                                                                        type="color"
                                                                        value={preSubClassicBgColor}
                                                                        onChange={(e) => setPreSubClassicBgColor(e.target.value)}
                                                                        className="absolute inset-0 opacity-0 cursor-pointer"
                                                                    />
                                                                </label>
                                                                <div className="flex-1 space-y-1">
                                                                    <div className="flex items-center justify-between">
                                                                        <span className="type-label !text-[9px]">Opacity</span>
                                                                        <span className="type-mono text-[10px] text-[oklch(82%_0.16_68)] tabular-nums">
                                                                            {Math.round(preSubClassicBgOpacity * 100)}%
                                                                        </span>
                                                                    </div>
                                                                    <input
                                                                        type="range"
                                                                        min={10}
                                                                        max={100}
                                                                        step={5}
                                                                        value={Math.round(preSubClassicBgOpacity * 100)}
                                                                        onChange={(e) => setPreSubClassicBgOpacity(Number(e.target.value) / 100)}
                                                                        aria-label="Background opacity"
                                                                        className="w-full accent-[oklch(74%_0.175_62)]"
                                                                    />
                                                                </div>
                                                            </div>
                                                        )}
                                                    </div>
                                                    {/* Position */}
                                                    <div className="space-y-2">
                                                        <p className="type-label">Position</p>
                                                        <Segmented
                                                            options={[
                                                                { id: 'top', label: 'Top' },
                                                                { id: 'middle', label: 'Middle' },
                                                                { id: 'bottom', label: 'Bottom' },
                                                            ]}
                                                            value={preSubClassicPosition}
                                                            onChange={setPreSubClassicPosition}
                                                            size="sm"
                                                            fullWidth
                                                        />
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                {/* Hook */}
                                <div className="space-y-2">
                                    <SwitchRow
                                        label="Hook"
                                        description="Text overlay on top of the video"
                                        checked={preHook}
                                        onChange={setPreHook}
                                        onConfigure={() => setShowHookConfig(!showHookConfig)}
                                        configureActive={showHookConfig}
                                    />

                                    {preHook && showHookConfig && (
                                        <div className="bg-white/[0.02] border border-white/[0.07] rounded-[3px] p-4 space-y-3 animate-fade-in">
                                            {/* Position */}
                                            <div className="space-y-2">
                                                <p className="type-label">Position</p>
                                                <Segmented
                                                    options={[
                                                        { id: 'top', label: 'Top' },
                                                        { id: 'center', label: 'Center' },
                                                        { id: 'bottom', label: 'Bottom' },
                                                    ]}
                                                    value={preHookPosition}
                                                    onChange={setPreHookPosition}
                                                    size="sm"
                                                    fullWidth
                                                />
                                            </div>
                                            {/* Size */}
                                            <div className="space-y-2">
                                                <p className="type-label">Size</p>
                                                <Segmented
                                                    options={[
                                                        { id: 'S', label: 'S' },
                                                        { id: 'M', label: 'M' },
                                                        { id: 'L', label: 'L' },
                                                    ]}
                                                    value={preHookSize}
                                                    onChange={setPreHookSize}
                                                    size="sm"
                                                    fullWidth
                                                />
                                            </div>
                                        </div>
                                    )}
                                </div>

                                </div>
                            </div>
                        )}
                    </div>

                    {/* Submit Button */}
                    <button
                        type="submit"
                        disabled={isDisabled}
                        className={`group relative w-full min-h-[56px] rounded-[3px] font-mono text-[11px] uppercase tracking-[0.2em] font-semibold flex items-center justify-center gap-3 transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)] focus-visible:ring-offset-2 focus-visible:ring-offset-background ${
                            isDisabled
                                ? 'bg-white/[0.04] text-zinc-600 border border-white/[0.08] cursor-not-allowed'
                                : 'bg-[oklch(74%_0.175_62)] hover:bg-[oklch(78%_0.175_65)] text-[oklch(12%_0.01_260)] border border-[oklch(70%_0.18_62)] shadow-[0_1px_0_0_oklch(100%_0_0/0.3)_inset,0_14px_30px_-14px_oklch(74%_0.175_62/0.55)] active:translate-y-px'
                        }`}
                    >
                        {isProcessing ? (
                            <>
                                <Loader2 size={20} className="animate-spin" />
                                <span>Processing…</span>
                            </>
                        ) : (
                            <span>
                                {mode === 'batch'
                                    ? batchTotal > 0
                                        ? `Generate clips from ${batchTotal} videos`
                                        : 'Add videos to batch'
                                    : 'Generate my shorts'}
                            </span>
                        )}
                    </button>
                </form>
            </div>
        </div>
    );
}
