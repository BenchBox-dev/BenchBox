import { expect, test } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("Home", () => {
  test("@smoke renders the leaderboard-first header, corpus summary, and recent-results table", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    await expect(page.getByRole("heading", { name: "BenchBox Database Leaderboards" })).toBeVisible();

    // Recent Results table header - a stable landmark that only renders
    // once the DuckDB snapshot has attached and listResults() resolves.
    await waitForDataLoaded(page, /Recent Results/i);

    const summary = page.getByRole("region", { name: "Corpus summary" });
    for (const label of [
      "supported benchmarks",
      "public result bundles",
      "platforms with public results",
      "PR-validated corpus",
    ]) {
      await expect(summary.getByText(label, { exact: true })).toBeVisible();
    }
    await expect(summary.getByText("Benchmarks", { exact: true })).toHaveCount(0);
  });

  test("browse-by-benchmark link deep-links to the benchmark index under /results/", async ({
    page,
  }) => {
    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);

    // The Home page lists each benchmark as a pill link; clicking one
    // must leave the base path intact.
    const tpchLink = page.getByRole("link", { name: /^TPC-H$/ }).first();
    await expect(tpchLink).toBeVisible();
    await tpchLink.click();
    await expect(page).toHaveURL(/\/results\/tpch\/?/);
  });
});
