import { expect, test } from "@playwright/test";
import { waitForDataElement, waitForDataLoaded, waitForShell } from "../support/fixtures";

test.describe("cross-benchmark leaderboard disclosure", () => {
  test("leaderboard keyboard traversal reaches a revealed unranked row", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);
    await waitForDataLoaded(page, /Recent Results/i);

    const grid = page.getByRole("grid", { name: "Cross-benchmark leaderboard" });
    const rankedRowCount = await grid.locator("tbody tr").count();
    expect(rankedRowCount).toBeGreaterThan(0);
    const expander = page.getByRole("button", {
      name: /more platforms? (?:has|have) published results but nothing ranked — Show them/,
    });
    await expect(expander).toHaveAttribute("aria-expanded", "false");
    await expander.click();

    const lastRankedCell = grid.locator(`[data-cell="${rankedRowCount - 1}-0"]`);
    const firstRevealedCell = grid.locator(`[data-cell="${rankedRowCount}-0"]`);
    await expect(firstRevealedCell).toBeVisible();
    await lastRankedCell.focus();
    await lastRankedCell.press("ArrowDown");
    await expect(firstRevealedCell).toBeFocused();
  });

  test("all excluded ranking states why no evidence is ranked and offers the detail route", async ({ page }) => {
    await page.goto("/results/?platform=fixture-aws-sql");
    await waitForShell(page);
    const state = page.getByTestId("all-excluded-ranking-tpch-sf0.01-standard");
    await waitForDataElement(page, state);

    await expect(state).toContainText("No ranked evidence");
    await expect(state).toContainText("Trust policy excludes this result from ranking.");
    await expect(state).toContainText("Open ranking for details.");
    const grid = page.getByRole("grid", { name: "Cross-benchmark leaderboard" });
    await expect(grid.getByRole("gridcell")).toHaveCount(0);

    await page.getByRole("button", {
      name: "1 more platform has published results but nothing ranked — Show them",
    }).click();
    await expect(
      grid.getByRole("gridcell", {
        name: /Fixture AWS SQL has published evidence.*Trust policy excludes this result from ranking/,
      }),
    ).toBeVisible();
  });
});
