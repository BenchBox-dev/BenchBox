import { expect, test } from "@playwright/test";
import { waitForDataElement, waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("PlatformIndex", () => {
  test("@smoke loads directly at /results/p/duckdb/ and renders the platform heading", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    await waitForDataLoaded(page, /DuckDB Results/i);
    await expect(page.getByRole("heading", { name: /DuckDB Results/i })).toBeVisible();
  });

  test("shows at least the TPC-H fixture result", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    await waitForDataLoaded(page, /DuckDB Results/i);
    const table = page.getByRole("table", { name: "DuckDB results" });
    await waitForDataElement(page, table.locator("tbody tr").first());
    await expect(table.getByText("TPC-H", { exact: true }).first()).toBeVisible();
  });
});
