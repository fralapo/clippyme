import React, { useState } from 'react';
import { X, Type, Loader2 } from 'lucide-react';

export default function SubtitleModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl }) {
    const [position, setPosition] = useState('bottom'); // bottom, middle, top
    const [fontSize, setFontSize] = useState(24);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
            <div className="bg-[#121214] border border-white/10 p-6 rounded-2xl w-full max-w-4xl shadow-2xl relative flex flex-col md:flex-row gap-6 max-h-[90vh]">
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 text-zinc-500 hover:text-white z-10"
                >
                    <X size={20} />
                </button>

                {/* Left: Preview */}
                <div className="flex-1 flex flex-col items-center justify-center bg-black rounded-lg border border-white/5 overflow-hidden relative aspect-[9/16] max-h-[600px]">
                     <video src={videoUrl} className="w-full h-full object-contain opacity-50" muted playsInline />
                     
                     {/* Subtitle Overlay Preview */}
                     <div className={`absolute w-full px-8 text-center transition-all duration-300 pointer-events-none flex flex-col items-center justify-center
                        ${position === 'top' ? 'top-20' : ''}
                        ${position === 'middle' ? 'top-0 bottom-0' : ''}
                        ${position === 'bottom' ? 'bottom-20' : ''}
                     `}>
                        <span 
                            className="bg-black/50 text-white font-bold px-2 py-1 rounded shadow-lg backdrop-blur-sm border border-white/10 text-center"
                            style={{ 
                                fontSize: '14px', 
                                maxWidth: '80%' 
                            }} 
                        >
                            This is how your subtitles<br/>will appear on the video
                        </span>
                     </div>
                </div>

                {/* Right: Controls */}
                <div className="w-full md:w-80 flex flex-col">
                    <h3 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                        <Type className="text-primary" /> Auto Subtitles
                    </h3>

                    <div className="space-y-6 flex-1">
                        {/* Position Selector */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">Position</label>
                            <div className="grid grid-cols-1 gap-2">
                                <button 
                                    onClick={() => setPosition('top')}
                                    className={`p-3 rounded-xl border flex items-center gap-3 transition-all ${position === 'top' ? 'bg-primary/20 border-primary text-white' : 'bg-white/5 border-white/5 text-zinc-400 hover:bg-white/10'}`}
                                >
                                    <div className="w-8 h-8 rounded-lg bg-black/50 border border-white/10 flex items-start justify-center pt-1">
                                        <div className="w-4 h-0.5 bg-white/50 rounded-full"></div>
                                    </div>
                                    <span className="font-medium">Top</span>
                                </button>
                                
                                <button 
                                    onClick={() => setPosition('middle')}
                                    className={`p-3 rounded-xl border flex items-center gap-3 transition-all ${position === 'middle' ? 'bg-primary/20 border-primary text-white' : 'bg-white/5 border-white/5 text-zinc-400 hover:bg-white/10'}`}
                                >
                                    <div className="w-8 h-8 rounded-lg bg-black/50 border border-white/10 flex items-center justify-center">
                                        <div className="w-4 h-0.5 bg-white/50 rounded-full"></div>
                                    </div>
                                    <span className="font-medium">Center</span>
                                </button>
                                
                                <button 
                                    onClick={() => setPosition('bottom')}
                                    className={`p-3 rounded-xl border flex items-center gap-3 transition-all ${position === 'bottom' ? 'bg-primary/20 border-primary text-white' : 'bg-white/5 border-white/5 text-zinc-400 hover:bg-white/10'}`}
                                >
                                    <div className="w-8 h-8 rounded-lg bg-black/50 border border-white/10 flex items-end justify-center pb-1">
                                        <div className="w-4 h-0.5 bg-white/50 rounded-full"></div>
                                    </div>
                                    <span className="font-medium">Bottom</span>
                                </button>
                            </div>
                        </div>
                    </div>

                    <button
                        onClick={() => onGenerate({ position, fontSize })}
                        disabled={isProcessing}
                        className="w-full py-4 mt-6 bg-gradient-to-r from-yellow-500 to-orange-500 hover:from-yellow-400 hover:to-orange-400 text-black font-bold rounded-xl shadow-lg shadow-orange-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2"
                    >
                        {isProcessing ? <Loader2 size={20} className="animate-spin" /> : <Type size={20} />}
                        {isProcessing ? 'Generating...' : 'Generate Subtitles'}
                    </button>
                    
                    <p className="text-[10px] text-zinc-500 text-center mt-3">
                        Uses AI word-level timestamps to sync perfectly.
                    </p>
                </div>
            </div>
        </div>
    );
}

