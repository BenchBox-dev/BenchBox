import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { waitForShell } from "../support/fixtures";
import {
  HEADER_BRAND,
  HEADER_CTA,
  HEADER_DESKTOP_MIN_HEIGHT_PX,
  HEADER_HEIGHT_TOLERANCE_PX,
  HEADER_LINKS,
  HEADER_MOBILE_MIN_HEIGHT_PX,
  HEADER_NAV_ARIA_LABEL,
  HEADER_TOGGLE_ARIA_LABEL,
  getHeaderVisibleLabels,
} from "../../src/components/headerContract";

const GLOBAL_LABELS = getHeaderVisibleLabels();
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "../../..");

const STATIC_SURFACES: ReadonlyArray<{ surface: string; path: string }> = [
  { surface: "landing", path: "landing/index.html" },
  { surface: "prompts", path: "landing/prompts/index.html" },
  { surface: "docs", path: "docs/_templates/page.html" },
];

function readStaticSurface(relativePath: string): string {
  return readFileSync(resolve(REPO_ROOT, relativePath), "utf8");
}

async function loadStaticHeader(page: Page, html: string): Promise<void> {
  await page.setContent(html, { waitUntil: "domcontentloaded" });
}

async function chooseTheme(page: Page, choice: "system" | "light" | "dark") {
  const button = page.locator("[data-theme-toggle]");
  for (let step = 0; step < 3; step++) {
    if ((await button.getAttribute("data-theme-choice")) === choice) break;
    await button.click();
  }
  await expect(page.locator("html")).toHaveAttribute("data-bb-theme-choice", choice);
}

test.describe("Global header", () => {
  test("@smoke preserves the global header contract on desktop", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    const globalNav = page.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL });
    await expect(globalNav.getByRole("link")).toHaveText(GLOBAL_LABELS);
    await expect(globalNav.getByRole("link", { name: "Results" })).toHaveAttribute("aria-current", "page");
    await expect(globalNav.getByRole("link", { name: HEADER_CTA.label })).toHaveAttribute("href", HEADER_CTA.href);
    await expect(globalNav.getByRole("button", { name: /Color theme/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Color theme: / })).toBeVisible();

    const explorerNav = page.getByRole("navigation", { name: "Results Explorer" });
    await expect(explorerNav.getByRole("link")).toHaveText(["Overview", "Benchmarks", "Platforms", "Compare", "Find runs"]);
  });

  test("@smoke preserves the global header contract behind the mobile disclosure", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/results/");
    await waitForShell(page);

    const toggle = page.getByRole("button", { name: HEADER_TOGGLE_ARIA_LABEL });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL }).getByRole("link")).toHaveText(GLOBAL_LABELS);
  });

  test("@smoke persists the theme choice from the footer theme button", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    await chooseTheme(page, "light");
    await page.reload();
    await waitForShell(page);
    await expect(page.locator("html")).toHaveAttribute("data-bb-theme-choice", "light");
    await expect(page.getByRole("button", { name: "Color theme: Light theme" })).toBeVisible();
  });

  test("Results global header bounding-box meets shared min-height contract", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    const headerBox = await page.getByTestId("benchbox-global-header").boundingBox();
    expect(headerBox).not.toBeNull();
    expect(headerBox!.height).toBeGreaterThanOrEqual(HEADER_DESKTOP_MIN_HEIGHT_PX - 0.5);
    expect(headerBox!.height).toBeLessThanOrEqual(HEADER_DESKTOP_MIN_HEIGHT_PX + HEADER_HEIGHT_TOLERANCE_PX);

    await page.setViewportSize({ width: 390, height: 844 });
    const mobileBox = await page.getByTestId("benchbox-global-header").boundingBox();
    expect(mobileBox).not.toBeNull();
    expect(mobileBox!.height).toBeGreaterThanOrEqual(HEADER_MOBILE_MIN_HEIGHT_PX - 0.5);
  });

  test("Results global header bounding-box is identical across light and dark themes", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    const measure = async () => {
      const box = await page.getByTestId("benchbox-global-header").boundingBox();
      expect(box).not.toBeNull();
      return box!;
    };

    await chooseTheme(page, "light");
    const lightBox = await measure();

    await chooseTheme(page, "dark");
    const darkBox = await measure();

    expect(Math.abs(darkBox.height - lightBox.height)).toBeLessThanOrEqual(0.5);
    expect(Math.abs(darkBox.width - lightBox.width)).toBeLessThanOrEqual(0.5);
  });

  test("Results renders no Explorer subnav links inside the global header", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    const globalNav = page.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL });
    for (const subnavLabel of ["Overview", "Benchmarks", "Platforms", "Compare", "Find runs"]) {
      await expect(globalNav.getByRole("link", { name: subnavLabel, exact: true })).toHaveCount(0);
    }
  });
});

test.describe("Global header cross-surface parity", () => {
  for (const { surface, path } of STATIC_SURFACES) {
    test(`static surface ${surface} matches the shared global header contract`, async ({ page }) => {
      const html = readStaticSurface(path);
      await loadStaticHeader(page, html);

      const nav = page.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL });
      await expect(nav.getByRole("link")).toHaveText(GLOBAL_LABELS);
      for (const link of HEADER_LINKS) {
        await expect(nav.getByRole("link", { name: link.label }).first()).toHaveAttribute("href", link.href);
      }
      await expect(nav.getByRole("link", { name: HEADER_CTA.label })).toHaveAttribute("href", HEADER_CTA.href);
      await expect(page.getByRole("button", { name: HEADER_TOGGLE_ARIA_LABEL })).toBeVisible();
      await expect(nav.getByRole("radiogroup")).toHaveCount(0);
      await expect(page.getByRole("radiogroup", { name: "Color theme" })).toBeVisible();
      for (const option of ["System theme", "Light theme", "Dark theme"]) {
        await expect(page.getByRole("radio", { name: option })).toBeVisible();
      }

      const brand = page.locator(".benchbox-site-header__logo");
      await expect(brand).toHaveText(HEADER_BRAND.label);
      await expect(brand).toHaveAttribute("href", HEADER_BRAND.href);
    });
  }

  const STATIC_AUTHORED_SURFACES = STATIC_SURFACES.filter(({ surface }) => surface !== "docs");

  test("static authored surfaces mark the expected aria-current link", async ({ page }) => {
    for (const { surface, path } of STATIC_AUTHORED_SURFACES) {
      const html = readStaticSurface(path);
      await loadStaticHeader(page, html);

      const nav = page.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL });
      const expectedActive = HEADER_LINKS.find((link) => link.activeOnSurface === surface);
      if (expectedActive) {
        await expect(nav.getByRole("link", { name: expectedActive.label })).toHaveAttribute("aria-current", "page");
      }
      for (const link of HEADER_LINKS) {
        if (link === expectedActive) continue;
        await expect(nav.getByRole("link", { name: link.label })).not.toHaveAttribute("aria-current", "page");
      }
    }
  });
});
