import { expect, test, type Locator, type Page } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForShell } from "../support/fixtures";

const SAME_VERSION_RUNS = [fixtureIds.ids.duckdb, fixtureIds.ids.duckdbTuned] as const;

test.describe("run identity in index tables", () => {
  test("run identity: same-version runs have distinguishable benchmark and platform index labels", async ({ page }) => {
    await page.goto("/results/tpch/?view=list");
    await waitForShell(page);
    await waitForDataElement(page, page.getByTestId(SAME_VERSION_RUNS[0]));

    const benchmarkLabels = await labelsForRows(page, SAME_VERSION_RUNS);
    expectDistinctSameVersionLabels(benchmarkLabels);

    await page.goto("/results/p/duckdb/");
    await waitForDataElement(page, page.getByTestId(SAME_VERSION_RUNS[0]));

    const platformLabels = await labelsForRows(page, SAME_VERSION_RUNS);
    expectDistinctSameVersionLabels(platformLabels);
  });

  test("run identity: ranking eligibility marker has an inline legend", async ({ page }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataElement(page, page.locator('[data-testid^="heatmap-compliance-marker-"]').first());

    await expect(page.getByTestId("ranking-eligibility-legend")).toContainText("Not eligible for ranking");
  });
});

async function labelsForRows(page: Page, resultIds: readonly string[]): Promise<string[]> {
  return Promise.all(resultIds.map((resultId) => runIdentityLabel(page.getByTestId(resultId)).innerText()));
}

function runIdentityLabel(row: Locator): Locator {
  return row.getByTestId("run-identity-label");
}

function expectDistinctSameVersionLabels(labels: readonly string[]) {
  expect(labels).toHaveLength(2);
  expect(labels[0]).toContain("DuckDB");
  expect(labels[1]).toContain("DuckDB");
  expect(labels[0]).not.toBe(labels[1]);
}
