import React, { useEffect, useState } from 'react';
import { Scan, Scissors, Activity, Radio } from 'lucide-react';

const ProcessingAnimation = ({ media }) => {
  const [videoSrc, setVideoSrc] = useState(null);
  const [isYouTube, setIsYouTube] = useState(false);

  useEffect(() => {
    if (!media) return;

    if (media.type === 'file') {
      const url = URL.createObjectURL(media.payload);
      setVideoSrc(url);
      return () => URL.revokeObjectURL(url);
    } else if (media.type === 'url') {
      setIsYouTube(true);
      const videoId = getYouTubeId(media.payload);
      setVideoSrc(videoId);
    }
  }, [media]);

  const getYouTubeId = (url) => {
    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
    const match = url.match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
  };

  return (
    <div className="relative w-full aspect-video rounded-xl overflow-hidden bg-black/40 border border-white/10 shadow-2xl mb-8 group animate-[fadeIn_0.5s_ease-out]">
      {/* Video Layer */}
      <div className="absolute inset-0 opacity-40 grayscale group-hover:grayscale-0 transition-all duration-700">
        {isYouTube && videoSrc ? (
            <iframe
            className="w-full h-full pointer-events-none scale-110"
            src={`https://www.youtube.com/embed/${videoSrc}?autoplay=1&mute=1&controls=0&loop=1&playlist=${videoSrc}&modestbranding=1&showinfo=0&rel=0`}
            title="Processing Video"
            frameBorder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          />
        ) : videoSrc ? (
          <video
            src={videoSrc}
            className="w-full h-full object-cover"
            autoPlay
            muted
            loop
            playsInline
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-zinc-900">
             <div className="w-16 h-16 border-4 border-zinc-700 border-t-zinc-500 rounded-full animate-spin"></div>
          </div>
        )}
      </div>

      {/* Grid Overlay */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:40px_40px] z-10 pointer-events-none"></div>

      {/* Scanner Animation Line */}
      <div className="absolute left-0 w-full h-[2px] bg-primary shadow-[0_0_15px_2px_rgba(59,130,246,0.5)] animate-[scan_2.5s_linear_infinite] z-20 pointer-events-none"></div>
      
      {/* Scanner Gradient Band */}
      <div className="absolute left-0 w-full h-[15%] bg-gradient-to-b from-primary/0 via-primary/5 to-primary/0 animate-[scan-overlay_2.5s_linear_infinite] z-10 pointer-events-none"></div>

      {/* HUD Elements */}
      <div className="absolute top-4 left-4 z-30 flex items-center gap-2 px-3 py-1.5 bg-black/60 backdrop-blur-md rounded-lg border border-primary/30 text-primary text-xs font-mono font-bold uppercase animate-pulse">
        <Scan size={14} />
        Scanning Content...
      </div>
      
      <div className="absolute top-4 right-4 z-30 flex items-center gap-2 px-3 py-1.5 bg-black/60 backdrop-blur-md rounded-lg border border-white/10 text-white/50 text-[10px] font-mono">
         AI_MODEL: GEMINI-2.5-PRO
      </div>
      
      {/* Visual Flair: Simulated Crop Marks */}
      <div className="absolute inset-0 pointer-events-none z-20 overflow-hidden">
         {/* Vertical crop lines showing "potential vertical format" */}
         <div className="absolute top-0 bottom-0 left-[35%] w-[1px] bg-yellow-500/20 border-r border-dashed border-yellow-500/40"></div>
         <div className="absolute top-0 bottom-0 right-[35%] w-[1px] bg-yellow-500/20 border-l border-dashed border-yellow-500/40"></div>
         
         {/* Center focus indicator */}
         <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-12 h-12 border border-white/20 rounded-full flex items-center justify-center">
            <div className="w-1 h-1 bg-red-500 rounded-full animate-ping"></div>
         </div>

         <div className="absolute bottom-1/3 left-1/2 -translate-x-1/2 flex flex-col items-center justify-center gap-2 opacity-60">
             <Scissors size={24} className="text-white/20" />
         </div>
      </div>
      
       {/* Bottom Info Bar */}
      <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black/90 to-transparent z-30 flex justify-between items-end border-t border-white/5">
          <div className="font-mono text-[10px] text-primary/80 space-y-1">
             <div className="flex items-center gap-2"><Activity size={10} className="animate-bounce" /> > ANALYSIS_THREAD_01: ACTIVE</div>
             <div className="flex items-center gap-2"><Radio size={10} /> > AUDIO_TRANSCRIPT: PROCESSING</div>
          </div>
          <div className="flex gap-1">
             <div className="w-1 h-3 bg-primary/40 animate-[pulse_0.5s_infinite]"></div>
             <div className="w-1 h-5 bg-primary/60 animate-[pulse_0.7s_infinite]"></div>
             <div className="w-1 h-2 bg-primary/30 animate-[pulse_0.4s_infinite]"></div>
             <div className="w-1 h-4 bg-primary/80 animate-[pulse_0.6s_infinite]"></div>
             <div className="w-1 h-3 bg-primary/50 animate-[pulse_0.5s_infinite]"></div>
          </div>
      </div>
    </div>
  );
};

export default ProcessingAnimation;

