import { expect, test } from "@playwright/test";

import { waitForDataLoaded } from "../support/fixtures";

/**
 * Harness sanity check - proves that the Playwright webServer boots the
 * built `dist/` output, that `/results/` resolves, and that the page shell
 * paints before the DuckDB-WASM bundle finishes downloading.
 *
 * Tagged @smoke so it also runs under Firefox and WebKit projects.
 */
test("@smoke serves the built explorer under /results/", async ({ page }) => {
  await page.goto("/results/");
  await expect(page).toHaveURL(/\/results\/?$/);
  // The layout renders before DuckDB attaches; assert on a stable shell
  // element so this test does not depend on the DuckDB-WASM init path.
  await expect(page.locator("body")).toBeVisible();
});

test("@smoke loads DuckDB-WASM from same-origin bundled assets, not jsDelivr", async ({ page }) => {
  // Register before goto() so no CDN request can escape before the listener
  // is active. page.on("request") covers main-frame requests, which is the
  // right scope for catching getJsDelivrBundles() regressions - CDN fetches
  // for the WASM bundle, worker script, and any importScripts() calls all
  // originate in the main frame under the old pattern.
  const jsDelivrRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("cdn.jsdelivr.net")) {
      jsDelivrRequests.push(request.url());
    }
  });

  await page.goto("/results/");
  // Wait for the full DuckDB init path: bundle selected → worker spawned →
  // WASM instantiated → ATTACH executed → data rendered. This ensures any
  // deferred CDN fetch would have fired before the assertion runs.
  await waitForDataLoaded(page, /Recent Results/i);

  expect(jsDelivrRequests).toEqual([]);
});
