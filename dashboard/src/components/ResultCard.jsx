import React, { useState } from 'react';
import { Download, Youtube, Video, AlertCircle, X, Loader2, Wand2, Type, Instagram, Share2, Copy, Check } from 'lucide-react';
import { getApiUrl } from '../config';
import SubtitleModal from './SubtitleModal';

export default function ResultCard({ clip, index, jobId, geminiApiKey, onPlay, onPause }) {
    const [showSubtitleModal, setShowSubtitleModal] = useState(false);
    const videoRef = React.useRef(null);
    const [currentVideoUrl, setCurrentVideoUrl] = useState(getApiUrl(clip.video_url));

    const [isEditing, setIsEditing] = useState(false);
    const [isSubtitling, setIsSubtitling] = useState(false);
    const [editError, setEditError] = useState(null);
    const [copiedField, setCopiedField] = useState(null);

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 2000);
    };

    const handleAutoEdit = async () => {
        setIsEditing(true);
        setEditError(null);
        try {
            const apiKey = geminiApiKey || localStorage.getItem('gemini_key');

            if (!apiKey) {
                throw new Error("Gemini API Key is missing. Please set it in Settings.");
            }

            const res = await fetch(getApiUrl('/api/edit'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Gemini-Key': apiKey
                },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    input_filename: currentVideoUrl.split('/').pop()
                })
            });

            if (!res.ok) {
                const errText = await res.text();
                try {
                    const jsonErr = JSON.parse(errText);
                    throw new Error(jsonErr.detail || errText);
                } catch (e) {
                    throw new Error(errText);
                }
            }

            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                if (videoRef.current) {
                    videoRef.current.load();
                }
            }

        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsEditing(false);
        }
    };

    const handleSubtitle = async (options) => {
        setIsSubtitling(true);
        setEditError(null);
        try {
            const res = await fetch(getApiUrl('/api/subtitle'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    position: options.position,
                    font_size: options.fontSize,
                    font_name: options.fontName,
                    font_color: options.fontColor,
                    border_color: options.borderColor,
                    border_width: options.borderWidth,
                    bg_color: options.bgColor,
                    bg_opacity: options.bgOpacity,
                    input_filename: currentVideoUrl.split('/').pop()
                })
            });

            if (!res.ok) {
                const errText = await res.text();
                throw new Error(errText);
            }

            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                if (videoRef.current) {
                    videoRef.current.load();
                }
                setShowSubtitleModal(false);
            }

        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsSubtitling(false);
        }
    };

    return (
        <div className="glass-panel overflow-hidden flex flex-col md:flex-row group/card border-white/5 hover:border-primary/20 transition-all duration-500 animate-fade-in" style={{ animationDelay: `${index * 0.1}s` }}>
            <div className="w-full md:w-[220px] bg-black relative shrink-0 aspect-[9/16] md:aspect-auto group/video overflow-hidden">
                <video
                    ref={videoRef}
                    src={currentVideoUrl}
                    controls
                    className="w-full h-full object-cover group-hover/video:scale-105 transition-transform duration-1000"
                    playsInline
                    onPlay={() => {
                        const currentTime = videoRef.current ? videoRef.current.currentTime : 0;
                        onPlay && onPlay(clip.start + currentTime);
                    }}
                    onPause={() => onPause && onPause()}
                    onEnded={() => {
                        if (videoRef.current) {
                            videoRef.current.currentTime = 0;
                            videoRef.current.play();
                        }
                    }}
                />
                
                <div className="absolute top-4 left-4 z-20">
                    <div className="bg-primary px-3 py-1.5 rounded-lg shadow-xl border border-white/10 flex items-center gap-2">
                        <span className="text-[10px] font-black text-white uppercase tracking-widest">SEGMENT {index + 1}</span>
                    </div>
                </div>

                {isEditing && (
                    <div className="absolute inset-0 bg-primary/20 backdrop-blur-md flex flex-col items-center justify-center z-30 p-6 text-center animate-pulse">
                        <Loader2 size={40} className="text-white animate-spin mb-4" />
                        <span className="text-sm font-black text-white uppercase tracking-[0.2em]">Synthesizing...</span>
                    </div>
                )}
            </div>

            <div className="flex-1 p-6 md:p-8 flex flex-col bg-surface-darker/40 overflow-hidden min-w-0">
                <div className="mb-6 flex justify-between items-start gap-4">
                    <div className="min-w-0 text-left">
                        <h3 className="text-xl font-black text-white leading-tight mb-3 line-clamp-2 uppercase tracking-tighter text-left" title={clip.video_title_for_youtube_short}>
                            {clip.video_title_for_youtube_short || "Viral Clip Generated"}
                        </h3>
                        <div className="flex flex-wrap gap-2">
                            <span className="bg-white/5 px-2 py-1 rounded-md border border-white/5 text-[10px] font-bold text-zinc-500 uppercase tracking-widest">{Math.floor(clip.end - clip.start)}s Duration</span>
                            <span className="bg-primary/10 px-2 py-1 rounded-md border border-primary/10 text-[10px] font-black text-primary uppercase tracking-widest">AI Ranked</span>
                        </div>
                    </div>
                </div>

                <div className="flex-1 space-y-4 mb-8 overflow-y-auto custom-scrollbar pr-2">
                    <div className="relative group/field text-left">
                        <div className="flex items-center justify-between mb-2 text-left">
                            <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2 text-left">
                                <Youtube size={12} className="text-red-500" /> YouTube Title
                            </label>
                            <button 
                                onClick={() => copyToClipboard(clip.video_title_for_youtube_short, 'title')}
                                className="opacity-0 group-hover/field:opacity-100 transition-opacity p-1 hover:text-white"
                            >
                                {copiedField === 'title' ? <Check size={12} className="text-success" /> : <Copy size={12} />}
                            </button>
                        </div>
                        <div className="bg-white/[0.02] border border-white/5 rounded-xl p-4 text-xs text-zinc-300 font-medium leading-relaxed text-left">
                            {clip.video_title_for_youtube_short || "Untitled Viral Short"}
                        </div>
                    </div>

                    <div className="relative group/field text-left">
                        <div className="flex items-center justify-between mb-2 text-left">
                            <label className="text-[10px] font-black text-zinc-600 uppercase tracking-[0.2em] flex items-center gap-2 text-left">
                                <Instagram size={12} className="text-pink-500" /> Viral Caption
                            </label>
                            <button 
                                onClick={() => copyToClipboard(clip.video_description_for_tiktok, 'caption')}
                                className="opacity-0 group-hover/field:opacity-100 transition-opacity p-1 hover:text-white"
                            >
                                {copiedField === 'caption' ? <Check size={12} className="text-success" /> : <Copy size={12} />}
                            </button>
                        </div>
                        <div className="bg-white/[0.02] border border-white/5 rounded-xl p-4 text-xs text-zinc-400 italic line-clamp-3 hover:line-clamp-none transition-all cursor-text text-left">
                            {clip.video_description_for_tiktok || clip.video_description_for_instagram}
                        </div>
                    </div>
                </div>

                {editError && (
                    <div className="mb-6 p-3 bg-error/10 border border-error/20 text-error text-[10px] font-bold rounded-xl flex items-center gap-3 animate-fade-in uppercase tracking-widest text-left">
                        <AlertCircle size={16} className="shrink-0" />
                        {editError}
                    </div>
                )}

                <div className="grid grid-cols-3 gap-4 mt-auto">
                    <button
                        onClick={handleAutoEdit}
                        disabled={isEditing}
                        className="col-span-1 btn-primary-glow !py-3 text-[10px] font-black uppercase tracking-widest"
                    >
                        {isEditing ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                        {isEditing ? '...' : 'Auto Edit'}
                    </button>

                    <button
                        onClick={() => setShowSubtitleModal(true)}
                        disabled={isSubtitling}
                        className="col-span-1 py-3 bg-warning hover:bg-warning/90 text-black rounded-xl text-[10px] font-black uppercase tracking-widest shadow-lg shadow-warning/10 transition-all active:scale-[0.98] flex items-center justify-center gap-2"
                    >
                        {isSubtitling ? <Loader2 size={14} className="animate-spin" /> : <Type size={14} />}
                        {isSubtitling ? '...' : 'Captions'}
                    </button>

                    <button
                        onClick={async (e) => {
                            e.preventDefault();
                            try {
                                const response = await fetch(currentVideoUrl);
                                if (!response.ok) throw new Error('Download failed');
                                const blob = await response.blob();
                                const url = window.URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.style.display = 'none';
                                a.href = url;
                                a.download = `clippyme-segment-${index + 1}.mp4`;
                                document.body.appendChild(a);
                                a.click();
                                window.URL.revokeObjectURL(url);
                                document.body.removeChild(a);
                            } catch (err) {
                                console.error('Download error:', err);
                                window.open(currentVideoUrl, '_blank');
                            }
                        }}
                        className="col-span-1 btn-secondary !py-3 text-[10px] font-black uppercase tracking-widest"
                    >
                        <Download size={14} className="shrink-0" /> Save
                    </button>
                </div>
            </div>

            <SubtitleModal
                isOpen={showSubtitleModal}
                onClose={() => setShowSubtitleModal(false)}
                onGenerate={handleSubtitle}
                isProcessing={isSubtitling}
                videoUrl={currentVideoUrl}
            />
        </div>
    );
}
