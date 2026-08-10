import { defineConfig, devices } from '@playwright/test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Critical browser workflows in e2e/ run against a real FastAPI server that
// serves the built Workbench (web/dist) under the same origin. The server uses
// synthetic pseudo metadata and the tests set an explicit k-grid, so no model
// download, network access, or private data is involved.
const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '..');

export default defineConfig({
  testDir: './e2e',
  // The Workbench e2e runs against one real FastAPI server with a bounded
  // compute gate. Running tests in parallel can collide on computation slots
  // and surface retryable server_busy 503s that the specs do not retry, so the
  // suite is serial: reliability over wall-clock here.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:8000',
    trace: 'on-first-retry',
  },
  webServer: {
    command:
      'uv run --extra http uvicorn goldilocks_core.server.main:app --host 127.0.0.1 --port 8000',
    cwd: repoRoot,
    url: 'http://localhost:8000/health',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      GOLDILOCKS_WEB_DIST: resolve(repoRoot, 'web', 'dist'),
      GOLDILOCKS_PSEUDO_METADATA: resolve(
        repoRoot,
        'web',
        'e2e',
        'fixtures',
        'pseudo_metadata.json',
      ),
    },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
