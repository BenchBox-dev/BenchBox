import { expect, test } from "@playwright/test";
import { waitForDataElement, waitForDataLoaded, waitForShell } from "../support/fixtures";

/**
 * Acceptance for the assembled GitHub Pages artifact.
 *
 * Deliberately fixture-free. This runs against the exact `site/` directory the
 * protected docs workflow produced, which is built from the production corpus
 * and has no relationship to the generated browser fixtures. Living in
 * `direct-route.spec.ts` meant it could not even be *discovered* without
 * `test-fixtures/.generated/data/fixture-ids.json`, and once discovered it
 * dragged five fixture-pinned tests - fixed short ids, exact row counts -
 * against a production artifact, so ordinary corpus changes failed a check that
 * only exists to prove route restoration.
 *
 * Keep assertions here structural: routes resolve, the 404 fallback restores
 * them, and docs links navigate natively. Nothing that counts corpus rows.
 */
test.describe("assembled GitHub Pages artifact", () => {
  test.skip(
    !process.env.E2E_PAGES_SHAPED || !process.env.E2E_SITE_DIR,
    "Set E2E_PAGES_SHAPED=1 and E2E_SITE_DIR to the assembled site directory for Pages-shaped acceptance.",
  );

  test("preserves direct routes through root 404 fallback and native docs links", async ({ page }) => {
    const directRouteStatuses: number[] = [];
    const benchmarkIndexStatuses: number[] = [];
    const platformIndexStatuses: number[] = [];
    const localPreviewStatuses: number[] = [];
    const docsStatuses: number[] = [];
    page.on("response", (response) => {
      const pathname = new URL(response.url()).pathname;
      if (pathname === "/results/p/polars/") directRouteStatuses.push(response.status());
      if (pathname === "/results/benchmarks/") benchmarkIndexStatuses.push(response.status());
      if (pathname === "/results/platforms/") platformIndexStatuses.push(response.status());
      if (pathname === "/results/local/local-aabbccddeeff") localPreviewStatuses.push(response.status());
      if (pathname === "/docs/usage/installation.html") docsStatuses.push(response.status());
    });

    const fallback = await page.request.get("/404.html");
    expect(fallback.status()).toBe(200);
    expect(await fallback.text()).toContain("benchbox.results.redirect");

    await page.goto("/results/p/polars/");
    await waitForShell(page);
    await waitForDataElement(page, page.getByRole("heading", { name: /^Polars Results$/ }));
    await expect(page).toHaveURL(/\/results\/p\/polars\/$/);
    expect(directRouteStatuses).toContain(404);
    // At least one row, not an exact count: the production corpus decides how
    // many Polars results exist, and that is not what this check is proving.
    await expect(page.locator("main table tbody tr[data-testid]").first()).toBeVisible();
    await expect(page.getByText(/No results found for platform/i)).not.toBeVisible();

    await page.goto("/results/benchmarks/");
    await waitForDataElement(page, page.getByTestId("benchmarks-index-list").getByRole("listitem").first());
    await expect(page.getByRole("heading", { name: "Benchmarks" })).toBeVisible();
    await expect(page).toHaveURL(/\/results\/benchmarks\/$/);
    expect(benchmarkIndexStatuses).toContain(404);

    await page.goto("/results/platforms/");
    await waitForDataElement(page, page.getByTestId("platforms-index-list").getByRole("listitem").first());
    await expect(page.getByRole("heading", { name: "Platforms" })).toBeVisible();
    await expect(page).toHaveURL(/\/results\/platforms\/$/);
    expect(platformIndexStatuses).toContain(404);

    await page.goto("/results/local/local-aabbccddeeff");
    await waitForShell(page);
    await expect(page).toHaveURL(/\/results\/local\/local-aabbccddeeff$/);
    await expect(page.getByRole("alert")).toContainText("no longer available");
    await expect(page.getByRole("button", { name: "Open result file again" })).toBeVisible();
    expect(localPreviewStatuses).toContain(404);

    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);
    await page.getByRole("link", { name: "Run a benchmark" }).click();
    await expect(page).toHaveURL(/\/docs\/usage\/installation\.html$/);
    expect(docsStatuses).toContain(200);
  });
});
