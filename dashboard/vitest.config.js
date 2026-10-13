// Vitest config — kept separate from vite.config.js so the dev-server plugins
// (tailwind, CSP injection) never load in the test runner. jsdom is the global
// environment: it serves both the pure-function suites (which only need a
// `window`) and the component tests (@testing-library/react).
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{js,jsx}'],
    setupFiles: ['./src/test/setup.js'],
    // Baseline lower than the last passing CI metrics; ratchet upward as
    // client/Create/Settings/History integration branches gain coverage.
    coverage: {
      provider: 'v8',
      thresholds: { statements: 65, branches: 60, functions: 60, lines: 70 },
    },
  },
})
