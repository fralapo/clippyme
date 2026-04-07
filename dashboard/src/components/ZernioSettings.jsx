import React, { useEffect, useState } from 'react';
import { Eye, EyeOff, RefreshCw, Save, Check, Link2 } from 'lucide-react';
import { toast } from 'sonner';
import { getApiUrl } from '../config';

/**
 * Zernio settings: API key + per-platform account IDs + timezone.
 * Persists via POST /api/config/zernio.
 * Account discovery via GET /api/zernio/accounts.
 */
export default function ZernioSettings() {
    const [apiKey, setApiKey] = useState('');
    const [showKey, setShowKey] = useState(false);
    const [maskedKey, setMaskedKey] = useState('');
    const [hasKey, setHasKey] = useState(false);
    const [accounts, setAccounts] = useState({ tiktok: '', instagram: '', youtube: '' });
    const [timezone, setTimezone] = useState('Europe/Rome');
    const [discovered, setDiscovered] = useState([]);
    const [saving, setSaving] = useState(false);
    const [discovering, setDiscovering] = useState(false);

    useEffect(() => {
        fetch(getApiUrl('/api/config/zernio'))
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                if (!data) return;
                setHasKey(!!data.configured);
                setMaskedKey(data.api_key_masked || '');
                setAccounts({
                    tiktok: data.accounts?.tiktok || '',
                    instagram: data.accounts?.instagram || '',
                    youtube: data.accounts?.youtube || '',
                });
                if (data.timezone) setTimezone(data.timezone);
            })
            .catch(() => { /* silent */ });
    }, []);

    const handleSave = async () => {
        setSaving(true);
        try {
            const body = {
                accounts,
                timezone,
            };
            // Only send api_key if user typed a new one
            if (apiKey.trim()) body.api_key = apiKey.trim();
            const res = await fetch(getApiUrl('/api/config/zernio'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            setHasKey(!!data.configured);
            setMaskedKey(data.api_key_masked || '');
            setApiKey(''); // clear input after save
            toast.success('Zernio settings saved');
        } catch (e) {
            toast.error(`Save failed: ${e.message}`);
        } finally {
            setSaving(false);
        }
    };

    const handleDiscover = async () => {
        setDiscovering(true);
        try {
            const res = await fetch(getApiUrl('/api/zernio/accounts'));
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            setDiscovered(data.accounts || []);
            toast.success(`Found ${(data.accounts || []).length} connected accounts`);
        } catch (e) {
            toast.error(`Discovery failed: ${e.message}`);
        } finally {
            setDiscovering(false);
        }
    };

    const pickAccount = (platform, id) => {
        setAccounts((prev) => ({ ...prev, [platform]: id }));
    };

    return (
        <div className="space-y-5">
            {/* API Key */}
            <div className="space-y-2">
                <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-zinc-300 flex items-center gap-2">
                        Zernio API Key
                        {hasKey ? (
                            <span className="flex items-center gap-1 text-[10px] text-success bg-success/10 border border-success/20 px-1.5 py-0.5 rounded">
                                <Check size={9} /> {maskedKey || 'Connected'}
                            </span>
                        ) : (
                            <span className="text-[10px] text-zinc-600 bg-white/[0.03] border border-white/[0.06] px-1.5 py-0.5 rounded">
                                Not connected
                            </span>
                        )}
                    </label>
                    <a
                        href="https://zernio.com"
                        target="_blank"
                        rel="noreferrer"
                        className="text-[11px] text-accent-pink hover:text-accent-pink/80 transition-colors"
                    >
                        Get token
                    </a>
                </div>
                <div className="relative">
                    <input
                        type={showKey ? 'text' : 'password'}
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        placeholder={hasKey ? 'Leave empty to keep current key, or paste a new one' : 'sk_...'}
                        className="w-full bg-[#0f0f13] border border-white/10 rounded-lg px-4 py-3 pr-10 text-sm text-white placeholder:text-zinc-700 focus:outline-none focus:border-accent-pink/50 font-mono"
                    />
                    <button
                        type="button"
                        onClick={() => setShowKey((s) => !s)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
                    >
                        {showKey ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                </div>
                <p className="text-[11px] text-zinc-600">
                    Powers one-click publishing to TikTok, Instagram and YouTube. Stored server-side in <code className="text-zinc-500">data/config.json</code>.
                </p>
            </div>

            {/* Account discovery */}
            <div className="space-y-2">
                <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
                        Connected accounts
                    </label>
                    <button
                        type="button"
                        onClick={handleDiscover}
                        disabled={!hasKey || discovering}
                        className="flex items-center gap-1.5 text-[11px] text-accent-pink hover:text-pink-300 disabled:text-zinc-600 disabled:cursor-not-allowed transition-colors"
                    >
                        <RefreshCw size={11} className={discovering ? 'animate-spin' : ''} />
                        {discovering ? 'Discovering...' : 'Discover from Zernio'}
                    </button>
                </div>
                {discovered.length > 0 && (
                    <div className="bg-white/[0.02] border border-white/5 rounded-lg p-2 space-y-1 max-h-48 overflow-y-auto">
                        {discovered.map((a) => {
                            const id = a._id || a.id;
                            const platform = (a.platform || '').toLowerCase();
                            const key = platform === 'tiktok' || platform === 'instagram' || platform === 'youtube' ? platform : null;
                            const isSelected = key && accounts[key] === id;
                            return (
                                <button
                                    key={id}
                                    type="button"
                                    onClick={() => key && pickAccount(key, id)}
                                    disabled={!key}
                                    className={`w-full flex items-center justify-between px-2 py-1.5 rounded text-xs transition-colors ${
                                        isSelected
                                            ? 'bg-accent-pink/20 text-accent-pink'
                                            : 'hover:bg-white/5 text-zinc-400'
                                    } ${!key && 'opacity-50 cursor-not-allowed'}`}
                                >
                                    <span className="flex items-center gap-2">
                                        <span className="uppercase text-[9px] tracking-wider text-zinc-500">{platform}</span>
                                        <span className="text-white">{a.username || a.displayName || id}</span>
                                    </span>
                                    {isSelected && <Check size={12} />}
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Per-platform IDs */}
            <div className="grid grid-cols-1 gap-3">
                {[
                    { key: 'tiktok', label: 'TikTok' },
                    { key: 'instagram', label: 'Instagram' },
                    { key: 'youtube', label: 'YouTube' },
                ].map(({ key, label }) => {
                    const isSet = !!accounts[key];
                    return (
                        <div key={key} className="space-y-1">
                            <label className="text-[11px] font-medium text-zinc-400 flex items-center gap-2">
                                {label} account ID
                                {isSet && (
                                    <span className="flex items-center gap-1 text-[9px] text-success bg-success/10 border border-success/20 px-1.5 py-0.5 rounded">
                                        <Check size={8} /> Linked
                                    </span>
                                )}
                            </label>
                            <input
                                type="text"
                                value={accounts[key]}
                                onChange={(e) => setAccounts({ ...accounts, [key]: e.target.value })}
                                placeholder="68becb..."
                                className="w-full bg-[#0f0f13] border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder:text-zinc-700 focus:outline-none focus:border-accent-pink/50 font-mono"
                            />
                        </div>
                    );
                })}
            </div>

            {/* Timezone */}
            <div className="space-y-1">
                <label className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">Default timezone</label>
                <input
                    type="text"
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    placeholder="Europe/Rome"
                    className="w-full bg-white/[0.03] border border-white/5 rounded-lg px-3 py-2 text-xs text-white placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                />
                <p className="text-[10px] text-zinc-600">
                    IANA timezone string (e.g. Europe/Rome, America/New_York).
                </p>
            </div>

            <div className="pt-2">
                <button
                    type="button"
                    onClick={handleSave}
                    disabled={saving}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent-pink/20 text-accent-pink border border-accent-pink/30 hover:bg-accent-pink/30 text-sm font-medium transition-colors disabled:opacity-50"
                >
                    <Save size={14} />
                    {saving ? 'Saving...' : 'Save Zernio settings'}
                </button>
            </div>
        </div>
    );
}
