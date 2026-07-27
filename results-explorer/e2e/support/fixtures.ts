import { expect, type Page } from "@playwright/test";

/**
 * Shared helpers for the browser-functional suite.
 *
 * Kept deliberately small - tests should read like user stories. Put
 * anything here that becomes duplicated across two or more specs.
 */

/**
 * Wait until the explorer's initial Preact bundle has mounted. We pick
 * a selector that the Layout / page shell renders synchronously (the
 * `BenchBox` header link) so this does not race DuckDB-WASM init.
 */
export async function waitForShell(page: Page) {
  await expect(page.getByRole("link", { name: /BenchBox/i }).first()).toBeVisible();
}

/**
 * Wait for the DuckDB-WASM attach to complete and the page to render
 * real data. We assert on a user-visible element rather than internal
 * state so these waits also double as user-flow assertions.
 *
 * The 45s budget (up from 30s) absorbs the serial DuckDB-WASM cold-start tail
 * in the Chromium blocking command (`test:e2e:chromium` overrides Playwright
 * to `--workers=1`). It matches the margin the more careful inline data waits
 * in the suite already use and sits inside the 90s per-test timeout. See
 * docs/operations/browser-ci.md.
 */
const DATA_LOADED_TIMEOUT_MS = 45_000;

export async function waitForDataLoaded(page: Page, locator: string | RegExp) {
  if (typeof locator === "string") {
    await expect(page.locator(locator).first()).toBeVisible({ timeout: DATA_LOADED_TIMEOUT_MS });
  } else {
    await expect(page.getByText(locator).first()).toBeVisible({ timeout: DATA_LOADED_TIMEOUT_MS });
  }
}
