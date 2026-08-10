import { expect, test, type Page } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForDataLoaded, waitForShell } from "../support/fixtures";

const SHORT_DUCKDB = fixtureIds.shortIds.duckdb;
const SHORT_DATAFUSION = fixtureIds.shortIds.datafusion;
const SHORT_DUCKDB_TUNED = fixtureIds.shortIds.duckdbTuned;

async function visibleRowCount(page: Page): Promise<number> {
  return page.locator("main table tbody tr[data-testid]").count();
}

async function expectNoFalsePlatformEmpty(page: Page) {
  await expect(page.getByText(/No results found for platform/i)).not.toBeVisible();
}

test.describe("direct route parity", () => {
  test.describe.configure({ mode: "serial" });

  test("direct route hard-loads platform pages with canonical headings and stable row counts", async ({ page }) => {
    await page.goto("/results/p/polars/");
    await waitForShell(page);
    await waitForDataElement(page, page.getByRole("heading", { name: /^Polars Results$/ }));
    await expect(page.locator("main table tbody tr[data-testid]")).toHaveCount(1);
    await expectNoFalsePlatformEmpty(page);

    await page.reload();
    await waitForDataElement(page, page.getByRole("heading", { name: /^Polars Results$/ }));
    await expect(page.locator("main table tbody tr[data-testid]")).toHaveCount(1);
    await expectNoFalsePlatformEmpty(page);

    await page.goto("/results/p/duckdb/");
    await waitForDataElement(page, page.getByRole("heading", { name: /^DuckDB Results$/ }));
    await expect(page.locator("main table tbody tr[data-testid]")).toHaveCount(5);
    await expectNoFalsePlatformEmpty(page);
  });

  test("direct route platform pages match the in-app platform switcher", async ({ page }) => {
    await page.goto("/results/p/polars/");
    await waitForShell(page);
    await waitForDataElement(page, page.getByRole("heading", { name: /^Polars Results$/ }));
    const directPolarsRows = await visibleRowCount(page);

    await page.goto("/results/p/duckdb/");
    await waitForDataElement(page, page.getByRole("heading", { name: /^DuckDB Results$/ }));
    await page.getByTestId("platform-switcher").selectOption("polars");
    await expect(page).toHaveURL(/\/results\/p\/polars\//);
    await waitForDataElement(page, page.getByRole("heading", { name: /^Polars Results$/ }));
    await expect(page.locator("main table tbody tr[data-testid]")).toHaveCount(directPolarsRows);
    await expectNoFalsePlatformEmpty(page);
  });

  test("direct route hard-loads benchmark, query, and compare entrypoints", async ({ page }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await expect(page).toHaveURL(/\/results\/tpch\/\?phase=standard$/);
    await waitForDataElement(page, page.getByRole("heading", { name: /^TPC-H Results$/ }));

    await page.goto("/results/query");
    await waitForDataElement(page, page.getByRole("heading", { name: /^Results Query Workbench$/ }));

    await page.goto("/results/compare");
    await waitForDataElement(page, page.getByRole("heading", { name: /^Pick runs to compare$/ }));
  });

  test("flywheel documentation CTAs use real native navigation", async ({ page }) => {
    await page.route("**/docs/**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<!doctype html><title>BenchBox docs</title><h1>Documentation route</h1>",
      });
    });
    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);

    await page.getByRole("link", { name: "Run a benchmark" }).click();
    await expect(page).toHaveURL(/\/docs\/usage\/installation\.html$/);
    await expect(page.getByRole("heading", { name: "Documentation route" })).toBeVisible();

    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);
    await page.getByRole("link", { name: "Submit a bundle" }).click();
    await expect(page).toHaveURL(/\/docs\/contributing-results\.html$/);
    await expect(page.getByRole("heading", { name: "Documentation route" })).toBeVisible();
  });

  test("direct route compare warning copy uses singular and plural labels", async ({ page }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);
    await waitForDataElement(page, page.getByRole("heading", { name: /^TPC-H Comparison$/ }));
    const guardrails = page.getByRole("region", { name: "Compare guardrails" });
    const receipt = page.getByRole("region", { name: "Comparability receipt" });
    await expect(guardrails).toContainText("1 warning");
    await expect(guardrails).not.toContainText("1 warnings");
    await expect(receipt).toContainText("1 warning");
    await expect(receipt).not.toContainText("1 warnings");

    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DUCKDB_TUNED},${SHORT_DATAFUSION}`);
    await waitForDataElement(page, page.getByRole("heading", { name: /^TPC-H Comparison$/ }));
    await expect(guardrails).toContainText("2 warnings");
    await expect(receipt).toContainText("2 warnings");
    await expect(guardrails).not.toContainText(/coverage\.\./i);
  });
});

test.describe("assembled GitHub Pages artifact", () => {
  test.skip(
    !process.env.E2E_SITE_DIR,
    "Set E2E_SITE_DIR to the workflow-produced site directory for Pages-shaped acceptance.",
  );

  test("preserves direct routes through root 404 fallback and native docs links", async ({ page }) => {
    const directRouteStatuses: number[] = [];
    const docsStatuses: number[] = [];
    page.on("response", (response) => {
      const pathname = new URL(response.url()).pathname;
      if (pathname === "/results/p/polars/") directRouteStatuses.push(response.status());
      if (pathname === "/docs/usage/installation.html") docsStatuses.push(response.status());
    });

    const fallback = await page.request.get("/404.html");
    expect(fallback.status()).toBe(200);
    expect(await fallback.text()).toContain("benchbox.results.redirect");

    await page.goto("/results/p/polars/");
    await waitForShell(page);
    await waitForDataElement(page, page.getByRole("heading", { name: /^Polars Results$/ }));
    await expect(page).toHaveURL(/\/results\/p\/polars\/$/);
    expect(directRouteStatuses).toContain(404);
    await expect(page.locator("main table tbody tr[data-testid]")).toHaveCount(1);
    await expectNoFalsePlatformEmpty(page);

    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);
    await page.getByRole("link", { name: "Run a benchmark" }).click();
    await expect(page).toHaveURL(/\/docs\/usage\/installation\.html$/);
    expect(docsStatuses).toContain(200);
  });
});
