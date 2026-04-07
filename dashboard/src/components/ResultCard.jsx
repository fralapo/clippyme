import React, { useState } from 'react';
import { Download, Youtube, Loader2, Type, Instagram, Copy, Check, Scissors, MessageSquare, Settings, Send } from 'lucide-react';
import PublishModal from './PublishModal';
import { toast } from 'sonner';
import { getApiUrl } from '../config';
import SubtitleModal from './SubtitleModal';
import HookModal from './HookModal';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Badge } from '@/components/ui/badge';

export default function ResultCard({ clip, index, jobId, onPlay, onPause, preselections }) {
    const [showSubtitleModal, setShowSubtitleModal] = useState(false);
    const [showHookModal, setShowHookModal] = useState(false);
    const videoRef = React.useRef(null);
    const [currentVideoUrl, setCurrentVideoUrl] = useState(getApiUrl(clip.video_url));

    const [copiedField, setCopiedField] = useState(null);

    // Toggle state — initialized from preselections prop
    const [toggles, setToggles] = useState({
        smartcut: preselections?.smartcut || false,
        hook: preselections?.hook ? true : false,
        subtitles: preselections?.subtitles ? true : false,
    });

    const [hookParams, setHookParams] = useState({
        text: clip.viral_hook_text || clip.hook_text || '',
        position: preselections?.hook?.position || 'top',
        size: preselections?.hook?.size || 'S',
        offset_y: 0,
    });

    const [subtitleParams, setSubtitleParams] = useState({
        preset: preselections?.subtitles?.preset || 'classic_white',
        mode: preselections?.subtitles?.mode || 'karaoke',
        display_mode: 'word_group',
        highlight_color: null,
        // Karaoke font default; classic mode overrides via preselections.font below
        font: preselections?.subtitles?.font || 'Montserrat-Black',
        uppercase: true,
        offset_y: 0,
        // Classic-mode params (only meaningful when mode === 'classic')
        font_color: preselections?.subtitles?.font_color || '#FFFFFF',
        position: preselections?.subtitles?.position || 'bottom',
    });

    const [isComposing, setIsComposing] = useState(false);
    const [showPublishModal, setShowPublishModal] = useState(false);

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 2000);
    };

    const handleDownload = async () => {
        const hasActiveToggles = Object.values(toggles).some(Boolean);

        if (!hasActiveToggles) {
            // Download original clip directly
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
            return;
        }

        setIsComposing(true);
        try {
            const res = await fetch(getApiUrl(`/api/compose/${jobId}/${index}`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    toggles,
                    hook_params: toggles.hook ? hookParams : {},
                    subtitle_params: toggles.subtitles ? subtitleParams : {},
                }),
            });
            const data = await res.json();
            if (data.composed_url) {
                const videoRes = await fetch(getApiUrl(data.composed_url));
                const blob = await videoRes.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = `clippyme-segment-${index + 1}.mp4`;
                document.body.appendChild(a);
                a.click();
                setTimeout(() => window.URL.revokeObjectURL(url), 60000);
                document.body.removeChild(a);
            } else {
                toast.error(data.detail || 'Compose returned no video URL');
            }
        } catch (err) {
            console.error('Compose failed:', err);
            toast.error('Compose failed — check console for details');
        } finally {
            setIsComposing(false);
        }
    };

    const duration = Math.floor(clip.end - clip.start);

    const scoreLevel = clip.viral_score >= 80 ? 'high' : clip.viral_score >= 50 ? 'mid' : 'low';
    const viralScoreGradient = {
        high: 'linear-gradient(135deg, #10b981, #059669)',
        mid: 'linear-gradient(135deg, #f59e0b, #d97706)',
        low: 'linear-gradient(135deg, #f97316, #ea580c)',
    }[scoreLevel];

    const toggleBtn = (active) =>
        `flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-all flex items-center gap-2 ${
            active
                ? 'bg-accent-pink/20 text-accent-pink border border-accent-pink/30'
                : 'bg-white/5 text-zinc-500 border border-white/5 hover:text-zinc-300'
        }`;

    const settingsBtn = 'p-2 rounded-lg bg-white/5 border border-white/5 text-zinc-500 hover:text-white transition-colors';

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

                {/* Toggle buttons — vertical stack */}
                <div className="space-y-2">
                    {/* Smart Cut */}
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setToggles(t => ({ ...t, smartcut: !t.smartcut }))}
                            className={toggleBtn(toggles.smartcut)}
                        >
                            <span className={`w-1.5 h-1.5 rounded-full transition-colors ${toggles.smartcut ? 'bg-accent-pink' : 'bg-zinc-600'}`} />
                            <Scissors size={13} />
                            Smart Cut
                        </button>
                    </div>

                    {/* Hook */}
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setToggles(t => ({ ...t, hook: !t.hook }))}
                            className={toggleBtn(toggles.hook)}
                        >
                            <span className={`w-1.5 h-1.5 rounded-full transition-colors ${toggles.hook ? 'bg-accent-pink' : 'bg-zinc-600'}`} />
                            <MessageSquare size={13} />
                            Hook
                        </button>
                        <button onClick={() => setShowHookModal(true)} className={settingsBtn}>
                            <Settings size={13} />
                        </button>
                    </div>

                    {/* Subtitles */}
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setToggles(t => ({ ...t, subtitles: !t.subtitles }))}
                            className={toggleBtn(toggles.subtitles)}
                        >
                            <span className={`w-1.5 h-1.5 rounded-full transition-colors ${toggles.subtitles ? 'bg-accent-pink' : 'bg-zinc-600'}`} />
                            <Type size={13} />
                            Subtitles
                        </button>
                        <button onClick={() => setShowSubtitleModal(true)} className={settingsBtn}>
                            <Settings size={13} />
                        </button>
                    </div>
                </div>

                {/* Download + Publish row */}
                <div className="flex gap-2">
                    <button
                        onClick={handleDownload}
                        disabled={isComposing}
                        className="flex-1 py-2.5 rounded-lg bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-500 hover:to-blue-400 text-white text-sm font-semibold flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-60 disabled:pointer-events-none"
                    >
                        {isComposing ? (
                            <>
                                <Loader2 size={15} className="animate-spin" />
                                Composing...
                            </>
                        ) : (
                            <>
                                <Download size={15} />
                                Download
                            </>
                        )}
                    </button>
                    <button
                        onClick={() => setShowPublishModal(true)}
                        disabled={isComposing}
                        title="Publish to TikTok / Instagram / YouTube via Zernio"
                        className="px-4 py-2.5 rounded-lg bg-accent-pink/20 hover:bg-accent-pink/30 border border-accent-pink/30 text-accent-pink text-sm font-semibold flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50"
                    >
                        <Send size={15} />
                        Publish
                    </button>
                </div>

                <PublishModal
                    isOpen={showPublishModal}
                    onClose={() => setShowPublishModal(false)}
                    jobId={jobId}
                    clipIndex={index}
                    defaultTitle={clip.video_title_for_youtube_short || ''}
                    defaultCaption={clip.tiktok_caption || ''}
                    videoUrl={currentVideoUrl}
                    composeBeforePublish={
                        Object.values(toggles).some(Boolean)
                            ? { toggles, hookParams, subtitleParams }
                            : null
                    }
                />

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
                onGenerate={(params) => {
                    setSubtitleParams(prev => ({ ...prev, ...params }));
                    setToggles(t => ({ ...t, subtitles: true }));
                    setShowSubtitleModal(false);
                }}
                isProcessing={false}
                videoUrl={currentVideoUrl}
            />

            <HookModal
                isOpen={showHookModal}
                onClose={() => setShowHookModal(false)}
                onGenerate={(params) => {
                    setHookParams(prev => ({ ...prev, ...params }));
                    setToggles(t => ({ ...t, hook: true }));
                    setShowHookModal(false);
                }}
                isProcessing={false}
                videoUrl={currentVideoUrl}
                initialText={clip.viral_hook_text || ''}
            />
        </div>
    );
}
