import { expect, test } from "@playwright/test";
import { waitForShell } from "../support/fixtures";

test.describe("NotFound", () => {
  test("an unknown path renders the 404 page with a link back to results", async ({ page }) => {
    // A three-segment path matches none of the routes in App.tsx:
    // `/results/:benchmark/` is one segment, `/results/p/:platform/` needs
    // `p`, `/results/r/:resultId` needs `r`. So this falls through to the
    // `NotFound default` route.
    await page.goto("/results/no/such/route/");
    await waitForShell(page);

    await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
    await expect(page.getByText(/Page not found/i)).toBeVisible();
    const backLink = page.getByRole("link", { name: /Back to Results/i });
    await expect(backLink).toHaveAttribute("href", "/results/");
  });

  test("an unknown :benchmark slug renders 404 with a benchmark-specific message", async ({ page }) => {
    // /results/:benchmark/ matches any single segment, so without the
    // BenchmarkIndex unknown-slug guard, /results/does-not-exist/ would
    // render an empty BenchmarkIndex shell that looks like a real but
    // empty page. The guard added in w5 of results-explorer-qa-pass1-fixes
    // routes unknown slugs to NotFound and passes a slug-specific message
    // so the user knows it's the slug that's wrong, not that the page is
    // generically missing.
    await page.goto("/results/does-not-exist/");
    await waitForShell(page);

    await expect(page.getByRole("heading", { name: "404" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/Benchmark "does-not-exist" is not part of the published corpus/i)).toBeVisible();
  });

  test("a known benchmark with no published results shows an empty-corpus state, not 404", async ({ page }) => {
    // `clickbench` is in BENCHMARK_LABELS but the fixture corpus contains
    // only tpch + star_schema. Distinguishes "unknown slug" from "known
    // family with no data yet" — the latter must NOT 404 since the
    // benchmark is genuinely supported.
    await page.goto("/results/clickbench/");
    await waitForShell(page);

    await expect(page.getByRole("heading", { name: /^ClickBench$/ })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/No published results yet for ClickBench/i)).toBeVisible();
    // Crucially: NOT a 404.
    await expect(page.getByRole("heading", { name: "404" })).not.toBeVisible();
  });
});
