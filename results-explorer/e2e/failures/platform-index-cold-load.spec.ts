import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { waitForShell } from "../support/fixtures";

async function expectPlatformRows(page: Page) {
  await expect
    .poll(() => page.locator("table tbody tr").count(), { timeout: 20_000 })
    .toBeGreaterThan(0);
  await expect(page.getByText(/No results found for platform/i)).not.toBeVisible();
}

test.describe.configure({ mode: "serial" });

test.describe("PlatformIndex cold-load regression (B2)", () => {
  test("cold-load renders DuckDB with rows and capital-D heading", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /^DuckDB Results$/ })).toBeVisible({ timeout: 20_000 });
    await expectPlatformRows(page);
  });

  test("cold-load renders Polars with rows and capital-P heading", async ({ page }) => {
    await page.goto("/results/p/polars/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /^Polars Results$/ })).toBeVisible({ timeout: 20_000 });
    await expectPlatformRows(page);
  });
});
