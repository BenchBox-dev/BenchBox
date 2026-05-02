import { expect, test, type Locator, type Page } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "./support/fixtures";

const SHORT_DUCKDB = "a556e716";
const SHORT_DATAFUSION = "4af35f65";

const VIEWPORTS = [
  { name: "mobile", width: 390, height: 900, maxY: 1200 },
  { name: "desktop", width: 1440, height: 900, maxY: 800 },
] as const;

test.describe.configure({ mode: "serial" });

test.describe("responsive explorer assertions", () => {
  for (const viewport of VIEWPORTS) {
    test(`home keeps headline, cohort summary, and leaderboard rows high in the viewport at ${viewport.name}`, async ({
      page,
    }) => {
      await setViewport(page, viewport);
      await page.goto("/results/");
      await waitForDataLoaded(page, /Recent Results/i);

      await expectTopWithin(
        page.getByRole("heading", { name: "BenchBox Database Leaderboards" }),
        viewport.maxY,
        "home headline",
      );
      await expectTopWithin(
        page.getByRole("region", { name: "Active leaderboard filters" }),
        viewport.maxY,
        "active leaderboard summary",
      );

      const leaderboard = page.getByRole("grid", { name: "Cross-benchmark leaderboard" });
      const firstRow = leaderboard.locator("tbody tr").first();
      await expect(firstRow).toBeVisible({ timeout: 20_000 });
      await expectTopWithin(firstRow, viewport.maxY, "first leaderboard row");

      if (viewport.name === "desktop") {
        const rowCount = await leaderboard.locator("tbody tr").count();
        const aboveFold = await rowsAboveFold(leaderboard.locator("tbody tr"), viewport.height);
        // The browser fixture corpus currently has fewer than 8 meta-platforms,
        // so assert all available rows stay above the fold and preserve the 8-row
        // density target automatically when the fixture corpus grows.
        expect(aboveFold).toBeGreaterThanOrEqual(Math.min(8, rowCount));
      }
    });

    test(`benchmark heatmap exposes overflow affordance when needed at ${viewport.name}`, async ({ page }) => {
      await setViewport(page, viewport);
      await page.goto("/results/star_schema/?phase=standard");
      await waitForShell(page);
      await expect(page.getByRole("heading", { name: /SSB Results/i })).toBeVisible({
        timeout: 20_000,
      });

      const heatmap = page.getByTestId("query-heatmap-scroll-container").first();
      await expect(heatmap).toBeAttached();
      const hasHorizontalOverflow = await heatmap.evaluate((element) => element.scrollWidth > element.clientWidth);
      if (hasHorizontalOverflow) {
        await expect(page.getByTestId("query-heatmap-scroll-hint")).toBeVisible();
      }
    });

    test(`query workbench renders summary, active filters, and rows before deep controls at ${viewport.name}`, async ({
      page,
    }) => {
      await setViewport(page, viewport);
      await page.goto("/results/query");
      await waitForDataLoaded(page, /matching result bundle/);

      await expectTopWithin(
        page.getByRole("heading", { name: "Results Query Workbench" }),
        viewport.maxY,
        "query headline",
      );
      await expectTopWithin(page.getByTestId("query-result-summary"), viewport.maxY, "query result summary");
      await expectTopWithin(page.getByTestId("query-results-panel"), viewport.maxY, "query results panel");

      const drawerTrigger = page.locator('[data-testid="query-mobile-filter-drawer"] button[data-result-count]').first();
      await expect(drawerTrigger).toHaveAttribute("data-result-count", /\d+/);

      if (viewport.name === "mobile") {
        const resultPanelY = await topOf(page.getByTestId("query-results-panel"));
        const visibleColumnsY = await topOf(page.getByTestId("query-visible-columns"));
        expect(resultPanelY).toBeLessThan(visibleColumnsY);
      }
    });

    test(`compare route keeps decision summary and query evidence reachable at ${viewport.name}`, async ({ page }) => {
      await setViewport(page, viewport);
      await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
      await waitForDataLoaded(page, /TPC-H Comparison/);

      await expectTopWithin(page.getByRole("heading", { name: /TPC-H Comparison/ }), viewport.maxY, "compare headline");
      const decisionSummary = page.getByRole("region", { name: "Decision Summary" });
      const queryEvidence = page.getByRole("heading", { name: "Query-Level Diff" });
      await expect(decisionSummary).toBeVisible();
      await expect(queryEvidence).toBeVisible();
      expect(await topOf(decisionSummary)).toBeLessThan(await topOf(queryEvidence));
    });
  }
});

async function setViewport(
  page: Page,
  viewport: (typeof VIEWPORTS)[number],
) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
}

async function topOf(locator: Locator): Promise<number> {
  await expect(locator).toBeAttached();
  const box = await locator.boundingBox();
  expect(box, `expected ${locator} to have a bounding box`).not.toBeNull();
  return box!.y;
}

async function expectTopWithin(locator: Locator, maxY: number, label: string) {
  await expect(locator).toBeVisible({ timeout: 20_000 });
  expect(await topOf(locator), `${label} top should be within ${maxY}px`).toBeLessThanOrEqual(maxY);
}

async function rowsAboveFold(rows: Locator, viewportHeight: number): Promise<number> {
  return rows.evaluateAll((elements, height) =>
    elements.filter((element) => {
      const rect = element.getBoundingClientRect();
      return rect.top >= 0 && rect.top < height;
    }).length,
    viewportHeight,
  );
}
