import { expect, test, type Locator, type Page } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

const DUCKDB = {
  id: "tpch-duckdb-sf0.01-20260403-010ee756",
  shortId: "ba6a8c83",
};
const DUCKDB_TUNED = {
  id: "tpch-duckdb-sf0.01-20260403-a5eff54e",
  shortId: "009ee9fd",
};
const DATAFUSION = {
  id: "tpch-datafusion-sf0.01-20260403-a6bb8a70",
  shortId: "5e6c5eba",
};
type FixtureRun = typeof DUCKDB;

test.describe("compare entrypoint happy paths", () => {
  test.describe.configure({ mode: "serial" });

  test("compare entrypoint: benchmark detail selection completes a comparison", async ({ page }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);

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
    await waitForDataLoaded(page, /matching result bundle/);

    await facetCheckbox(page, "Benchmark", "TPC-H").check();
    await expect(page.getByTestId("query-result-summary")).toContainText("10 matching result bundle");
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
    await waitForDataLoaded(page, /Query Timings/);

    await page.getByRole("link", { name: /Compare this result/i }).click();
    await expect(page.getByTestId("compare-builder")).toBeVisible({ timeout: 20_000 });

    const pinnedRow = page.getByTestId(`compare-builder-row-${DUCKDB.id}`);
    await expect(pinnedRow).toContainText("(from result detail)");
    await expect(page.getByTestId("compare-builder-status")).toContainText("1 selected");

    const filters = page.getByRole("region", { name: "Filters" });
    await filters.getByLabel("Scale").selectOption("0.1");
    await expect(pinnedRow).toBeVisible();
    await expect(pinnedRow).toContainText("selected outside filters");
    await filters.getByLabel("Scale").selectOption("");

    await checkRow(page.getByTestId(`compare-builder-row-${DATAFUSION.id}`));
    await expect(page.getByTestId("compare-builder-launch")).toBeEnabled();
    await page.getByTestId("compare-builder-launch").click();

    await expectCompletedComparison(page, [DUCKDB, DATAFUSION]);
  });

  test("compare entrypoint: empty Compare builder can start and complete a comparison", async ({ page }) => {
    await page.goto("/results/compare");
    await waitForShell(page);
    await expect(page.getByTestId("compare-builder")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("You never need to edit the URL.")).toBeVisible();

    const filters = page.getByRole("region", { name: "Filters" });
    await filters.getByLabel("Benchmark").selectOption("tpch");
    await filters.getByLabel("Scale").selectOption("0.01");
    await filters.getByLabel("Phase").selectOption("standard");

    await checkRow(page.getByTestId(`compare-builder-row-${DUCKDB.id}`));
    await checkRow(page.getByTestId(`compare-builder-row-${DATAFUSION.id}`));
    await expect(page.getByTestId("compare-builder-launch")).toBeEnabled();
    await page.getByTestId("compare-builder-launch").click();

    await expectCompletedComparison(page, [DUCKDB, DATAFUSION]);
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

  const ids = new URL(page.url()).searchParams.get("ids")?.split(",") ?? [];
  expect([...ids].sort()).toEqual(runs.map((run) => run.shortId).sort());

  const breadcrumb = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(breadcrumb).toContainText("TPC-H");
  await expect(breadcrumb).toContainText("Compare");

  const main = page.getByRole("main");
  for (const run of runs) {
    await expect(main.locator(`a[href="/results/r/${run.id}"]`).first()).toBeVisible();
  }
  await expect(main.getByRole("heading", { name: "Decision Summary" })).toBeVisible();
  await expect(main.getByRole("heading", { name: "Charts" })).toBeVisible();
  await expect(main.getByRole("region", { name: "Comparability receipt" })).toBeVisible();
  await expect(main.getByRole("button", { name: /Share URL/ })).toBeVisible();

  if (options.reload) {
    await page.reload();
    await waitForDataLoaded(page, /TPC-H Comparison/);
    await expect(main.getByRole("heading", { name: "Decision Summary" })).toBeVisible();
    await expect(main.getByRole("region", { name: "Comparability receipt" })).toBeVisible();
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
