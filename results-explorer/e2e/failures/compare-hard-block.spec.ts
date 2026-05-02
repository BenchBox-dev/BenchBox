import { expect, test } from "@playwright/test";
import { waitForShell } from "../support/fixtures";

const TPCH_ID = "tpch-duckdb-sf0.01-20260403-010ee756";
const STAR_SCHEMA_ID = "star_schema-duckdb-sf0.01-20260403-3cdeede0";
const TPCH_SF01_ID = "tpch-duckdb-sf0.1-20260403-f88815c2";

test.describe.configure({ mode: "serial" });

test.describe("Compare hard blocks", () => {
  test("mixing benchmarks blocks the compare render with an explicit error", async ({
    page,
  }) => {
    await page.goto(`/results/compare?ids=${TPCH_ID},${STAR_SCHEMA_ID}`);
    await waitForShell(page);

    // The error card is rendered by ErrorMessage under an explicit
    // "Cannot compare" heading. We assert on both halves so a generic
    // "error" string alone does not count as passing.
    await expect(page.getByRole("heading", { name: /Cannot compare/i })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(/different benchmarks/i)).toBeVisible();
  });

  test("mixing scale factors blocks the compare render with an explicit error", async ({
    page,
  }) => {
    await page.goto(`/results/compare?ids=${TPCH_ID},${TPCH_SF01_ID}`);
    await waitForShell(page);

    await expect(page.getByRole("heading", { name: /Cannot compare/i })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(/different scale factors/i)).toBeVisible();
  });

  test("a Compare URL that references an unknown result_id surfaces a removal-hint error", async ({
    page,
  }) => {
    await page.goto(`/results/compare?ids=${TPCH_ID},tpch-unknown-does-not-exist`);
    await waitForShell(page);

    await expect(page.getByText(/No result found for/i)).toBeVisible({ timeout: 20_000 });
  });
});
