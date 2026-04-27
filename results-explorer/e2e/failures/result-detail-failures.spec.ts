import { expect, test } from "@playwright/test";
import { waitForShell } from "../support/fixtures";

const TPCH_TUNED_ID = "tpch-duckdb-sf0.01-20260403-78762750";

// Failure tests share the same DuckDB-WASM cold-boot cost as the happy
// paths but add network interception. Run serially so three parallel
// chromium contexts do not fight over worker startup and time out.
test.describe.configure({ mode: "serial" });

test.describe("ResultDetail failure paths", () => {
  test("an unreachable results.duckdb renders a user-visible error rather than a blank page", async ({ page }) => {
    // Block the snapshot request before the explorer even boots. DuckDB-WASM
    // bubbles the IOException up through `queryRows` and listResults; the
    // Home page renders `ErrorMessage` once the promise rejects.
    await page.route("**/results/data/results.duckdb", (route) => route.fulfill({ status: 404 }));

    await page.goto("/results/");
    await waitForShell(page);

    // The Home page surfaces the attach failure through the ErrorMessage
    // component, which renders an explicit `<h3>Error</h3>` over a message
    // paragraph. Asserting on the role + the ErrorMessage wrapper keeps
    // this tight: a stray "failed" or "could not" elsewhere in the DOM
    // won't accidentally satisfy the assertion.
    const errorBox = page.locator("div.bg-red-50").filter({
      has: page.getByRole("heading", { name: /^Error$/ }),
    });
    await expect(errorBox).toBeVisible({ timeout: 20_000 });
  });

  test("a failing tuning-config sidecar fetch surfaces a visible error", async ({ page }) => {
    await page.goto(`/results/r/${TPCH_TUNED_ID}`);
    await waitForShell(page);
    // Wait for the detail to render so the Tuning Config section is in
    // the DOM. The tuned fixture is the only bundle with has_tuning=true.
    await expect(page.getByRole("heading", { name: /TPC-H\s+-\s+DuckDB/ })).toBeVisible({
      timeout: 45_000,
    });

    // Route the sidecar request to a 500 before the user expands the
    // collapsed Tuning Config panel.
    await page.route("**/*.tuning.json", (route) => route.fulfill({ status: 500, body: "simulated sidecar failure" }));

    await page.getByRole("button", { name: /Show config/ }).click();
    await expect(page.getByText(/Could not load tuning config/)).toBeVisible();
  });
});
