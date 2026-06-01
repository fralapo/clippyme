import React, { useState, useEffect } from 'react';
import { Youtube, Loader2, Type, Instagram, Copy, Check, Scissors, MessageSquare, Settings, Trash2, ChevronDown, Trophy, Clock, Quote } from 'lucide-react';
import { toast } from 'sonner';
import { getApiUrl } from '../config';
import { seedToggles, seedHookParams, seedSubtitleParams } from '../lib/seedClipParams';
import SubtitleModal from './SubtitleModal';
import HookModal from './HookModal';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/**
 * Segmented toggle cell used in the ResultCard action row.
 * Has a clear ON/OFF state via LED indicator, mono uppercase label,
 * and an optional gear affordance that only shows when the cell is
 * active (avoids the "why is there a settings icon on an inactive
 * thing" confusion the previous version had).
 *
 * @param {{
 *   icon: React.ComponentType<{ size?: number, strokeWidth?: number }>,
 *   label: string,
 *   active: boolean,
 *   onToggle: () => void,
 *   onConfigure?: () => void,
 *   title?: string,
 * }} props
 */
function ToggleCell({ icon: Icon, label, active, onToggle, onConfigure, title }) {
    return (
        <div className="relative">
            <button
                type="button"
                onClick={onToggle}
                aria-pressed={active}
                title={title}
                className={`group w-full min-h-[52px] flex flex-col items-center justify-center gap-1 py-2 px-1.5 rounded-[3px] border transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/60 focus-visible:ring-offset-1 focus-visible:ring-offset-[oklch(14%_0.009_260)] ${
                    active
                        ? 'bg-[oklch(74%_0.175_62)]/[0.12] border-[oklch(74%_0.175_62)]/55 text-[oklch(82%_0.16_68)] shadow-[0_0_0_1px_oklch(74%_0.175_62/0.2)_inset]'
                        : 'bg-white/[0.02] border-white/[0.07] text-zinc-500 hover:text-zinc-200 hover:border-white/[0.14] hover:bg-white/[0.04]'
                }`}
            >
                <div className="flex items-center gap-1.5 w-full justify-center">
                    {/* LED indicator — lit amber when active */}
                    <span
                        aria-hidden
                        className={`w-1.5 h-1.5 rounded-full transition-all ${
                            active
                                ? 'bg-[oklch(74%_0.175_62)] shadow-[0_0_6px_oklch(74%_0.175_62/0.85)]'
                                : 'bg-zinc-700 group-hover:bg-zinc-500'
                        }`}
                    />
                    <Icon size={13} strokeWidth={active ? 2.2 : 1.8} />
                </div>
                <span
                    className="type-mono text-[9px] uppercase tracking-[0.14em] leading-none"
                    style={{ letterSpacing: '0.13em' }}
                >
                    {label}
                </span>
            </button>
            {onConfigure && active && (
                <button
                    type="button"
                    onClick={(e) => {
                        e.stopPropagation();
                        onConfigure();
                    }}
                    aria-label={`Configure ${label}`}
                    title={`${label} settings`}
                    className="absolute top-1 right-1 w-5 h-5 flex items-center justify-center rounded-[2px] text-[oklch(82%_0.16_68)]/70 hover:text-white hover:bg-[oklch(74%_0.175_62)]/25 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[oklch(74%_0.175_62)]"
                >
                    <Settings size={11} strokeWidth={2} />
                </button>
            )}
        </div>
    );
}

function ResultCard({
    clip,
    index,
    rank = null,
    totalClips = 0,
    jobId,
    onPlay,
    onPause,
    preselections,
    clipState = {},
    onUpdateClipState = () => {},
}) {
    // Bind the stable 2-arg parent callback to THIS card's index so the
    // internal `onUpdateState(patch)` API stays unchanged while the prop
    // ResultsGrid passes (onUpdateClipState) keeps a stable reference —
    // letting React.memo skip re-renders that don't touch this card.
    const onUpdateState = React.useCallback(
        (patch) => onUpdateClipState(index, patch),
        [onUpdateClipState, index],
    );
    const [showMetadata, setShowMetadata] = useState(false);
    // Selection model v2 — 'selected' is the opt-in flag for bulk
    // publish/download/delete. Legacy records lacking it default to
    // selected=true so nothing vanishes on upgrade from the old
    // 'disabled' shape.
    const isSelected = clipState.selected !== false;
    const publishedAt = clipState.publishedAt;
    // Reframe mode precedence: explicit per-clip override (persisted) >
    // backend-written clip.reframe_mode (from metadata.json) > job-level
    // preselection (the choice the user made at submission time) > 'auto'.
    // The preselection fallback matters for clips from older jobs where
    // the backend didn't yet write reframe_mode into each clip entry.
    const reframeMode =
        clipState.reframeMode
        || clip.reframe_mode
        || preselections?.reframe_mode
        || 'auto';
    const isReframing = !!clipState.reframing;
    const [showSubtitleModal, setShowSubtitleModal] = useState(false);
    const [showHookModal, setShowHookModal] = useState(false);
    const videoRef = React.useRef(null);
    const [currentVideoUrl, setCurrentVideoUrl] = useState(getApiUrl(clip.video_url));

    const [copiedField, setCopiedField] = useState(null);

    // Layered state seeding: clipState (persisted per-clip) > preselections
    // (pipeline defaults) > hard-coded defaults. This way a refresh restores
    // the user's exact choices for this specific clip. Seeding lives in a
    // shared util so the single-clip and batch-publish paths stay identical.
    const defaultToggles = seedToggles(preselections);
    const defaultHookParams = seedHookParams(clip, preselections);
    const defaultSubtitleParams = seedSubtitleParams(preselections);

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

    // Persist seeded state into clipStates on first mount so BatchPublishModal
    // (which reads toggles/hookParams/subtitleParams from clipStates, not
    // from each ResultCard's local state) sees the user's preselections
    // even if they never manually touched a toggle on this specific card.
    //
    // Without this, the batch publisher was receiving empty {} for every
    // clip that still had its "fresh from preselections" state — so
    // compose_first was never triggered and the raw clip was uploaded
    // regardless of the Smart Cut / Hook / Subtitles pre-selections the
    // user had set in the home Advanced Options.
    //
    // Guarded by "only if clipState is missing the field" so we don't
    // overwrite user overrides on subsequent renders.
    useEffect(() => {
        const patch = {};
        if (!clipState.toggles) patch.toggles = toggles;
        if (!clipState.hookParams) patch.hookParams = hookParams;
        if (!clipState.subtitleParams) patch.subtitleParams = subtitleParams;
        if (Object.keys(patch).length > 0) {
            onUpdateState(patch);
        }
        // Run once per clip mount — the seeded state does not change after
        // initial computation, so the deps list is intentionally empty.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Re-sync local state whenever the parent clipState changes externally
    // (e.g. Bulk Edit Apply in ResultsGrid writes new toggles directly to
    // clipStates without going through this card's setToggles). Without
    // this sync the card kept showing its own stale local toggles forever
    // — the bulk edit felt like a no-op even though clipStates was
    // correctly updated and downstream (download/publish) honoured it.
    //
    // We compare object identity on the incoming clipState slice: since
    // useClipStates only produces a new reference when the value
    // actually changed (functional setState with spread), reference
    // equality is a free and correct change detector — no JSON.stringify
    // per render.
    useEffect(() => {
        if (clipState.toggles) {
            setTogglesLocal((prev) => ({ ...prev, ...clipState.toggles }));
        }
    }, [clipState.toggles]);
    useEffect(() => {
        if (clipState.hookParams) {
            setHookParamsLocal((prev) => ({ ...prev, ...clipState.hookParams }));
        }
    }, [clipState.hookParams]);
    // Cache-bust the <video> src when a bulk reframe finishes. The
    // ResultsGrid bulk edit posts /api/reframe/{jobId}/{idx} in parallel
    // and then writes {reframeMode, reframeBust: timestamp} into
    // clipState — we listen for reframeBust and append it to the
    // original clip URL so the browser stops serving the stale file.
    useEffect(() => {
        if (clipState.reframeBust) {
            const base = clip.video_url || '';
            if (!base) return;
            const joiner = base.includes('?') ? '&' : '?';
            setCurrentVideoUrl(getApiUrl(`${base}${joiner}v=${clipState.reframeBust}`));
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [clipState.reframeBust]);
    useEffect(() => {
        if (clipState.subtitleParams) {
            setSubtitleParamsLocal((prev) => ({ ...prev, ...clipState.subtitleParams }));
        }
    }, [clipState.subtitleParams]);

    // isComposing + showPublishModal were used by the now-removed per-card
    // Download + Publish buttons. The sticky action rail in ResultsGrid
    // hosts those actions via the selection model, so both pieces of
    // state are obsolete. handleDownload() and <PublishModal/> are also
    // deleted below.

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 2000);
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
            subtitleParams.offset_y !== 0 ||
            // Classic-mode stroke + background drift
            subtitleParams.border_color !== (preselections?.subtitles?.border_color || '#000000') ||
            subtitleParams.border_width !== (preselections?.subtitles?.border_width ?? 2) ||
            subtitleParams.bg_color !== (preselections?.subtitles?.bg_color || '#000000') ||
            subtitleParams.bg_opacity !== (preselections?.subtitles?.bg_opacity ?? 0)
        );
    const isCustomized =
        toggles.smartcut !== defaultSmartCut ||
        toggles.hook !== defaultHookOn ||
        toggles.subtitles !== defaultSubsOn ||
        hookDrift ||
        subtitleDrift;

    const scoreLevel = clip.viral_score >= 80 ? 'high' : clip.viral_score >= 50 ? 'mid' : 'low';
    // Tiered accent — green / amber / red — so the viral score pops
    // visually and the user can triage a 15-clip grid at a glance.
    // Reserves the product amber (oklch 74 0.175 62) for primary CTAs
    // only (Publish). High = confident green, mid = cautious amber-
    // yellow, low = desaturated red.
    const viralScoreAccent = {
        high: 'oklch(72% 0.18 145)',   // green
        mid: 'oklch(82% 0.17 85)',     // yellow-amber (distinct from CTA orange)
        low: 'oklch(64% 0.19 25)',     // red
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
    const handleToggleSelected = () => {
        onUpdateState({ selected: !isSelected });
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
                        ? 'Auto reframe OFF — clip now shows letterbox (black bars top & bottom).'
                        : 'Auto reframe ON — face tracking is back on.',
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
                isSelected
                    ? 'border-[oklch(74%_0.175_62)]/45 shadow-[0_0_0_1px_oklch(74%_0.175_62/0.18),0_24px_60px_-30px_oklch(0%_0_0/0.9)]'
                    : 'border-white/[0.08] opacity-80 hover:border-white/25 hover:opacity-100'
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

                {/* Top-left selection checkbox — prominent, click target
                    is the whole pill. When selected, the card border
                    also glows amber (see root element className above). */}
                {/* Selection pill: outline-only style. The product amber
                    is reserved for the primary 'Publish' CTA in the
                    sticky rail, so the selected state here uses an
                    amber-tinted outline + check icon instead of a solid
                    fill. This lets the Publish action stand out while
                    selection stays visually quiet. */}
                <button
                    type="button"
                    onClick={handleToggleSelected}
                    aria-pressed={isSelected}
                    aria-label={isSelected ? 'Deselect clip' : 'Select clip for bulk actions'}
                    title={isSelected ? 'Click to exclude from bulk actions' : 'Click to include in bulk actions'}
                    className={`absolute top-2 left-2 z-20 flex items-center gap-1.5 px-2 py-1 rounded-[2px] type-mono text-[10px] uppercase tracking-[0.14em] font-semibold backdrop-blur-sm shadow-lg transition-colors ${
                        isSelected
                            ? 'bg-[oklch(74%_0.175_62)]/15 text-[oklch(82%_0.16_68)] border border-[oklch(74%_0.175_62)]/70'
                            : 'bg-black/75 text-zinc-300 border border-white/15 hover:bg-black/90 hover:border-white/30'
                    }`}
                >
                    <span
                        aria-hidden
                        className={`w-3.5 h-3.5 rounded-[2px] border-[1.5px] flex items-center justify-center ${
                            isSelected
                                ? 'border-[oklch(74%_0.175_62)] bg-[oklch(74%_0.175_62)]/20'
                                : 'border-zinc-400 bg-transparent'
                        }`}
                    >
                        {isSelected && <Check size={10} strokeWidth={3} className="text-[oklch(82%_0.16_68)]" />}
                    </span>
                    {isSelected ? 'Selected' : 'Select'}
                </button>

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

                {/* Clip action rail — reframe toggle switch (ON = face
                    tracking, OFF = letterbox with black bars) grows to
                    fill the row; a 36px icon-only Trash button anchors
                    the right edge for per-clip delete. Selection lives
                    in the separate pill overlay on the video frame,
                    not in this rail. The reframe pill mimics an iOS
                    switch so non-technical users grasp ON/OFF instantly. */}
                <div className="flex items-stretch gap-1.5 border border-white/[0.07] bg-white/[0.02] rounded-[3px] overflow-hidden">
                    <button
                        type="button"
                        onClick={() => { if (!isReframing) handleToggleReframe(); }}
                        disabled={isReframing}
                        role="switch"
                        aria-checked={reframeMode === 'auto'}
                        aria-label={reframeMode === 'auto' ? 'Auto reframe is ON — click to turn OFF' : 'Auto reframe is OFF — click to turn ON'}
                        title={
                            isReframing
                                ? 'Reframing\u2026'
                                : reframeMode === 'auto'
                                    ? 'Auto reframe ON — face tracking in a 9:16 vertical frame'
                                    : 'Auto reframe OFF — clip is shown with letterbox (black bars top & bottom)'
                        }
                        className="flex flex-1 min-w-0 items-center gap-2.5 h-9 px-3 text-left transition-colors border-r border-white/[0.07] hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(74%_0.175_62)]/55 focus-visible:ring-inset disabled:opacity-60 disabled:cursor-wait"
                    >
                        <span
                            aria-hidden
                            className={`relative shrink-0 w-8 h-[18px] rounded-full border transition-colors ${
                                reframeMode === 'auto'
                                    ? 'bg-[oklch(74%_0.175_62)] border-[oklch(70%_0.18_62)] shadow-[0_0_8px_-1px_oklch(74%_0.175_62/0.55)]'
                                    : 'bg-white/[0.05] border-white/15'
                            }`}
                        >
                            <span
                                className={`absolute top-[1px] w-[14px] h-[14px] rounded-full bg-white shadow-sm transition-[left] duration-200 ease-out ${
                                    reframeMode === 'auto' ? 'left-[15px]' : 'left-[1px]'
                                }`}
                            >
                                {isReframing && (
                                    <Loader2 size={10} className="animate-spin text-zinc-800 m-0.5" strokeWidth={2.4} />
                                )}
                            </span>
                        </span>
                        <span className="flex flex-col min-w-0 leading-tight">
                            <span className="type-mono text-[10px] uppercase tracking-[0.14em] text-zinc-400 truncate">
                                Auto&nbsp;reframe
                            </span>
                            <span className={`type-mono text-[9px] uppercase tracking-[0.12em] tabular-nums ${
                                reframeMode === 'auto' ? 'text-[oklch(82%_0.16_68)]' : 'text-zinc-600'
                            }`}>
                                {reframeMode === 'auto' ? 'ON · face track' : 'OFF · letterbox'}
                            </span>
                        </span>
                    </button>
                    <button
                        type="button"
                        onClick={handleDelete}
                        aria-label="Remove clip from grid"
                        title="Remove this clip from the grid — the file stays on disk, undo available in the toast"
                        className="shrink-0 w-9 h-9 flex items-center justify-center text-[oklch(70%_0.2_25)] hover:text-[oklch(82%_0.2_25)] hover:bg-[oklch(62%_0.22_25)]/12 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(62%_0.22_25)]/55 focus-visible:ring-inset"
                    >
                        <Trash2 size={13} strokeWidth={2} />
                    </button>
                </div>

                {/* Toggle row — three segmented buttons with LED indicator,
                    mono label, and a gear settings affordance that only
                    shows when the toggle is ON. */}
                <div className="grid grid-cols-3 gap-1.5">
                    <ToggleCell
                        icon={Scissors}
                        label="Smart Cut"
                        active={toggles.smartcut}
                        onToggle={() => setToggles((t) => ({ ...t, smartcut: !t.smartcut }))}
                        title="Smart Cut — remove silences and filler words"
                    />
                    <ToggleCell
                        icon={MessageSquare}
                        label="Hook"
                        active={toggles.hook}
                        onToggle={() => setToggles((t) => ({ ...t, hook: !t.hook }))}
                        onConfigure={() => setShowHookModal(true)}
                        title="Hook — text overlay on top of the video"
                    />
                    <ToggleCell
                        icon={Type}
                        label="Subtitles"
                        active={toggles.subtitles}
                        onToggle={() => setToggles((t) => ({ ...t, subtitles: !t.subtitles }))}
                        onConfigure={() => setShowSubtitleModal(true)}
                        title="Subtitles — burn captions into the video"
                    />
                </div>

                {/* Per-card Download + Publish buttons (and their
                    PublishModal) removed in favour of the sticky action
                    rail in ResultsGrid. The rail's 'Download NN' /
                    'Publish NN' operate on the selected clips, so this
                    card's actions are now exposed via the selection
                    checkbox on the video overlay + the bulk buttons.
                    Single-clip publish still works: tick this card, then
                    click 'Publish 01' in the rail. Eliminates the visual
                    duplication the user called out. */}

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
                initialValues={subtitleParams}
                onGenerate={(params) => {
                    // Normalize camelCase emitted by SubtitleModal into the
                    // snake_case shape the backend compose endpoint expects.
                    // The modal always emits `mode` explicitly so we never
                    // have to infer it from the presence of other fields.
                    const normalized = {
                        ...(params.mode !== undefined && { mode: params.mode }),
                        ...(params.position !== undefined && { position: params.position }),
                        ...(params.offset_y !== undefined && { offset_y: params.offset_y }),
                        ...(params.fontSize !== undefined && { font_size: params.fontSize }),
                        ...(params.fontName !== undefined && { font: params.fontName }),
                        ...(params.fontColor !== undefined && { font_color: params.fontColor }),
                        ...(params.borderColor !== undefined && { border_color: params.borderColor }),
                        ...(params.borderWidth !== undefined && { border_width: params.borderWidth }),
                        ...(params.bgColor !== undefined && { bg_color: params.bgColor }),
                        ...(params.bgOpacity !== undefined && { bg_opacity: params.bgOpacity }),
                        ...(params.preset !== undefined && { preset: params.preset }),
                        ...(params.karaoke_mode !== undefined && { display_mode: params.karaoke_mode }),
                        ...(params.words_per_group !== undefined && { words_per_group: params.words_per_group }),
                        ...(params.uppercase !== undefined && { uppercase: params.uppercase }),
                        ...(params.highlight_color !== undefined && { highlight_color: params.highlight_color }),
                    };
                    setSubtitleParams(prev => ({ ...prev, ...normalized }));
                    setToggles(t => ({ ...t, subtitles: true }));
                    setShowSubtitleModal(false);
                }}
                isProcessing={false}
                videoUrl={currentVideoUrl}
            />

            <HookModal
                isOpen={showHookModal}
                onClose={() => setShowHookModal(false)}
                initialValues={hookParams}
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

// Memoized: ResultsGrid re-renders on every poll tick (2s) and on any clip's
// state change. Without memo, all N cards re-render each time; with it, only
// cards whose props actually changed re-render. Relies on the grid passing
// stable callback refs (see the useCallback wrapping in ResultsGrid).
export default React.memo(ResultCard);
