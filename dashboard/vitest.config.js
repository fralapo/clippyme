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
  },
})
