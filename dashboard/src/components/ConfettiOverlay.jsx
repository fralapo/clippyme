import React from 'react';

const COLORS = ['#3b82f6', '#ec4899', '#a855f7', '#10b981', '#f59e0b'];
const PARTICLES = 40;

/**
 * Full-screen confetti celebration overlay + scoped keyframe styles.
 *
 * @param {{ visible: boolean }} props
 */
export default function ConfettiOverlay({ visible }) {
  if (!visible) return null;
  return (
    <>
      <div className="fixed inset-0 z-[200] pointer-events-none overflow-hidden">
        {Array.from({ length: PARTICLES }).map((_, i) => (
          <div
            key={i}
            className="absolute w-2 h-2 rounded-full animate-confetti"
            style={{
              left: `${Math.random() * 100}%`,
              top: '-10px',
              backgroundColor: COLORS[i % COLORS.length],
              animationDelay: `${Math.random() * 1}s`,
              animationDuration: `${1.5 + Math.random() * 2}s`,
            }}
          />
        ))}
      </div>
      <style>{`
        @keyframes confetti-fall {
          0% { transform: translateY(0) rotate(0deg); opacity: 1; }
          100% { transform: translateY(100vh) rotate(720deg); opacity: 0; }
        }
        .animate-confetti {
          animation: confetti-fall 2s ease-out forwards;
        }
      `}</style>
    </>
  );
}
