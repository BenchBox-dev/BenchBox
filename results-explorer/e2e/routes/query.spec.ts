import { expect, test, type Locator, type Page } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("Query workbench", () => {
  test("@smoke loads /results/query and renders the schema-driven table", async ({ page }) => {
    await page.goto("/results/query");
    await waitForShell(page);

    await expect(page.getByRole("heading", { name: /Results Query Workbench/i })).toBeVisible();

    // Match count text is the stable landmark that renders once both the
    // facet queries and the main SELECT resolve.
    await waitForDataLoaded(page, /matching result bundle/);

    const main = page.getByRole("main");
    // Column-toggle pills include one per column in the attached schema.
    for (const column of ["benchmark", "platform", "trust_label"]) {
      await expect(main.getByText(column, { exact: true }).first()).toBeVisible();
    }
  });

  test("@smoke filters environment facet fixture rows", async ({ page }) => {
    await page.goto("/results/query");
    await waitForShell(page);
    await waitForDataLoaded(page, /matching result bundle/);

    const summary = page.getByTestId("query-result-summary");
    await expect(summary).toContainText(/matching result bundle/);

    await expect(facetCheckbox(page, "Deployment", "cloud")).toBeVisible();
    await expect(facetCheckbox(page, "Deployment", "local")).toHaveCount(1);
    await expect(page.getByRole("checkbox", { name: /^Deployment:\s+local\b/ })).toHaveCount(1);
    await expect(facetCheckbox(page, "Cloud provider", "aws")).toBeVisible();
    await expect(facetCheckbox(page, "Cloud region", "us-east-1")).toBeVisible();
    await expect(facetCheckbox(page, "Instance / warehouse", "m6i.large")).toBeVisible();

    await facetCheckbox(page, "Deployment", "cloud").check();
    await facetCheckbox(page, "Cloud provider", "aws").check();
    await facetCheckbox(page, "Cloud region", "us-east-1").check();
    await facetCheckbox(page, "Instance / warehouse", "m6i.large").check();

    await expectQueryParam(page, "deployment", "cloud");
    await expectQueryParam(page, "cloud_provider", "aws");
    await expectQueryParam(page, "cloud_region", "us-east-1");
    await expectQueryParam(page, "shape", "m6i.large");
    await expect(summary).toContainText("1 matching result bundle");
    await expect(page.getByRole("cell", { name: "Fixture AWS SQL" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Fixture GCP Serverless" })).toHaveCount(0);

    await facetCheckbox(page, "Instance / warehouse", "m6i.large").uncheck();
    await facetCheckbox(page, "Cloud region", "us-east-1").uncheck();
    await facetCheckbox(page, "Cloud provider", "aws").uncheck();
    await facetCheckbox(page, "Deployment", "cloud").uncheck();

    await expectQueryParam(page, "deployment", null);
    await expect(summary).toContainText(/matching result bundle/);

    await facetCheckbox(page, "Deployment", "local").check();
    await facetCheckbox(page, "Instance / warehouse", "container-cpu-10").check();
    await facetCheckbox(page, "Storage", "duckdb_native").check();

    await expectQueryParam(page, "deployment", "local");
    await expectQueryParam(page, "shape", "container-cpu-10");
    await expectQueryParam(page, "storage_format", "duckdb_native");
    await expect(summary).toContainText("1 matching result bundle");
    await expect(page.getByRole("cell", { name: "Fixture Container SQL" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Fixture AWS SQL" })).toHaveCount(0);
  });

  test("the explicit trailing-slash query route resolves the same workbench", async ({ page }) => {
    await page.goto("/results/query/");
    await waitForShell(page);
    await waitForDataLoaded(page, /matching result bundle/);

    await expect(page).toHaveURL(/\/results\/query\/$/);
    await expect(page.getByRole("heading", { name: /Results Query Workbench/i })).toBeVisible();
  });

  test("clicking a column header toggles its sort indicator", async ({ page }) => {
    await page.goto("/results/query");
    await waitForDataLoaded(page, /matching result bundle/);

    // Pick `benchmark` - not the default sort column (run_date desc) so
    // the first click asserts the arrow appears rather than flips. Scope
    // to the data table's thead so the column-toggle pills in the
    // "Visible Columns" bar don't steal the locator.
    const header = page
      .locator("thead th")
      .filter({ hasText: /^benchmark/ })
      .first();
    await header.click();
    await expect(header).toContainText("↑");
    await header.click();
    await expect(header).toContainText("↓");
  });

  test("row-limit toggle updates the URL and shows the all-rows query limit", async ({ page }) => {
    await page.goto("/results/query");
    await waitForDataLoaded(page, /matching result bundle/);

    await page.getByRole("button", { name: /^All$/ }).click();
    await expect
      .poll(() => new URL(page.url()).searchParams.get("limit"))
      .toBe("all");
    await expect(page.getByText(/Query limit: all/)).toBeVisible();
    await expect(page.getByText(/Showing \d+ of \d+ returned rows/)).toBeVisible();

    await page.getByRole("button", { name: /^Default$/ }).click();
    await expect
      .poll(() => new URL(page.url()).searchParams.get("limit"))
      .toBeNull();
  });

  test("toggling a column off removes it from the rendered table", async ({ page }) => {
    await page.goto("/results/query");
    await waitForDataLoaded(page, /matching result bundle/);

    // `trust_label` is in the default visible set; untoggle it and the
    // matching columnheader must disappear.
    const trustCheckbox = page.locator("label", { hasText: "trust_label" }).getByRole("checkbox");
    await expect(trustCheckbox).toBeChecked();
    await trustCheckbox.uncheck();
    await expect(page.getByRole("columnheader", { name: /^trust_label\s*/ })).toHaveCount(0);
  });

  test("loading a starter query populates the SQL textarea", async ({ page }) => {
    await page.goto("/results/query");
    await waitForDataLoaded(page, /matching result bundle/);

    // Advanced SQL is a <details> element collapsed by default; click
    // the summary to expand it before the textarea and starter-query
    // pills become interactive.
    await page.locator("summary", { hasText: "Advanced SQL" }).click();

    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible();

    await page.getByRole("button", { name: /^Recent results$/ }).click();
    await expect(textarea).toHaveValue(/SELECT/i);
    await expect(textarea).toHaveValue(/FROM\s+bench\.results/i);
  });

  test("a read-only write against the attached snapshot surfaces a user-visible error", async ({ page }) => {
    await page.goto("/results/query");
    await waitForDataLoaded(page, /matching result bundle/);

    await page.locator("summary", { hasText: "Advanced SQL" }).click();
    const textarea = page.locator("textarea");

    // Attempt to mutate the READ_ONLY-attached `bench` database. DuckDB
    // must reject this with a binder/catalog error surfaced to the user.
    await textarea.fill("DELETE FROM bench.results");
    await page.getByRole("button", { name: /^Run SQL$/ }).click();

    const advancedSection = page.locator("details", { hasText: "Advanced SQL" });
    await expect(advancedSection.locator(".text-red-600")).toBeVisible();
    await expect(advancedSection.locator(".text-red-600")).toContainText(/read[- ]only|not allowed|cannot/i);
  });

  test("Download JSON emits a file with the current query rows", async ({ page }) => {
    await page.goto("/results/query");
    await waitForDataLoaded(page, /matching result bundle/);

    // The button triggers an anchor.click() with a blob URL - Playwright's
    // `page.waitForEvent('download')` captures it deterministically.
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: /Download JSON/ }).click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toMatch(/^benchbox-query-export-\d+\.json$/);
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(chunk as Buffer);
    const body = Buffer.concat(chunks).toString("utf-8");
    const parsed = JSON.parse(body);
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed.length).toBeGreaterThan(0);
  });

  test("Download CSV emits a file sourced from a COPY of the filtered set", async ({ page }) => {
    await page.goto("/results/query");
    await waitForDataLoaded(page, /matching result bundle/);

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: /Download CSV/ }).click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toMatch(/^benchbox-query-export-\d+\.csv$/);
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(chunk as Buffer);
    const body = Buffer.concat(chunks).toString("utf-8");
    // First line must be a CSV header (no DuckDB error HTML).
    const header = body.split(/\r?\n/)[0] ?? "";
    expect(header.split(",").length).toBeGreaterThan(1);
    expect(body.split(/\r?\n/).length).toBeGreaterThan(1);
  });
});

function facetSection(page: Page, label: string): Locator {
  return page
    .getByTestId("query-desktop-filters")
    .getByRole("heading", { name: label, exact: true })
    .locator("xpath=ancestor::section[1]");
}

function facetCheckbox(page: Page, sectionLabel: string, optionValue: string): Locator {
  return facetSection(page, sectionLabel).getByRole("checkbox", {
    name: new RegExp(`^${escapeRegExp(sectionLabel)}:\\s+${escapeRegExp(optionValue)}\\b`),
  });
}

async function expectQueryParam(page: Page, key: string, value: string | null): Promise<void> {
  await expect.poll(() => new URL(page.url()).searchParams.get(key)).toBe(value);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
