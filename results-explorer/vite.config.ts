import { defineConfig } from "vitest/config";
import preact from "@preact/preset-vite";
import { resolve } from "path";

export default defineConfig({
  plugins: [preact()],

  base: "/results/",

  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },

  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 5000,
    rollupOptions: {
      output: {
        manualChunks: {
          duckdb: ["@duckdb/duckdb-wasm"],
        },
      },
    },
  },

  optimizeDeps: {
    exclude: ["@duckdb/duckdb-wasm"],
  },

  server: {
    fs: {
      allow: ["..", resolve(__dirname, "..")],
    },
    headers: {
      "Cross-Origin-Embedder-Policy": "require-corp",
      "Cross-Origin-Opener-Policy": "same-origin",
    },
  },

  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["node_modules/**", "dist/**", "e2e/**", "test-fixtures/**"],
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
});
