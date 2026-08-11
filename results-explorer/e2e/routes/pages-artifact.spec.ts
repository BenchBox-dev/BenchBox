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
    !process.env.E2E_SITE_DIR,
    "Set E2E_SITE_DIR to the workflow-produced site directory for Pages-shaped acceptance.",
  );

  test("preserves direct routes through root 404 fallback and native docs links", async ({ page }) => {
    const directRouteStatuses: number[] = [];
    const docsStatuses: number[] = [];
    page.on("response", (response) => {
      const pathname = new URL(response.url()).pathname;
      if (pathname === "/results/p/polars/") directRouteStatuses.push(response.status());
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

    await page.goto("/results/");
    await waitForDataLoaded(page, /Recent Results/i);
    await page.getByRole("link", { name: "Run a benchmark" }).click();
    await expect(page).toHaveURL(/\/docs\/usage\/installation\.html$/);
    expect(docsStatuses).toContain(200);
  });
});
