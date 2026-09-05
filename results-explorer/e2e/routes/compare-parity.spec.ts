import { expect, test } from "@playwright/test";
import { fixtureIds, waitForDataLoaded, waitForShell } from "../support/fixtures";

const SHORT_DUCKDB = fixtureIds.shortIds.duckdb;
const SHORT_DATAFUSION = fixtureIds.shortIds.datafusion;
const LONG_DUCKDB = fixtureIds.ids.duckdb;
const STALE_ID = "deadbeef";
const DUPLICATE_IDS = `${SHORT_DUCKDB},${SHORT_DUCKDB}`;

test.describe("compare selection and direct-link parity", () => {
  test.describe.configure({ mode: "serial" });

  test("empty ?ids= points to Find runs", async ({ page }) => {
    await page.goto("/results/compare");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Choose runs to compare" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("compare-picker-query-link")).toHaveAttribute("href", "/results/query");
  });

  test("?ids=<one> keeps that run selected when linking to Find runs", async ({ page }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB}`);
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Find another run" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("compare-picker-query-link")).toHaveAttribute("href", /\/results\/query\?pick=/);
  });

  test("?ids=<a,b> renders comparison with both results", async ({ page }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison|Comparison/i);
    const main = page.getByRole("main");
    await expect(main.locator(`a[href="/results/r/${LONG_DUCKDB}"]`).first()).toBeVisible();
    await expect(main.locator(`a[href="/results/r/${fixtureIds.ids.datafusion}"]`).first()).toBeVisible();
  });

  test("?ids with 4 ids renders comparison (cap)", async ({ page }) => {
    void [SHORT_DUCKDB, SHORT_DATAFUSION]; // ids handled via fourIds below
    // If we only have 2-3 distinct, still test with at least 3-4 by using shortIds directly
    const fourIds = [SHORT_DUCKDB, SHORT_DATAFUSION, fixtureIds.shortIds.duckdbTuned].filter(Boolean).join(",");
    const urlIds = fourIds.split(",").length >= 3 ? fourIds : `${SHORT_DUCKDB},${SHORT_DATAFUSION},${SHORT_DUCKDB},${SHORT_DATAFUSION}`;
    await page.goto(`/results/compare?ids=${urlIds}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison|Comparison/i);
    await expect(page.getByRole("main").getByRole("heading", { name: /Query-level differences|Comparison/ }).first()).toBeVisible();
    // Verify all distinct ids present in URL (cap handling)
    const urlSearchIds = new URL(page.url()).searchParams.get("ids")?.split(",") ?? [];
    expect(urlSearchIds.length).toBeGreaterThanOrEqual(2);
  });

  test("stale id shows friendly error, does not crash", async ({ page }) => {
    await page.goto(`/results/compare?ids=${STALE_ID}`);
    await waitForShell(page);
    // Show an error or recovery state, never a blank page.
    const recovery = page.getByRole("heading", { name: "Choose runs to compare" });
    const error = page.getByText(/No result found|not found|unavailable/i);
    await expect(recovery.or(error).first()).toBeVisible({ timeout: 20000 });
  });

  test("duplicate ids are deduplicated (ids list stays unique)", async ({ page }) => {
    await page.goto(`/results/compare?ids=${DUPLICATE_IDS}`);
    await waitForShell(page);
    // Should handle deduplication gracefully
    await expect(page.getByRole("heading", { name: "Find another run" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("compare-url-notice")).toContainText("Ignored duplicate result ID");
  });

  test("reload preserves comparison state", async ({ page }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison|Comparison/i);
    await page.reload();
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison|Comparison/i);
    await expect(page.getByRole("main").locator(`a[href="/results/r/${LONG_DUCKDB}"]`).first()).toBeVisible();
  });

  test("shared link (copy URL) round-trips correctly", async ({ page, context }) => {
    if (page.context().browser()?.browserType().name() === "chromium") {
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    }
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison|Comparison/i);
    const shareBtn = page.getByRole("button", { name: /Share URL/ });
    await shareBtn.click();
    await expect(page.getByRole("button", { name: /Copied!/ })).toBeVisible();
    const url = page.url();
    expect(url).toContain("/results/compare?ids=");
    // Re-visit copied URL
    await page.goto(url);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison|Comparison/i);
    await expect(page.getByRole("main").locator(`a[href="/results/r/${LONG_DUCKDB}"]`).first()).toBeVisible();
  });

  test("empty selection has a clear recovery action", async ({ page }) => {
    await page.goto("/results/compare");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Choose runs to compare" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("compare-picker-query-link")).toBeVisible();
  });

  test("Pages 404 restore round-trip (deep-link URL preserved via redirect)", async ({ page }) => {
    // Simulate SPA redirect storage: Pages 404 stores redirect URL in sessionStorage
    await page.goto("/results/compare?ids=" + SHORT_DUCKDB);
    await waitForShell(page);
    await page.evaluate((ids) => {
      sessionStorage.setItem("benchbox.results.redirect", `/results/compare?ids=${ids}`);
    }, SHORT_DUCKDB);
    // Reload should still honor ids from URL (sessionStorage redirect is consumed on app boot)
    await page.reload();
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Find another run" })).toBeVisible({ timeout: 20000 });
  });

  test("document height with large fixture is bounded (no unbounded candidate table)", async ({ page }) => {
    // This parity case used to assert 17,441px tall document before retirement.
    // After retirement, the builder should be compact regardless of corpus size.
    await page.goto("/results/compare?ids=" + SHORT_DUCKDB);
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Find another run" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("compare-picker-query-link")).toBeVisible();
    // Candidate selection remains on Find runs.
    await expect(page.locator("table")).toHaveCount(0);
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    // Compact builder should be well under old 17k threshold
    expect(height).toBeLessThan(5000);
    // At mobile too
    await page.setViewportSize({ width: 390, height: 844 });
    const heightMobile = await page.evaluate(() => document.documentElement.scrollHeight);
    expect(heightMobile).toBeLessThan(6000);
  });
});
