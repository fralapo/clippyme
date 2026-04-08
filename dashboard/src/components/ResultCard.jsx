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

    // Layered state seeding: clipState (persisted per-clip) > preselections
    // (pipeline defaults) > hard-coded defaults. This way a refresh restores
    // the user's exact choices for this specific clip.
    const defaultToggles = {
        smartcut: !!preselections?.smartcut,
        hook: !!preselections?.hook,
        subtitles: !!preselections?.subtitles,
    };
    const defaultHookParams = {
        text: clip.viral_hook_text || clip.hook_text || '',
        position: preselections?.hook?.position || 'top',
        size: preselections?.hook?.size || 'S',
        offset_y: 0,
    };
    const defaultSubtitleParams = {
        preset: preselections?.subtitles?.preset || 'classic_white',
        mode: preselections?.subtitles?.mode || 'karaoke',
        display_mode: 'word_group',
        highlight_color: null,
        font: preselections?.subtitles?.font || 'Montserrat-Black',
        uppercase: true,
        offset_y: 0,
        font_color: preselections?.subtitles?.font_color || '#FFFFFF',
        position: preselections?.subtitles?.position || 'bottom',
    };

    const [toggles, setTogglesLocal] = useState({
        ...defaultToggles,
        ...(clipState.toggles || {}),
    });
    const [hookParams, setHookParamsLocal] = useState({
        ...defaultHookParams,
        ...(clipState.hookParams || {}),
    });
    const [subtitleParams, setSubtitleParamsLocal] = useState({
        ...defaultSubtitleParams,
        ...(clipState.subtitleParams || {}),
    });

    // Wrapped setters that ALSO persist into per-clip state so reloads and
    // batch publish both see the user's actual choices. We use refs-less
    // closure updates — React batches, and onUpdateState writes localStorage
    // via useClipStates.
    const setToggles = (updater) => {
        setTogglesLocal((prev) => {
            const next = typeof updater === 'function' ? updater(prev) : updater;
            onUpdateState({ toggles: next });
            return next;
        });
    };
    const setHookParams = (updater) => {
        setHookParamsLocal((prev) => {
            const next = typeof updater === 'function' ? updater(prev) : updater;
            onUpdateState({ hookParams: next });
            return next;
        });
    };
    const setSubtitleParams = (updater) => {
        setSubtitleParamsLocal((prev) => {
            const next = typeof updater === 'function' ? updater(prev) : updater;
            onUpdateState({ subtitleParams: next });
            return next;
        });
    };

    const [isComposing, setIsComposing] = useState(false);
    const [showPublishModal, setShowPublishModal] = useState(false);

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 2000);
    };

    const handleDownload = async () => {
        // Idempotency guard: React sets isComposing asynchronously so a fast
        // double-click can fire two requests before the first setState lands.
        // Bail out immediately if a compose is already in flight.
        if (isComposing) return;

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
    const baselineHookText = clip.viral_hook_text || clip.hook_text || '';
    const hookDrift =
        toggles.hook && (
            hookParams.text !== baselineHookText ||
            hookParams.position !== (preselections?.hook?.position || 'top') ||
            hookParams.size !== (preselections?.hook?.size || 'S') ||
            hookParams.offset_y !== 0
        );
    const subtitleDrift =
        toggles.subtitles && (
            subtitleParams.mode !== (preselections?.subtitles?.mode || 'karaoke') ||
            subtitleParams.preset !== (preselections?.subtitles?.preset || 'classic_white') ||
            subtitleParams.font !== (preselections?.subtitles?.font || 'Montserrat-Black') ||
            subtitleParams.font_color !== (preselections?.subtitles?.font_color || '#FFFFFF') ||
            subtitleParams.position !== (preselections?.subtitles?.position || 'bottom') ||
            subtitleParams.offset_y !== 0
        );
    const isCustomized =
        toggles.smartcut !== defaultSmartCut ||
        toggles.hook !== defaultHookOn ||
        toggles.subtitles !== defaultSubsOn ||
        hookDrift ||
        subtitleDrift;

    const scoreLevel = clip.viral_score >= 80 ? 'high' : clip.viral_score >= 50 ? 'mid' : 'low';
    // Single accent color for every tier. The VU-meter encodes
    // severity via how many segments light up, not via hue swings.
    const viralScoreAccent = {
        high: 'oklch(74% 0.175 62)',
        mid: 'oklch(78% 0.16 75)',
        low: 'oklch(58% 0.12 55)',
    }[scoreLevel];
    // 8-segment VU: light up ceil(score/12.5) segments (so 100 = 8 lit).
    const vuLit = Math.min(8, Math.ceil((clip.viral_score || 0) / 12.5));

    // Non-destructive delete with undo toast. The clip file stays on
    // disk — we only hide it from the grid, so undo is free. The toast
    // stays visible for 6 seconds, giving the user plenty of time to
    // correct an accidental click (Forgiveness / Error Recovery
    // principle from the UX brainstorm).
    const handleDelete = () => {
        onUpdateState({ deleted: true });
        toast(`Clip #${index + 1} removed from grid`, {
            description: 'The file stays on disk. You have 6 seconds to undo.',
            duration: 6000,
            action: {
                label: 'Undo',
                onClick: () => onUpdateState({ deleted: false }),
            },
        });
    };

    // Toggle visibility (disable/enable) with the same undo affordance.
    // Batch-publish excludes disabled clips, so an accidental click can
    // silently drop a clip from the publish run — the toast with undo
    // fixes that.
    const handleToggleDisabled = () => {
        const nextDisabled = !isDisabled;
        onUpdateState({ disabled: nextDisabled });
        if (nextDisabled) {
            toast(`Clip #${index + 1} excluded from publishing`, {
                description: 'It will not be included in "Publish all". You have 6 seconds to undo.',
                duration: 6000,
                action: {
                    label: 'Undo',
                    onClick: () => onUpdateState({ disabled: false }),
                },
            });
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
            className={`group relative bg-[oklch(14%_0.009_260)] border rounded-[3px] overflow-hidden transition-all duration-300 ${
                isDisabled
                    ? 'border-white/5 opacity-45 grayscale'
                    : 'border-white/[0.08] hover:border-[oklch(74%_0.175_62)]/40 hover:shadow-[0_24px_60px_-30px_oklch(0%_0_0/0.9),0_0_0_1px_oklch(74%_0.175_62/0.2)]'
            }`}
        >
            {/* Slate strip — the little "CLIP #003" header that frames the
                whole card, like a clapperboard slate. */}
            <div className="flex items-center justify-between px-3 h-7 border-b border-white/[0.06] bg-white/[0.015]">
                <div className="flex items-center gap-2 type-mono text-[10px] text-zinc-500 tabular-nums">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-[oklch(74%_0.175_62)] shadow-[0_0_6px_oklch(74%_0.175_62/0.6)]" />
                    CLIP&nbsp;#{String(index + 1).padStart(3, '0')}
                </div>
                <div className="type-label !text-[9px] !tracking-[0.2em] text-zinc-600 tabular-nums">
                    {startTs}<span className="text-zinc-700 mx-1">→</span>{endTs}
                </div>
            </div>

            {/* Video player - 9:16 container */}
            <div className="relative w-full aspect-[9/16] bg-black overflow-hidden">
                {/* Card action row (top-left) — flat editorial toolbar */}
                <div className="absolute top-2 left-2 z-20 flex items-center bg-black/75 backdrop-blur-sm rounded-[2px] border border-white/[0.12] shadow-lg">
                    {/* Larger target areas (min 32x32, touch-friendly).
                        Full 44x44 isn't practical inside a 9:16 thumbnail but
                        32x32 is already ~2.6x the previous hit area. */}
                    <button
                        onClick={handleToggleDisabled}
                        aria-label={isDisabled ? 'Enable clip' : 'Disable clip (excluded from Publish all)'}
                        title={isDisabled ? 'Enable clip' : 'Disable clip (excluded from Publish all)'}
                        className="w-8 h-8 flex items-center justify-center rounded-none hover:bg-white/10 text-zinc-300 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/70"
                    >
                        {isDisabled ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                    <button
                        onClick={handleToggleReframe}
                        disabled={isReframing}
                        aria-label={
                            isReframing
                                ? 'Reframing in progress'
                                : reframeMode === 'auto'
                                    ? 'Auto reframe active — click to disable'
                                    : 'Reframe disabled (4:3) — click to re-enable'
                        }
                        title={
                            isReframing
                                ? 'Reframing\u2026'
                                : reframeMode === 'auto'
                                    ? 'Auto reframe (face tracking) \u2014 click to disable'
                                    : 'Reframe disabled (4:3 + black bars) \u2014 click to re-enable'
                        }
                        className={`w-8 h-8 flex items-center justify-center rounded-none transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/70 ${
                            reframeMode === 'auto'
                                ? 'text-[oklch(78%_0.175_65)] hover:bg-[oklch(74%_0.175_62)]/20'
                                : 'text-zinc-300 hover:text-white hover:bg-white/10'
                        } disabled:opacity-60 disabled:cursor-wait`}
                    >
                        {isReframing ? (
                            <Loader2 size={14} className="animate-spin" />
                        ) : reframeMode === 'auto' ? (
                            <Crop size={14} />
                        ) : (
                            <Square size={14} />
                        )}
                    </button>
                    <div className="w-px h-5 bg-white/[0.12]" />
                    <button
                        onClick={handleDelete}
                        aria-label="Remove clip from grid"
                        title="Remove clip from grid"
                        className="w-8 h-8 flex items-center justify-center rounded-none text-[oklch(70%_0.2_25)] hover:text-[oklch(78%_0.2_25)] hover:bg-[oklch(62%_0.22_25)]/15 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(62%_0.22_25)]/70"
                    >
                        <Trash2 size={14} />
                    </button>
                </div>

                {/* Top-right stack: rank + viral score + published (vertical) */}
                <div className="absolute top-2 right-2 z-20 flex flex-col items-end gap-1.5">
                    {rank && totalClips > 1 && (
                        <div
                            className={`flex items-center gap-1 px-2 py-1 rounded-[2px] type-mono text-[10px] font-semibold tabular-nums shadow-lg backdrop-blur-sm ${
                                rank === 1
                                    ? 'bg-[oklch(74%_0.175_62)] text-[oklch(14%_0.01_260)] border border-[oklch(74%_0.175_62)]'
                                    : 'bg-black/75 text-white border border-white/[0.14]'
                            }`}
                            title={rank === 1 ? 'Top clip (highest viral score)' : `Rank ${rank}/${totalClips}`}
                        >
                            {rank === 1 && <Trophy size={9} strokeWidth={2.4} />}
                            <span>#{String(rank).padStart(2, '0')}</span>
                            <span className="opacity-60 font-normal">/{String(totalClips).padStart(2, '0')}</span>
                        </div>
                    )}
                    {publishedAt && (
                        <div className="flex items-center gap-1.5 px-2 py-1 rounded-[2px] bg-[oklch(20%_0.04_145)] border border-[oklch(68%_0.18_145)]/50 text-[oklch(82%_0.15_145)] type-mono text-[10px] font-semibold uppercase tracking-[0.14em] shadow-lg rec-blink">
                            <span className="w-1.5 h-1.5 rounded-full bg-[oklch(68%_0.18_145)] shadow-[0_0_6px_oklch(68%_0.18_145/0.9)]" />
                            Published
                        </div>
                    )}
                </div>

                {/* Disabled overlay banner */}
                {isDisabled && (
                    <div className="absolute bottom-16 left-0 right-0 z-10 text-center pointer-events-none">
                        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-[2px] bg-black/85 backdrop-blur-sm border border-white/20 type-mono text-[10px] font-semibold text-zinc-300 uppercase tracking-[0.14em] shadow-xl">
                            <EyeOff size={10} />
                            Disabled — excluded from batch
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
            <div className="p-4 space-y-3.5">
                {/* Header — VU-meter score, title, mono duration */}
                <div className="flex items-start gap-3.5">
                    {clip.viral_score != null && (
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <div
                                    className="flex flex-col items-center gap-1.5 shrink-0 cursor-help select-none"
                                    aria-label={`Viral score ${clip.viral_score} of 100`}
                                >
                                    <div className="flex items-end gap-[3px] h-10" aria-hidden>
                                        {Array.from({ length: 8 }, (_, i) => (
                                            <div
                                                key={i}
                                                className={`vu-segment ${i < vuLit ? 'is-lit' : ''}`}
                                                style={{
                                                    height: `${38 + i * 2}%`,
                                                    backgroundColor: i < vuLit ? viralScoreAccent : undefined,
                                                    boxShadow: i < vuLit ? `0 0 6px ${viralScoreAccent}99` : undefined,
                                                }}
                                            />
                                        ))}
                                    </div>
                                    <div className="flex flex-col items-center leading-none">
                                        <span
                                            className="type-mono text-[15px] font-semibold tabular-nums"
                                            style={{ color: viralScoreAccent }}
                                        >
                                            {String(clip.viral_score).padStart(2, '0')}
                                        </span>
                                        <span className="type-label !text-[8px] !tracking-[0.22em] mt-0.5">Score</span>
                                    </div>
                                </div>
                            </TooltipTrigger>
                            <TooltipContent side="top" className="max-w-[240px] text-center">
                                {clip.viral_reason || 'AI viral potential score'}
                            </TooltipContent>
                        </Tooltip>
                    )}
                    <div className="flex-1 min-w-0 pt-0.5">
                        <div className="flex items-start gap-2 mb-1.5">
                            <h3
                                className="type-display text-[17px] sm:text-[18px] text-white leading-[1.15] line-clamp-2 font-normal"
                                title={clip.video_title_for_youtube_short}
                                style={{ letterSpacing: '-0.015em' }}
                            >
                                {clip.video_title_for_youtube_short || 'Untitled clip'}
                            </h3>
                            {isCustomized && (
                                <span
                                    className="w-1.5 h-1.5 rounded-full bg-[oklch(74%_0.175_62)] shrink-0 mt-2 shadow-[0_0_6px_oklch(74%_0.175_62/0.7)]"
                                    title="Customized — toggles or params differ from defaults"
                                />
                            )}
                        </div>
                        <div className="flex items-center gap-2 type-label !text-[10px] !tracking-[0.14em] tabular-nums">
                            <Clock size={9} strokeWidth={1.8} />
                            <span>{duration}s&nbsp;clip</span>
                            <span className="text-zinc-700">/</span>
                            <span className="text-zinc-600">
                                {clip.viral_score >= 80 ? 'High viral' : clip.viral_score >= 50 ? 'Good' : 'Low'}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Viral reason — pull quote, Fraunces italic */}
                {clip.viral_reason && (
                    <div className="relative pl-4 pr-2 py-0.5 border-l-2 border-[oklch(74%_0.175_62)]/40">
                        <Quote size={11} className="absolute -left-[1px] -top-1 text-[oklch(74%_0.175_62)]/60" strokeWidth={1.6} />
                        <p className="type-display italic text-[13px] text-zinc-400 leading-snug line-clamp-2">
                            {clip.viral_reason}
                        </p>
                    </div>
                )}

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
