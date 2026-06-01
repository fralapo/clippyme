import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Send, Loader2, Check, AlertCircle, Clock, Zap, Calendar } from 'lucide-react';
import { toast } from 'sonner';
import { getApiUrl } from '../config';
import { seedToggles, seedHookParams, seedSubtitleParams } from '../lib/seedClipParams';

/**
 * BatchPublishModal — publish multiple clips in sequence on Zernio.
 *
 * Props:
 *   isOpen, onClose
 *   jobId
 *   clips: Array<{ clip: object, originalIndex: number }>  (already filtered)
 *   onPublished: (originalIndex) => void
 */
export default function BatchPublishModal({ isOpen, onClose, jobId, clips, clipStates = {}, preselections = null, onPublished }) {
    const [zernioConfig, setZernioConfig] = useState(null);
    const [scheduleMode, setScheduleMode] = useState('auto');
    // Start date for auto slots — defaults to today (local YYYY-MM-DD).
    // Only meaningful when scheduleMode === 'auto'. The batch publisher
    // schedules **one clip per day** starting from this date (replicating
    // the behavior of the original tmp/programma_shorts.py script) so a
    // single batch doesn't hit Zernio's per-platform daily limits.
    const todayLocalISO = () => {
        const d = new Date();
        const off = d.getTimezoneOffset();
        const local = new Date(d.getTime() - off * 60_000);
        return local.toISOString().slice(0, 10);
    };
    // Add N days to a YYYY-MM-DD string, returning YYYY-MM-DD.
    const addDaysISO = (isoDate, days) => {
        const [y, m, d] = isoDate.split('-').map(Number);
        // Construct in local time to avoid TZ drift across midnight
        const dt = new Date(y, m - 1, d);
        dt.setDate(dt.getDate() + days);
        const yy = dt.getFullYear();
        const mm = String(dt.getMonth() + 1).padStart(2, '0');
        const dd = String(dt.getDate()).padStart(2, '0');
        return `${yy}-${mm}-${dd}`;
    };
    const [startDate, setStartDate] = useState(todayLocalISO());
    // "One per day" spacing mode: default ON, replicates the original
    // tmp/programma_shorts.py behavior. When OFF all clips get the same
    // start_date and the backend SmartScheduler distributes them across
    // slots within that single day (old behavior, only useful for very
    // small batches ≤ 5 that fit under the daily limit).
    const [oneClipPerDay, setOneClipPerDay] = useState(true);
    const [enabled, setEnabled] = useState({ tiktok: true, instagram: true, youtube: true });
    const [publishing, setPublishing] = useState(false);
    const [results, setResults] = useState({}); // {originalIndex: 'ok' | 'error' | 'pending'}

    useEffect(() => {
        if (!isOpen) return;
        setResults({});
        setStartDate(todayLocalISO());
        fetch(getApiUrl('/api/config/zernio'))
            .then((r) => (r.ok ? r.json() : null))
            .then(setZernioConfig)
            .catch(() => setZernioConfig(null));
    }, [isOpen]);

    if (!isOpen) return null;

    const accounts = zernioConfig?.accounts || {};
    const isConfigured = !!zernioConfig?.configured;
    const platformsAvailable = {
        tiktok: !!accounts.tiktok,
        instagram: !!accounts.instagram,
        youtube: !!accounts.youtube,
    };
    const enabledCount = Object.entries(enabled).filter(
        ([k, v]) => v && platformsAvailable[k],
    ).length;

    const buildPlatformTargets = () => {
        const out = [];
        if (enabled.tiktok && accounts.tiktok) {
            out.push({
                platform: 'tiktok',
                accountId: accounts.tiktok,
                platformSpecificData: {
                    tiktokSettings: {
                        privacy_level: 'PUBLIC_TO_EVERYONE',
                        allow_comment: true,
                        allow_duet: true,
                        allow_stitch: true,
                        content_preview_confirmed: true,
                        express_consent_given: true,
                    },
                },
            });
        }
        if (enabled.instagram && accounts.instagram) {
            out.push({
                platform: 'instagram',
                accountId: accounts.instagram,
                platformSpecificData: { shareToFeed: true },
            });
        }
        if (enabled.youtube && accounts.youtube) {
            out.push({
                platform: 'youtube',
                accountId: accounts.youtube,
                platformSpecificData: { visibility: 'public', madeForKids: false },
            });
        }
        return out;
    };

    const handlePublishAll = async () => {
        if (!isConfigured) {
            toast.error('Configure your Zernio API key in Settings first');
            return;
        }
        if (enabledCount === 0) {
            toast.error('Select at least one platform');
            return;
        }
        if (clips.length === 0) {
            toast.info('No clips to publish');
            return;
        }

        // Local, mutable view of which platforms are still healthy for THIS
        // batch run. If Zernio reports a daily quota exhaustion for a
        // platform on any clip, we remove that platform from subsequent
        // clips in the batch instead of blindly hammering the rate limit.
        const activePlatforms = { ...enabled };
        const exhausted = new Set();

        // --- TikTok daily-API-call workaround ---
        // Zernio/TikTok enforces a hard 5 POST/day limit per account on the
        // create-post endpoint, counting API calls (not scheduled posts).
        // Even if every clip is scheduled for a DIFFERENT future day, call
        // #6 still 429s with "Daily limit reached: 5/5 posts today". We
        // pre-count how many TikTok creates we've already made today and
        // skip TikTok preventively when the local counter reaches 5 —
        // saves a round-trip to Zernio and keeps the batch progressing
        // on Instagram + YouTube without error spam.
        const todayLocalKey = todayLocalISO();
        const tiktokCounterKey = `clippyme_tiktok_daily_count_${accounts.tiktok || 'noaccount'}_${todayLocalKey}`;
        const readTikTokCount = () => {
            try {
                const v = Number(localStorage.getItem(tiktokCounterKey) || '0');
                return Number.isFinite(v) ? v : 0;
            } catch { return 0; }
        };
        const incTikTokCount = () => {
            try {
                const next = readTikTokCount() + 1;
                localStorage.setItem(tiktokCounterKey, String(next));
                return next;
            } catch { return 0; }
        };
        const TIKTOK_DAILY_CAP = 5;
        if (readTikTokCount() >= TIKTOK_DAILY_CAP && activePlatforms.tiktok) {
            activePlatforms.tiktok = false;
            exhausted.add('tiktok');
            toast.info('TikTok daily limit (5/day) already reached — this batch will publish only to Instagram / YouTube.');
        }

        setPublishing(true);

        let ok = 0;
        let fail = 0;
        let skipped = 0;
        let batchIdx = 0;
        for (const { clip, originalIndex } of clips) {
            // Each clip gets its OWN start_date when "one per day" is on:
            //   clip #0 → startDate
            //   clip #1 → startDate + 1 day
            //   clip #N → startDate + N days
            // This matches tmp/programma_shorts.py (original script) and
            // avoids Zernio's per-platform 5/day limit on medium batches.
            const perClipStartDate = oneClipPerDay
                ? addDaysISO(startDate, batchIdx)
                : startDate;
            batchIdx += 1;
            setResults((prev) => ({ ...prev, [originalIndex]: 'pending' }));

            // Pre-check TikTok local counter right before emitting each
            // target list — if we've already issued 5 create-post calls
            // for TikTok today across ANY batch run, drop it now so we
            // don't waste a round-trip on a guaranteed 429.
            if (activePlatforms.tiktok && readTikTokCount() >= TIKTOK_DAILY_CAP) {
                activePlatforms.tiktok = false;
                if (!exhausted.has('tiktok')) {
                    exhausted.add('tiktok');
                    toast.info(`TikTok daily cap (${TIKTOK_DAILY_CAP}/day) reached mid-batch — remaining clips publish only to Instagram / YouTube.`);
                }
            }

            // Rebuild target list per-clip from the current active set so
            // exhausted platforms drop out for the rest of the batch.
            // NOTE: tiktokSettings goes at the ROOT body level (below), NOT
            // inside platformSpecificData. Same cleanup as PublishModal.
            const platformTargets = [];
            if (activePlatforms.tiktok && accounts.tiktok) {
                platformTargets.push({
                    platform: 'tiktok',
                    accountId: accounts.tiktok,
                    platformSpecificData: {},
                });
            }
            if (activePlatforms.instagram && accounts.instagram) {
                platformTargets.push({
                    platform: 'instagram',
                    accountId: accounts.instagram,
                    platformSpecificData: { shareToFeed: true },
                });
            }
            if (activePlatforms.youtube && accounts.youtube) {
                platformTargets.push({
                    platform: 'youtube',
                    accountId: accounts.youtube,
                    platformSpecificData: { visibility: 'public', madeForKids: false },
                });
            }

            if (platformTargets.length === 0) {
                // Every selected platform has been exhausted. Stop the loop
                // entirely — keep remaining clips untouched so the user can
                // republish them tomorrow.
                setResults((prev) => ({ ...prev, [originalIndex]: 'skipped' }));
                skipped += 1;
                continue;
            }

            // Per-clip compose intent: pick up toggles + params the user
            // configured in ResultCard (persisted via useClipStates). If any
            // toggle is active we send compose_first=true so the backend
            // runs the Smart Cut → Hook → Subtitles pipeline before upload.
            // Without this the batch path uploaded the raw base clip,
            // ignoring every toggle the user had turned on.
            //
            // Race-proof fallback: the ResultCard seeds clipStates from
            // preselections on mount via a useEffect, but useClipStates
            // loads from localStorage in a SEPARATE effect driven by
            // jobId change. The two can race on history restore — if
            // BatchPublishModal opens before the seed has settled, the
            // persisted clipState.toggles may still be undefined, and
            // the old code would send an empty body. Fix: if toggles is
            // missing, fall back to a fresh seed built from preselections
            // (same shape as ResultCard.defaultToggles). This works for
            // both 'brand new job just finished' and 'job restored from
            // history' paths without relying on React timing.
            const clipState = clipStates[originalIndex] || {};
            // Race-proof fallback: if the persisted clipState hasn't settled
            // yet (modal opened right after the job finished, or job restored
            // from history), reconstruct toggles/params from preselections via
            // the shared seeding util ResultCard also uses.
            const toggles = clipState.toggles ?? seedToggles(preselections);
            const anyToggleActive = Object.values(toggles).some(Boolean);
            const hookParams = clipState.hookParams ?? seedHookParams(clip, preselections);
            const subtitleParams = clipState.subtitleParams ?? seedSubtitleParams(preselections);

            const titleText = (clip.video_title_for_youtube_short || `Clip ${originalIndex + 1}`).slice(0, 100);
            const captionText = (clip.tiktok_caption && clip.tiktok_caption.trim()) || titleText;

            try {
                const body = {
                    title: titleText,
                    caption: captionText,
                    platforms: platformTargets,
                    schedule_mode: scheduleMode,
                    // Only send start_date in auto mode — ignored by backend for now/manual
                    ...(scheduleMode === 'auto' && perClipStartDate ? { start_date: perClipStartDate } : {}),
                    timezone: zernioConfig?.timezone || 'Europe/Rome',
                    // TikTok settings at the root (Zernio expects them here).
                    tiktok_settings: activePlatforms.tiktok && accounts.tiktok ? {
                        privacy_level: 'PUBLIC_TO_EVERYONE',
                        allow_comment: true,
                        allow_duet: true,
                        allow_stitch: true,
                        content_preview_confirmed: true,
                        express_consent_given: true,
                    } : undefined,
                    // Honor per-clip Smart Cut / Hook / Subtitles toggles.
                    ...(anyToggleActive ? {
                        compose_first: true,
                        toggles,
                        hook_params: toggles.hook ? hookParams : {},
                        subtitle_params: toggles.subtitles ? subtitleParams : {},
                    } : {}),
                };
                const res = await fetch(getApiUrl(`/api/publish/${jobId}/${originalIndex}`), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    const detail = (err.detail || `HTTP ${res.status}`).toString();

                    // Detect Zernio per-platform daily-limit responses and
                    // disable the offending platform for the rest of the
                    // batch. The backend surfaces the Zernio error body
                    // verbatim in the detail (see app.py publish handler),
                    // so we match on the stable substrings:
                    //   "Daily limit reached for this account"
                    //   "platform":"youtube" / "tiktok" / "instagram"
                    const isDailyLimit = /daily limit/i.test(detail);
                    // Tolerant regex: matches "platform":"youtube" with any
                    // amount of whitespace or escaping.
                    const platformMatch = detail.match(/"?platform"?\s*:\s*\\?"([a-zA-Z]+)/i);
                    let offending = platformMatch ? platformMatch[1].toLowerCase() : null;
                    // Secondary heuristic: if the detail mentions a platform
                    // name in plain text (e.g. "youtube daily limit"), pick
                    // that up too. Useful when Zernio changes its body shape.
                    if (!offending && isDailyLimit) {
                        for (const p of ['youtube', 'tiktok', 'instagram']) {
                            if (detail.toLowerCase().includes(p)) {
                                offending = p;
                                break;
                            }
                        }
                    }
                    // Last-resort fallback: on a 429 with "daily limit" that
                    // we still can't attribute, disable **all** currently
                    // active platforms so we don't keep hammering Zernio.
                    if (isDailyLimit && !offending && res.status === 429) {
                        Object.keys(activePlatforms).forEach((k) => {
                            if (activePlatforms[k]) exhausted.add(k);
                            activePlatforms[k] = false;
                        });
                        toast.warning('Zernio daily quota reached — stopping batch (could not identify the specific platform, disabling all).');
                        setResults((prev) => ({ ...prev, [originalIndex]: 'error' }));
                        fail += 1;
                        continue;
                    }

                    if (isDailyLimit && offending && activePlatforms[offending]) {
                        activePlatforms[offending] = false;
                        exhausted.add(offending);
                        const nicer = offending.charAt(0).toUpperCase() + offending.slice(1);
                        toast.warning(
                            `${nicer} daily quota reached — skipping ${nicer} for the rest of this batch. Remaining clips continue on other platforms.`,
                        );
                        // This clip partially failed (on the exhausted
                        // platform) but may still have succeeded on the
                        // others — Zernio returns a hard fail on any
                        // platform rejection, so we mark it as error and
                        // move on without throwing.
                        setResults((prev) => ({ ...prev, [originalIndex]: 'error' }));
                        fail += 1;
                        continue;
                    }

                    throw new Error(detail);
                }
                setResults((prev) => ({ ...prev, [originalIndex]: 'ok' }));
                onPublished(originalIndex);
                ok += 1;
                // Track TikTok API-call count for the preventive daily cap.
                // We only increment on successful create-post responses so
                // a transient network error doesn't falsely burn quota.
                if (platformTargets.some((p) => p.platform === 'tiktok')) {
                    incTikTokCount();
                }
            } catch (e) {
                setResults((prev) => ({ ...prev, [originalIndex]: 'error' }));
                fail += 1;
                toast.error(`Clip ${originalIndex + 1}: ${e.message}`);
            }
        }
        setPublishing(false);

        const exhaustedList = Array.from(exhausted).join(', ');
        if (fail === 0 && skipped === 0) {
            toast.success(`All ${ok} clips published successfully!`);
        } else if (skipped > 0) {
            toast.warning(
                `${ok} published, ${fail} failed, ${skipped} skipped (all selected platforms exhausted${exhaustedList ? `: ${exhaustedList}` : ''}). Try again tomorrow.`,
            );
        } else {
            toast.warning(
                `${ok} published, ${fail} failed${exhaustedList ? ` — ${exhaustedList} daily quota reached` : ''}.`,
            );
        }
    };

    return createPortal(
        <div
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
            onClick={publishing ? undefined : onClose}
        >
            <div
                className="bg-[oklch(9%_0.006_260)] border border-white/10 rounded-[3px] w-full max-w-xl shadow-elevated relative flex flex-col max-h-[90vh] overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                {!publishing && (
                    <button
                        onClick={onClose}
                        className="absolute top-4 right-4 z-30 p-1.5 rounded-[3px] bg-white/5 hover:bg-white/10"
                    >
                        <X size={18} className="text-zinc-400" />
                    </button>
                )}

                <div className="px-6 pt-6 pb-4 border-b border-white/5">
                    <h3 className="text-lg font-display font-bold text-white flex items-center gap-2">
                        <Send size={18} className="text-accent-pink" />
                        Publish all clips
                    </h3>
                    <p className="text-xs text-zinc-500 mt-0.5">
                        Publishing {clips.length} clip{clips.length === 1 ? '' : 's'} in sequence on the selected platforms.
                    </p>
                </div>

                <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
                    {!isConfigured && (
                        <div className="px-4 py-3 rounded-[3px] bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs">
                            ⚠ Zernio is not configured. Open <strong>Settings → Social Publishing</strong> first.
                        </div>
                    )}

                    {/* Platforms */}
                    <div className="space-y-2">
                        <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">Platforms</label>
                        <div className="grid grid-cols-3 gap-2">
                            {[
                                { id: 'tiktok', label: 'TikTok' },
                                { id: 'instagram', label: 'Instagram' },
                                { id: 'youtube', label: 'YouTube' },
                            ].map(({ id, label }) => {
                                const available = platformsAvailable[id];
                                const active = enabled[id] && available;
                                return (
                                    <button
                                        key={id}
                                        onClick={() => available && setEnabled({ ...enabled, [id]: !enabled[id] })}
                                        disabled={!available || publishing}
                                        className={`py-2.5 px-3 rounded-[3px] text-xs font-medium border transition-all ${
                                            active
                                                ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                                : available
                                                    ? 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300'
                                                    : 'bg-white/[0.01] text-zinc-700 border-white/5 cursor-not-allowed'
                                        }`}
                                    >
                                        {label}
                                        {!available && <span className="block text-[9px] mt-0.5">No account ID</span>}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Schedule mode */}
                    <div className="space-y-2">
                        <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">When</label>
                        <div className="grid grid-cols-2 gap-2">
                            {[
                                { id: 'auto', label: 'Auto slots (recommended)', icon: Clock },
                                { id: 'now', label: 'Now (all at once)', icon: Zap },
                            ].map(({ id, label, icon: Icon }) => (
                                <button
                                    key={id}
                                    onClick={() => setScheduleMode(id)}
                                    disabled={publishing}
                                    className={`py-2.5 px-3 rounded-[3px] text-xs font-medium border transition-all flex items-center justify-center gap-1.5 ${
                                        scheduleMode === id
                                            ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                            : 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300'
                                    }`}
                                >
                                    <Icon size={12} />
                                    {label}
                                </button>
                            ))}
                        </div>
                        <p className="text-[10px] text-zinc-600">
                            {scheduleMode === 'auto'
                                ? 'One clip per day starting from the selected date (default). SmartScheduler picks the optimal slot per day.'
                                : 'All clips publish immediately on every selected platform.'}
                        </p>
                    </div>

                    {/* Start date picker + one-per-day toggle — only visible when schedule_mode === 'auto' */}
                    {scheduleMode === 'auto' && (
                        <div className="space-y-3">
                            <div className="space-y-2">
                                <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
                                    <Calendar size={11} />
                                    Start from day
                                </label>
                                <input
                                    type="date"
                                    value={startDate}
                                    min={todayLocalISO()}
                                    onChange={(e) => setStartDate(e.target.value)}
                                    disabled={publishing}
                                    className="w-full bg-[oklch(9%_0.006_260)] border border-white/10 rounded-[3px] px-3 py-2.5 text-sm text-white focus:outline-none focus:border-[oklch(74%_0.175_62)]/55 disabled:opacity-50"
                                />
                            </div>

                            {/* One-per-day toggle */}
                            <div className="flex items-start justify-between gap-3 p-3 rounded-[3px] bg-white/[0.02] border border-white/5">
                                <div className="flex-1 min-w-0">
                                    <div className="text-[11px] font-medium text-zinc-300">
                                        One clip per day
                                    </div>
                                    <p className="text-[10px] text-zinc-500 mt-0.5">
                                        {oneClipPerDay
                                            ? `Each clip lands on its own day starting from ${startDate} → ${addDaysISO(startDate, Math.max(0, clips.length - 1))} (${clips.length} day${clips.length === 1 ? '' : 's'}). Bypasses Zernio's 5/day per-platform limit.`
                                            : `All ${clips.length} clips on ${startDate} in different slots. Only works for batches ≤ 5 due to daily posting limits.`}
                                    </p>
                                </div>
                                <button
                                    onClick={() => setOneClipPerDay(!oneClipPerDay)}
                                    disabled={publishing}
                                    className={`shrink-0 w-10 h-5 rounded-full transition-all duration-300 relative p-0.5 ${
                                        oneClipPerDay ? 'bg-accent-pink' : 'bg-white/10'
                                    } disabled:opacity-50`}
                                >
                                    <div
                                        className={`w-4 h-4 rounded-full bg-white transition-all duration-300 ${
                                            oneClipPerDay ? 'translate-x-5' : 'translate-x-0'
                                        }`}
                                    />
                                </button>
                            </div>

                            <p className="text-[10px] text-zinc-600">
                                Past dates auto-bump to today. SmartScheduler picks the optimal time slot on each day (prime-time IT windows).
                            </p>
                        </div>
                    )}

                    {/* Clip list with per-clip status */}
                    <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                        {clips.map(({ clip, originalIndex }) => {
                            const status = results[originalIndex];
                            return (
                                <div
                                    key={originalIndex}
                                    className="flex items-center gap-2 px-3 py-2 rounded-[3px] bg-white/[0.02] border border-white/5"
                                >
                                    <span className="text-[10px] text-zinc-600 font-mono w-6">#{originalIndex + 1}</span>
                                    <span className="flex-1 text-[11px] text-zinc-400 truncate">
                                        {clip.video_title_for_youtube_short || `Clip ${originalIndex + 1}`}
                                    </span>
                                    {status === 'pending' && <Loader2 size={12} className="animate-spin text-accent-pink" />}
                                    {status === 'ok' && <Check size={12} className="text-emerald-400" />}
                                    {status === 'error' && <AlertCircle size={12} className="text-red-400" />}
                                    {status === 'skipped' && (
                                        <span className="text-[9px] font-medium text-amber-400 uppercase">Skipped</span>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>

                <div className="px-6 py-4 border-t border-white/5 flex items-center justify-between bg-black/20">
                    <p className="text-[11px] text-zinc-500">
                        {enabledCount} platform{enabledCount === 1 ? '' : 's'} × {clips.length} clips
                    </p>
                    <button
                        onClick={handlePublishAll}
                        disabled={publishing || !isConfigured || enabledCount === 0 || clips.length === 0}
                        className="flex items-center gap-2 px-5 py-2.5 rounded-[3px] bg-gradient-to-r from-accent-pink to-accent-purple text-white text-sm font-semibold shadow-glow-pink disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {publishing ? (
                            <>
                                <Loader2 size={14} className="animate-spin" />
                                Publishing {Object.values(results).filter((r) => r === 'ok' || r === 'error' || r === 'skipped').length}/{clips.length}
                            </>
                        ) : (
                            <>
                                <Send size={14} />
                                {scheduleMode === 'now' ? 'Publish all now' : 'Schedule all'}
                            </>
                        )}
                    </button>
                </div>
            </div>
        </div>,
        document.body,
    );
}
