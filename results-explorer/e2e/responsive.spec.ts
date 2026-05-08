import { expect, test, type Locator, type Page } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "./support/fixtures";

const SHORT_DUCKDB = "ba6a8c83";
const SHORT_DATAFUSION = "5e6c5eba";
const DETAIL_ID = "tpch-duckdb-sf0.01-20260403-010ee756";

// Desktop/wide use maxY = viewport.height (900); mobile/tablet use 1200 (1.33x).
// PR #276 brought the live `query-results-panel.top` from 909 to 897 against
// the 900 budget — only 3px of headroom. If you add height above the grid on
// the Query workbench (intro paragraph, breadcrumb, banner) or change
// `lg:order-1` placement of `query-visible-columns`, run the responsive grep
// before merging or relax this budget. See DONE TODO
// `results-explorer-responsive-desktop-query-panel-regression` for the
// full layout accounting and rationale.
const VIEWPORTS = [
  { name: "mobile", width: 390, height: 900, maxY: 1200 },
  { name: "tablet", width: 768, height: 900, maxY: 1200 },
  { name: "desktop", width: 1280, height: 900, maxY: 900 },
  { name: "wide", width: 1600, height: 900, maxY: 900 },
] as const;

const AUDITED_ROUTES = [
  { path: "/results/", ready: /Recent Results/i },
  { path: "/results/tpch/", ready: /TPC-H Results/i },
  { path: "/results/p/duckdb/", ready: /DuckDB/i },
  { path: `/results/r/${DETAIL_ID}`, ready: /Query Timings/i },
  { path: `/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`, ready: /TPC-H Comparison/i },
  { path: "/results/query", ready: /matching result bundle/ },
] as const;

test.describe.configure({ mode: "serial" });

test.describe("responsive explorer assertions", () => {
  for (const viewport of VIEWPORTS) {
    test(`secondary nav exposes every Explorer route at ${viewport.name}`, async ({ page }) => {
      await setViewport(page, viewport);
      await page.goto("/results/query");
      await waitForShell(page);

      const nav = page.getByTestId("results-explorer-nav");
      for (const label of ["Leaderboards", "Benchmarks", "Platforms", "Compare", "Query"]) {
        await expect(nav.getByRole("link", { name: label })).toBeVisible();
      }
      await expect(nav.getByRole("link", { name: "Query" })).toHaveAttribute("aria-current", "page");
    });

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

      if (viewport.width >= 1280) {
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

      if (viewport.width <= 768) {
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

  for (const viewport of VIEWPORTS.filter((item) => item.width <= 768)) {
    test(`audited routes avoid document overflow at ${viewport.name}`, async ({ page }) => {
      await setViewport(page, viewport);
      for (const route of AUDITED_ROUTES) {
        await page.goto(route.path);
        await waitForDataLoaded(page, route.ready);
        await expectNoDocumentOverflow(page, route.path);
      }
    });

    test(`mobile table affordances remain visible at ${viewport.name}`, async ({ page }) => {
      await setViewport(page, viewport);

      await page.goto("/results/");
      await waitForDataLoaded(page, /Recent Results/i);
      await expect(page.getByTestId("recent-results-scroll-hint")).toBeVisible();

      await page.goto(`/results/r/${DETAIL_ID}`);
      await waitForDataLoaded(page, /Query Timings/i);
      await expect(page.getByTestId("detail-timings-scroll-hint")).toBeVisible();

      await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
      await waitForDataLoaded(page, /TPC-H Comparison/i);
      await expect(page.getByTestId("query-diff-scroll-hint")).toBeVisible();

      await page.goto("/results/query");
      await waitForDataLoaded(page, /matching result bundle/);
      await expect(page.getByTestId("query-results-scroll-hint")).toBeVisible();
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

async function expectNoDocumentOverflow(page: Page, label: string) {
  const offenders = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    return Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .filter((element) => {
        if (element.closest(".overflow-x-auto") || element.closest("svg[role='img']")) return false;
        const rect = element.getBoundingClientRect();
        return rect.right > viewportWidth + 1 || rect.left < -1;
      })
      .map((element) => ({
        tag: element.tagName,
        text: (element.textContent ?? "").trim().slice(0, 80),
        className: element.className,
      }))
      .slice(0, 5);
  });
  expect(offenders, `${label} should not leak content outside intentional scroll containers`).toEqual([]);
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
