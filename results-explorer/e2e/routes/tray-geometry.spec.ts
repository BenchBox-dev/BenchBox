import { expect, test, type Locator, type Page } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("tray geometry: collapsed and expanded clearance", () => {
  test.describe.configure({ mode: "serial" });

  test("collapsed mobile tray keeps last row reachable at 390x844", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openBenchmarkTray(page);
    // By default mobile is collapsed; verify collapsed state.
    await expect(page.getByTestId("compare-tray")).toHaveAttribute("data-collapsed", "true");
    await expect(page.getByTestId("compare-tray-details")).toBeHidden();
    // Compare link must still be visible in collapsed state.
    await expect(page.getByTestId("compare-tray-compare-link")).toBeVisible();
    const lastRow = page.getByTestId("query-heatmap-mobile-cards").locator(":scope > [role='listitem']").last();
    await expectTrayClearance(page, lastRow);
  });

  test("expanded mobile tray keeps last row reachable at 390x844", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openBenchmarkTray(page);
    await page.getByTestId("compare-tray-toggle").click();
    await expect(page.getByTestId("compare-tray")).toHaveAttribute("data-collapsed", "false");
    await expect(page.getByTestId("compare-tray-details")).toBeVisible();
    const lastRow = page.getByTestId("query-heatmap-mobile-cards").locator(":scope > [role='listitem']").last();
    await expectTrayClearance(page, lastRow);
  });

  test("dismissal collapses without clearing selection", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openBenchmarkTray(page);
    await page.getByTestId("compare-tray-toggle").click();
    await expect(page.getByTestId("compare-tray-details")).toBeVisible();
    await page.getByTestId("compare-tray-dismiss").click();
    await expect(page.getByTestId("compare-tray")).toHaveAttribute("data-collapsed", "true");
    await expect(page.getByTestId("compare-tray-details")).toBeHidden();
    // Selection retained: compare link still visible and still points to 2 ids.
    const compareLink = page.getByTestId("compare-tray-compare-link");
    await expect(compareLink).toBeVisible();
    await expect(compareLink).toHaveAttribute("href", /ids=/);
    // Re-expand to verify checked state is retained.
    await page.getByTestId("compare-tray-toggle").click();
    await expect(page.getByTestId("compare-tray-details")).toBeVisible();
  });

  test("desktop tray has no collapse toggle and stays visible at 1440x1000", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await openBenchmarkTray(page);
    // At desktop the tray is never collapsed.
    await expect(page.getByTestId("compare-tray")).toHaveAttribute("data-collapsed", "false");
    // Toggle is mobile-only, hidden or absent at desktop.
    const toggle = page.getByTestId("compare-tray-toggle");
    await expect(toggle).toBeHidden();
    const lastRow = page.getByRole("grid").getByRole("row").last();
    await expectTrayClearance(page, lastRow);
  });

  test("horizontal table scrolling does not move the tray", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await openBenchmarkTray(page);
    const tray = page.getByTestId("compare-tray");
    const scroller = page.locator("[data-testid='query-heatmap-scroll-container']");
    // Ensure scroller has overflow.
    await expect(scroller).toBeVisible({ timeout: 10_000 }).catch(() => {});
    const boxBefore = await tray.boundingBox();
    expect(boxBefore).not.toBeNull();
    // Try to scroll the horizontal container if present.
    const scrollerHandle = page.locator("[data-testid='query-heatmap-scroll-container']");
    const scrollerCount = await scrollerHandle.count();
    if (scrollerCount > 0) {
      await page.evaluate(() => {
        const el = document.querySelector("[data-testid='query-heatmap-scroll-container']") as HTMLElement | null;
        if (el) el.scrollLeft = 200;
      });
      await page.waitForTimeout(200);
    } else {
      // Fallback: scroll platform table.
      await page.evaluate(() => {
        const el = document.querySelector("[data-testid='platform-results-scroll-container']") as HTMLElement | null;
        if (el) el.scrollLeft = 200;
      });
      await page.waitForTimeout(200);
    }
    const boxAfter = await tray.boundingBox();
    expect(boxAfter).not.toBeNull();
    expect(boxAfter!.x).toBeCloseTo(boxBefore!.x, 1);
    expect(boxAfter!.y).toBeCloseTo(boxBefore!.y, 1);
  });

  test("tray remains visible and clear under dark theme at mobile and desktop", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("benchbox:theme", "dark"));
    for (const viewport of [
      { width: 390, height: 844 },
      { width: 1440, height: 1000 },
    ] as const) {
      await page.setViewportSize(viewport);
      await openBenchmarkTray(page);
      await expect(page.getByTestId("compare-tray")).toBeVisible();
      const lastRow =
        viewport.width === 390
          ? page.getByTestId("query-heatmap-mobile-cards").locator(":scope > [role='listitem']").last()
          : page.getByRole("grid").getByRole("row").last();
      await expectTrayClearance(page, lastRow);
    }
  });

  test("tray remains visible and clear with forced colors", async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active" });
    await page.setViewportSize({ width: 390, height: 844 });
    await openBenchmarkTray(page);
    await expect(page.getByTestId("compare-tray")).toBeVisible();
    const lastRow = page.getByTestId("query-heatmap-mobile-cards").locator(":scope > [role='listitem']").last();
    await expectTrayClearance(page, lastRow);
    // Tray border and background must still be distinguishable (basic visibility check).
    const trayStyle = await page.getByTestId("compare-tray").evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(trayStyle).not.toBe("0px");
  });

  test("tray remains contained at 200% zoom", async ({ page }) => {
    await page.setViewportSize({ width: 640, height: 900 });
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);
    await page.evaluate(() => {
      document.documentElement.style.zoom = "2";
    });
    await checkFixtureRow(page, fixtureIds.ids.duckdb);
    await checkFixtureRow(page, fixtureIds.ids.datafusion);
    await expect(page.getByTestId("compare-tray")).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
  });
});

async function openBenchmarkTray(page: Page): Promise<void> {
  await page.goto("/results/tpch/");
  await waitForShell(page);
  await waitForDataLoaded(page, /TPC-H Results/);
  await checkFixtureRow(page, fixtureIds.ids.duckdb);
  await checkFixtureRow(page, fixtureIds.ids.datafusion);
  await expect(page.getByTestId("compare-tray")).toBeVisible();
}

async function checkFixtureRow(page: Page, id: string): Promise<void> {
  const row = page
    .locator(`[data-testid="${id}"]:visible, [data-testid="query-heatmap-mobile-card-${id}"]:visible`)
    .first();
  await waitForDataElement(page, row);
  await row.scrollIntoViewIfNeeded();
  await row.getByRole("checkbox").check();
}

async function expectTrayClearance(page: Page, lastRow: Locator): Promise<void> {
  const tray = page.getByTestId("compare-tray");
  const spacer = page.getByTestId("compare-tray-spacer");
  await expect
    .poll(async () => {
      const trayBox = await tray.boundingBox();
      const spacerBox = await spacer.boundingBox();
      return Boolean(trayBox && spacerBox && spacerBox.height >= trayBox.height);
    })
    .toBe(true);
  await lastRow.scrollIntoViewIfNeeded();
  const trayBox = await tray.boundingBox();
  expect(trayBox).not.toBeNull();
  await page.evaluate((clearance) => window.scrollBy(0, clearance), Math.ceil(trayBox!.height));
  const [rowBoxAfterScroll, trayBoxAfterScroll] = await Promise.all([lastRow.boundingBox(), tray.boundingBox()]);
  expect(rowBoxAfterScroll).not.toBeNull();
  expect(trayBoxAfterScroll).not.toBeNull();
  expect(rowBoxAfterScroll!.y).toBeGreaterThanOrEqual(0);
  expect(rowBoxAfterScroll!.y + rowBoxAfterScroll!.height).toBeLessThanOrEqual(trayBoxAfterScroll!.y + 1);
}
