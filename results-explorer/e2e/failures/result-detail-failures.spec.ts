import { expect, test } from "@playwright/test";
import { fixtureIds, waitForDataElement, waitForShell } from "../support/fixtures";

const TPCH_TUNED_ID = fixtureIds.ids.duckdbTuned;

test.describe.configure({ mode: "serial" });

test.describe("ResultDetail failure paths", () => {
  test("an unreachable results.duckdb renders a user-visible error rather than a blank page", async ({ page }) => {
    await page.route("**/results/data/results.duckdb", (route) => route.fulfill({ status: 404 }));

    await page.goto("/results/");
    await waitForShell(page);

    const errorBox = page.locator("[role='alert']").filter({
      has: page.getByRole("heading", { name: "Could not load results" }),
    });
    await expect(errorBox).toBeVisible({ timeout: 20_000 });
  });

  test("a failing tuning-config bundle fetch surfaces a visible error", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_TUNED_ID}`);
    await waitForShell(page);
    await waitForDataElement(page, page.getByRole("heading", { name: /TPC-H result:\s+DuckDB/ }));

    await page.route("**/bundles/*.json", (route) => route.fulfill({ status: 500, body: "simulated bundle failure" }));

    await page.getByRole("button", { name: /Show settings/ }).click();
    await expect(page.getByText(/Could not load tuning settings/)).toBeVisible();
  });
});
