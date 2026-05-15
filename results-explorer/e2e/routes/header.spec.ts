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

// Static surfaces share `landing/shared/site-header.css` via the
// `benchbox-site-header` class contract. Results consumes the same contract
// through a Preact mirror in components/Layout.tsx that imports the same
// canonical labels/hrefs/CTA from src/components/headerContract.ts. This test
// loads each static HTML file directly and asserts label/href parity so any
// drift in either side fails the build.
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

test.describe("Global header", () => {
  test("@smoke preserves the global header contract on desktop", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    const globalNav = page.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL });
    await expect(globalNav.getByRole("link")).toHaveText(GLOBAL_LABELS);
    await expect(globalNav.getByRole("link", { name: "Results" })).toHaveAttribute("aria-current", "page");
    await expect(globalNav.getByRole("link", { name: HEADER_CTA.label })).toHaveAttribute("href", HEADER_CTA.href);
    await expect(page.getByRole("button", { name: /Theme: system/i })).toBeVisible();

    const explorerNav = page.getByRole("navigation", { name: "Results Explorer" });
    await expect(explorerNav.getByRole("link")).toHaveText(["Leaderboards", "Benchmarks", "Platforms", "Compare", "Query"]);
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

    const lightToggle = page.getByRole("button", { name: /Theme: system/i });
    await lightToggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-bb-theme-choice", "light");
    const lightBox = await measure();

    const darkToggle = page.getByRole("button", { name: /Theme: light/i });
    await darkToggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-bb-theme-choice", "dark");
    const darkBox = await measure();

    expect(Math.abs(darkBox.height - lightBox.height)).toBeLessThanOrEqual(0.5);
    expect(Math.abs(darkBox.width - lightBox.width)).toBeLessThanOrEqual(0.5);
  });

  test("Results renders no Explorer subnav links inside the global header", async ({ page }) => {
    await page.goto("/results/");
    await waitForShell(page);

    const globalNav = page.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL });
    for (const subnavLabel of ["Leaderboards", "Benchmarks", "Platforms", "Compare", "Query"]) {
      await expect(globalNav.getByRole("link", { name: subnavLabel, exact: true })).toHaveCount(0);
    }
  });
});

test.describe("Global header cross-surface parity", () => {
  // Reads `landing/index.html`, `landing/prompts/index.html` and
  // `docs/_templates/page.html` directly so the parity gate covers every
  // public surface that consumes the shared `benchbox-site-header` contract
  // without needing additional servers in the e2e harness.
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
      await expect(page.getByRole("button", { name: /Theme: (system|light|dark)\. Activate to switch theme\./i })).toBeVisible();

      const brand = page.locator(".benchbox-site-header__logo");
      await expect(brand).toHaveText(HEADER_BRAND.label);
      await expect(brand).toHaveAttribute("href", HEADER_BRAND.href);
    });
  }

  // Docs surface is built from a Sphinx Jinja template
  // (`docs/_templates/page.html`) whose `aria-current` markers are
  // conditional on `is_blog_page`. Loading the raw template bypasses Jinja
  // evaluation and exposes both branches, so this assertion is restricted to
  // fully-static surfaces. The labels/hrefs gate above still runs against
  // the Sphinx template, so any drift in the docs header still trips a
  // parity failure.
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
