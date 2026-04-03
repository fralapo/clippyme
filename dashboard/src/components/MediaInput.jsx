import React, { useState } from 'react';
import { Youtube, Upload, FileVideo, X, Check, Globe, Link2, FileUp, Loader2, ChevronDown, Sparkles, Layers } from 'lucide-react';

export default function MediaInput({ onProcess, onBatchProcess, isProcessing }) {
    const [mode, setMode] = useState('url'); // 'url' | 'file' | 'batch'
    const [url, setUrl] = useState('');
    const [file, setFile] = useState(null);
    const [cookiesFile, setCookiesFile] = useState(null);
    const [instructions, setInstructions] = useState('');
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [batchUrls, setBatchUrls] = useState('');

    const handleSubmit = (e) => {
        e.preventDefault();
        const opts = { instructions: instructions.trim() || undefined };
        if (mode === 'batch' && batchUrls.trim()) {
            const urls = batchUrls.split('\n').map(u => u.trim()).filter(u => u);
            if (urls.length > 0 && onBatchProcess) {
                onBatchProcess({ urls, ...opts });
            }
        } else if (mode === 'url' && url) {
            onProcess({ type: 'url', payload: url, cookiesFile, ...opts });
        } else if (mode === 'file' && file) {
            onProcess({ type: 'file', payload: file, ...opts });
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setFile(e.dataTransfer.files[0]);
            setMode('file');
        }
    };

    return (
        <div className="glass-panel p-1 overflow-hidden animate-fade-in">
            <div className="flex bg-black/20 p-1 shrink-0">
                <button
                    onClick={() => setMode('url')}
                    className={`flex-1 flex items-center justify-center gap-2 py-3 rounded-xl transition-all duration-500 font-black text-[10px] uppercase tracking-[0.15em] ${mode === 'url'
                        ? 'bg-primary text-white shadow-glow-primary'
                        : 'text-zinc-500 hover:text-white'
                        }`}
                >
                    <Globe size={14} />
                    URL
                </button>
                <button
                    onClick={() => setMode('file')}
                    className={`flex-1 flex items-center justify-center gap-2 py-3 rounded-xl transition-all duration-500 font-black text-[10px] uppercase tracking-[0.15em] ${mode === 'file'
                        ? 'bg-primary text-white shadow-glow-primary'
                        : 'text-zinc-500 hover:text-white'
                        }`}
                >
                    <FileUp size={14} />
                    Upload
                </button>
                <button
                    onClick={() => setMode('batch')}
                    className={`flex-1 flex items-center justify-center gap-2 py-3 rounded-xl transition-all duration-500 font-black text-[10px] uppercase tracking-[0.15em] ${mode === 'batch'
                        ? 'bg-primary text-white shadow-glow-primary'
                        : 'text-zinc-500 hover:text-white'
                        }`}
                >
                    <Layers size={14} />
                    Batch
                </button>
            </div>

            <div className="p-8">
                <form onSubmit={handleSubmit} className="space-y-8">
                    {mode === 'batch' ? (
                        <div className="space-y-4">
                            <div className="space-y-3">
                                <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                    <Layers size={12} /> Batch URLs (one per line)
                                </label>
                                <textarea
                                    value={batchUrls}
                                    onChange={(e) => setBatchUrls(e.target.value)}
                                    placeholder={"https://www.youtube.com/watch?v=abc\nhttps://www.youtube.com/watch?v=def\nhttps://www.youtube.com/watch?v=ghi"}
                                    className="w-full bg-black/40 border border-white/5 rounded-xl px-4 py-3 text-sm text-white placeholder:text-zinc-700 focus:outline-none focus:border-primary/30 resize-none h-32 font-mono"
                                    maxLength={5000}
                                />
                                <p className="text-[10px] text-zinc-600">
                                    {batchUrls.split('\n').filter(u => u.trim()).length} URLs — Max 20 per batch
                                </p>
                            </div>
                        </div>
                    ) : mode === 'url' ? (
                        <div className="space-y-6">
                            <div className="space-y-3">
                                <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2">
                                    <Link2 size={12} /> Target Video URL
                                </label>
                                <input
                                    type="url"
                                    value={url}
                                    onChange={(e) => setUrl(e.target.value)}
                                    placeholder="https://www.youtube.com/watch?v=..."
                                    className="input-field !bg-black/40 !border-white/5 focus:!border-primary/30"
                                    required
                                />
                            </div>
                            
                            <div className="p-6 rounded-2xl bg-white/[0.02] border border-white/5 space-y-4">
                                <div className="flex items-center justify-between">
                                    <label className="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em]">
                                        Auth_Cookies.txt (Optional)
                                    </label>
                                    {cookiesFile && <span className="text-[10px] font-black text-success uppercase">Loaded</span>}
                                </div>
                                <div className="relative group/file">
                                    <input
                                        type="file"
                                        accept=".txt"
                                        onChange={(e) => setCookiesFile(e.target.files?.[0] || null)}
                                        className="absolute inset-0 opacity-0 cursor-pointer z-10"
                                    />
                                    <div className="w-full bg-black/40 border border-white/5 border-dashed rounded-xl py-3 px-4 text-xs text-zinc-600 group-hover/file:border-primary/30 transition-all flex items-center justify-between">
                                        <span>{cookiesFile ? cookiesFile.name : "Drop netscape cookies to bypass bot detection"}</span>
                                        <Upload size={14} className="group-hover/file:text-primary" />
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div
                            className={`border-2 border-dashed rounded-2xl p-12 text-center transition-all duration-500 relative group ${file ? 'border-primary/50 bg-primary/5 shadow-inner' : 'border-white/5 hover:border-primary/20 bg-black/20'
                                }`}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={handleDrop}
                        >
                            {file ? (
                                <div className="flex flex-col items-center gap-4 animate-fade-in">
                                    <div className="w-16 h-16 rounded-2xl bg-primary/20 flex items-center justify-center text-primary border border-primary/20 shadow-lg shadow-primary/5">
                                        <FileVideo size={32} />
                                    </div>
                                    <div className="text-center">
                                        <p className="text-white font-black text-sm uppercase tracking-tight truncate max-w-[200px]">{file.name}</p>
                                        <p className="text-[10px] font-bold text-zinc-500 uppercase mt-1">Ready for ingestion</p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setFile(null)}
                                        className="mt-2 p-2 hover:bg-white/10 rounded-xl transition-all text-zinc-500 hover:text-white"
                                    >
                                        <X size={20} />
                                    </button>
                                </div>
                            ) : (
                                <label className="cursor-pointer flex flex-col items-center gap-4">
                                    <input
                                        type="file"
                                        accept="video/*"
                                        onChange={(e) => setFile(e.target.files?.[0] || null)}
                                        className="hidden"
                                    />
                                    <div className="w-16 h-16 rounded-2xl bg-white/[0.03] flex items-center justify-center text-zinc-600 group-hover:text-primary group-hover:bg-primary/5 border border-white/5 transition-all duration-500">
                                        <Upload size={32} />
                                    </div>
                                    <div className="text-center space-y-1">
                                        <p className="text-zinc-400 font-bold uppercase text-xs tracking-widest">Master Video Ingest</p>
                                        <p className="text-[10px] text-zinc-600 font-medium uppercase tracking-tighter">MP4, MOV, WEBM up to 2GB</p>
                                    </div>
                                </label>
                            )}
                        </div>
                    )}

                    {/* AI Instructions (Advanced) */}
                    <div className="border border-white/5 rounded-2xl overflow-hidden">
                        <button
                            type="button"
                            onClick={() => setShowAdvanced(!showAdvanced)}
                            className="w-full flex items-center justify-between px-5 py-3 text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em] hover:text-zinc-300 transition-colors"
                        >
                            <span className="flex items-center gap-2"><Sparkles size={12} /> AI Instructions</span>
                            <ChevronDown size={14} className={`transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
                        </button>
                        {showAdvanced && (
                            <div className="px-5 pb-5 space-y-2 animate-fade-in">
                                <textarea
                                    value={instructions}
                                    onChange={(e) => setInstructions(e.target.value)}
                                    placeholder="Tell the AI what to look for... e.g. 'Find the funniest moments' or 'Focus on the gaming parts, skip the intro'"
                                    className="w-full bg-black/40 border border-white/5 rounded-xl px-4 py-3 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-primary/30 resize-none h-20"
                                    maxLength={500}
                                />
                                <p className="text-[10px] text-zinc-600">Optional. Guide the AI to find specific types of clips.</p>
                            </div>
                        )}
                    </div>

                    <button
                        type="submit"
                        disabled={isProcessing || (mode === 'url' && !url) || (mode === 'file' && !file) || (mode === 'batch' && !batchUrls.trim())}
                        className="w-full btn-primary-glow !py-5 font-black uppercase tracking-[0.2em] italic text-lg"
                    >
                        {isProcessing ? (
                            <>
                                <Loader2 size={24} className="animate-spin" />
                                <span>Processing...</span>
                            </>
                        ) : (
                            <>
                                <span>{mode === 'batch' ? 'Launch Batch' : 'Engage Engine'}</span>
                            </>
                        )}
                    </button>
                </form>
            </div>
        </div>
    );
}
