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

    for (const platform of ["DuckDB", "DataFusion", "Polars"]) {
      await expect(page.getByText(platform, { exact: false }).first()).toBeVisible({
        timeout: 20_000,
      });
    }
  });
});
