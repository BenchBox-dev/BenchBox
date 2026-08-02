import { expect, test } from "@playwright/test";
import { waitForDataLoaded } from "../support/fixtures";

test.describe("accessibility and responsive regressions", () => {
  test("reduced motion and forced contrast preserve keyboard focus", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
    await page.setViewportSize({ width: 640, height: 900 });
    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);

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

  test("the home surface remains horizontally contained at 200 percent zoom", async ({ page }) => {
    await page.setViewportSize({ width: 640, height: 900 });
    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);

    await page.evaluate(() => {
      document.documentElement.style.zoom = "2";
    });

    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      bodyScrollWidth: document.body.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
    expect(dimensions.bodyScrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  });
});
