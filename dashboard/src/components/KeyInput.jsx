import React, { useState, useEffect, useCallback } from 'react';
import { Key, Eye, EyeOff, Check, Save, ShieldCheck, Loader2, AlertCircle, Cpu } from 'lucide-react';
import { config } from '../config';

const KEY_TYPES = [
    { id: 'GEMINI_API_KEY', label: 'Gemini API Key', icon: <Key size={18} />, link: 'https://aistudio.google.com/app/apikey', placeholder: 'AIzaSy...' }
];

export default function KeyInput({ onKeySet }) {
    const [keys, setKeys] = useState({});
    const [serverConfig, setServerConfig] = useState({});
    const [visibleKeys, setVisibleKeys] = useState({});
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [message, setMessage] = useState({ type: '', text: '' });
    
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

    const fetchConfig = useCallback(async () => {
        try {
            const response = await fetch(`${config.API_BASE_URL}/api/config`);
            if (response.ok) {
                const data = await response.json();
                setServerConfig(data);
                if (data.GEMINI_MODEL) {
                    setSelectedModel(data.GEMINI_MODEL);
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

    // Fetch current config from server on mount
    useEffect(() => {
        fetchConfig();
    }, [fetchConfig]);

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
                await fetchConfig(); // Refresh masked keys
                setKeys({ ...keys, [keyId]: '' }); // Clear input
                
                if (keyId === 'GEMINI_API_KEY') {
                    onKeySet(value);
                    localStorage.setItem('gemini_key', value);
                    fetchModels(value); // Refresh models with new key
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

    const handleModelChange = async (e) => {
        const newModel = e.target.value;
        setSelectedModel(newModel);
        
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
            <div className="bg-surface border border-white/5 rounded-2xl p-8 mb-8 flex flex-col items-center justify-center min-h-[200px]">
                <Loader2 className="animate-spin text-primary mb-2" size={32} />
                <p className="text-zinc-500">Loading configuration...</p>
            </div>
        );
    }

    return (
        <div className="bg-surface border border-white/5 rounded-2xl p-6 mb-8 animate-[fadeIn_0.5s_ease-out]">
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-accent/20 rounded-lg text-accent">
                        <ShieldCheck size={20} />
                    </div>
                    <h2 className="text-lg font-semibold">API Configuration</h2>
                </div>
                {message.text && (
                    <div className={`flex items-center gap-2 text-sm px-3 py-1 rounded-full animate-bounce ${
                        message.type === 'success' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                    }`}>
                        {message.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
                        {message.text}
                    </div>
                )}
            </div>

            <div className="space-y-8">
                {/* API Keys */}
                {KEY_TYPES.map((type) => {
                    const isConfigured = !!serverConfig[type.id];
                    return (
                        <div key={type.id} className="group">
                            <div className="flex items-center justify-between mb-2">
                                <label className="text-sm font-medium text-zinc-400 flex items-center gap-2">
                                    {type.icon}
                                    {type.label}
                                    {isConfigured && (
                                        <span className="flex items-center gap-1 text-[10px] bg-green-500/10 text-green-500 px-2 py-0.5 rounded-full border border-green-500/20">
                                            <Check size={10} /> Active: {serverConfig[type.id]}
                                        </span>
                                    )}
                                </label>
                                <a
                                    href={type.link}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-[10px] text-primary hover:underline"
                                >
                                    Get key →
                                </a>
                            </div>

                            <div className="flex gap-3">
                                <div className="relative flex-1">
                                    <input
                                        type={visibleKeys[type.id] ? "text" : "password"}
                                        value={keys[type.id] || ''}
                                        onChange={(e) => setKeys({ ...keys, [type.id]: e.target.value })}
                                        placeholder={type.placeholder}
                                        className="input-field pr-12 font-mono text-sm h-11"
                                    />
                                    <button
                                        onClick={() => toggleVisibility(type.id)}
                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white transition-colors"
                                    >
                                        {visibleKeys[type.id] ? <EyeOff size={16} /> : <Eye size={16} />}
                                    </button>
                                </div>
                                <button
                                    onClick={() => handleSave(type.id)}
                                    disabled={!keys[type.id] || isSaving}
                                    className={`px-5 rounded-xl font-medium transition-all flex items-center gap-2 h-11 ${
                                        !keys[type.id] || isSaving
                                        ? 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
                                        : 'bg-primary hover:bg-blue-600 text-white shadow-lg shadow-primary/20'
                                    }`}
                                >
                                    {isSaving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />}
                                    <span>{isConfigured ? 'Update' : 'Save'}</span>
                                </button>
                            </div>
                        </div>
                    );
                })}

                {/* Model Selection */}
                <div className="pt-6 border-t border-white/5">
                    <div className="flex items-center gap-3 mb-4">
                        <div className="p-2 bg-blue-500/20 rounded-lg text-blue-400">
                            <Cpu size={20} />
                        </div>
                        <div>
                            <h2 className="text-lg font-semibold">Gemini Model</h2>
                            <p className="text-xs text-zinc-500">Choose which AI model to use for analysis</p>
                        </div>
                    </div>

                    <div className="relative">
                        <select
                            value={selectedModel}
                            onChange={handleModelChange}
                            disabled={isLoadingModels}
                            className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-primary/50 appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-wait"
                        >
                            {models.length > 0 ? (
                                models.map(m => (
                                    <option key={m.name} value={m.name}>
                                        {m.display_name} ({m.name})
                                    </option>
                                ))
                            ) : (
                                <>
                                    <option value="gemini-2.5-flash">Gemini 2.5 Flash (Recommended)</option>
                                    <option value="gemini-2.5-pro">Gemini 2.5 Pro (Advanced)</option>
                                    <option value="gemini-2.5-flash-lite">Gemini 2.5 Flash-Lite (Fastest)</option>
                                    <option value="gemini-1.5-flash">Gemini 1.5 Flash (Legacy)</option>
                                    <option value="gemini-1.5-pro">Gemini 1.5 Pro (Legacy)</option>
                                </>
                            )}
                        </select>
                        {isLoadingModels ? (
                            <div className="absolute right-4 top-1/2 -translate-y-1/2">
                                <Loader2 size={16} className="animate-spin text-zinc-500" />
                            </div>
                        ) : (
                            <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-zinc-500">
                                <ChevronDown size={16} />
                            </div>
                        )}
                    </div>
                    {models.length === 0 && !isLoadingModels && (
                        <p className="mt-2 text-[10px] text-zinc-500 flex items-center gap-1">
                            <AlertCircle size={10} /> 
                            Save a valid API key to fetch the full list of available models.
                        </p>
                    )}
                </div>
            </div>
            
            <div className="mt-8 pt-6 border-t border-white/5">
                <p className="text-[11px] text-zinc-500 leading-relaxed">
                    Settings are stored securely in <code>data/config.json</code> on the server. 
                    Changes take effect immediately for all new processing jobs.
                </p>
            </div>
        </div>
    );
}

const ChevronDown = ({ size, className }) => (
    <svg 
        width={size} height={size} viewBox="0 0 24 24" fill="none" 
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" 
        strokeLinejoin="round" className={className}
    >
        <path d="m6 9 6 6 6-6"/>
    </svg>
);
