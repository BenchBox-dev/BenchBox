import { expect, test, type Page } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForDataLoaded, waitForResultRows, waitForShell } from "../support/fixtures";

const A4_LANDSCAPE_PRINTABLE_WIDTH_PX = 1047;
const TPCH_DUCKDB_ID = fixtureIds.ids.duckdb;
const TPCH_DUCKDB_SHORT_ID = fixtureIds.shortIds.duckdb;
const TPCH_DATAFUSION_SHORT_ID = fixtureIds.shortIds.datafusion;

test.describe("print rendering", () => {
  test("prints the benchmark matrix without chrome or horizontal clipping", async ({ page }) => {
    await page.setViewportSize({ width: A4_LANDSCAPE_PRINTABLE_WIDTH_PX, height: 760 });
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);
    await waitForResultRows(page, page.getByRole("grid"));

    await page.emulateMedia({ media: "print" });

    await expect(page.getByTestId("benchbox-global-header")).toBeHidden();
    await expect(page.getByTestId("results-explorer-nav")).toBeHidden();
    await expect(page.getByTestId("query-heatmap-page-sticky-header-shell")).toBeHidden();
    await expectVisibleTablesToFit(page);
    await expectRenderedPdf(page);
  });

  test("prints Query in a light palette without facets, controls, or clipped tables", async ({ page }) => {
    await page.setViewportSize({ width: A4_LANDSCAPE_PRINTABLE_WIDTH_PX, height: 760 });
    await page.addInitScript(() => localStorage.setItem("benchbox:theme", "dark"));
    await page.goto("/results/query");
    await waitForShell(page);
    await waitForDataLoaded(page, /Find benchmark runs/);
    await waitForDataElement(page, page.getByTestId("query-results-panel").locator("tbody tr").first());

    await page.emulateMedia({ media: "print" });

    await expect(page.getByLabel("Result facets", { exact: true })).toBeHidden();
    await expect(page.getByTestId("query-mobile-filter-drawer")).toBeHidden();
    await expect(page.getByRole("button", { name: /Download CSV/ })).toBeHidden();
    await expect(page.getByTestId("query-results-panel").locator("table").first()).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme))
      .toBe("light");
    await expectVisibleTablesToFit(page);
    await expectRenderedPdf(page);
  });

  test("prints Compare with its evidence tables inside the page", async ({ page }) => {
    await page.setViewportSize({ width: A4_LANDSCAPE_PRINTABLE_WIDTH_PX, height: 760 });
    await page.goto(`/results/compare?ids=${TPCH_DUCKDB_SHORT_ID},${TPCH_DATAFUSION_SHORT_ID}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison/);
    await expect(page.getByRole("heading", { name: "Query-level differences" })).toBeVisible();

    await page.emulateMedia({ media: "print" });

    await expect(page.getByTestId("benchbox-global-header")).toBeHidden();
    await expectVisibleTablesToFit(page);
    await expectRenderedPdf(page);
  });

  test("prints Result detail with its receipt and query timings", async ({ page }) => {
    await page.setViewportSize({ width: A4_LANDSCAPE_PRINTABLE_WIDTH_PX, height: 760 });
    await page.goto(`/results/r/${TPCH_DUCKDB_ID}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /Query timings/);

    await page.emulateMedia({ media: "print" });

    await expect(page.getByRole("region", { name: "Run receipt" })).toBeVisible();
    await expectVisibleTablesToFit(page);
    await expectRenderedPdf(page);
  });

  test("prints a within-run measurement comparison without clipping", async ({ page }) => {
    await page.setViewportSize({ width: A4_LANDSCAPE_PRINTABLE_WIDTH_PX, height: 760 });
    await page.goto(`/results/r/${TPCH_DUCKDB_ID}/passes`);
    await waitForShell(page);
    await waitForDataLoaded(page, /Compare measurements from one DuckDB run/);

    await page.emulateMedia({ media: "print" });

    await expectVisibleTablesToFit(page);
    await expectRenderedPdf(page);
  });
});

async function expectVisibleTablesToFit(page: Page): Promise<void> {
  const tableGeometry = await page.locator("table:visible").evaluateAll((tables) =>
    tables.map((table) => {
      const rect = table.getBoundingClientRect();
      return {
        ariaLabel: table.getAttribute("aria-label"),
        className: table.getAttribute("class"),
        left: rect.left,
        right: rect.right,
        viewportWidth: document.documentElement.clientWidth,
      };
    }),
  );

  expect(tableGeometry.length).toBeGreaterThan(0);
  for (const geometry of tableGeometry) {
    const tableName = geometry.ariaLabel ?? geometry.className ?? "unlabelled table";
    expect(geometry.left, `${tableName} left edge`).toBeGreaterThanOrEqual(-1);
    expect(geometry.right, `${tableName} right edge`).toBeLessThanOrEqual(
      geometry.viewportWidth + 1,
    );
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth + 1),
  );
}

async function expectRenderedPdf(page: Page): Promise<void> {
  const pdf = await page.pdf({ preferCSSPageSize: true, printBackground: true });
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  expect(pdf.byteLength).toBeGreaterThan(10_000);
}
