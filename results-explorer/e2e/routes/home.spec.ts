import { expect, test } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("Home", () => {
  test("@smoke renders the overview header, corpus summary, and recent-results table", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    await waitForDataLoaded(page, /Recent Results/i);

    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

    const summary = page.getByRole("region", { name: "Corpus summary" });
    for (const label of [
      /^supported benchmarks?$/,
      /^published runs?$/,
      /^platforms? with public results$/,
      /^rankings?$/,
    ]) {
      await expect(summary.getByText(label).first()).toBeVisible();
    }
    await expect(summary.getByText("leaderboard cohorts", { exact: true })).toHaveCount(0);
    await expect(summary.getByText("PR-validated corpus", { exact: true })).toHaveCount(0);
    await expect(summary.getByText("Benchmarks", { exact: true })).toHaveCount(0);
  });

  test("applies the selected BenchBox theme to hero and data surfaces", async ({ page }) => {
    await page.addInitScript(() => {
      if (!localStorage.getItem("benchbox:theme")) {
        localStorage.setItem("benchbox:theme", "light");
      }
    });
    await page.goto("/results/compare/");
    await waitForDataLoaded(page, /Compare benchmark results/i);

    const hero = page.getByTestId("home-hero-filter-band");
    const dataSurface = page.getByTestId("home-data-surface");
    await expect(hero).toHaveAttribute("data-surface", "hero");
    await expect(dataSurface).toHaveAttribute("data-surface", "app");

    const [lightHeroBg, lightDataBg] = await Promise.all([
      hero.evaluate((element) => getComputedStyle(element).backgroundColor),
      dataSurface.evaluate((element) => getComputedStyle(element).backgroundColor),
    ]);
    expect(lightHeroBg).toBe("rgb(249, 240, 231)");
    expect(lightDataBg).toBe("rgb(242, 225, 212)");

    await page.evaluate(() => localStorage.setItem("benchbox:theme", "dark"));
    await page.reload();
    await waitForDataLoaded(page, /Compare benchmark results/i);

    const [darkHeroBg, darkDataBg] = await Promise.all([
      page.getByTestId("home-hero-filter-band").evaluate((element) => getComputedStyle(element).backgroundColor),
      page.getByTestId("home-data-surface").evaluate((element) => getComputedStyle(element).backgroundColor),
    ]);
    expect(darkHeroBg).toBe("rgb(74, 21, 38)");
    expect(darkDataBg).toBe("rgb(74, 21, 38)");
  });

  test("browse-by-benchmark link deep-links to the benchmark index under /results/", async ({
    page,
  }) => {
    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);

    const tpchLink = page.getByRole("link", { name: /^TPC-H$/ }).first();
    await expect(tpchLink).toBeVisible();
    await tpchLink.click();
    await expect(page).toHaveURL(/\/results\/tpch\/?/);
  });
});
