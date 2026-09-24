import { expect, test } from "@playwright/test";
import { waitForDataLoaded } from "../support/fixtures";

test.describe("accessibility and responsive regressions", () => {
  test("reduced motion and forced contrast preserve keyboard focus", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
    await page.setViewportSize({ width: 640, height: 900 });
    await page.goto("/results/compare/");
    await waitForDataLoaded(page, /Compare benchmark results/i);

    await page.getByText("Advanced filters").click();
    const control = page.getByRole("button", { name: /All (tuning labels|trust tiers|time)/ }).first();
    await control.focus();
    await expect(control).toBeFocused();
    await expect
      .poll(() => control.evaluate((element) => getComputedStyle(element).outlineWidth))
      .not.toBe("0px");

    const media = await page.evaluate(() => ({
      reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
      forcedColors: matchMedia("(forced-colors: active)").matches,
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(media.reducedMotion).toBe(true);
    expect(media.forcedColors).toBe(true);
    expect(media.scrollWidth).toBeLessThanOrEqual(media.clientWidth);
  });

  test("comparison loading and controls stay usable at 200 percent zoom", async ({ page }) => {
    await page.setViewportSize({ width: 640, height: 900 });
    let releaseSnapshot!: () => void;
    const snapshotGate = new Promise<void>((resolve) => { releaseSnapshot = resolve; });
    await page.route("**/results/data/results.duckdb", async (route) => {
      await snapshotGate;
      await route.continue();
    });
    await page.goto("/results/compare/");
    await expect(page.getByRole("region", { name: "Cross-benchmark leaderboard loading" })).toBeVisible();
    await page.evaluate(() => { document.documentElement.style.zoom = "2"; });
    const widths = () => page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    const loading = await widths();
    expect(loading.scroll).toBeLessThanOrEqual(loading.client);
    expect(loading.body).toBeLessThanOrEqual(loading.client);
    releaseSnapshot();
    await expect(page.getByRole("grid", { name: "Cross-benchmark leaderboard" })).toBeVisible();
    const loaded = await widths();
    expect(loaded.scroll).toBeLessThanOrEqual(loaded.client);
    expect(loaded.body).toBeLessThanOrEqual(loaded.client);
    const controls = page.getByRole("group", { name: "Leaderboard display controls" });
    for (const radio of await controls.getByRole("radio").all()) {
      await radio.scrollIntoViewIfNeeded();
      const box = await radio.boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(640);
    }
    const recent = controls.getByRole("radio", { name: "Recent", exact: true });
    await recent.click();
    await expect(recent).toHaveAttribute("aria-checked", "true");
  });
});
