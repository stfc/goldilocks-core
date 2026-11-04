import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    target: "es2022",
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/capabilities": "http://127.0.0.1:8000",
      "/explain": "http://127.0.0.1:8000",
      "/magnetic-orderings": "http://127.0.0.1:8000",
      "/run": "http://127.0.0.1:8000",
      "/inspect": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/ready": "http://127.0.0.1:8000",
      "/openapi.json": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/{unit,integration}/**/*.test.{ts,tsx}"],
    setupFiles: "./tests/support/setup.ts",
    css: true,
    // The App tests wait out the real /explain (400 ms) and preview (150 ms)
    // debounces and pause a second to show nothing is sent again: about 3 s
    // of fixed wall-clock time. Their waits give up within 5 s, so a failing
    // test reports what it was waiting for before the test itself times out.
    testTimeout: 15_000,
  },
});
