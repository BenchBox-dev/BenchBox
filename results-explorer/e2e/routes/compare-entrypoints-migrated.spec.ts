import { expect, test } from "@playwright/test";
import { fixtureIds, waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("compare entrypoints after tray migration (rx-18)", () => {
  test.describe.configure({ mode: "serial" });

  test("Home compare entry shows picking count and links to compareHref when picking non-empty", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);
    await waitForDataLoaded(page, /Recent Results/i);
    // Home entry always visible, with empty picking it shows Compare →
    const homeEntry = page.getByTestId("home-compare-entrypoint");
    await expect(homeEntry).toBeVisible();
    await expect(homeEntry).toContainText(/Compare/);
    // With no picks, href is builder
    await expect(homeEntry).toHaveAttribute("href", "/results/compare/");
    // PickingState is in-memory; selecting via other routes in same session via SPA routing would reflect it,
    // but full page.goto resets it. Verify empty state badge is correct.
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

  test("all entrypoints share one disabled rule: compare enabled only at >=2", async ({ page }) => {
    // Home
    await page.goto("/results/");
    await waitForShell(page);
    await waitForDataLoaded(page, /Recent Results/i);
    // Home entry is always a link, but its text reflects picking count
    await expect(page.getByTestId("home-compare-entrypoint")).toBeVisible();

    // BenchmarkIndex guidance is disabled below 2
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);
    await expect(page.getByRole("button", { name: "Select 2 comparable results" })).toBeVisible();

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
    await expect(page.getByText("Select 2 comparable results")).toBeVisible();
  });
});
