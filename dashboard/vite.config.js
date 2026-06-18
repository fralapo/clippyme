import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [tailwindcss(), react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
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
