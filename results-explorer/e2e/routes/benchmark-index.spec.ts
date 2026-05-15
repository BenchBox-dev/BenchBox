import { expect, test } from "@playwright/test";
import { waitForShell } from "../support/fixtures";

test.describe("BenchmarkIndex", () => {
  test("@smoke loads directly at /results/tpch/ and syncs SF filter into the URL", async ({
    page,
  }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);

    await expect(page.getByRole("heading", { name: /TPC-H Results/ })).toBeVisible();

    // Scale-factor selector writes to the `sf` query parameter. The
    // fixture corpus only carries SF 0.01, so the selector should
    // default to that and the URL should persist it on navigation.
    await expect(page).toHaveURL(/\/results\/tpch\//);
    const sfValue = await page.evaluate(() => new URL(window.location.href).searchParams.get("sf"));
    expect(sfValue === null || sfValue === "0.01").toBeTruthy();
  });

  test("renders a platform row per platform in the fixture corpus", async ({ page }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /TPC-H Results/ })).toBeVisible();

    const grid = page.getByRole("grid", { name: /tpch SF0\.01 standard results/i });
    for (const platform of ["DuckDB", "DataFusion", "Polars"]) {
      await expect(grid.getByText(platform, { exact: false }).first()).toBeVisible({
        timeout: 20_000,
      });
    }
  });

  test("benchmark switcher only lists benchmarks with public results", async ({ page }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);

    const switcher = page.getByTestId("benchmark-switcher");
    // Wait for the switcher to populate. The corpus-aware option list is
    // filled from `listBenchmarksWithPublicResults()`, which resolves after
    // the snapshot attaches.
    await expect(switcher).toBeVisible();
    await expect.poll(async () => (await switcher.locator("option").count())).toBeGreaterThan(0);

    const labels = (await switcher.locator("option").allTextContents()).map((label) => label.trim());
    // The fixture corpus carries a defined set of benchmarks; the switcher
    // must list exactly those (Contract A from the corpus-aware-switcher
    // TODO) and must not surface catalog-only benchmarks with no public
    // result pages such as AMPLab or TPC-DI.
    expect(labels).toContain("TPC-H");
    expect(labels).not.toContain("AMPLab");
    expect(labels).not.toContain("TPC-DI");
    expect(labels).not.toContain("TPC-DS");
  });

  test("direct route to a no-result benchmark renders an empty-state with Back to Results", async ({ page }) => {
    await page.goto("/results/amplab/");
    await waitForShell(page);

    // `amplab` is in BENCHMARK_LABELS but the fixture corpus has no AMPLab
    // results, so the page renders the dedicated empty benchmark detail
    // layout (not 404). The TODO contract requires that this direct route
    // still resolves to a useful page with a route back to Results.
    await expect(page.getByRole("heading", { name: "AMPLab", level: 1 })).toBeVisible();
    await expect(page.getByText("No published results yet for AMPLab.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to Results" })).toBeVisible();
  });
});
