import { defineConfig, devices } from '@playwright/test';

// Critical-browser-workflow tests live in e2e/ and run against a real FastAPI
// server in later slices. This config keeps the runner wired for the full
// Workbench test stack.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:8000',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
