// Library-mode build for publishing `goldilocks-workbench` as an
// importable package (see src/index.ts) -- separate from vite.config.ts's
// own `build` (core's standalone app, `dist/`) so `npm run build` and
// `npm run build:lib` never clobber each other's output. Consumed by
// `npm pack`/CI to produce the tarball goldilocks-agent (or any other
// embedder) installs -- see package.json's `main`/`module`/`types`/
// `exports`/`files`, all pointing at this config's `dist-lib` output.
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import dts from "vite-plugin-dts";

export default defineConfig({
  plugins: [
    react(),
    // Mirrors the whole reachable src/ tree's declarations into dist-lib/
    // (not just index.d.ts) -- same shape the original build produced, so
    // TS consumers get real per-module types, not just an untyped `any`
    // surface at the barrel.
    dts({
      tsconfigPath: "./tsconfig.app.json",
      bundleTypes: false,
      entryRoot: "src",
      include: ["src/**/*.ts", "src/**/*.tsx"],
      exclude: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    }),
  ],
  build: {
    outDir: "dist-lib",
    target: "es2022",
    lib: {
      entry: resolve(__dirname, "src/index.ts"),
      formats: ["es"],
      fileName: () => "index.js",
    },
    rollupOptions: {
      // react/react-dom are peerDependencies (package.json) -- the
      // embedder's own copy is what must run, not a second bundled one
      // (that's exactly what caused the "Invalid hook call" crash the
      // first time this was built, before they were moved out of
      // `dependencies`). @mantine/core, lucide-react, 3dmol, zustand stay
      // bundled -- they're regular `dependencies`, embedders shouldn't
      // need to install them separately.
      external: ["react", "react-dom", "react/jsx-runtime"],
      output: {
        assetFileNames: (info) =>
          info.names[0]?.endsWith(".css")
            ? "goldilocks-workbench.css"
            : "assets/[name]-[hash][extname]",
      },
    },
    cssCodeSplit: false,
    emptyOutDir: true,
  },
});
