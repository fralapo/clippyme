import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Send, Loader2, Check, AlertCircle, Clock, Zap, Calendar } from 'lucide-react';
import { toast } from 'sonner';
import { getApiUrl } from '../config';

/**
 * BatchPublishModal — publish multiple clips in sequence on Zernio.
 *
 * Props:
 *   isOpen, onClose
 *   jobId
 *   clips: Array<{ clip: object, originalIndex: number }>  (already filtered)
 *   onPublished: (originalIndex) => void
 */
export default function BatchPublishModal({ isOpen, onClose, jobId, clips, onPublished }) {
    const [zernioConfig, setZernioConfig] = useState(null);
    const [scheduleMode, setScheduleMode] = useState('auto');
    const [enabled, setEnabled] = useState({ tiktok: true, instagram: true, youtube: true });
    const [publishing, setPublishing] = useState(false);
    const [results, setResults] = useState({}); // {originalIndex: 'ok' | 'error' | 'pending'}

    useEffect(() => {
        if (!isOpen) return;
        setResults({});
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

        const platformTargets = buildPlatformTargets();
        setPublishing(true);

        let ok = 0;
        let fail = 0;
        for (const { clip, originalIndex } of clips) {
            setResults((prev) => ({ ...prev, [originalIndex]: 'pending' }));
            try {
                const body = {
                    title: (clip.video_title_for_youtube_short || `Clip ${originalIndex + 1}`).slice(0, 100),
                    caption: clip.tiktok_caption || '',
                    platforms: platformTargets.map((p) => {
                        if (p.platform !== 'youtube') return p;
                        return {
                            ...p,
                            platformSpecificData: {
                                ...p.platformSpecificData,
                                title: (clip.video_title_for_youtube_short || `Clip ${originalIndex + 1}`).slice(0, 100),
                            },
                        };
                    }),
                    schedule_mode: scheduleMode,
                    timezone: zernioConfig?.timezone || 'Europe/Rome',
                };
                const res = await fetch(getApiUrl(`/api/publish/${jobId}/${originalIndex}`), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${res.status}`);
                }
                setResults((prev) => ({ ...prev, [originalIndex]: 'ok' }));
                onPublished(originalIndex);
                ok += 1;
            } catch (e) {
                setResults((prev) => ({ ...prev, [originalIndex]: 'error' }));
                fail += 1;
                toast.error(`Clip ${originalIndex + 1}: ${e.message}`);
            }
        }
        setPublishing(false);
        if (fail === 0) toast.success(`All ${ok} clips published successfully!`);
        else toast.warning(`${ok} succeeded, ${fail} failed`);
    };

    return createPortal(
        <div
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
            onClick={publishing ? undefined : onClose}
        >
            <div
                className="bg-[#0f0f13] border border-white/10 rounded-2xl w-full max-w-xl shadow-elevated relative flex flex-col max-h-[90vh] overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                {!publishing && (
                    <button
                        onClick={onClose}
                        className="absolute top-4 right-4 z-30 p-1.5 rounded-lg bg-white/5 hover:bg-white/10"
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
                        <div className="px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs">
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
                                        className={`py-2.5 px-3 rounded-lg text-xs font-medium border transition-all ${
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
                                    className={`py-2.5 px-3 rounded-lg text-xs font-medium border transition-all flex items-center justify-center gap-1.5 ${
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
                                ? 'Each clip gets its own optimal slot today/tomorrow (anti-collision via SmartScheduler).'
                                : 'All clips publish immediately on every selected platform.'}
                        </p>
                    </div>

                    {/* Clip list with per-clip status */}
                    <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                        {clips.map(({ clip, originalIndex }) => {
                            const status = results[originalIndex];
                            return (
                                <div
                                    key={originalIndex}
                                    className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/[0.02] border border-white/5"
                                >
                                    <span className="text-[10px] text-zinc-600 font-mono w-6">#{originalIndex + 1}</span>
                                    <span className="flex-1 text-[11px] text-zinc-400 truncate">
                                        {clip.video_title_for_youtube_short || `Clip ${originalIndex + 1}`}
                                    </span>
                                    {status === 'pending' && <Loader2 size={12} className="animate-spin text-accent-pink" />}
                                    {status === 'ok' && <Check size={12} className="text-emerald-400" />}
                                    {status === 'error' && <AlertCircle size={12} className="text-red-400" />}
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
                        className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-accent-pink to-accent-purple text-white text-sm font-semibold shadow-glow-pink disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {publishing ? (
                            <>
                                <Loader2 size={14} className="animate-spin" />
                                Publishing {Object.values(results).filter((r) => r === 'ok' || r === 'error').length}/{clips.length}
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
