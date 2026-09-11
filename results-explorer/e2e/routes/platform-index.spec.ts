import { expect, test } from "@playwright/test";
import { waitForDataElement, waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("PlatformIndex", () => {
  test("@smoke loads directly at /results/p/duckdb/ and renders the platform heading", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    // Same webkit cold-start DuckDB-WASM latency noted in
    // benchmark-index.spec.ts (webkit-smoke-fix-or-demote-2): wait for the
    // data-bound heading text before asserting its role.
    await waitForDataLoaded(page, /DuckDB Results/i);
    await expect(page.getByRole("heading", { name: /DuckDB Results/i })).toBeVisible();
  });

  test("shows at least the TPC-H fixture result", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    // The fixture corpus includes TPC-H SF 0.01 on DuckDB - the page
    // must surface at least one result that mentions the benchmark.
    await waitForDataLoaded(page, /DuckDB Results/i);
    const table = page.getByRole("table", { name: "DuckDB results" });
    await waitForDataElement(page, table.locator("tbody tr").first());
    await expect(table.getByText("TPC-H", { exact: true }).first()).toBeVisible();
  });
});
