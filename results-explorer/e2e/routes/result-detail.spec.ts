import { expect, test } from "@playwright/test";
import { fixtureIds, waitForDataLoaded, waitForShell } from "../support/fixtures";

// Stable full-form result IDs from the deterministic generated fixture corpus.
const TPCH_DUCKDB_ID = fixtureIds.ids.duckdb;
const TPCH_DATAFUSION_ID = fixtureIds.ids.datafusion;
const TPCH_ZERO_TIMING_ID = fixtureIds.ids.zeroTiming;

test.describe("ResultDetail", () => {
  test("@smoke loads /results/r/<id> and renders the run header, badges, and timings table", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_DUCKDB_ID}`);
    await waitForShell(page);

    // The page heading is `<Benchmark> - <Platform>` once DuckDB-WASM has
    // attached and the detail metrics query resolves.
    await waitForDataLoaded(page, /TPC-H result:\s+DuckDB/);

    // Trust badge and SF row are rendered synchronously beside the heading.
    const main = page.getByRole("main");
    await expect(
      main.getByRole("region", { name: "Result summary" }).getByText("SF 0.01", { exact: true }),
    ).toBeVisible();

    // Query timings header is the stable landmark for the medians table.
    await expect(main.getByRole("heading", { name: /Query timings/ })).toBeVisible();
  });

  test("the pass table reports every query once and closes with run totals", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_DUCKDB_ID}`);
    await waitForDataLoaded(page, /Query timings/);

    // One per-query table, not two: the median table would repeat the warm
    // median this one already reports beside the passes behind it.
    await expect(page.getByRole("columnheader", { name: /Median latency/ })).toHaveCount(0);
    const totals = page.getByTestId("pass-strip-totals");
    await expect(totals).toBeVisible();
    await expect(totals.locator("th")).toHaveText("Overall");
    await expect(totals.locator("td").first()).not.toHaveText("");
  });

  test("sortable headers expose state and native Space activation does not scroll", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_DUCKDB_ID}`);
    await waitForDataLoaded(page, /Query timings/);

    await page.getByText(/Individual samples \(/).click();
    const durationHeader = page.locator('th[aria-sort]').filter({ hasText: "Duration" }).first();
    await expect(durationHeader.locator('[role="button"]')).toHaveCount(0);
    await expect(durationHeader).toHaveAttribute("aria-sort", "none");
    const durationButton = durationHeader.getByRole("button");
    await durationButton.click();
    await expect(durationHeader).toHaveAttribute("aria-sort", "ascending");

    const scrollBeforeSpace = await page.evaluate(() => window.scrollY);
    await durationButton.press("Space");
    await expect(durationHeader).toHaveAttribute("aria-sort", "descending");
    expect(await page.evaluate(() => window.scrollY)).toBe(scrollBeforeSpace);
  });

  test("'Find a run to compare' opens Find runs with the result selected", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_DUCKDB_ID}`);
    await waitForDataLoaded(page, /Query timings/);

    await page.getByRole("link", { name: "Find a run to compare" }).click();
    await waitForDataLoaded(page, /matching run/);
    await expect(page).toHaveURL(new RegExp(`/results/query\\?pick=${encodeURIComponent(TPCH_DUCKDB_ID)}`));
    await expect(page.getByTestId(`query-compare-checkbox-${TPCH_DUCKDB_ID}`)).toBeChecked();
  });

  test("a missing result_id surfaces a user-visible error rather than a blank screen", async ({ page }) => {
    await page.goto("/results/r/does-not-exist");
    await waitForShell(page);
    // ErrorMessage renders the "No result found for..." string. This is a
    // happy-path slice for route coverage - the failure-injection suite
    // (w7) extends this to snapshot-missing / range-read cases.
    await expect(page.getByText(/No result found for/i)).toBeVisible({ timeout: 20_000 });
  });

  test("result detail zero timing omits absent metric and timing surfaces", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_ZERO_TIMING_ID}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H result:\s+DuckDB Zero Timing/);

    const main = page.getByRole("main");
    const summary = main.getByRole("region", { name: "Result summary" });
    await expect(summary).not.toContainText("N/A");
    await expect(summary.getByText(/Primary metric/)).toHaveCount(0);
    await expect(summary.locator('[data-role="validation"]')).toHaveCount(0);
    await expect(main.getByRole("heading", { name: /Query timings/ })).toHaveCount(0);
    await expect(main.getByText("Charts", { exact: true })).toHaveCount(0);
    await expect(main.getByText(/\d+ fields? not recorded for this run\./)).toHaveCount(1);
    await expect(main.getByRole("region", { name: "Run receipt" })).toBeVisible();
  });
});

// Export constants so compare.spec.ts can share the same IDs without
// duplicating the contract-with-the-fixture-generator.
export { TPCH_DUCKDB_ID, TPCH_DATAFUSION_ID };
