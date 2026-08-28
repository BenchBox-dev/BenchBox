import { expect, test, type Locator, type Page } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForDataLoaded, waitForResultRows, waitForShell } from "../support/fixtures";

const INSETS = { top: 47, right: 44, bottom: 34, left: 44 } as const;
const ORIENTATIONS = [
  { name: "portrait", width: 430, height: 932 },
  { name: "landscape", width: 932, height: 430 },
] as const;

const ROUTES = [
  "/results/",
  "/results/benchmarks/",
  "/results/platforms/",
  "/results/tpch/",
  "/results/p/duckdb/",
  "/results/query",
] as const;

test.describe("safe area layout", () => {
  test.describe.configure({ mode: "serial" });

  for (const orientation of ORIENTATIONS) {
    test(`every route clears simulated insets in ${orientation.name}`, async ({ page }) => {
      await page.setViewportSize(orientation);
      const fixtureRoutes = [
        ...ROUTES,
        `/results/r/${fixtureIds.ids.duckdb}`,
        `/results/compare?ids=${fixtureIds.ids.duckdb},${fixtureIds.ids.datafusion}`,
        "/results/not/a-route/",
      ];

      for (const route of fixtureRoutes) {
        await page.goto(route);
        await waitForShell(page);
        await installSimulatedInsets(page);
        await expectShellToClearInsets(page);
      }
    });
  }

  test("facet rail and wide tables clear simulated landscape insets", async ({ page }) => {
    await page.setViewportSize({ width: 1180, height: 820 });
    await page.goto("/results/query");
    await waitForShell(page);
    await installSimulatedInsets(page);
    await waitForDataLoaded(page, /Results Query Workbench/);
    await waitForDataElement(page, page.getByTestId("query-results-panel").locator("tbody tr").first());

    await expectInsideHorizontalInsets(page, page.getByTestId("query-desktop-filters"));
    await expectInsideHorizontalInsets(page, page.getByTestId("query-results-panel"));

    await page.goto("/results/tpch/");
    await installSimulatedInsets(page);
    await waitForDataLoaded(page, /TPC-H Results/);
    await waitForResultRows(page, page.getByRole("grid"));
    await expectInsideHorizontalInsets(page, page.getByTestId("query-heatmap-scroll-container"));
  });

  for (const orientation of ORIENTATIONS) {
    test(`compare tray content clears simulated insets in ${orientation.name}`, async ({ page }) => {
      await page.setViewportSize(orientation);
      await page.goto("/results/tpch/");
      await waitForShell(page);
      await installSimulatedInsets(page);
      await waitForDataLoaded(page, /TPC-H Results/);
      for (const id of [fixtureIds.ids.duckdb, fixtureIds.ids.datafusion]) {
        const row = page
          .locator(`[data-testid="${id}"]:visible, [data-testid="query-heatmap-mobile-card-${id}"]:visible`)
          .first();
        await waitForDataElement(page, row);
        await row.getByRole("checkbox").check();
      }

      const tray = page.getByTestId("compare-tray");
      await expect(tray).toBeVisible();
      await expectInsideHorizontalInsets(page, tray.locator(":scope > div"));
      await expect
        .poll(() => tray.evaluate((element) => Number.parseFloat(getComputedStyle(element).paddingBottom)))
        .toBeGreaterThanOrEqual(INSETS.bottom);
    });
  }

  test("mobile facet dialog controls clear simulated portrait insets", async ({ page }) => {
    await page.setViewportSize(ORIENTATIONS[0]);
    await page.goto("/results/query");
    await waitForShell(page);
    await installSimulatedInsets(page);
    await page.getByRole("button", { name: /Filters/ }).click();

    const dialog = page.getByRole("dialog", { name: "Filter results" });
    await expect(dialog).toBeVisible();
    const closeButton = dialog.getByRole("button", { name: "Done" });
    await expectInsideHorizontalInsets(page, closeButton);
    const closeBox = await closeButton.boundingBox();
    expect(closeBox).not.toBeNull();
    expect(closeBox!.y).toBeGreaterThanOrEqual(INSETS.top - 1);
  });

  test("conventional desktop keeps zero safe-area padding", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/results/");
    await waitForShell(page);

    const shellPadding = await page.getByTestId("app-shell").evaluate((element) => {
      const style = getComputedStyle(element);
      return [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft];
    });
    expect(shellPadding).toEqual(["0px", "0px", "0px", "0px"]);
    const header = await page.getByTestId("benchbox-global-header").boundingBox();
    expect(header).not.toBeNull();
    expect(header!.x).toBe(0);
    expect(header!.width).toBe(1440);
  });
});

async function installSimulatedInsets(page: Page): Promise<void> {
  await page.evaluate((insets) => {
    const root = document.documentElement;
    root.style.setProperty("--bb-inset-top", `${insets.top}px`);
    root.style.setProperty("--bb-inset-right", `${insets.right}px`);
    root.style.setProperty("--bb-inset-bottom", `${insets.bottom}px`);
    root.style.setProperty("--bb-inset-left", `${insets.left}px`);
  }, INSETS);
}

async function expectShellToClearInsets(page: Page): Promise<void> {
  const shell = page.getByTestId("app-shell");
  const padding = await shell.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      top: Number.parseFloat(style.paddingTop),
      right: Number.parseFloat(style.paddingRight),
      bottom: Number.parseFloat(style.paddingBottom),
      left: Number.parseFloat(style.paddingLeft),
    };
  });
  expect(padding).toEqual(INSETS);

  const header = page.getByTestId("benchbox-global-header");
  const subNav = page.getByTestId("results-explorer-nav");
  await expectInsideHorizontalInsets(page, header);
  await expectInsideHorizontalInsets(page, subNav);
  await expectInsideHorizontalInsets(page, page.locator("main"));
  await expectInsideHorizontalInsets(page, page.locator("footer"));

  const headerBox = await header.boundingBox();
  expect(headerBox).not.toBeNull();
  expect(headerBox!.y).toBeGreaterThanOrEqual(INSETS.top);
  expect(await header.evaluate((element) => Number.parseFloat(getComputedStyle(element).top))).toBeGreaterThanOrEqual(
    INSETS.top,
  );
}

async function expectInsideHorizontalInsets(page: Page, locator: Locator): Promise<void> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(INSETS.left - 1);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width - INSETS.right + 1);
}
