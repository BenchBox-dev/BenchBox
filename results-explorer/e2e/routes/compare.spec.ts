import { expect, test } from "@playwright/test";
import { fixtureIds, waitForDataLoaded, waitForShell } from "../support/fixtures";

const SHORT_DUCKDB = fixtureIds.shortIds.duckdb;
const SHORT_DATAFUSION = fixtureIds.shortIds.datafusion;
const LONG_DUCKDB = fixtureIds.ids.duckdb;
const LONG_DATAFUSION = fixtureIds.ids.datafusion;

test.describe("Compare", () => {
  test.describe.configure({ mode: "serial" });

  test("@smoke loads /results/compare?ids=<a>,<b> and renders both platform cards", async ({
    page,
  }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);

    await waitForDataLoaded(page, /TPC-H Comparison/);

    const main = page.getByRole("main");
    await expect(main.locator(`a[href="/results/r/${LONG_DUCKDB}"]`)).toBeVisible();
    await expect(main.locator(`a[href="/results/r/${LONG_DATAFUSION}"]`)).toBeVisible();

    await expect(main.getByRole("heading", { name: /Query-level differences/ })).toBeVisible();
  });

  test("the explicit trailing-slash compare route resolves the same comparison page", async ({
    page,
  }) => {
    await page.goto(`/results/compare/?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison/);

    await expect(page).toHaveURL(/\/results\/compare\/\?ids=/);
    await expect(page.getByRole("main").getByText("DuckDB", { exact: true }).first()).toBeVisible();
  });

  test("long-form IDs in the URL get rewritten to short IDs after load", async ({ page }) => {
    const ids = [LONG_DUCKDB, LONG_DATAFUSION].map(encodeURIComponent).join(",");
    await page.goto(`/results/compare?ids=${ids}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison/);

    await expect
      .poll(() => new URL(page.url()).searchParams.get("ids"), { timeout: 15_000 })
      .toMatch(/^[0-9a-f]{8},[0-9a-f]{8}$/);
  });

  test("a single-id compare URL sends the selected run to Find runs", async ({ page }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB}`);
    await waitForShell(page);

    await expect(page.getByRole("heading", { name: "Compare benchmark results" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("link", { name: "Find runs to compare with this run" })).toHaveAttribute("href", /\/results\/query\?pick=/);
  });

  test("the browser URL reproduces the selected comparison", async ({ page }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForDataLoaded(page, /TPC-H Comparison/);
    const sharedUrl = page.url();
    await page.goto("/results/");
    await page.goto(sharedUrl);
    await waitForDataLoaded(page, /TPC-H Comparison/);
    await expect(page.getByRole("main").locator(`a[href="/results/r/${LONG_DUCKDB}"]`)).toBeVisible();
    await expect(page.getByRole("main").locator(`a[href="/results/r/${LONG_DATAFUSION}"]`)).toBeVisible();
  });

  test("selecting two platforms on BenchmarkIndex routes to Compare via the sticky bar", async ({
    page,
  }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);

    const duckdb = page.getByRole("checkbox", { name: /Select DuckDB .* for comparison/i });
    const datafusion = page.getByRole("checkbox", { name: /Select DataFusion .* for comparison/i });
    await expect(duckdb.first()).toBeVisible();
    await duckdb.first().check();
    await datafusion.first().check();

    const compareLink = page.getByTestId("compare-tray-compare-link");
    await expect(compareLink).toBeVisible();
    await compareLink.click();

    await expect(page).toHaveURL(/\/results\/compare\?ids=/);
    await waitForDataLoaded(page, /TPC-H Comparison/);
  });
});
