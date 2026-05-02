import { expect, test } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

// Short IDs assigned deterministically by the pipeline to the fixture
// corpus. Tests that round-trip long-form → short-form use these.
const SHORT_DUCKDB = "ba6a8c83";
const SHORT_DATAFUSION = "5e6c5eba";
const LONG_DUCKDB = "tpch-duckdb-sf0.01-20260403-010ee756";
const LONG_DATAFUSION = "tpch-datafusion-sf0.01-20260403-a6bb8a70";

test.describe("Compare", () => {
  test.describe.configure({ mode: "serial" });

  test("@smoke loads /results/compare?ids=<a>,<b> and renders both platform cards", async ({
    page,
  }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);

    // Heading appears once resolveShortId() + getDetailResult() have
    // resolved for every ID in the URL.
    await waitForDataLoaded(page, /TPC-H Comparison/);

    const main = page.getByRole("main");
    // Both platforms must render as comparison cards. We search inside
    // the detail links to avoid matching hidden baseline <option> nodes.
    await expect(main.locator(`a[href="/results/r/${LONG_DUCKDB}"]`)).toBeVisible();
    await expect(main.locator(`a[href="/results/r/${LONG_DATAFUSION}"]`)).toBeVisible();

    // Query-Level Diff is the stable landmark for the per-query evidence table.
    await expect(main.getByRole("heading", { name: /Query-Level Diff/ })).toBeVisible();
  });

  test("the explicit trailing-slash compare route resolves the same comparison page", async ({
    page,
  }) => {
    await page.goto(`/results/compare/?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison/);

    await expect(page).toHaveURL(/\/results\/compare\/\?ids=/);
    await expect(page.getByRole("main").getByText("DuckDB", { exact: true }).first()).toBeVisible();
  });

  test("long-form IDs in the URL get rewritten to short IDs after load", async ({ page }) => {
    const ids = [LONG_DUCKDB, LONG_DATAFUSION].map(encodeURIComponent).join(",");
    await page.goto(`/results/compare?ids=${ids}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison/);

    // The Compare page canonicalizes the URL via history.replaceState
    // once toShortIds() resolves. Poll the location rather than the DOM.
    await expect
      .poll(() => new URL(page.url()).searchParams.get("ids"), { timeout: 15_000 })
      .toMatch(/^[0-9a-f]{8},[0-9a-f]{8}$/);
  });

  test("a single-id compare URL redirects to the result detail page", async ({ page }) => {
    await page.goto(`/results/compare?ids=${SHORT_DUCKDB}`);
    await waitForShell(page);

    await expect(page).toHaveURL(new RegExp(`/results/r/${LONG_DUCKDB}$`), {
      timeout: 20_000,
    });
    await waitForDataLoaded(page, /Query Timings/);
  });

  test("Share URL button copies the current URL and updates its label", async ({
    page,
    context,
  }) => {
    // Clipboard reads/writes require explicit grants under Chromium and
    // are a no-op under WebKit/Firefox. This test runs under every project
    // but only the permission grant is Chromium-only guarded.
    const browserName = page.context().browser()?.browserType().name();
    if (browserName === "chromium") {
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    }

    await page.goto(`/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Comparison/);

    const shareButton = page.getByRole("button", { name: /Share URL/ });
    await shareButton.click();

    // Label flips to "Copied!" for two seconds. We only assert the label
    // change because clipboard readback varies across browsers.
    await expect(page.getByRole("button", { name: /Copied!/ })).toBeVisible();

    if (browserName === "chromium") {
      const clipboardText = await page.evaluate(() => navigator.clipboard.readText());
      expect(clipboardText).toContain("/results/compare?ids=");
    }
  });

  test("selecting two platforms on BenchmarkIndex routes to Compare via the sticky bar", async ({
    page,
  }) => {
    await page.goto("/results/tpch/");
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H Results/);

    // Checkboxes render on the matrix view by default, one per platform.
    const duckdb = page.getByRole("checkbox", { name: /Select DuckDB for comparison/i });
    const datafusion = page.getByRole("checkbox", { name: /Select DataFusion for comparison/i });
    await expect(duckdb.first()).toBeVisible();
    await duckdb.first().check();
    await datafusion.first().check();

    // Sticky compare bar materializes once two platforms are selected.
    const compareLink = page.getByRole("link", { name: /Compare 2 selected/ });
    await expect(compareLink).toBeVisible();
    await compareLink.click();

    await expect(page).toHaveURL(/\/results\/compare\?ids=/);
    await waitForDataLoaded(page, /TPC-H Comparison/);
  });
});
