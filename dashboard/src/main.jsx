import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';

const App = React.lazy(() => import('./App'));

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
