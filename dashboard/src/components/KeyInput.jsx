import React, { useState, useEffect, useCallback } from 'react';
import { Eye, EyeOff, Check, Save, Loader2, AlertCircle, ChevronDown, Upload, Trash2 } from 'lucide-react';
import { config } from '../config';

const KEY_TYPES = [
    { id: 'GEMINI_API_KEY', label: 'Gemini API Key', link: 'https://aistudio.google.com/app/apikey', placeholder: 'AIzaSy...', required: true },
    { id: 'HF_TOKEN', label: 'Hugging Face Token', link: 'https://huggingface.co/settings/tokens', placeholder: 'hf_...', required: false, hint: 'Optional — enables faster Whisper model downloads and avoids rate limits.' }
];

export default function KeyInput({ onKeySet, onHfTokenSet }) {
    const [keys, setKeys] = useState({});
    const [serverConfig, setServerConfig] = useState({});
    const [visibleKeys, setVisibleKeys] = useState({});
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [message, setMessage] = useState({ type: '', text: '' });

    const [cookiesFile, setCookiesFile] = useState(null);
    const [cookiesConfigured, setCookiesConfigured] = useState(false);
    const [isSavingCookies, setIsSavingCookies] = useState(false);

    const [models, setModels] = useState([]);
    const [selectedModel, setSelectedModel] = useState('gemini-2.5-flash');
    const [isLoadingModels, setIsLoadingModels] = useState(false);

    const fetchModels = useCallback(async (key) => {
        if (!key) return;
        setIsLoadingModels(true);
        try {
            const response = await fetch(`${config.API_BASE_URL}/api/config/models`, {
                headers: { 'X-Gemini-Key': key }
            });
            if (response.ok) {
                const data = await response.json();
                if (data.models && data.models.length > 0) {
                    setModels(data.models);
                }
            }
        } catch (error) {
            console.error("Failed to fetch models:", error);
        } finally {
            setIsLoadingModels(false);
        }
    }, []);

    const checkCookies = useCallback(async () => {
        try {
            const response = await fetch(`${config.API_BASE_URL}/api/config/cookies/status`);
            if (response.ok) {
                const data = await response.json();
                setCookiesConfigured(!!data.configured);
            }
        } catch (error) {
            console.error("Failed to check cookie status:", error);
        }
    }, []);

    const fetchConfig = useCallback(async () => {
        try {
            const response = await fetch(`${config.API_BASE_URL}/api/config`);
            if (response.ok) {
                const data = await response.json();
                setServerConfig(data);
                if (data.GEMINI_MODEL) {
                    setSelectedModel(data.GEMINI_MODEL);
                    localStorage.setItem('clippyme_model', data.GEMINI_MODEL);
                }

                const geminiKey = data.GEMINI_API_KEY || localStorage.getItem('gemini_key');
                if (geminiKey) {
                    fetchModels(geminiKey);
                }
            }
        } catch (error) {
            console.error("Failed to fetch config:", error);
        } finally {
            setIsLoading(false);
        }
    }, [fetchModels]);

    useEffect(() => {
        fetchConfig();
        checkCookies();
    }, [fetchConfig, checkCookies]);

    const handleSave = async (keyId) => {
        const value = keys[keyId];
        if (!value) return;

        setIsSaving(true);
        setMessage({ type: '', text: '' });

        try {
            const response = await fetch(`${config.API_BASE_URL}/api/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ keys: { [keyId]: value } })
            });

            if (response.ok) {
                setMessage({ type: 'success', text: 'Key saved successfully!' });
                await fetchConfig();
                setKeys({ ...keys, [keyId]: '' });

                if (keyId === 'GEMINI_API_KEY') {
                    onKeySet(value);
                    localStorage.setItem('gemini_key', value);
                    fetchModels(value);
                }
                if (keyId === 'HF_TOKEN' && onHfTokenSet) {
                    onHfTokenSet();
                }
            } else {
                setMessage({ type: 'error', text: 'Failed to save key to server.' });
            }
        } catch (error) {
            setMessage({ type: 'error', text: 'Network error while saving.' });
        } finally {
            setIsSaving(false);
            setTimeout(() => setMessage({ type: '', text: '' }), 3000);
        }
    };

    const handleCookieUpload = async () => {
        if (!cookiesFile) return;
        setIsSavingCookies(true);
        setMessage({ type: '', text: '' });
        try {
            const formData = new FormData();
            formData.append('cookies_file', cookiesFile);
            const response = await fetch(`${config.API_BASE_URL}/api/config/cookies`, {
                method: 'POST',
                body: formData,
            });
            if (response.ok) {
                setMessage({ type: 'success', text: 'Cookies saved successfully!' });
                setCookiesFile(null);
                await checkCookies();
            } else {
                setMessage({ type: 'error', text: 'Failed to upload cookies.' });
            }
        } catch (error) {
            setMessage({ type: 'error', text: 'Network error while saving cookies.' });
        } finally {
            setIsSavingCookies(false);
            setTimeout(() => setMessage({ type: '', text: '' }), 3000);
        }
    };

    const handleCookieDelete = async () => {
        setIsSavingCookies(true);
        try {
            const response = await fetch(`${config.API_BASE_URL}/api/config/cookies`, {
                method: 'DELETE',
            });
            if (response.ok) {
                setMessage({ type: 'success', text: 'Cookies removed.' });
                await checkCookies();
            } else {
                setMessage({ type: 'error', text: 'Failed to remove cookies.' });
            }
        } catch (error) {
            setMessage({ type: 'error', text: 'Network error while removing cookies.' });
        } finally {
            setIsSavingCookies(false);
            setTimeout(() => setMessage({ type: '', text: '' }), 3000);
        }
    };

    const handleModelChange = async (e) => {
        const newModel = e.target.value;
        setSelectedModel(newModel);
        localStorage.setItem('clippyme_model', newModel);

        try {
            await fetch(`${config.API_BASE_URL}/api/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ keys: { 'GEMINI_MODEL': newModel } })
            });
        } catch (error) {
            console.error("Failed to update model on server:", error);
        }
    };

    const toggleVisibility = (id) => {
        setVisibleKeys(prev => ({ ...prev, [id]: !prev[id] }));
    };

    if (isLoading) {
        return (
            <div className="flex items-center justify-center py-8">
                <Loader2 className="animate-spin text-zinc-500" size={20} />
                <span className="ml-2 text-sm text-zinc-500">Loading configuration...</span>
            </div>
        );
    }

    return (
        <div className="space-y-5 animate-[fadeIn_0.5s_ease-out]">
            {/* Status message */}
            {message.text && (
                <div className={`flex items-center gap-2 text-sm px-3 py-2 rounded-lg ${
                    message.type === 'success' ? 'bg-success/10 text-success border border-success/20' : 'bg-error/10 text-error border border-error/20'
                }`}>
                    {message.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
                    {message.text}
                </div>
            )}

            {/* API Key fields */}
            {KEY_TYPES.map((type) => {
                const isConfigured = !!serverConfig[type.id];
                return (
                    <div key={type.id} className="space-y-2">
                        <div className="flex items-center justify-between">
                            <label className="text-sm font-medium text-zinc-300 flex items-center gap-2">
                                {type.label}
                                {!type.required && (
                                    <span className="text-[10px] text-zinc-600 bg-white/[0.03] border border-white/[0.06] px-1.5 py-0.5 rounded">
                                        Optional
                                    </span>
                                )}
                                {isConfigured && (
                                    <span className="flex items-center gap-1 text-[10px] text-success bg-success/10 border border-success/20 px-1.5 py-0.5 rounded">
                                        <Check size={9} /> {serverConfig[type.id]}
                                    </span>
                                )}
                            </label>
                            <a
                                href={type.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[11px] text-accent-pink hover:text-accent-pink/80 transition-colors"
                            >
                                Get token
                            </a>
                        </div>
                        {type.hint && (
                            <p className="text-[11px] text-zinc-600">{type.hint}</p>
                        )}
                        <div className="flex gap-2">
                            <div className="relative flex-1">
                                <input
                                    type={visibleKeys[type.id] ? "text" : "password"}
                                    value={keys[type.id] || ''}
                                    onChange={(e) => setKeys({ ...keys, [type.id]: e.target.value })}
                                    placeholder={type.placeholder}
                                    className="w-full bg-[#0f0f13] border border-white/10 rounded-lg px-4 py-3 text-white text-sm font-mono focus:outline-none focus:border-accent-pink/50 pr-10 placeholder:text-zinc-700"
                                />
                                <button
                                    onClick={() => toggleVisibility(type.id)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
                                >
                                    {visibleKeys[type.id] ? <EyeOff size={15} /> : <Eye size={15} />}
                                </button>
                            </div>
                            <button
                                onClick={() => handleSave(type.id)}
                                disabled={!keys[type.id] || isSaving}
                                className={`px-4 rounded-lg font-medium text-sm transition-all flex items-center gap-1.5 ${
                                    !keys[type.id] || isSaving
                                        ? 'bg-white/[0.03] text-zinc-600 cursor-not-allowed border border-white/[0.06]'
                                        : 'text-white border border-transparent'
                                }`}
                                style={keys[type.id] && !isSaving ? { background: 'linear-gradient(135deg, #e6428d, #9850c3)' } : undefined}
                            >
                                {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                                {isConfigured ? 'Update' : 'Save'}
                            </button>
                        </div>
                    </div>
                );
            })}

            {/* Model selection */}
            <div className="space-y-2 pt-2">
                <label className="text-sm font-medium text-zinc-300">Gemini Model</label>
                <p className="text-[11px] text-zinc-600">Choose which AI model to use for analysis</p>
                <div className="relative">
                    <select
                        value={selectedModel}
                        onChange={handleModelChange}
                        disabled={isLoadingModels}
                        className="w-full bg-[#0f0f13] border border-white/10 rounded-lg px-4 py-3 text-sm text-white focus:outline-none focus:border-accent-pink/50 appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-wait"
                    >
                        {models.length > 0 ? (
                            models.map(m => (
                                <option key={m.name} value={m.name} className="bg-[#0f0f13]">
                                    {m.display_name} ({m.name})
                                </option>
                            ))
                        ) : (
                            <>
                                <option value="gemini-2.5-flash">Gemini 2.5 Flash (Recommended)</option>
                                <option value="gemini-2.5-pro">Gemini 2.5 Pro (Advanced)</option>
                                <option value="gemini-2.5-flash-lite">Gemini 2.5 Flash-Lite (Fastest)</option>
                            </>
                        )}
                    </select>
                    {isLoadingModels ? (
                        <div className="absolute right-3 top-1/2 -translate-y-1/2">
                            <Loader2 size={14} className="animate-spin text-zinc-500" />
                        </div>
                    ) : (
                        <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-zinc-500">
                            <ChevronDown size={14} />
                        </div>
                    )}
                </div>
                {models.length === 0 && !isLoadingModels && (
                    <p className="text-[10px] text-zinc-600 flex items-center gap-1">
                        <AlertCircle size={10} />
                        Save a valid API key to fetch the full list of available models.
                    </p>
                )}
            </div>

            {/* Cookie upload section */}
            <div className="space-y-2 pt-2">
                <div className="flex items-center justify-between">
                    <label className="text-sm font-medium text-zinc-300 flex items-center gap-2">
                        YouTube / Twitch Cookies
                        <span className="text-[10px] text-zinc-600 bg-white/[0.03] border border-white/[0.06] px-1.5 py-0.5 rounded">
                            Optional
                        </span>
                        {cookiesConfigured && (
                            <span className="flex items-center gap-1 text-[10px] text-success bg-success/10 border border-success/20 px-1.5 py-0.5 rounded">
                                <div className="w-1.5 h-1.5 rounded-full bg-success" /> Configured
                            </span>
                        )}
                    </label>
                    <a
                        href="https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[11px] text-accent-pink hover:text-accent-pink/80 transition-colors"
                    >
                        Get extension
                    </a>
                </div>
                <p className="text-[11px] text-zinc-600">Upload a Netscape .txt cookies file to bypass bot detection on YouTube or Twitch.</p>
                <div className="flex gap-2">
                    <div className="relative flex-1 group/cookie">
                        <input
                            type="file"
                            accept=".txt"
                            onChange={(e) => setCookiesFile(e.target.files?.[0] || null)}
                            className="absolute inset-0 opacity-0 cursor-pointer z-10"
                        />
                        <div className="w-full bg-[#0f0f13] border border-dashed border-white/10 rounded-lg py-3 px-4 text-xs text-zinc-500 group-hover/cookie:border-accent-pink/30 transition-all flex items-center justify-between">
                            <span>{cookiesFile ? cookiesFile.name : 'Drop .txt cookies file here'}</span>
                            <Upload size={13} className="text-zinc-600 group-hover/cookie:text-zinc-400 transition-colors" />
                        </div>
                    </div>
                    <button
                        onClick={handleCookieUpload}
                        disabled={!cookiesFile || isSavingCookies}
                        className={`px-4 rounded-lg font-medium text-sm transition-all flex items-center gap-1.5 ${
                            !cookiesFile || isSavingCookies
                                ? 'bg-white/[0.03] text-zinc-600 cursor-not-allowed border border-white/[0.06]'
                                : 'text-white border border-transparent'
                        }`}
                        style={cookiesFile && !isSavingCookies ? { background: 'linear-gradient(135deg, #e6428d, #9850c3)' } : undefined}
                    >
                        {isSavingCookies ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                        Save
                    </button>
                    {cookiesConfigured && (
                        <button
                            onClick={handleCookieDelete}
                            disabled={isSavingCookies}
                            className="px-3 rounded-lg font-medium text-sm transition-all flex items-center gap-1.5 bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/20 disabled:opacity-50"
                            title="Remove cookies"
                        >
                            <Trash2 size={14} />
                        </button>
                    )}
                </div>
            </div>

            <p className="text-[11px] text-zinc-600 pt-2">
                Settings are stored in <code className="text-zinc-500">data/config.json</code> on the server. Changes take effect immediately.
            </p>
        </div>
    );
}
