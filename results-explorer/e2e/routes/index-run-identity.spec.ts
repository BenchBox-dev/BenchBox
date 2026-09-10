import { expect, test, type Locator, type Page } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForShell } from "../support/fixtures";

const SAME_VERSION_RUNS = [fixtureIds.ids.duckdb, fixtureIds.ids.duckdbTuned] as const;

test.describe("run identity in index tables", () => {
  test("run identity: same-version runs have distinguishable benchmark and platform index labels", async ({ page }) => {
    // Matrix, Ranks, and List are all sections of one page now (rather than
    // mutually exclusive states), so List's rows carry a `list-` prefixed
    // testid to stay distinct from Matrix's rows, which keep the bare
    // result-id testid used across the rest of the app.
    await page.goto("/results/tpch/?view=list");
    await waitForShell(page);
    const listRunIds = SAME_VERSION_RUNS.map((id) => `list-${id}`);
    await waitForDataElement(page, page.getByTestId(listRunIds[0]!));

    const benchmarkLabels = await labelsForRows(page, listRunIds);
    expectDistinctSameVersionLabels(benchmarkLabels);

    await page.goto("/results/p/duckdb/");
    await waitForDataElement(page, page.getByTestId(SAME_VERSION_RUNS[0]));

    // On a platform page the platform is the page, so the row label carries
    // the version plus whatever it takes to separate two runs of it.
    const platformLabels = await labelsForRows(page, SAME_VERSION_RUNS);
    expect(platformLabels).toHaveLength(2);
    expect(platformLabels[0]).not.toBe(platformLabels[1]);
    for (const label of platformLabels) expect(label).toContain("v");
  });

  test("run identity: ranking eligibility marker has an inline legend", async ({ page }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataElement(page, page.locator('[data-testid^="heatmap-compliance-marker-"]').first());

    // The marker itself always names its reason; the matrix legend restates it
    // for readers who open the legend rather than hovering a single cell.
    await expect(page.locator('[data-testid^="heatmap-compliance-marker-"]').first()).toHaveAttribute(
      "aria-label",
      /ranking/i,
    );
    await page.locator('[data-testid="query-heatmap-legend"] > summary').click();
    await expect(
      page.getByTestId("query-heatmap-legend").getByTestId("ranking-eligibility-legend"),
    ).toContainText("not eligible for ranking");
  });
});

async function labelsForRows(scope: Page | Locator, resultIds: readonly string[]): Promise<string[]> {
  return Promise.all(resultIds.map((resultId) => runIdentityLabel(scope.getByTestId(resultId)).innerText()));
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
