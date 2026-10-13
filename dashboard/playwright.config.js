import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 45000,
  expect: { timeout: 10000 },
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: 'http://127.0.0.1:5175',
    ...devices['Desktop Chrome'],
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5175',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
