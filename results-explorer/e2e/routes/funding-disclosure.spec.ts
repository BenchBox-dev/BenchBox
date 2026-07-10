import { expect, test, type Page } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

/**
 * Funding-disclosure surface on the result detail page: the funding chip and
 * the provenance legend that explains it.
 *
 * Corpus facts these tests rely on (see scripts/generate-browser-fixtures.mjs):
 *   - the `community` variant is the ONLY bundle declaring `provenance.funding`
 *     (employer), and it is simultaneously `trust_label=community-submission`
 *   - every other fixture leaves funding at the `unspecified` default
 */

// Community-submission + employer-funded. The pairing is the point: it shows
// the funding axis is independent of the trust axis.
const FUNDED_ID = "tpch-duckdb-sf0.01-20260403-b92a4ffb";
// Maintainer-run, funding left `unspecified` -> no chip.
const UNSPECIFIED_ID = "tpch-duckdb-sf0.01-20260403-010ee756";

// Scope header assertions to the summary region: the expanded legend renders
// its own sample chips, so an unscoped [data-role="funding"] would match those
// too and make the "no chip" assertion depend on legend state.
const summary = (page: Page) => page.getByRole("region", { name: "Result summary" });
const fundingChip = (page: Page) => summary(page).locator('[data-role="funding"]');
const trustBadge = (page: Page) => summary(page).locator('[data-role="trust"]');

test.describe("Funding chip", () => {
  test("@smoke a funded result renders its funding chip beside the trust badge", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H\s+-\s+DuckDB/);

    const chip = fundingChip(page).first();
    await expect(chip).toBeVisible();
    await expect(chip).toHaveText("Employer funded");
    await expect(chip).toHaveAttribute("title", /employer/i);
  });

  test("funding is orthogonal to trust: a community result can be employer-funded", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForDataLoaded(page, /TPC-H\s+-\s+DuckDB/);

    // Both badges render, independently, in the same header row.
    await expect(trustBadge(page).first()).toHaveText("Community");
    await expect(fundingChip(page).first()).toHaveText("Employer funded");
  });

  test("funding chip is neutral-toned, never a trust-style warning", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForDataLoaded(page, /TPC-H\s+-\s+DuckDB/);

    // A tone gradient would re-encode "who paid" as "how much to trust this".
    await expect(fundingChip(page).first()).toHaveAttribute("data-tone", "neutral");
  });

  test("a result with unspecified funding renders no chip, and its trust badge is untouched", async ({
    page,
  }) => {
    await page.goto(`/results/r/${UNSPECIFIED_ID}`);
    await waitForDataLoaded(page, /TPC-H\s+-\s+DuckDB/);

    // The trust badge still renders - proving the page loaded and that omitting
    // the funding chip did not suppress the orthogonal trust surface.
    await expect(trustBadge(page).first()).toBeVisible();
    await expect(fundingChip(page)).toHaveCount(0);
  });
});

test.describe("Provenance legend", () => {
  test("@smoke the legend is reachable from a page that shows the badges", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForDataLoaded(page, /TPC-H\s+-\s+DuckDB/);

    // hosted-results-contract.md requires a legend accessible from every page
    // displaying trust labels.
    const toggle = page.getByRole("button", { name: /What do these labels mean\?/i });
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  test("expanding the legend explains both the trust and funding axes", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForDataLoaded(page, /TPC-H\s+-\s+DuckDB/);

    const toggle = page.getByRole("button", { name: /What do these labels mean\?/i });
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");

    const legend = page.getByTestId("provenance-legend");
    await expect(legend.getByRole("heading", { name: "Trust label" })).toBeVisible();
    await expect(legend.getByRole("heading", { name: "Funding" })).toBeVisible();

    // Every disclosed funding source gets a row, and the omitted `unspecified`
    // case is explained rather than left as a silent absence.
    for (const label of ["Employer funded", "Personally funded", "Free trial", "Vendor sponsored", "Grant funded"]) {
      await expect(legend.getByText(label, { exact: true })).toBeVisible();
    }
    await expect(legend.getByText(/Funding was not disclosed for this run/i)).toBeVisible();

    // The legend states the orthogonality explicitly.
    await expect(legend.getByText(/disclosure, not a trust signal/i)).toBeVisible();
  });
});
