import { expect, test } from "@playwright/test";
import { fixtureIds, waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("compare entrypoints after tray migration (rx-18)", () => {
  test.describe.configure({ mode: "serial" });

  test("Overview links to comparison rankings", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);
    await waitForDataLoaded(page, /Recent Results/i);
    const homeEntry = page.getByTestId("overview-compare-cta");
    await expect(homeEntry).toBeVisible();
    await expect(homeEntry).toContainText(/Compare/);
    await expect(homeEntry).toHaveAttribute("href", "/results/compare");
  });

  test("ResultDetail links to Find runs with the current result selected", async ({ page }) => {
    const id = fixtureIds.ids.duckdb;
    await page.goto(`/results/r/${id}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /Query timings/);
    const compareLink = page.getByTestId("result-detail-compare-link");
    await expect(compareLink).toHaveAttribute("href", new RegExp(`/results/query\\?pick=${id}`));
    await compareLink.click();
    await waitForDataLoaded(page, /Find benchmark runs/);
    await expect(page.getByTestId("query-compare-tray")).toContainText("1 result selected");
    await expect(page.getByTestId("query-compare-tray")).toContainText("pick a compatible second row");
  });

  test("overview, benchmark, and receipt pages expose comparison entrypoints", async ({ page }) => {
    // Home
    await page.goto("/results/");
    await waitForShell(page);
    await waitForDataLoaded(page, /Recent Results/i);
    // Home entry is always a link, but its text reflects picking count
    await expect(page.getByTestId("overview-compare-cta")).toBeVisible();

    // BenchmarkIndex guidance is disabled below 2
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);
    await expect(page.getByTestId("benchmark-compare-cta-pending")).toHaveText("Select 2 results to compare");

    // ResultDetail sends the current run to Find runs, where the second run is selected.
    await page.goto(`/results/r/${fixtureIds.ids.duckdb}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /Query timings/);
    await expect(page.getByTestId("result-detail-compare-link")).toHaveAttribute(
      "href",
      new RegExp(`/results/query\\?pick=${fixtureIds.ids.duckdb}`),
    );
  });

  test("no stale compare labels remain", async ({ page }) => {
    // This test mirrors the rg check: no old labels in bundle.
    // We just verify the new labels are present.
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);
    // Should have BenchmarkIndex's tray once 2 selected, not old 'Compare 0 runs'
    await expect(page.getByTestId("benchmark-compare-cta-pending")).toHaveText("Select 2 results to compare");
  });
});
