import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Content-Security-Policy injected into the PRODUCTION build only. It blocks
// inline/eval'd scripts and foreign script origins, which is the practical
// mitigation for XSS — the main threat to the Gemini key held in localStorage
// (see src/app/App.jsx). Build-only via `apply: 'build'` because the Vite dev
// server / HMR needs 'unsafe-eval', which we never want shipped. 'unsafe-inline'
// is allowed for styles only (Tailwind v4 / React inline styles), not scripts.
// Remote origins the app genuinely loads: Google Fonts (tokens.css @import →
// stylesheet from fonts.googleapis.com, font files from fonts.gstatic.com)
// and the simpleicons CDN used for the TikTok/Instagram/YouTube marks.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "img-src 'self' data: blob: https://cdn.simpleicons.org",
  "media-src 'self' blob:",
  "font-src 'self' data: https://fonts.gstatic.com",
  "connect-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
].join('; ')

const cspPlugin = () => ({
  name: 'clippyme-inject-csp',
  apply: 'build',
  transformIndexHtml() {
    return [{
      tag: 'meta',
      attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP },
      injectTo: 'head-prepend',
    }]
  },
})

export default defineConfig({
  plugins: [tailwindcss(), react(), cspPlugin()],
  server: {
    host: '0.0.0.0',
    port: 5175,
    strictPort: true,
    hmr: {
      clientPort: 5175,
    },
    // File-watching across the Docker bind mount. On Windows/macOS Docker
    // (WSL2 / gRPC-FUSE) inotify events do NOT propagate from the host into the
    // container, so Vite's default native watcher never sees host edits and HMR
    // silently stops working ("Docker is serving an old version"). Polling is
    // the portable fix. Costs a little CPU; dev-only, never affects `build`.
    watch: {
      usePolling: true,
      interval: 150,
    },
    // Dev-server Host allow-list. Only local names — the unrelated upstream
    // 'openshorts.app' was removed (DNS-rebinding hardening). Add your own
    // hostname here if you proxy the dev server through a custom domain.
    allowedHosts: [
      'localhost',
      '127.0.0.1',
    ],
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
      '/videos': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
      '/thumbnails': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
      '/fonts': {
        target: 'http://backend:8000',
        changeOrigin: true,
      }
    }
  }
})
