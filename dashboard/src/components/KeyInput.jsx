import React, { useState, useEffect } from 'react';
import { Key, Eye, EyeOff, Check, Save, ShieldCheck, Loader2, AlertCircle } from 'lucide-react';
import { config } from '../config';

const KEY_TYPES = [
    { id: 'GEMINI_API_KEY', label: 'Gemini API Key', icon: <Key size={18} />, link: 'https://aistudio.google.com/app/apikey', placeholder: 'AIzaSy...' }
];

export default function KeyInput({ onKeySet, savedKey }) {
    const [keys, setKeys] = useState({});
    const [serverConfig, setServerConfig] = useState({});
    const [visibleKeys, setVisibleKeys] = useState({});
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [message, setMessage] = useState({ type: '', text: '' });

    // Fetch current config from server on mount
    useEffect(() => {
        fetchConfig();
    }, []);

    const fetchConfig = async () => {
        try {
            const response = await fetch(`${config.API_BASE_URL}/api/config`);
            if (response.ok) {
                const data = await response.json();
                setServerConfig(data);
            }
        } catch (error) {
            console.error("Failed to fetch config:", error);
        } finally {
            setIsLoading(false);
        }
    };

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
                
                // If it's the Gemini key, notify parent for immediate use
                if (keyId === 'GEMINI_API_KEY') {
                    onKeySet(value);
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

            <div className="space-y-6">
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
            </div>
            
            <div className="mt-6 pt-6 border-t border-white/5">
                <p className="text-[11px] text-zinc-500 leading-relaxed">
                    Keys are stored securely in <code>data/config.json</code> on the server. 
                    Changes take effect immediately for all new processing jobs.
                </p>
            </div>
        </div>
    );
}
