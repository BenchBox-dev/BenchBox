import { expect, test } from "@playwright/test";
import { waitForShell } from "../support/fixtures";

const GLOBAL_LABELS = ["Home", "Docs", "Blog", "Results", "Instruct an agent", "GitHub", "Run benchmark"];

test.describe("Global header", () => {
  test("@smoke preserves the global header contract on desktop", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    const globalNav = page.getByRole("navigation", { name: "BenchBox" });
    await expect(globalNav.getByRole("link")).toHaveText(GLOBAL_LABELS);
    await expect(globalNav.getByRole("link", { name: "Results" })).toHaveAttribute("aria-current", "page");
    await expect(globalNav.getByRole("link", { name: "Run benchmark" })).toHaveAttribute(
      "href",
      "https://benchbox.dev/docs/usage/installation.html",
    );
    await expect(page.getByRole("button", { name: /Theme: system/i })).toBeVisible();

    const explorerNav = page.getByRole("navigation", { name: "Results Explorer" });
    await expect(explorerNav.getByRole("link")).toHaveText(["Leaderboards", "Benchmarks", "Platforms", "Compare", "Query"]);
  });

  test("@smoke preserves the global header contract behind the mobile disclosure", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/results/");
    await waitForShell(page);

    const toggle = page.getByRole("button", { name: "Toggle site navigation" });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("navigation", { name: "BenchBox" }).getByRole("link")).toHaveText(GLOBAL_LABELS);
  });

  test("@smoke persists the theme choice from the global header", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    const themeToggle = page.getByRole("button", { name: /Theme: system/i });
    await themeToggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-bb-theme-choice", "light");
    await page.reload();
    await waitForShell(page);
    await expect(page.locator("html")).toHaveAttribute("data-bb-theme-choice", "light");
  });
});
