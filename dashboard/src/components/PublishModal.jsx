import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Send, Loader2, Calendar, Clock, Zap } from 'lucide-react';
import { toast } from 'sonner';
import { getApiUrl } from '../config';

/**
 * PublishModal — schedule a clip on TikTok / Instagram / YouTube via Zernio.
 *
 * Props:
 *   isOpen, onClose
 *   jobId, clipIndex
 *   defaultTitle, defaultCaption
 *   videoUrl (for preview)
 *   composeBeforePublish: { toggles, hookParams, subtitleParams } | null
 *     If provided, the backend will run a fresh compose pass before upload.
 */
export default function PublishModal({
    isOpen, onClose,
    jobId, clipIndex,
    defaultTitle = '', defaultCaption = '',
    videoUrl,
    composeBeforePublish = null,
    onPublished = null,
}) {
    const [title, setTitle] = useState(defaultTitle);
    const [caption, setCaption] = useState(defaultCaption);
    const [scheduleMode, setScheduleMode] = useState('now');
    const [manualDateTime, setManualDateTime] = useState('');
    const [enabled, setEnabled] = useState({ tiktok: true, instagram: true, youtube: true });
    const [zernioConfig, setZernioConfig] = useState(null);
    const [publishing, setPublishing] = useState(false);
    const [result, setResult] = useState(null);

    useEffect(() => {
        if (!isOpen) return;
        setTitle(defaultTitle);
        setCaption(defaultCaption);
        setResult(null);
        fetch(getApiUrl('/api/config/zernio'))
            .then((r) => r.ok ? r.json() : null)
            .then(setZernioConfig)
            .catch(() => setZernioConfig(null));
    }, [isOpen, defaultTitle, defaultCaption]);

    if (!isOpen) return null;

    const accounts = zernioConfig?.accounts || {};
    const isConfigured = !!zernioConfig?.configured;
    const platformsAvailable = {
        tiktok: !!accounts.tiktok,
        instagram: !!accounts.instagram,
        youtube: !!accounts.youtube,
    };
    const enabledCount = Object.entries(enabled)
        .filter(([k, v]) => v && platformsAvailable[k])
        .length;

    const handlePublish = async () => {
        if (!isConfigured) {
            toast.error('Configure your Zernio API key in Settings first');
            return;
        }
        if (enabledCount === 0) {
            toast.error('Select at least one platform');
            return;
        }
        if (scheduleMode === 'manual' && !manualDateTime) {
            toast.error('Pick a date/time for manual scheduling');
            return;
        }

        const platformTargets = [];
        if (enabled.tiktok && accounts.tiktok) {
            platformTargets.push({
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
            platformTargets.push({
                platform: 'instagram',
                accountId: accounts.instagram,
                platformSpecificData: { shareToFeed: true },
            });
        }
        if (enabled.youtube && accounts.youtube) {
            platformTargets.push({
                platform: 'youtube',
                accountId: accounts.youtube,
                platformSpecificData: {
                    title: (title || 'Clip').slice(0, 100),
                    visibility: 'public',
                    madeForKids: false,
                },
            });
        }

        const body = {
            title,
            caption,
            platforms: platformTargets,
            schedule_mode: scheduleMode,
            timezone: zernioConfig?.timezone || 'Europe/Rome',
        };
        if (scheduleMode === 'manual') {
            // ISO 8601 from datetime-local input (no timezone offset → backend treats it as local)
            body.scheduled_for = new Date(manualDateTime).toISOString();
        }
        if (composeBeforePublish) {
            body.compose_first = true;
            body.toggles = composeBeforePublish.toggles;
            body.hook_params = composeBeforePublish.hookParams;
            body.subtitle_params = composeBeforePublish.subtitleParams;
        }

        setPublishing(true);
        try {
            const res = await fetch(getApiUrl(`/api/publish/${jobId}/${clipIndex}`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            setResult(data);
            if (onPublished) onPublished(data);
            toast.success(
                scheduleMode === 'now'
                    ? 'Published successfully!'
                    : `Scheduled for ${data.scheduled_for || 'auto-picked slot'}`
            );
        } catch (e) {
            toast.error(`Publish failed: ${e.message}`);
        } finally {
            setPublishing(false);
        }
    };

    return createPortal(
        <div
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
            onClick={onClose}
        >
            <div
                className="bg-[#0f0f13] border border-white/10 rounded-2xl w-full max-w-2xl shadow-elevated relative flex flex-col max-h-[90vh] overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 z-30 p-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
                >
                    <X size={18} className="text-zinc-400" />
                </button>

                <div className="px-6 pt-6 pb-4 border-b border-white/5">
                    <h3 className="text-lg font-display font-bold text-white flex items-center gap-2">
                        <Send size={18} className="text-accent-pink" />
                        Publish to social
                    </h3>
                    <p className="text-xs text-zinc-500 mt-0.5">
                        Schedule this clip on TikTok, Instagram and YouTube via Zernio.
                    </p>
                </div>

                <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
                    {!isConfigured && (
                        <div className="px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs">
                            ⚠ Zernio is not configured. Open <strong>Settings → Social Publishing</strong> and add your API key + account IDs.
                        </div>
                    )}

                    {/* Title */}
                    <div className="space-y-1.5">
                        <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">Title</label>
                        <input
                            type="text"
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            maxLength={100}
                            className="w-full bg-white/[0.03] border border-white/5 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                            placeholder="YouTube title (max 100 chars)"
                        />
                    </div>

                    {/* Caption */}
                    <div className="space-y-1.5">
                        <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">Caption</label>
                        <textarea
                            value={caption}
                            onChange={(e) => setCaption(e.target.value)}
                            rows={4}
                            maxLength={2200}
                            className="w-full bg-white/[0.03] border border-white/5 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30 resize-none"
                            placeholder="Caption / description shown on all platforms"
                        />
                        <p className="text-[10px] text-zinc-600 text-right">{caption.length} / 2200</p>
                    </div>

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
                                        type="button"
                                        onClick={() => available && setEnabled({ ...enabled, [id]: !enabled[id] })}
                                        disabled={!available}
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
                        <div className="grid grid-cols-3 gap-2">
                            {[
                                { id: 'now', label: 'Now', icon: Zap },
                                { id: 'auto', label: 'Auto slot', icon: Clock },
                                { id: 'manual', label: 'Pick time', icon: Calendar },
                            ].map(({ id, label, icon: Icon }) => (
                                <button
                                    key={id}
                                    type="button"
                                    onClick={() => setScheduleMode(id)}
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
                        {scheduleMode === 'manual' && (
                            <input
                                type="datetime-local"
                                value={manualDateTime}
                                onChange={(e) => setManualDateTime(e.target.value)}
                                className="w-full bg-white/[0.03] border border-white/5 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30 mt-2"
                            />
                        )}
                        {scheduleMode === 'auto' && (
                            <p className="text-[10px] text-zinc-600">
                                A smart scheduler will pick the next optimal slot today (or tomorrow if it's late) avoiding collisions with your other scheduled posts.
                            </p>
                        )}
                    </div>

                    {/* Result */}
                    {result && (
                        <div className="px-4 py-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs space-y-1">
                            <p>✅ Post created — id: <code className="text-[10px] bg-black/20 px-1 rounded">{result.post_id || '?'}</code></p>
                            {result.scheduled_for && <p>Scheduled for: {result.scheduled_for}</p>}
                        </div>
                    )}
                </div>

                <div className="px-6 py-4 border-t border-white/5 flex items-center justify-between bg-black/20">
                    <p className="text-[11px] text-zinc-500">
                        {enabledCount} platform{enabledCount === 1 ? '' : 's'} selected
                    </p>
                    <button
                        type="button"
                        onClick={handlePublish}
                        disabled={publishing || !isConfigured || enabledCount === 0}
                        className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-accent-pink to-accent-purple text-white text-sm font-semibold shadow-glow-pink disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                    >
                        {publishing ? (
                            <>
                                <Loader2 size={14} className="animate-spin" />
                                Publishing...
                            </>
                        ) : (
                            <>
                                <Send size={14} />
                                {scheduleMode === 'now' ? 'Publish now' : 'Schedule'}
                            </>
                        )}
                    </button>
                </div>
            </div>
        </div>,
        document.body
    );
}
