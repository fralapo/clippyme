import React, { useState } from 'react';
import { Download, Youtube, Loader2, Type, Instagram, Copy, Check, Scissors, MessageSquare, Settings, Send, Trash2, Eye, EyeOff, Crop, Square, ChevronDown, Trophy, Clock, Quote } from 'lucide-react';
import PublishModal from './PublishModal';
import { toast } from 'sonner';
import { getApiUrl } from '../config';
import SubtitleModal from './SubtitleModal';
import HookModal from './HookModal';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

export default function ResultCard({
    clip,
    index,
    rank = null,
    totalClips = 0,
    jobId,
    onPlay,
    onPause,
    preselections,
    clipState = {},
    onUpdateState = () => {},
}) {
    const [showMetadata, setShowMetadata] = useState(false);
    const isDisabled = !!clipState.disabled;
    const publishedAt = clipState.publishedAt;
    // Reframe mode: persisted per-clip. Default to 'auto' — the backend
    // never sets an explicit mode on the initial clip, so we assume the
    // pipeline's default (auto / face tracking) was used.
    const reframeMode = clipState.reframeMode || clip.reframe_mode || 'auto';
    const isReframing = !!clipState.reframing;
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
    // Format timestamp as mm:ss
    const fmtTs = (sec) => {
        const s = Math.max(0, Math.floor(sec || 0));
        const m = Math.floor(s / 60);
        const r = s % 60;
        return `${m}:${String(r).padStart(2, '0')}`;
    };
    const startTs = fmtTs(clip.start);
    const endTs = fmtTs(clip.end);

    // A clip is "customized" when the user has modified any toggle or
    // param away from the preselection defaults. Shown as a pink dot
    // next to the title so the user can see at a glance which cards
    // have been touched vs which still use the default pipeline config.
    const defaultSmartCut = !!preselections?.smartcut;
    const defaultHookOn = !!preselections?.hook;
    const defaultSubsOn = !!preselections?.subtitles;
    const isCustomized =
        toggles.smartcut !== defaultSmartCut ||
        toggles.hook !== defaultHookOn ||
        toggles.subtitles !== defaultSubsOn ||
        (toggles.hook && hookParams.text && hookParams.text !== (clip.viral_hook_text || clip.hook_text || ''));

    const scoreLevel = clip.viral_score >= 80 ? 'high' : clip.viral_score >= 50 ? 'mid' : 'low';
    const viralScoreGradient = {
        high: 'linear-gradient(135deg, #10b981, #059669)',
        mid: 'linear-gradient(135deg, #f59e0b, #d97706)',
        low: 'linear-gradient(135deg, #f97316, #ea580c)',
    }[scoreLevel];

    const handleDelete = () => {
        if (window.confirm(`Delete clip #${index + 1} permanently? This only hides it from the grid — the file stays on disk.`)) {
            onUpdateState({ deleted: true });
        }
    };

    const handleToggleReframe = async () => {
        if (isReframing) return;
        const nextMode = reframeMode === 'auto' ? 'disabled' : 'auto';
        onUpdateState({ reframing: true });
        try {
            const res = await fetch(getApiUrl(`/api/reframe/${jobId}/${index}`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reframe_mode: nextMode }),
            });
            if (!res.ok) {
                const errText = await res.text();
                // 409 = source slice missing (legacy jobs)
                if (res.status === 409) {
                    toast.error('Source slice not preserved for this clip — reprocess the video to enable reframe switching.');
                } else {
                    toast.error(`Reframe failed: ${errText.slice(0, 200)}`);
                }
                onUpdateState({ reframing: false });
                return;
            }
            const data = await res.json();
            if (data.success && data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                onUpdateState({ reframeMode: nextMode, reframing: false });
                toast.success(
                    nextMode === 'disabled'
                        ? 'Reframe disabled — clip now shows the full 4:3 frame with black bars.'
                        : 'Auto reframe enabled — face tracking is back on.',
                );
            } else {
                onUpdateState({ reframing: false });
                toast.error('Reframe returned no video URL');
            }
        } catch (err) {
            console.error('Reframe error:', err);
            toast.error('Reframe failed — check console for details');
            onUpdateState({ reframing: false });
        }
    };

    return (
        <div
            className={`bg-[#0f0f13] border rounded-2xl overflow-hidden animate-fade-in transition-opacity ${
                isDisabled ? 'border-white/5 opacity-50' : 'border-white/5'
            }`}
            style={{ animationDelay: `${index * 0.1}s` }}
        >
            {/* Video player - 9:16 container */}
            <div className="relative w-full aspect-[9/16] bg-black rounded-t-2xl overflow-hidden">
                {/* Card action row (top-left) — disable/delete grouped in a translucent pill */}
                <div className="absolute top-2 left-2 z-20 flex items-center gap-1 bg-black/60 backdrop-blur-sm rounded-full p-1 border border-white/10 shadow-lg">
                    <button
                        onClick={() => onUpdateState({ disabled: !isDisabled })}
                        title={isDisabled ? 'Enable clip' : 'Disable clip (excluded from Publish all)'}
                        className="p-1 rounded-full hover:bg-white/10 text-zinc-300 hover:text-white transition-colors"
                    >
                        {isDisabled ? <EyeOff size={12} /> : <Eye size={12} />}
                    </button>
                    <button
                        onClick={handleToggleReframe}
                        disabled={isReframing}
                        title={
                            isReframing
                                ? 'Reframing…'
                                : reframeMode === 'auto'
                                    ? 'Reframe: Auto (face tracking) — click to disable'
                                    : 'Reframe: Disabled (4:3 + black bars) — click to enable auto'
                        }
                        className={`p-1 rounded-full transition-colors ${
                            reframeMode === 'auto'
                                ? 'text-accent-pink hover:bg-accent-pink/20'
                                : 'text-zinc-300 hover:text-white hover:bg-white/10'
                        } disabled:opacity-60 disabled:cursor-wait`}
                    >
                        {isReframing ? (
                            <Loader2 size={12} className="animate-spin" />
                        ) : reframeMode === 'auto' ? (
                            <Crop size={12} />
                        ) : (
                            <Square size={12} />
                        )}
                    </button>
                    <div className="w-px h-3 bg-white/10" />
                    <button
                        onClick={handleDelete}
                        title="Remove clip from grid"
                        className="p-1 rounded-full text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors"
                    >
                        <Trash2 size={12} />
                    </button>
                </div>

                {/* Top-right stack: rank + viral score + published (vertical) */}
                <div className="absolute top-2 right-2 z-20 flex flex-col items-end gap-1.5">
                    {rank && totalClips > 1 && (
                        <div
                            className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold shadow-lg backdrop-blur-sm ${
                                rank === 1
                                    ? 'bg-gradient-to-r from-yellow-400 to-amber-500 text-black'
                                    : 'bg-black/60 text-white border border-white/10'
                            }`}
                            title={rank === 1 ? 'Top clip (highest viral score)' : `Rank ${rank}/${totalClips}`}
                        >
                            {rank === 1 && <Trophy size={9} />}
                            #{rank}
                            <span className="opacity-60 font-normal">/{totalClips}</span>
                        </div>
                    )}
                    {publishedAt && (
                        <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/90 text-white text-[10px] font-semibold shadow-lg">
                            <Check size={10} />
                            Published
                        </div>
                    )}
                </div>

                {/* Disabled overlay banner */}
                {isDisabled && (
                    <div className="absolute bottom-16 left-0 right-0 z-10 text-center pointer-events-none">
                        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-black/80 backdrop-blur-sm border border-white/20 text-[10px] font-semibold text-zinc-300 uppercase tracking-wider shadow-xl">
                            <EyeOff size={10} />
                            Disabled — not published in batch
                        </span>
                    </div>
                )}

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
            <div className="p-4 space-y-3">
                {/* Header — title, viral score, timestamp */}
                <div className="space-y-2">
                    <div className="flex items-start gap-2">
                        {clip.viral_score != null && (
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <div
                                        className="flex flex-col items-center justify-center rounded-xl px-2.5 py-1.5 shrink-0 cursor-help select-none shadow-md"
                                        style={{ background: viralScoreGradient }}
                                    >
                                        <span className="text-base font-black text-white leading-none">{clip.viral_score}</span>
                                        <span className="text-[8px] font-semibold text-white/70 uppercase tracking-wider leading-none mt-0.5">score</span>
                                    </div>
                                </TooltipTrigger>
                                <TooltipContent side="top" className="max-w-[220px] text-center">
                                    {clip.viral_reason || 'AI viral potential score'}
                                </TooltipContent>
                            </Tooltip>
                        )}
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 mb-0.5">
                                <h3
                                    className="text-[14px] font-semibold text-white leading-snug line-clamp-2"
                                    title={clip.video_title_for_youtube_short}
                                >
                                    {clip.video_title_for_youtube_short || 'Viral Clip Generated'}
                                </h3>
                                {isCustomized && (
                                    <span
                                        className="w-1.5 h-1.5 rounded-full bg-accent-pink shrink-0 mt-1"
                                        title="Customized — toggles or params differ from defaults"
                                    />
                                )}
                            </div>
                            <div className="flex items-center gap-2 text-[10px] text-zinc-500 font-mono">
                                <span className="flex items-center gap-1">
                                    <Clock size={9} />
                                    {startTs} → {endTs}
                                </span>
                                <span className="text-zinc-700">·</span>
                                <span>{duration}s</span>
                            </div>
                        </div>
                    </div>

                    {/* Viral reason quote — below the header, subtle */}
                    {clip.viral_reason && (
                        <div className="flex items-start gap-1.5 px-2 py-1.5 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                            <Quote size={10} className="text-zinc-600 mt-0.5 shrink-0" />
                            <p className="text-[11px] text-zinc-500 italic leading-relaxed line-clamp-2">
                                {clip.viral_reason}
                            </p>
                        </div>
                    )}
                </div>

                {/* Compact toggles — single horizontal row, 3 slim pills */}
                <div className="grid grid-cols-3 gap-1.5">
                    <button
                        onClick={() => setToggles((t) => ({ ...t, smartcut: !t.smartcut }))}
                        title="Smart Cut — remove silences and filler words"
                        className={`flex flex-col items-center justify-center gap-0.5 py-2 rounded-lg border text-[10px] font-semibold transition-all ${
                            toggles.smartcut
                                ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                : 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300 hover:bg-white/[0.04]'
                        }`}
                    >
                        <Scissors size={13} />
                        Smart Cut
                    </button>

                    <div className={`relative flex flex-col ${toggles.hook ? '' : ''}`}>
                        <button
                            onClick={() => setToggles((t) => ({ ...t, hook: !t.hook }))}
                            title="Hook text overlay"
                            className={`flex flex-col items-center justify-center gap-0.5 py-2 rounded-lg border text-[10px] font-semibold transition-all w-full ${
                                toggles.hook
                                    ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                    : 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300 hover:bg-white/[0.04]'
                            }`}
                        >
                            <MessageSquare size={13} />
                            Hook
                        </button>
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                setShowHookModal(true);
                            }}
                            title="Hook settings"
                            className="absolute top-1 right-1 p-0.5 rounded text-zinc-600 hover:text-white hover:bg-white/10 transition-colors"
                        >
                            <Settings size={10} />
                        </button>
                    </div>

                    <div className="relative flex flex-col">
                        <button
                            onClick={() => setToggles((t) => ({ ...t, subtitles: !t.subtitles }))}
                            title="Subtitles"
                            className={`flex flex-col items-center justify-center gap-0.5 py-2 rounded-lg border text-[10px] font-semibold transition-all w-full ${
                                toggles.subtitles
                                    ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                    : 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300 hover:bg-white/[0.04]'
                            }`}
                        >
                            <Type size={13} />
                            Subtitles
                        </button>
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                setShowSubtitleModal(true);
                            }}
                            title="Subtitle settings"
                            className="absolute top-1 right-1 p-0.5 rounded text-zinc-600 hover:text-white hover:bg-white/10 transition-colors"
                        >
                            <Settings size={10} />
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
                        disabled={isComposing || isDisabled}
                        title={
                            isDisabled
                                ? 'Clip is disabled — enable it to publish'
                                : publishedAt
                                    ? 'Already published — click to publish again'
                                    : 'Publish to TikTok / Instagram / YouTube via Zernio'
                        }
                        className={`px-4 py-2.5 rounded-lg border text-sm font-semibold flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50 ${
                            publishedAt
                                ? 'bg-emerald-500/20 hover:bg-emerald-500/30 border-emerald-500/30 text-emerald-300'
                                : 'bg-accent-pink/20 hover:bg-accent-pink/30 border-accent-pink/30 text-accent-pink'
                        }`}
                    >
                        {publishedAt ? <Check size={15} /> : <Send size={15} />}
                        {publishedAt ? 'Republish' : 'Publish'}
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
                    onPublished={() => onUpdateState({ publishedAt: Date.now() })}
                />

                {/* Metadata (collapsible) — YouTube title + TikTok caption */}
                <div className="border-t border-white/5 pt-2 -mx-4 px-4">
                    <button
                        onClick={() => setShowMetadata((v) => !v)}
                        className="w-full flex items-center justify-between text-[10px] font-semibold text-zinc-500 uppercase tracking-wider hover:text-zinc-300 transition-colors"
                    >
                        <span>Copy metadata</span>
                        <ChevronDown size={12} className={`transition-transform ${showMetadata ? 'rotate-180' : ''}`} />
                    </button>
                    {showMetadata && (
                        <div className="space-y-2 mt-2 animate-fade-in">
                            {/* YouTube title */}
                            <div>
                                <div className="flex items-center justify-between mb-0.5">
                                    <label className="text-[10px] text-zinc-600 flex items-center gap-1">
                                        <Youtube size={9} className="text-red-500" />
                                        YouTube title
                                    </label>
                                    <button
                                        onClick={() => copyToClipboard(clip.video_title_for_youtube_short, 'title')}
                                        aria-label={copiedField === 'title' ? 'Copied!' : 'Copy YouTube title'}
                                        className="p-1 text-zinc-500 hover:text-white rounded transition-colors"
                                    >
                                        {copiedField === 'title' ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
                                    </button>
                                </div>
                                <p className="text-[11px] text-zinc-400 leading-relaxed bg-white/[0.02] rounded px-2 py-1.5 border border-white/[0.04]">
                                    {clip.video_title_for_youtube_short || 'Untitled Viral Short'}
                                </p>
                            </div>

                            {/* TikTok / Instagram caption */}
                            <div>
                                <div className="flex items-center justify-between mb-0.5">
                                    <label className="text-[10px] text-zinc-600 flex items-center gap-1">
                                        <Instagram size={9} className="text-pink-500" />
                                        TikTok / IG caption
                                    </label>
                                    <button
                                        onClick={() => copyToClipboard(clip.video_description_for_tiktok || clip.video_description_for_instagram, 'caption')}
                                        aria-label={copiedField === 'caption' ? 'Copied!' : 'Copy caption'}
                                        className="p-1 text-zinc-500 hover:text-white rounded transition-colors"
                                    >
                                        {copiedField === 'caption' ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
                                    </button>
                                </div>
                                <p className="text-[11px] text-zinc-500 italic leading-relaxed bg-white/[0.02] rounded px-2 py-1.5 border border-white/[0.04] line-clamp-3 hover:line-clamp-none transition-all cursor-text">
                                    {clip.video_description_for_tiktok || clip.video_description_for_instagram || 'No caption available'}
                                </p>
                            </div>
                        </div>
                    )}
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
