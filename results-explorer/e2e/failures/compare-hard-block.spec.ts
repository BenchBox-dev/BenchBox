import { expect, test } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

const TPCH_ID = "tpch-duckdb-sf0.01-20260403-010ee756";
const TPCH_SHORT = "ba6a8c83";
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

  test("a Compare URL that references an unknown result_id surfaces a removal-hint error", async ({
    page,
  }) => {
    await page.goto(`/results/compare?ids=${TPCH_ID},tpch-unknown-does-not-exist`);
    await waitForShell(page);

    await expect(page.getByText(/No result found for/i)).toBeVisible({ timeout: 20_000 });
  });
});
