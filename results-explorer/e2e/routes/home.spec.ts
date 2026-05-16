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
    // Corpus Summary labels are count-aware: when the fixture corpus has
    // exactly one item, the label must read singular ("leaderboard ranking"),
    // otherwise plural ("leaderboard rankings"). The route gate enforces both
    // forms via the regex below so changes to fixture counts cannot reintroduce
    // grammatically wrong copy like "1 leaderboard rankings".
    for (const label of [
      /^supported benchmarks?$/,
      /^public result bundles?$/,
      /^platforms? with public results$/,
      /^leaderboard rankings?$/,
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
    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);

    const hero = page.getByTestId("home-hero-filter-band");
    const dataSurface = page.getByTestId("home-data-surface");
    await expect(hero).toHaveAttribute("data-surface", "hero");
    await expect(dataSurface).toHaveAttribute("data-surface", "app");

    const [lightHeroBg, lightDataBg] = await Promise.all([
      hero.evaluate((element) => getComputedStyle(element).backgroundColor),
      dataSurface.evaluate((element) => getComputedStyle(element).backgroundColor),
    ]);
    expect(lightHeroBg).toBe("rgb(255, 255, 255)");
    expect(lightDataBg).toBe("rgb(245, 246, 248)");

    await page.evaluate(() => localStorage.setItem("benchbox:theme", "dark"));
    await page.reload();
    await waitForDataLoaded(page, /Recent Results/i);

    const [darkHeroBg, darkDataBg] = await Promise.all([
      page.getByTestId("home-hero-filter-band").evaluate((element) => getComputedStyle(element).backgroundColor),
      page.getByTestId("home-data-surface").evaluate((element) => getComputedStyle(element).backgroundColor),
    ]);
    expect(darkHeroBg).toBe("rgb(13, 17, 23)");
    expect(darkDataBg).toBe("rgb(13, 17, 23)");
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
