import { expect, test, type Locator, type Page } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForDataLoaded, waitForShell } from "../support/fixtures";

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
] as const;

test.describe("compare tray clearance and print suppression", () => {
  test.describe.configure({ mode: "serial" });

  for (const viewport of VIEWPORTS) {
    test(`benchmark tray clearance keeps the last result row reachable at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openBenchmarkTray(page);
      const lastResult =
        viewport.name === "mobile"
          ? page.getByTestId("query-heatmap-mobile-cards").locator(":scope > [role='listitem']").last()
          : page.getByRole("grid").getByRole("row").last();
      await expectTrayClearance(page, lastResult);
    });

    test(`platform tray clearance keeps the last result row reachable at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openPlatformTray(page);
      await expectTrayClearance(page, page.locator('[data-testid="platform-results-scroll-container"] tbody tr').last());
    });
  }

  test("benchmark tray is absent from print media", async ({ page }) => {
    await openBenchmarkTray(page);
    await expectTraySuppressedForPrint(page);
  });

  test("platform tray is absent from print media", async ({ page }) => {
    await openPlatformTray(page);
    await expectTraySuppressedForPrint(page);
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

async function openPlatformTray(page: Page): Promise<void> {
  await page.goto("/results/p/duckdb/");
  await waitForShell(page);
  await waitForDataLoaded(page, /DuckDB Results/);
  await checkFixtureRow(page, fixtureIds.ids.duckdb);
  await checkFixtureRow(page, fixtureIds.ids.duckdbTuned);
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

async function expectTraySuppressedForPrint(page: Page): Promise<void> {
  await page.emulateMedia({ media: "print" });
  await expect(page.getByTestId("compare-tray")).toBeHidden();
  await expect(page.getByTestId("compare-tray-spacer")).toBeHidden();
}
