import { expect, test } from "@playwright/test";
import { waitForDataElement, waitForShell } from "../support/fixtures";

test.describe("benchmark and platform section indexes", () => {
  test("loads both routes, exposes URL-backed sort, and links to existing detail indexes", async ({ page }) => {
    await page.goto("/results/benchmarks/?sort=results");
    await waitForShell(page);
    await waitForDataElement(page, page.getByTestId("benchmarks-index-list").getByRole("listitem").first());

    await expect(page.getByRole("heading", { name: "Benchmarks" })).toBeVisible();
    const explorerNav = page.getByRole("navigation", { name: "Results Explorer" });
    await expect(explorerNav.getByRole("link", { name: "Benchmarks" })).toHaveAttribute("aria-current", "page");
    await expect(explorerNav.getByRole("link", { name: "Benchmarks" })).toHaveAttribute(
      "href",
      "/results/benchmarks/",
    );
    await expect(page.getByRole("link", { name: /TPC-H/ })).toHaveAttribute("href", "/results/tpch/");
    await page.getByRole("combobox", { name: "Sort benchmarks" }).selectOption("recent");
    await expect(page).toHaveURL(/\/results\/benchmarks\/\?sort=recent$/);

    await page.goto("/results/platforms/");
    await waitForDataElement(page, page.getByTestId("platforms-index-list").getByRole("listitem").first());

    await expect(page.getByRole("heading", { name: "Platforms" })).toBeVisible();
    await expect(explorerNav.getByRole("link", { name: "Platforms" })).toHaveAttribute("aria-current", "page");
    await expect(explorerNav.getByRole("link", { name: "Platforms" })).toHaveAttribute(
      "href",
      "/results/platforms/",
    );
    await expect(page.getByRole("link", { name: /DuckDB/ }).first()).toHaveAttribute("href", "/results/p/duckdb/");
  });
});
