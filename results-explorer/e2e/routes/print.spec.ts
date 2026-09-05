import { expect, test, type Page } from "@playwright/test";
import { waitForDataElement, waitForDataLoaded, waitForResultRows, waitForShell } from "../support/fixtures";

const A4_LANDSCAPE_PRINTABLE_WIDTH_PX = 1047;

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
});

async function expectVisibleTablesToFit(page: Page): Promise<void> {
  const tableGeometry = await page.locator("table:visible").evaluateAll((tables) =>
    tables.map((table) => {
      const rect = table.getBoundingClientRect();
      return {
        ariaLabel: table.getAttribute("aria-label"),
        left: rect.left,
        right: rect.right,
        viewportWidth: document.documentElement.clientWidth,
      };
    }),
  );

  expect(tableGeometry.length).toBeGreaterThan(0);
  for (const geometry of tableGeometry) {
    expect(geometry.left, geometry.ariaLabel ?? "unlabelled table left edge").toBeGreaterThanOrEqual(-1);
    expect(geometry.right, geometry.ariaLabel ?? "unlabelled table right edge").toBeLessThanOrEqual(
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
