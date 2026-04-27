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
});
