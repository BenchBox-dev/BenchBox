import { expect, test } from "@playwright/test";
import { waitForShell } from "../support/fixtures";

test.describe("PlatformIndex", () => {
  test("@smoke loads directly at /results/p/duckdb/ and renders the platform heading", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /DuckDB Results/i })).toBeVisible();
  });

  test("shows at least the TPC-H fixture result", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    // The fixture corpus includes TPC-H SF 0.01 on DuckDB - the page
    // must surface at least one result that mentions the benchmark.
    await expect(page.getByText(/TPC-H/i).first()).toBeVisible({ timeout: 20_000 });
  });
});
