import React, { useState } from 'react';
import { Youtube, Upload, FileVideo, X, Check, Globe, Link2, FileUp } from 'lucide-react';

export default function MediaInput({ onProcess, isProcessing }) {
    const [mode, setMode] = useState('url'); // 'url' | 'file'
    const [url, setUrl] = useState('');
    const [file, setFile] = useState(null);
    const [cookiesFile, setCookiesFile] = useState(null);

    const handleSubmit = (e) => {
        e.preventDefault();
        if (mode === 'url' && url) {
            onProcess({ type: 'url', payload: url, cookiesFile });
        } else if (mode === 'file' && file) {
            onProcess({ type: 'file', payload: file });
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
                    className={`flex-1 flex items-center justify-center gap-3 py-3 rounded-xl transition-all duration-500 font-black text-[10px] uppercase tracking-[0.2em] ${mode === 'url'
                        ? 'bg-primary text-white shadow-glow-primary'
                        : 'text-zinc-500 hover:text-white'
                        }`}
                >
                    <Globe size={16} />
                    Remote URL
                </button>
                <button
                    onClick={() => setMode('file')}
                    className={`flex-1 flex items-center justify-center gap-3 py-3 rounded-xl transition-all duration-500 font-black text-[10px] uppercase tracking-[0.2em] ${mode === 'file'
                        ? 'bg-primary text-white shadow-glow-primary'
                        : 'text-zinc-500 hover:text-white'
                        }`}
                >
                    <FileUp size={16} />
                    Local Upload
                </button>
            </div>

            <div className="p-8">
                <form onSubmit={handleSubmit} className="space-y-8">
                    {mode === 'url' ? (
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

                    <button
                        type="submit"
                        disabled={isProcessing || (mode === 'url' && !url) || (mode === 'file' && !file)}
                        className="w-full btn-primary-glow !py-5 font-black uppercase tracking-[0.2em] italic text-lg"
                    >
                        {isProcessing ? (
                            <>
                                <Loader2 size={24} className="animate-spin" />
                                <span>Processing...</span>
                            </>
                        ) : (
                            <>
                                <span>Engage Engine</span>
                            </>
                        )}
                    </button>
                </form>
            </div>
        </div>
    );
}

const Loader2 = ({ size, className }) => (
    <svg 
        width={size} height={size} viewBox="0 0 24 24" fill="none" 
        stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" 
        strokeLinejoin="round" className={`${className} animate-spin`}
    >
        <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
    </svg>
);
