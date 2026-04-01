import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';

const App = React.lazy(() => import('./App'));
const Landing = React.lazy(() => import('./Landing'));

function isAppRoute() {
    return window.location.hash === '#app' || localStorage.getItem('clippyme_skip_landing') === '1';
}

function Main() {
    const [showApp, setShowApp] = useState(isAppRoute());

    const handleLaunch = () => {
        localStorage.setItem('clippyme_skip_landing', '1');
        window.location.hash = '#app';
        setShowApp(true);
    };

    return (
        <React.Suspense fallback={
            <div className="h-screen w-screen bg-[#09090b] flex items-center justify-center">
                <div className="w-12 h-12 rounded-full border-2 border-zinc-800 border-t-primary animate-spin" />
            </div>
        }>
            {showApp ? <App /> : <Landing onLaunchApp={handleLaunch} />}
        </React.Suspense>
    );
}

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <Main />
    </React.StrictMode>,
);
