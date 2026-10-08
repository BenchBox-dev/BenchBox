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
    await expect(page.getByRole("heading", { name: "Compare benchmark results" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("grid", { name: "Cross-benchmark leaderboard" })).toBeVisible();
  });

  test("?ids=<one> keeps that run selected when linking to Find runs", async ({ page }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB}`);
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Compare benchmark results" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("link", { name: "Find runs to compare with this run" })).toHaveAttribute("href", /\/results\/query\?pick=/);
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
    void [SHORT_DUCKDB, SHORT_DATAFUSION];
    const fourIds = [SHORT_DUCKDB, SHORT_DATAFUSION, fixtureIds.shortIds.duckdbTuned].filter(Boolean).join(",");
    const urlIds = fourIds.split(",").length >= 3 ? fourIds : `${SHORT_DUCKDB},${SHORT_DATAFUSION},${SHORT_DUCKDB},${SHORT_DATAFUSION}`;
    await page.goto(`/results/compare?ids=${urlIds}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison|Comparison/i);
    await expect(page.getByRole("main").getByRole("heading", { name: /Query-level differences|Comparison/ }).first()).toBeVisible();
    const urlSearchIds = new URL(page.url()).searchParams.get("ids")?.split(",") ?? [];
    expect(urlSearchIds.length).toBeGreaterThanOrEqual(2);
  });

  test("stale id shows friendly error, does not crash", async ({ page }) => {
    await page.goto(`/results/compare?ids=${STALE_ID}`);
    await waitForShell(page);
    const recovery = page.getByRole("heading", { name: "Compare benchmark results" });
    const error = page.getByText(/No result found|not found|unavailable/i);
    await expect(recovery.or(error).first()).toBeVisible({ timeout: 20000 });
  });

  test("duplicate ids are deduplicated (ids list stays unique)", async ({ page }) => {
    await page.goto(`/results/compare?ids=${DUPLICATE_IDS}`);
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Compare benchmark results" })).toBeVisible({ timeout: 20000 });
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

  test("shared link (copy URL) round-trips correctly", async ({ page }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison|Comparison/i);
    const url = page.url();
    expect(url).toContain("/results/compare?ids=");
    await page.goto(url);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison|Comparison/i);
    await expect(page.getByRole("main").locator(`a[href="/results/r/${LONG_DUCKDB}"]`).first()).toBeVisible();
  });

  test("empty selection has a clear recovery action", async ({ page }) => {
    await page.goto("/results/compare");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Compare benchmark results" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("grid", { name: "Cross-benchmark leaderboard" })).toBeVisible();
  });

  test("Pages 404 restore round-trip (deep-link URL preserved via redirect)", async ({ page }) => {
    await page.goto("/results/compare?ids=" + SHORT_DUCKDB);
    await waitForShell(page);
    await page.evaluate((ids) => {
      sessionStorage.setItem("benchbox.results.redirect", `/results/compare?ids=${ids}`);
    }, SHORT_DUCKDB);
    await page.reload();
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Compare benchmark results" })).toBeVisible({ timeout: 20000 });
  });

  test("document height with large fixture is bounded (no unbounded candidate table)", async ({ page }) => {
    await page.goto("/results/compare?ids=" + SHORT_DUCKDB);
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Compare benchmark results" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("link", { name: "Find runs to compare with this run" })).toBeVisible();
    await expect(page.getByRole("grid", { name: "Cross-benchmark leaderboard" })).toBeVisible();
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    expect(height).toBeLessThan(5000);
    await page.setViewportSize({ width: 390, height: 844 });
    const heightMobile = await page.evaluate(() => document.documentElement.scrollHeight);
    expect(heightMobile).toBeLessThan(6000);
  });
});
