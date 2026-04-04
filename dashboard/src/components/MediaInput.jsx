import React, { useState, useRef } from 'react';
import { Youtube, Upload, FileVideo, X, Globe, Link2, FileUp, Loader2, ChevronDown, Sparkles, Layers, Clipboard } from 'lucide-react';

export default function MediaInput({ onProcess, onBatchProcess, isProcessing, cookiesConfigured }) {
    const [mode, setMode] = useState('url'); // 'url' | 'file' | 'batch'
    const [url, setUrl] = useState('');
    const [file, setFile] = useState(null);
    const [instructions, setInstructions] = useState('');
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [batchUrls, setBatchUrls] = useState('');
    const [isDragging, setIsDragging] = useState(false);
    const urlInputRef = useRef(null);

    const handleSubmit = (e) => {
        e.preventDefault();
        const opts = { instructions: instructions.trim() || undefined };
        if (mode === 'batch' && batchUrls.trim()) {
            const urls = batchUrls.split('\n').map(u => u.trim()).filter(u => u);
            if (urls.length > 0 && onBatchProcess) {
                onBatchProcess({ urls, ...opts });
            }
        } else if (mode === 'url' && url) {
            onProcess({ type: 'url', payload: url, ...opts });
        } else if (mode === 'file' && file) {
            onProcess({ type: 'file', payload: file, ...opts });
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragging(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setFile(e.dataTransfer.files[0]);
            setMode('file');
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

    const tabs = [
        { id: 'url', label: 'URL', icon: Globe },
        { id: 'file', label: 'Upload', icon: FileUp },
        { id: 'batch', label: 'Batch', icon: Layers },
    ];

    const isDisabled = isProcessing || (mode === 'url' && !url) || (mode === 'file' && !file) || (mode === 'batch' && !batchUrls.trim());

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

                    {/* URL Mode */}
                    {mode === 'url' && (
                        <div className="space-y-4">
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
                                    required
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

                            {/* Cookie warning banner */}
                            {!cookiesConfigured && (
                                <div className="flex items-start gap-2 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs">
                                    <span className="mt-0.5">⚠</span>
                                    <span>Cookie non configurati. Senza cookie, il download potrebbe fallire o essere più lento. Configura i cookie nelle <strong>Impostazioni</strong>.</span>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Upload Mode */}
                    {mode === 'file' && (
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

                    {/* Batch Mode */}
                    {mode === 'batch' && (
                        <div className="space-y-2.5">
                            <label htmlFor="batch-urls" className="sr-only">Batch URLs (one per line)</label>
                            <textarea
                                id="batch-urls"
                                value={batchUrls}
                                onChange={(e) => setBatchUrls(e.target.value)}
                                placeholder={"https://youtube.com/watch?v=abc\nhttps://youtube.com/watch?v=def\nhttps://youtube.com/watch?v=ghi"}
                                className="w-full bg-white/[0.03] border border-white/5 rounded-xl px-4 py-3.5 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-transparent resize-none h-36 font-mono leading-relaxed transition-all"
                                maxLength={5000}
                                aria-describedby="batch-url-hint"
                            />
                            <div className="flex items-center justify-between px-1">
                                <p id="batch-url-hint" className="text-[11px] text-zinc-500">
                                    One URL per line
                                </p>
                                <p className={`text-[11px] font-medium ${batchUrlCount > 20 ? 'text-red-400' : batchUrlCount > 0 ? 'text-zinc-400' : 'text-zinc-600'}`}>
                                    {batchUrlCount} / 20 URLs
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
