import { expect, test, type Locator, type Page } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("tray geometry: collapsed and expanded clearance", () => {
  test.describe.configure({ mode: "serial" });

  test("collapsed mobile tray keeps last row reachable at 390x844", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openBenchmarkTray(page);
    await expect(page.getByTestId("compare-tray")).toHaveAttribute("data-collapsed", "true");
    await expect(page.getByTestId("compare-tray-details")).toBeHidden();
    await expect(page.getByTestId("compare-tray-compare-link")).toBeVisible();
    const lastRow = benchmarkListLastRow(page);
    await expectTrayClearance(page, lastRow);
  });

  test("expanded mobile tray keeps last row reachable at 390x844", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openBenchmarkTray(page);
    await page.getByTestId("compare-tray-toggle").click();
    await expect(page.getByTestId("compare-tray")).toHaveAttribute("data-collapsed", "false");
    await expect(page.getByTestId("compare-tray-details")).toBeVisible();
    const lastRow = benchmarkListLastRow(page);
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
    const compareLink = page.getByTestId("compare-tray-compare-link");
    await expect(compareLink).toBeVisible();
    await expect(compareLink).toHaveAttribute("href", /ids=/);
    await page.getByTestId("compare-tray-toggle").click();
    await expect(page.getByTestId("compare-tray-details")).toBeVisible();
  });

  test("desktop tray has no collapse toggle and stays visible at 1440x1000", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await openBenchmarkTray(page);
    await expect(page.getByTestId("compare-tray")).toHaveAttribute("data-collapsed", "false");
    const toggle = page.getByTestId("compare-tray-toggle");
    await expect(toggle).toBeHidden();
    const lastRow = benchmarkListLastRow(page);
    await expectTrayClearance(page, lastRow);
  });

  test("horizontal table scrolling does not move the tray", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await openBenchmarkTray(page);
    const tray = page.getByTestId("compare-tray");
    const scroller = page.locator("[data-testid='benchmark-list-scroll-container']");
    await expect(scroller).toBeVisible({ timeout: 10_000 }).catch(() => {});
    const boxBefore = await tray.boundingBox();
    expect(boxBefore).not.toBeNull();
    const scrollerHandle = page.locator("[data-testid='benchmark-list-scroll-container']");
    const scrollerCount = await scrollerHandle.count();
    if (scrollerCount > 0) {
      await page.evaluate(() => {
        const el = document.querySelector("[data-testid='benchmark-list-scroll-container']") as HTMLElement | null;
        if (el) el.scrollLeft = 200;
      });
      await page.waitForTimeout(200);
    } else {
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
      const lastRow = benchmarkListLastRow(page);
      await expectTrayClearance(page, lastRow);
    }
  });

  test("tray remains visible and clear with forced colors", async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active" });
    await page.setViewportSize({ width: 390, height: 844 });
    await openBenchmarkTray(page);
    await expect(page.getByTestId("compare-tray")).toBeVisible();
    const lastRow = benchmarkListLastRow(page);
    await expectTrayClearance(page, lastRow);
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
    const expectPageContained = async () => {
      const dimensions = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
    };
    await expectPageContained();
    const queriesHeader = page.locator("#benchmark-section-list").getByRole("columnheader", { name: /Queries/ });
    await queriesHeader.getByRole("button").click();
    await expect(queriesHeader).toHaveAttribute("aria-sort", "ascending");
    await expect(queriesHeader.locator(".sr-only")).toHaveText("sorted ascending");
    await expectPageContained();
    await checkFixtureRow(page, fixtureIds.ids.duckdb);
    await checkFixtureRow(page, fixtureIds.ids.datafusion);
    await expect(page.getByTestId("compare-tray")).toBeVisible();
    await expectPageContained();
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
  const row = page.locator(`#benchmark-section-list [data-testid="list-${id}"]`).first();
  await waitForDataElement(page, row);
  await row.scrollIntoViewIfNeeded();
  await row.getByRole("checkbox").check();
}

function benchmarkListLastRow(page: Page): Locator {
  return page.locator("#benchmark-section-list tbody tr[data-testid]").last();
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
