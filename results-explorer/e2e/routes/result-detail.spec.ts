import { expect, test } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

// Stable full-form result IDs from the deterministic generated fixture corpus.
const TPCH_DUCKDB_ID = "tpch-duckdb-sf0.01-20260403-010ee756";
const TPCH_DATAFUSION_ID = "tpch-datafusion-sf0.01-20260403-a6bb8a70";

test.describe("ResultDetail", () => {
  test("@smoke loads /results/r/<id> and renders the run header, badges, and timings table", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_DUCKDB_ID}`);
    await waitForShell(page);

    // The page heading is `<Benchmark> - <Platform>` once DuckDB-WASM has
    // attached and the detail metrics query resolves.
    await waitForDataLoaded(page, /TPC-H\s+-\s+DuckDB/);

    // Trust badge and SF row are rendered synchronously beside the heading.
    const main = page.getByRole("main");
    await expect(
      main.getByRole("region", { name: "Result summary" }).getByText("SF 0.01", { exact: true }),
    ).toBeVisible();

    // Query Timings header is the stable landmark for the medians table.
    await expect(main.getByRole("heading", { name: /Query Timings/ })).toBeVisible();
  });

  test("sorting the median table toggles the indicator arrow", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_DUCKDB_ID}`);
    await waitForDataLoaded(page, /Query Timings/);

    const header = page.getByRole("columnheader", { name: /Median latency/ });
    // First click sorts ascending; second click flips to descending. We
    // assert on the arrow indicator because row-order comparison is noisy
    // across browsers.
    await header.click();
    await expect(header).toContainText("↑");
    await header.click();
    await expect(header).toContainText("↓");
  });

  test("'Compare this result' opens the compare builder with the result pinned", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_DUCKDB_ID}`);
    await waitForDataLoaded(page, /Query Timings/);

    await page.getByRole("link", { name: /Compare this result/i }).click();
    await expect(page).toHaveURL(new RegExp(`/results/compare\\?ids=${TPCH_DUCKDB_ID}$`));
    await expect(page.getByTestId("compare-builder")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("compare-builder-status")).toContainText("1 selected");
    await expect(page.getByTestId(`compare-builder-row-${TPCH_DUCKDB_ID}`)).toContainText("(from result detail)");
  });

  test("a missing result_id surfaces a user-visible error rather than a blank screen", async ({ page }) => {
    await page.goto("/results/r/does-not-exist");
    await waitForShell(page);
    // ErrorMessage renders the "No result found for..." string. This is a
    // happy-path slice for route coverage - the failure-injection suite
    // (w7) extends this to snapshot-missing / range-read cases.
    await expect(page.getByText(/No result found for/i)).toBeVisible({ timeout: 20_000 });
  });
});

// Export constants so compare.spec.ts can share the same IDs without
// duplicating the contract-with-the-fixture-generator.
export { TPCH_DUCKDB_ID, TPCH_DATAFUSION_ID };
