import { expect, test } from "@playwright/test";
import { fixtureIds, waitForDataLoaded, waitForShell } from "../support/fixtures";

const TPCH_ID = fixtureIds.duckdbId;
const TPCH_SHORT = fixtureIds.shortDuckdb;
const STAR_SCHEMA_SHORT = "0f0add9f";
const TPCH_SF01_SHORT = "0820b170";

test.describe.configure({ mode: "serial" });

test.describe("Compare guardrails", () => {
  test("mixing benchmarks renders guardrails without suppressing raw evidence", async ({
    page,
  }) => {
    await page.goto(`/results/compare?ids=${TPCH_SHORT},${STAR_SCHEMA_SHORT}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /Mixed Benchmark Comparison/);

    const main = page.getByRole("main");
    const receipt = main.getByRole("region", { name: "Comparability receipt" });
    const summary = main.getByRole("region", { name: "Decision Summary" });
    await expect(receipt).toContainText("Benchmark");
    await expect(summary).toContainText("Not directly comparable: benchmarks differ");
    await expect(summary).toContainText("Claims suppressed");
    await expect(main.getByRole("heading", { name: "Query-Level Diff" })).toBeVisible();
    await expect(main.getByRole("heading", { name: /Cannot compare/i })).toHaveCount(0);
  });

  test("mixing scale factors renders guardrails without suppressing raw evidence", async ({
    page,
  }) => {
    await page.goto(`/results/compare?ids=${TPCH_SHORT},${TPCH_SF01_SHORT}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison/);

    const main = page.getByRole("main");
    const receipt = main.getByRole("region", { name: "Comparability receipt" });
    const summary = main.getByRole("region", { name: "Decision Summary" });
    await expect(receipt).toContainText("Scale factor");
    await expect(summary).toContainText("Not directly comparable: scale factors differ");
    await expect(summary).toContainText("Claims suppressed");
    await expect(main.getByRole("heading", { name: "Query-Level Diff" })).toBeVisible();
    await expect(main.getByRole("heading", { name: /Cannot compare/i })).toHaveCount(0);
  });

  test("a Compare URL that references one stale ID retains the resolvable result", async ({
    page,
  }) => {
    await page.goto(`/results/compare?ids=${TPCH_ID},tpch-unknown-does-not-exist`);
    await waitForShell(page);

    await waitForDataLoaded(page, /TPC-H Comparison/);
    await expect(page.getByTestId("compare-url-notice")).toContainText("Ignored unavailable result ID");
    await expect(page.getByRole("heading", { name: "Decision Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Cannot compare/i })).toHaveCount(0);

    expect(page.url()).toContain("tpch-unknown-does-not-exist");
    await page.reload();
    await waitForDataLoaded(page, /TPC-H Comparison/);
    await expect(page.getByRole("heading", { name: "Decision Summary" })).toBeVisible();
  });

  test("all-unavailable compare IDs retain the removal-hint error", async ({ page }) => {
    await page.goto("/results/compare?ids=tpch-unknown-one,tpch-unknown-two");
    await waitForShell(page);
    await expect(page.getByText(/No result found for/i)).toBeVisible({ timeout: 20_000 });
  });

  test("duplicate and excess IDs are disclosed while the first four unique entries are retained", async ({ page }) => {
    const ids = [TPCH_SHORT, TPCH_SHORT, STAR_SCHEMA_SHORT, TPCH_SF01_SHORT, "stale-one", "stale-two"].join(",");
    await page.goto(`/results/compare?ids=${ids}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /Comparison/);

    const notice = page.getByTestId("compare-url-notice");
    await expect(notice).toContainText("Ignored duplicate result ID");
    await expect(notice).toContainText("comparisons are limited to 4 unique results");
    await expect(notice).toContainText("Ignored unavailable result ID");
    await expect(page.getByRole("heading", { name: "Decision Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Cannot compare/i })).toHaveCount(0);
  });
});
