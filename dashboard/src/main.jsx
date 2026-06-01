import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';

// The flat-editorial redesign (Claude Design handoff, wired to the real
// backend) is now the default UI. The previous app is still reachable at
// ?ui=legacy as a safety net.
const useLegacy = typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).get('ui') === 'legacy';

const App = React.lazy(() => (useLegacy ? import('./App') : import('./redesign/RedesignApp')));

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <React.Suspense fallback={
            <div className="h-screen w-screen bg-background flex items-center justify-center">
                <div className="w-12 h-12 rounded-full border-2 border-zinc-800 border-t-[oklch(74%_0.175_62)] animate-spin" />
            </div>
        }>
            <App />
        </React.Suspense>
    </React.StrictMode>,
);
