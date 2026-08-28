// Strict cold-load row counts: the pass-1 cold-load bug surfaced as
// PARTIAL rows (e.g. 1 row of 5 for DuckDB), not zero rows. A `count > 0`
// assertion would silently pass that regression. Counts come from the
// fixtures DB at results-explorer/test-fixtures/.generated/data/results.duckdb;
// regenerate the fixtures and update these constants together.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { waitForShell } from "../support/fixtures";

const EXPECTED_ROWS_BY_PLATFORM: Record<string, number> = {
  duckdb: 5,
  polars: 1,
};

async function expectExactPlatformRows(page: Page, expected: number) {
  await expect(page.locator("table tbody tr[data-testid]")).toHaveCount(expected, { timeout: 20_000 });
  await expect(page.getByText(/No results found for platform/i)).not.toBeVisible();
}

test.describe.configure({ mode: "serial" });

test.describe("PlatformIndex cold-load regression (B2)", () => {
  test("cold-load renders DuckDB with the expected row count and capital-D heading", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /^DuckDB Results$/ })).toBeVisible({ timeout: 20_000 });
    await expectExactPlatformRows(page, EXPECTED_ROWS_BY_PLATFORM.duckdb!);
  });

  test("cold-load renders Polars with the expected row count and capital-P heading", async ({ page }) => {
    await page.goto("/results/p/polars/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /^Polars Results$/ })).toBeVisible({ timeout: 20_000 });
    await expectExactPlatformRows(page, EXPECTED_ROWS_BY_PLATFORM.polars!);
  });
});
