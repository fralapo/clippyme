import React, { useEffect, useState, useRef } from 'react';
import { CheckCircle, Cpu, Zap, Activity } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';

const ProcessingAnimation = ({ media, isComplete, syncedTime, isSyncedPlaying, syncTrigger }) => {
  const [videoSrc, setVideoSrc] = useState(null);
  const [isYouTube, setIsYouTube] = useState(false);
  const [dots, setDots] = useState('');
  const videoRef = useRef(null);
  const iframeRef = useRef(null);

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

  // Animated dots for status text
  useEffect(() => {
    if (isComplete) return;
    const interval = setInterval(() => {
      setDots(prev => prev.length >= 3 ? '' : prev + '.');
    }, 500);
    return () => clearInterval(interval);
  }, [isComplete]);

  // Handle Sync Playback for Local Video
  useEffect(() => {
    if (!isYouTube && videoRef.current) {
      if (isSyncedPlaying) {
        videoRef.current.currentTime = syncedTime;
        videoRef.current.play().catch(e => console.log("Auto-play prevented", e));
        videoRef.current.loop = false;
        videoRef.current.muted = true;
      } else {
        videoRef.current.pause();
        if (isComplete) {
          videoRef.current.loop = true;
          videoRef.current.play().catch(e => console.log("Ambient play prevented", e));
        }
      }
    }
  }, [syncedTime, isSyncedPlaying, isYouTube, isComplete, syncTrigger]);

  // Handle Sync Playback for YouTube
  useEffect(() => {
    if (isYouTube && iframeRef.current && videoSrc) {
      const iframeWindow = iframeRef.current.contentWindow;
      // Target the YouTube embed origin explicitly — never '*' — so the
      // IPC command can't be delivered to a different document if the iframe
      // navigates away.
      const YT_ORIGIN = 'https://www.youtube.com';
      if (isSyncedPlaying) {
        iframeWindow.postMessage(JSON.stringify({ event: 'command', func: 'seekTo', args: [syncedTime, true] }), YT_ORIGIN);
        iframeWindow.postMessage(JSON.stringify({ event: 'command', func: 'playVideo', args: [] }), YT_ORIGIN);
      } else {
        iframeWindow.postMessage(JSON.stringify({ event: 'command', func: 'pauseVideo', args: [] }), YT_ORIGIN);
      }
    }
  }, [syncedTime, isSyncedPlaying, isYouTube, videoSrc, syncTrigger]);

  const getYouTubeId = (url) => {
    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
    const match = url.match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
  };

  const modelName = (localStorage.getItem('clippyme_model') || 'gemini-2.5-flash');

  return (
    <div className="relative w-full mb-8 animate-[fadeIn_0.5s_ease-out]">
      {/* Video container with pulsing border */}
      <div
        className={`relative aspect-video rounded-[3px] overflow-hidden bg-[oklch(9%_0.006_260)] transition-all duration-500 ${
          isSyncedPlaying
            ? 'ring-2 ring-primary outline outline-2 outline-background'
            : !isComplete
              ? 'shadow-[0_0_0_2px_rgba(152,80,195,0.3)] pulse-ring-active'
              : ''
        }`}
      >
        {/* Video layer */}
        <div className={`absolute inset-0 transition-all duration-700 ${
          isSyncedPlaying ? 'opacity-100' :
          isComplete ? 'opacity-30 grayscale brightness-50' :
          'opacity-50'
        }`}>
          {isYouTube && videoSrc ? (
            <iframe
              ref={iframeRef}
              className={`w-full h-full ${isSyncedPlaying ? '' : 'pointer-events-none scale-105'}`}
              src={`https://www.youtube.com/embed/${videoSrc}?autoplay=1&mute=1&controls=0&loop=1&playlist=${videoSrc}&modestbranding=1&showinfo=0&rel=0&enablejsapi=1`}
              title="Processing Video"
              frameBorder="0"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            />
          ) : videoSrc ? (
            <video
              ref={videoRef}
              src={videoSrc}
              className="w-full h-full object-cover"
              autoPlay
              muted
              loop
              playsInline
            />
          ) : (
            <Skeleton className="w-full h-full" />
          )}
        </div>

        {/* Processing overlay - scan line + center indicator */}
        {!isSyncedPlaying && !isComplete && (
          <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
            {/* Scan line */}
            <div
              className="scan-line absolute left-0 right-0 h-px opacity-60 pointer-events-none"
              style={{ background: 'linear-gradient(90deg, transparent, rgba(152,80,195,0.8), rgba(230,66,141,0.6), transparent)' }}
            />
            {/* Center pulse dot */}
            <div className="relative">
              <div className="w-14 h-14 rounded-full border border-white/10 animate-ping opacity-15" />
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-2.5 h-2.5 rounded-full bg-accent-pink animate-pulse" />
              </div>
            </div>
          </div>
        )}

        {/* Status badge - top left */}
        {!isSyncedPlaying && (
          <div className={`absolute top-3 left-3 z-20 flex items-center gap-2 px-3 py-1.5 rounded-[3px] text-xs font-medium backdrop-blur-md transition-all duration-500 ${
            isComplete
              ? 'bg-success/10 border border-success/20 text-success'
              : 'bg-black/50 border border-white/10 text-white/70'
          }`}>
            {isComplete ? (
              <>
                <CheckCircle size={13} />
                <span>Ready</span>
              </>
            ) : (
              <>
                <div className="w-1.5 h-1.5 rounded-full bg-accent-pink animate-pulse" />
                <span>Processing{dots}</span>
              </>
            )}
          </div>
        )}

        {/* Synced playing indicator */}
        {isSyncedPlaying && (
          <div className="absolute top-3 right-3 z-20 flex items-center gap-1.5 px-3 py-1.5 bg-red-500/90 backdrop-blur-sm text-white rounded-[3px] text-xs font-medium animate-pulse">
            <Activity size={12} />
            Live Sync
          </div>
        )}
      </div>

      {/* HUD badges below the video */}
      {!isSyncedPlaying && (
        <div className="flex items-center gap-2 mt-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-[oklch(9%_0.006_260)] border border-white/[0.06] rounded-[3px] text-[11px] text-zinc-500">
            <Cpu size={11} className="text-zinc-400" />
            {modelName}
          </div>
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-[oklch(9%_0.006_260)] border border-white/[0.06] rounded-[3px] text-[11px] text-zinc-500">
            <Zap size={11} className="text-warning" />
            Auto Hardware
          </div>
        </div>
      )}

    </div>
  );
};

export default ProcessingAnimation;
