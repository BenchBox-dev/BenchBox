import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT ?? 4319);
const HOST = process.env.E2E_HOST ?? "127.0.0.1";
const BASE_URL = `http://${HOST}:${PORT}`;
const CAPTURE_FIRST_FAILURE = Boolean(process.env.E2E_CAPTURE_FIRST_FAILURE);

export default defineConfig({
  testDir: "./e2e",
  testIgnore: process.env.E2E_EXCLUDE_FAILURES ? /failures\// : undefined,
  outputDir: "./test-results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [["github"], ["html", { outputFolder: "playwright-report", open: "never" }]]
    : [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  timeout: 90_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    trace: CAPTURE_FIRST_FAILURE ? "retain-on-failure" : "on-first-retry",
    screenshot: "only-on-failure",
    video: CAPTURE_FIRST_FAILURE ? "retain-on-failure" : "on-first-retry",
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
    },
  ],

  webServer: {
    command: `node scripts/serve-browser-tests.mjs --port ${PORT} --host ${HOST}`,
    url: `${BASE_URL}/results/`,
    reuseExistingServer: !process.env.CI && !process.env.E2E_FIXTURE_DIR,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
