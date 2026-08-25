import { tmpdir } from "node:os";
import { join } from "node:path";

import { defineConfig } from "@playwright/test";

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

export default defineConfig({
  testDir: "./e2e",
  outputDir:
    process.env.PLAYWRIGHT_OUTPUT_DIR ??
    join(tmpdir(), "goldilocks-workbench-playwright"),
  fullyParallel: false,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: {
    baseURL: process.env.WORKBENCH_BASE_URL ?? "http://127.0.0.1:8000",
    ...(executablePath === undefined
      ? {}
      : { launchOptions: { executablePath } }),
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
