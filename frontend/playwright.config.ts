/**
 * frontend/playwright.config.ts
 *
 * Playwright e2e config. Spins up `vite` (npm run dev) on its default port
 * and runs the browser tests under tests/e2e/. Backend is mocked at the
 * `page.route()` level so Playwright never depends on a live FastAPI/LLM
 * stack — this is intentionally a *frontend regression net*, not full e2e.
 */

import { defineConfig, devices } from '@playwright/test'

const PORT = 5183

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
    actionTimeout: 5_000,
    navigationTimeout: 10_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
