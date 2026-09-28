// Configuration for API endpoints
// If VITE_API_URL is set (e.g. in production), use it.
// Otherwise, default to empty string which means relative paths (proxied in dev).

// Guarded so the module also loads under plain Node (npm test / node --test),
// where import.meta.env does not exist. Vite statically defines import.meta.env
// in dev/build, so browser behaviour is unchanged.
export const API_BASE_URL = (import.meta.env && import.meta.env.VITE_API_URL) || '';

export const config = {
    API_BASE_URL
};

// Origins we trust to serve clip/video/poster assets: our own page origin and,
// if configured, the explicit API base. Anything else (a server response that
// somehow carries an external absolute URL) must not be fetched as-is.
const _trustedOrigins = () => {
    const origins = new Set();
    if (typeof window !== 'undefined' && window.location) {
        origins.add(window.location.origin);
        if (API_BASE_URL) {
            try { origins.add(new URL(API_BASE_URL, window.location.origin).origin); } catch { /* ignore */ }
        }
    }
    return origins;
};

export const getApiUrl = (path) => {
    if (typeof path !== 'string' || !path) return '';
    // Absolute http(s) URL: only pass through if it targets a trusted origin.
    // An untrusted external URL is reduced to its path and re-resolved against
    // our own base, so a crafted server `video_url` can't point the browser at
    // an attacker host or a cloud metadata endpoint (SSRF/defense-in-depth).
    if (/^https?:\/\//i.test(path)) {
        try {
            const u = new URL(path);
            if (_trustedOrigins().has(u.origin)) return path;
            path = u.pathname + u.search;
        } catch {
            return '';
        }
    }
    // Any other scheme (javascript:, data:, …) falls through here and gets a
    // leading slash, turning it into an inert relative path.
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${API_BASE_URL}${normalizedPath}`;
};
