import { expect, test, type Page } from "@playwright/test";
import { fixtureIds, waitForDataLoaded, waitForShell } from "../support/fixtures";

const FUNDED_ID = fixtureIds.ids.duckdbCommunity;
const UNSPECIFIED_ID = fixtureIds.ids.duckdb;

const identity = (page: Page) => page.getByTestId("page-header");
const fundingChip = (page: Page) => identity(page).locator('[data-role="funding"]');
const trustBadge = (page: Page) => identity(page).locator('[data-role="trust"]');

test.describe("Funding chip", () => {
  test("@smoke a funded result renders its funding chip beside the trust badge", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForShell(page);
    await waitForDataLoaded(page, /TPC-H result:\s+DuckDB/);

    const chip = fundingChip(page).first();
    await expect(chip).toBeVisible();
    await expect(chip).toHaveText("Employer funded");
    await expect(chip).toHaveAttribute("title", /employer/i);
  });

  test("funding is orthogonal to trust: a community result can be employer-funded", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForDataLoaded(page, /TPC-H result:\s+DuckDB/);

    await expect(trustBadge(page).first()).toHaveText("Community");
    await expect(fundingChip(page).first()).toHaveText("Employer funded");
  });

  test("funding chip is neutral-toned, never a trust-style warning", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForDataLoaded(page, /TPC-H result:\s+DuckDB/);

    await expect(fundingChip(page).first()).toHaveAttribute("data-tone", "neutral");
  });

  test("a result with unspecified funding renders no chip, and its trust badge is untouched", async ({
    page,
  }) => {
    await page.goto(`/results/r/${UNSPECIFIED_ID}`);
    await waitForDataLoaded(page, /TPC-H result:\s+DuckDB/);

    await expect(trustBadge(page).first()).toBeVisible();
    await expect(fundingChip(page)).toHaveCount(0);
  });
});

test.describe("Provenance legend", () => {
  test("@smoke the legend is reachable from a page that shows the badges", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForDataLoaded(page, /TPC-H result:\s+DuckDB/);

    const toggle = page.getByRole("button", { name: /What do these labels mean\?/i });
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  test("expanding the legend explains both the trust and funding axes", async ({ page }) => {
    await page.goto(`/results/r/${FUNDED_ID}`);
    await waitForDataLoaded(page, /TPC-H result:\s+DuckDB/);

    const toggle = page.getByRole("button", { name: /What do these labels mean\?/i });
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");

    const legend = page.getByTestId("provenance-legend");
    await expect(legend.getByRole("heading", { name: "Result source" })).toBeVisible();
    await expect(legend.getByRole("heading", { name: "Funding" })).toBeVisible();

    for (const label of ["Employer funded", "Personally funded", "Free trial", "Vendor sponsored", "Grant funded"]) {
      await expect(legend.getByText(label, { exact: true })).toBeVisible();
    }
    await expect(legend.getByText(/Funding was not disclosed for this run/i)).toBeVisible();

    await expect(legend.getByText(/Funding does not change how BenchBox reviews or ranks a result/i)).toBeVisible();
  });
});

test.describe("Funding on card surfaces", () => {
  test("@smoke platform index shows a compact funding chip only for the funded run", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForDataLoaded(page, /DuckDB Results/);

    const chips = page.getByRole("main").locator('[data-role="funding"]');
    await expect(chips).toHaveCount(1);
    await expect(chips.first()).toHaveText("Employer");
  });

  test("@smoke the legend is reachable from the platform index", async ({ page }) => {
    await page.goto("/results/p/duckdb/");
    await waitForDataLoaded(page, /DuckDB Results/);

    const toggle = page.getByRole("button", { name: /What do these labels mean\?/i });
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.getByTestId("provenance-legend").getByRole("heading", { name: "Funding" })).toBeVisible();
  });
});
