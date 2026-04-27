import { expect, test } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("Home", () => {
  test("@smoke renders the header, counts, and recent-results table", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    await expect(page.getByRole("heading", { name: "BenchBox Results" })).toBeVisible();

    // Recent Results table header - a stable landmark that only renders
    // once the DuckDB snapshot has attached and listResults() resolves.
    await waitForDataLoaded(page, /Recent Results/i);

    // Stat cards show counts derived from the fixture corpus. We scope
    // to the main area so we don't collide with header links like
    // "BenchBox Results" which also contain the literal "Results".
    const main = page.getByRole("main");
    for (const label of ["Results", "Benchmarks", "Platforms"]) {
      await expect(main.getByText(label, { exact: true })).toBeVisible();
    }
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
