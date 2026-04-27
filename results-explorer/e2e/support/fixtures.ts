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
 */
export async function waitForDataLoaded(page: Page, locator: string | RegExp) {
  if (typeof locator === "string") {
    await expect(page.locator(locator).first()).toBeVisible({ timeout: 30_000 });
  } else {
    await expect(page.getByText(locator).first()).toBeVisible({ timeout: 30_000 });
  }
}
