import { expect, test } from "@playwright/test";
import { waitForShell } from "../support/fixtures";

// B2 reproduction: against a production-shape corpus (12 results across
// 4 platforms), /results/p/duckdb/ and /results/p/polars/ intermittently
// render "No results found" because DuckDB-WASM's cold-load can return a
// partial row set on the first SELECT (see w1 notes in
// _project/TODO/main/active/results-explorer-qa-pass1-fixes.yaml).
//
// These specs are pinned with `test.fixme` because:
//   1) The default e2e fixtures DB is generated from the small
//      test-fixtures/source corpus, not from results-data/. To exercise
//      the cold-load partial-data race you must overwrite
//      test-fixtures/.generated/data/results.duckdb with the prod-shape
//      DB before running.
//   2) Even with the prod DB, the test passes ~50% of the time because
//      the race resolves once WASM is warm. Until w3 lands a mitigation
//      in db.ts (or PlatformIndex/getPlatformIndexRows), running this
//      spec by default would just add flake to CI.
//
// Re-enable (drop `.fixme`) as part of w3 once the partial-data window
// is closed. The expected_output specs in the parent TODO's verification
// section name the success criteria.
test.describe("PlatformIndex (production-shape corpus)", () => {
  test.fixme("DuckDB page shows 4 rows and capital-D heading", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /DuckDB Results/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.locator("table tbody tr")).toHaveCount(4);
  });

  test.fixme("Polars page shows 2 rows and capital-P heading", async ({ page }) => {
    await page.goto("/results/p/polars/");
    await waitForShell(page);
    await expect(page.getByRole("heading", { name: /Polars Results/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.locator("table tbody tr")).toHaveCount(2);
  });
});
