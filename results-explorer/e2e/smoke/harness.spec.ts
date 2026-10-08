import { expect, test } from "@playwright/test";

import { dataWaitNavigationAction, waitForDataLoaded } from "../support/fixtures";

test("@smoke serves the built explorer under /results/", async ({ page }) => {
  await page.goto("/results/");
  await expect(page).toHaveURL(/\/results\/?$/);
  await expect(page.locator("body")).toBeVisible();
});

test("@smoke loads DuckDB-WASM from same-origin bundled assets, not jsDelivr", async ({ page }) => {
  const jsDelivrRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("cdn.jsdelivr.net")) {
      jsDelivrRequests.push(request.url());
    }
  });

  await page.goto("/results/");
  await waitForDataLoaded(page, /Recent Results/i);

  expect(jsDelivrRequests).toEqual([]);
});

test("data waits re-wait after same-route query canonicalization", () => {
  expect(
    dataWaitNavigationAction(
      "http://127.0.0.1:4319/results/query/?sql=SELECT%20*%20FROM%20bench.results",
      "http://127.0.0.1:4319/results/query/?sql=SELECT+*+FROM+bench.results",
    ),
  ).toBe("rewait");
});
