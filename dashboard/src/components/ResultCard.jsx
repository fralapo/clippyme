import React, { useState } from 'react';
import { Download, Youtube, Loader2, Type, Instagram, Copy, Check, Scissors, MessageSquare } from 'lucide-react';
import { toast } from 'sonner';
import { getApiUrl } from '../config';
import SubtitleModal from './SubtitleModal';
import HookModal from './HookModal';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Badge } from '@/components/ui/badge';

export default function ResultCard({ clip, index, jobId, onPlay, onPause }) {
    const [showSubtitleModal, setShowSubtitleModal] = useState(false);
    const [showHookModal, setShowHookModal] = useState(false);
    const videoRef = React.useRef(null);
    const [currentVideoUrl, setCurrentVideoUrl] = useState(getApiUrl(clip.video_url));

    const [isSubtitling, setIsSubtitling] = useState(false);
    const [isHooking, setIsHooking] = useState(false);
    const [isSmartCutting, setIsSmartCutting] = useState(false);
    const [copiedField, setCopiedField] = useState(null);

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 2000);
    };

    const handleSubtitle = async (options) => {
        setIsSubtitling(true);
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
                    input_filename: currentVideoUrl.split('/').pop(),
                    ...(options.preset && { preset: options.preset }),
                    ...(options.karaoke_mode && { karaoke_mode: options.karaoke_mode }),
                    ...(options.words_per_group && { words_per_group: options.words_per_group }),
                    ...(options.uppercase !== undefined && { uppercase: options.uppercase }),
                    ...(options.highlight_color && { highlight_color: options.highlight_color }),
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
            toast.error(e.message);
        } finally {
            setIsSubtitling(false);
        }
    };

    const handleSmartCut = async () => {
        setIsSmartCutting(true);
        try {
            const res = await fetch(getApiUrl(`/api/smartcut/${jobId}/${index}`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            if (!res.ok) {
                const errText = await res.text();
                throw new Error(errText || `Smart Cut failed (${res.status})`);
            }
            const data = await res.json();
            if (data.success && data.new_video_url) {
                toast.success(`Smart Cut saved ${data.stats?.time_saved}s`);
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                if (videoRef.current) videoRef.current.load();
            } else {
                toast.info(data.message || "No silences found to remove.");
            }
        } catch (e) {
            toast.error(e.message);
        } finally {
            setIsSmartCutting(false);
        }
    };

    const handleHook = async (options) => {
        setIsHooking(true);
        try {
            const res = await fetch(getApiUrl('/api/hook'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    text: options.text,
                    position: options.position,
                    size: options.size,
                    input_filename: currentVideoUrl.split('/').pop()
                })
            });
            if (!res.ok) {
                const errText = await res.text();
                try { throw new Error(JSON.parse(errText).detail || errText); }
                catch { throw new Error(res.status === 404 ? 'Session expired — process a new video first.' : errText); }
            }
            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                if (videoRef.current) videoRef.current.load();
                setShowHookModal(false);
            }
        } catch (e) {
            toast.error(e.message);
        } finally {
            setIsHooking(false);
        }
    };

    const duration = Math.floor(clip.end - clip.start);

    const scoreLevel = clip.viral_score >= 80 ? 'high' : clip.viral_score >= 50 ? 'mid' : 'low';
    const viralScoreGradient = {
        high: 'linear-gradient(135deg, #10b981, #059669)',
        mid: 'linear-gradient(135deg, #f59e0b, #d97706)',
        low: 'linear-gradient(135deg, #f97316, #ea580c)',
    }[scoreLevel];
    const viralScoreColor = {
        high: 'bg-green-500/15 text-green-400 border-green-500/20',
        mid: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/20',
        low: 'bg-orange-500/15 text-orange-400 border-orange-500/20',
    }[scoreLevel];

    const ghostBtn = 'bg-white/5 hover:bg-white/10 text-zinc-300 rounded-lg px-3 py-2.5 text-xs transition-colors flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:pointer-events-none min-h-[44px]';

    return (
        <div
            className="bg-[#0f0f13] border border-white/5 rounded-2xl overflow-hidden animate-fade-in"
            style={{ animationDelay: `${index * 0.1}s` }}
        >
            {/* Video player - 9:16 container */}
            <div className="relative w-full aspect-[9/16] bg-black rounded-t-2xl overflow-hidden">
                <video
                    ref={videoRef}
                    src={currentVideoUrl}
                    controls
                    className="w-full h-full object-cover"
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


            </div>

            {/* Content area */}
            <div className="p-5 space-y-4">
                {/* Title + badges row */}
                <div>
                    <h3
                        className="text-[15px] font-semibold text-white leading-snug line-clamp-2 mb-3"
                        title={clip.video_title_for_youtube_short}
                    >
                        {clip.video_title_for_youtube_short || "Viral Clip Generated"}
                    </h3>
                    <div className="flex items-center gap-2 flex-wrap">
                        {clip.viral_score != null && (
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <span
                                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold text-white cursor-help select-none"
                                        style={{ background: viralScoreGradient }}
                                    >
                                        {clip.viral_score}
                                        <span className="opacity-70 font-normal">/100</span>
                                    </span>
                                </TooltipTrigger>
                                <TooltipContent side="top" className="max-w-[220px] text-center">
                                    {clip.viral_reason || 'AI viral potential score'}
                                </TooltipContent>
                            </Tooltip>
                        )}
                        {!clip.viral_score && (
                            <Badge variant="outline" className="border-blue-500/20 text-blue-400 bg-blue-500/10">
                                AI Ranked
                            </Badge>
                        )}
                        <span className="text-xs text-zinc-500 font-medium">{duration}s</span>
                    </div>
                </div>

                {/* Action buttons grid */}
                <div className="grid grid-cols-2 gap-2">
                    <button onClick={() => setShowSubtitleModal(true)} disabled={isSubtitling} className={ghostBtn}>
                        {isSubtitling ? <Loader2 size={13} className="animate-spin" /> : <Type size={13} />}
                        Subtitles
                    </button>
                    <button onClick={() => setShowHookModal(true)} disabled={isHooking} className={ghostBtn}>
                        {isHooking ? <Loader2 size={13} className="animate-spin" /> : <MessageSquare size={13} />}
                        Hook
                    </button>
                    <button onClick={handleSmartCut} disabled={isSmartCutting} className={ghostBtn}>
                        {isSmartCutting ? <Loader2 size={13} className="animate-spin" /> : <Scissors size={13} />}
                        Smart Cut
                    </button>
                </div>

                {/* Download button - full width gradient */}
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
                            setTimeout(() => window.URL.revokeObjectURL(url), 60000);
                            document.body.removeChild(a);
                        } catch (err) {
                            console.error('Download error:', err);
                            window.open(currentVideoUrl, '_blank');
                        }
                    }}
                    className="w-full py-2.5 rounded-lg bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-500 hover:to-blue-400 text-white text-sm font-semibold flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
                >
                    <Download size={15} />
                    Download
                </button>

                {/* Copy-to-clipboard fields */}
                <div className="space-y-2.5">
                    {/* YouTube title */}
                    <div className="group/field">
                        <div className="flex items-center justify-between mb-1">
                            <label className="text-[11px] text-zinc-500 flex items-center gap-1.5">
                                <Youtube size={11} className="text-red-500" />
                                YouTube Title
                            </label>
                            <button
                                onClick={() => copyToClipboard(clip.video_title_for_youtube_short, 'title')}
                                aria-label={copiedField === 'title' ? 'Copied!' : 'Copy YouTube title'}
                                className="opacity-0 group-hover/field:opacity-100 transition-opacity p-1.5 text-zinc-500 hover:text-white rounded"
                            >
                                {copiedField === 'title' ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                            </button>
                        </div>
                        <div className="bg-white/[0.03] border border-white/5 rounded-lg px-3 py-2 text-xs text-zinc-400 leading-relaxed">
                            {clip.video_title_for_youtube_short || "Untitled Viral Short"}
                        </div>
                    </div>

                    {/* TikTok / Instagram caption */}
                    <div className="group/field">
                        <div className="flex items-center justify-between mb-1">
                            <label className="text-[11px] text-zinc-500 flex items-center gap-1.5">
                                <Instagram size={11} className="text-pink-500" />
                                TikTok Caption
                            </label>
                            <button
                                onClick={() => copyToClipboard(clip.video_description_for_tiktok, 'caption')}
                                aria-label={copiedField === 'caption' ? 'Copied!' : 'Copy TikTok caption'}
                                className="opacity-0 group-hover/field:opacity-100 transition-opacity p-1.5 text-zinc-500 hover:text-white rounded"
                            >
                                {copiedField === 'caption' ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                            </button>
                        </div>
                        <div className="bg-white/[0.03] border border-white/5 rounded-lg px-3 py-2 text-xs text-zinc-500 italic line-clamp-3 hover:line-clamp-none transition-all cursor-text leading-relaxed">
                            {clip.video_description_for_tiktok || clip.video_description_for_instagram}
                        </div>
                    </div>
                </div>
            </div>

            <SubtitleModal
                isOpen={showSubtitleModal}
                onClose={() => setShowSubtitleModal(false)}
                onGenerate={handleSubtitle}
                isProcessing={isSubtitling}
                videoUrl={currentVideoUrl}
            />

            <HookModal
                isOpen={showHookModal}
                onClose={() => setShowHookModal(false)}
                onGenerate={handleHook}
                isProcessing={isHooking}
                videoUrl={currentVideoUrl}
                initialText={clip.viral_hook_text || ''}
            />
        </div>
    );
}
