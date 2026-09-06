import { expect, test, type Locator, type Page } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForDataLoaded, waitForShell } from "../support/fixtures";

const DUCKDB = {
  id: fixtureIds.ids.duckdb,
  shortId: fixtureIds.shortIds.duckdb,
};
const DUCKDB_TUNED = {
  id: fixtureIds.ids.duckdbTuned,
  shortId: fixtureIds.shortIds.duckdbTuned,
};
const DATAFUSION = {
  id: fixtureIds.ids.datafusion,
  shortId: fixtureIds.shortIds.datafusion,
};
type FixtureRun = typeof DUCKDB;

test.describe("compare entrypoint happy paths", () => {
  test.describe.configure({ mode: "serial" });

  test("compare entrypoint: benchmark detail selection completes a comparison", async ({ page }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);
    // The heading renders from the shell, so it can be visible while the
    // keyed row query has answered with zero rows. Wait on a row itself
    // before interacting with it.
    await waitForDataElement(page, page.getByTestId(DUCKDB.id));

    await checkRow(page.getByTestId(DUCKDB.id));
    await checkRow(page.getByTestId(DATAFUSION.id));

    const compareLink = page.getByRole("link", { name: /Compare 2 selected/ });
    await expect(compareLink).toBeVisible();
    await compareLink.click();

    await expectCompletedComparison(page, [DUCKDB, DATAFUSION]);
  });

  test("compare entrypoint: platform detail selection completes a comparison", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /^DuckDB Results$/ })).toBeVisible({ timeout: 20_000 });

    await checkRow(page.getByTestId(DUCKDB.id));
    await expect(page.getByTestId("platform-compare-guidance")).toContainText("1 result selected");

    await checkRow(page.getByTestId(DUCKDB_TUNED.id));
    const compareLink = page.getByRole("link", { name: /Compare 2 selected/ });
    await expect(compareLink).toBeVisible();
    await compareLink.click();

    await expectCompletedComparison(page, [DUCKDB, DUCKDB_TUNED]);
  });

  test("compare entrypoint: Query Workbench selection completes a comparison", async ({ page }) => {
    await page.goto("/results/query");
    await waitForShell(page);
    await waitForDataLoaded(page, /matching run/);

    await facetCheckbox(page, "Benchmark", "TPC-H").check();
    // The additive zero-timing ResultDetail fixture is a TPC-H bundle too.
    await expect(page.getByTestId("query-result-summary")).toContainText("11 matching run");
    await expect(page.getByRole("button", { name: /Download CSV/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Download JSON/ })).toBeVisible();

    await page.getByTestId(`query-compare-checkbox-${DUCKDB.id}`).check();
    await page.getByTestId(`query-compare-checkbox-${DATAFUSION.id}`).check();

    const compareLink = page.getByTestId("query-compare-launch");
    await expect(compareLink).toBeVisible();
    await compareLink.click();

    await expectCompletedComparison(page, [DUCKDB, DATAFUSION], { reload: true });
  });

  test("compare entrypoint: result detail pinned run can add a compatible second row", async ({ page }) => {
    await page.goto(`/results/r/${DUCKDB.id}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /Query timings/);

    await page.getByRole("link", { name: "Find a run to compare" }).click();
    await waitForShell(page);
    await waitForDataLoaded(page, /matching run/);
    await expect(page).toHaveURL(new RegExp(`/results/query\\?pick=${encodeURIComponent(DUCKDB.id)}`));
    await expect(page.getByTestId(`query-compare-checkbox-${DUCKDB.id}`)).toBeChecked();
    await facetCheckbox(page, "Benchmark", "TPC-H").check();
    await page.getByTestId(`query-compare-checkbox-${DATAFUSION.id}`).check();
    await page.getByTestId("query-compare-launch").click();
    await expectCompletedComparison(page, [DUCKDB, DATAFUSION]);
  });

  test("compare entrypoint: empty Compare page can start and complete a comparison", async ({ page }) => {
    await page.goto("/results/compare");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: "Choose runs to compare" })).toBeVisible({ timeout: 20_000 });
    await page.getByTestId("compare-picker-query-link").click();
    await waitForShell(page);
    await waitForDataLoaded(page, /matching run/);
    await facetCheckbox(page, "Benchmark", "TPC-H").check();
    await page.getByTestId(`query-compare-checkbox-${DUCKDB.id}`).check();
    await page.getByTestId(`query-compare-checkbox-${DATAFUSION.id}`).check();
    const link = page.getByTestId("query-compare-launch");
    await expect(link).toBeVisible();
    await link.click();
    await expectCompletedComparison(page, [DUCKDB, DATAFUSION], { reload: true });
  });
});

async function checkRow(row: Locator): Promise<void> {
  await row.scrollIntoViewIfNeeded();
  await expect(row).toBeVisible();
  await row.getByRole("checkbox").check();
}

async function expectCompletedComparison(
  page: Page,
  runs: readonly FixtureRun[],
  options: { reload?: boolean } = {},
): Promise<void> {
  await expect(page).toHaveURL(/\/results\/compare\?ids=/, { timeout: 20_000 });
  await waitForDataLoaded(page, /TPC-H Comparison/);

  const expectedIds = runs.map((run) => run.shortId).sort();
  await expect
    .poll(() => (new URL(page.url()).searchParams.get("ids")?.split(",") ?? []).sort(), { timeout: 15_000 })
    .toEqual(expectedIds);

  const breadcrumb = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(breadcrumb).toContainText("TPC-H");
  await expect(breadcrumb).toContainText("Compare");

  const main = page.getByRole("main");
  for (const run of runs) {
    await expect(main.locator(`a[href="/results/r/${run.id}"]`).first()).toBeVisible();
  }
  await expect(main.getByRole("heading", { name: "Comparison summary" })).toBeVisible();
  await expect(main.getByRole("heading", { name: "Charts" })).toBeVisible();
  await expect(main.getByRole("region", { name: "Comparison checks" })).toBeVisible();
  await expect(main.getByRole("button", { name: /Share URL/ })).toBeVisible();

  if (options.reload) {
    await page.reload();
    await waitForDataLoaded(page, /TPC-H Comparison/);
    await expect(main.getByRole("heading", { name: "Comparison summary" })).toBeVisible();
    await expect(main.getByRole("region", { name: "Comparison checks" })).toBeVisible();
  }
}

function facetSection(page: Page, label: string): Locator {
  return page
    .getByTestId("query-desktop-filters")
    .getByRole("heading", { name: label, exact: true })
    .locator("xpath=ancestor::section[1]");
}

function facetCheckbox(page: Page, sectionLabel: string, optionValue: string): Locator {
  return facetSection(page, sectionLabel).getByRole("checkbox", {
    name: new RegExp(`^${escapeRegExp(sectionLabel)}:\\s+${escapeRegExp(optionValue)}\\b`, "i"),
  });
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
