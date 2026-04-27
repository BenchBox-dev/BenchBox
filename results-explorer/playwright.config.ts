import { defineConfig, devices } from "@playwright/test";

/**
 * Browser-functional test harness for the results explorer.
 *
 * Architecture decisions (accepted 2026-04-18) live in
 * `docs/development/browser-test-architecture.md`. In particular:
 *
 * - Tests run against the built `dist/` output, not `vite dev`, so
 *   chunking, the `/results/` base path, and the DuckDB-WASM worker
 *   behavior are all validated as production would see them.
 * - The Playwright `webServer` below serves `dist/` while routing
 *   `/results/data/` to `test-fixtures/.generated/data/`. The curated
 *   corpus under `public/data/` is never mutated.
 * - Chromium runs the full suite and is the blocking gate.
 *   Firefox and WebKit run `@smoke`-tagged coverage only until we have
 *   flake data to graduate them. Promotion criteria are captured in w7
 *   of the implementing TODO and in the architecture note.
 * - There is no production-code seam for failure injection. All error
 *   paths are exercised through `page.route()`, `context.setOffline()`,
 *   permission grants, and download events.
 */

const PORT = Number(process.env.E2E_PORT ?? 4319);
const HOST = process.env.E2E_HOST ?? "127.0.0.1";
const BASE_URL = `http://${HOST}:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [["github"], ["html", { outputFolder: "playwright-report", open: "never" }]]
    : [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  timeout: 60_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      grep: /@smoke/,
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      grep: /@smoke/,
      use: { ...devices["Desktop Safari"] },
      // WebKit serializes DuckDB-WASM init: concurrent worker startup stalls
      // past the default 10 s expect timeout. The test:e2e:webkit npm script
      // enforces --workers=1 to eliminate the race. Remove once graduated to
      // blocking gate (see stabilize-webkit-browser-smoke-flake-under-parallel-workers TODO w3).
    },
  ],

  webServer: {
    command: `node scripts/serve-browser-tests.mjs --port ${PORT} --host ${HOST}`,
    url: `${BASE_URL}/results/`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
