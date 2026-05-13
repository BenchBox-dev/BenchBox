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
      "leaderboard cohorts",
    ]) {
      await expect(summary.getByText(label, { exact: true })).toBeVisible();
    }
    await expect(summary.getByText("PR-validated corpus", { exact: true })).toHaveCount(0);
    await expect(summary.getByText("Benchmarks", { exact: true })).toHaveCount(0);
  });

  test("documents the mixed home theme contract", async ({ page }) => {
    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);

    const hero = page.getByTestId("home-hero-filter-band");
    const dataSurface = page.getByTestId("home-data-surface");
    await expect(hero).toHaveAttribute("data-surface", "hero");
    await expect(dataSurface).toHaveAttribute("data-surface", "app");

    const [heroBg, dataBg] = await Promise.all([
      hero.evaluate((element) => getComputedStyle(element).backgroundColor),
      dataSurface.evaluate((element) => getComputedStyle(element).backgroundColor),
    ]);
    expect(heroBg).not.toBe(dataBg);
    expect(heroBg).toBe("rgb(13, 17, 23)");
    expect(dataBg).toBe("rgb(245, 246, 248)");
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
