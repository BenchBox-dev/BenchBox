import { defineConfig } from "vitest/config";
import preact from "@preact/preset-vite";
import { resolve } from "path";

// NOTE: Pre-rendering (e.g. with vite-plugin-ssg or vite-plugin-prerender) can
// be added later to improve SEO and cold-load performance. For Phase 1 the app
// is a client-rendered SPA served under /results/.

export default defineConfig({
  plugins: [preact()],

  // The explorer is hosted at benchbox.dev/results/
  base: "/results/",

  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },

  build: {
    outDir: "dist",
    // Increase chunk size warning limit - DuckDB-WASM is intentionally large
    chunkSizeWarningLimit: 5000,
    rollupOptions: {
      output: {
        manualChunks: {
          // Isolate DuckDB-WASM into its own chunk so it loads lazily
          duckdb: ["@duckdb/duckdb-wasm"],
        },
      },
    },
  },

  // Keep duckdb-wasm assets bundled by Vite rather than externalizing them.
  optimizeDeps: {
    exclude: ["@duckdb/duckdb-wasm"],
  },

  server: {
    // During dev, /results/ base path is served from root
    headers: {
      "Cross-Origin-Embedder-Policy": "require-corp",
      "Cross-Origin-Opener-Policy": "same-origin",
    },
  },

  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // Playwright browser-functional tests under e2e/ use a different
    // runner; excluding them keeps Vitest from picking them up.
    exclude: ["node_modules/**", "dist/**", "e2e/**", "test-fixtures/**"],
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
});
