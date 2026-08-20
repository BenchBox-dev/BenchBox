import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

import {
  compareVisualManifests,
  PUBLIC_SITE_CAPTURE_PROFILE,
  type VisualCapture,
  type VisualManifest,
} from "../../src/lib/publicSiteVisual";
import { waitForDataLoaded } from "../support/fixtures";

const OUTPUT = path.resolve(
  process.env.PUBLIC_SITE_VISUAL_OUTPUT ?? path.join("test-results", "public-site-visual"),
);
const BASELINE = process.env.PUBLIC_SITE_VISUAL_BASELINE
  ? path.resolve(process.env.PUBLIC_SITE_VISUAL_BASELINE)
  : undefined;
const REQUIRE_BASELINE = process.env.PUBLIC_SITE_VISUAL_REQUIRE_BASELINE === "1";
const SOURCE_SHA = process.env.PUBLIC_SITE_VISUAL_SOURCE_SHA ?? "unknown";
const VIEWPORTS = [390, 768, 1280, 1600] as const;
const ROUTES = [
  { slug: "landing", path: "/", heading: /benchbox/i },
  { slug: "getting-started", path: "/docs/usage/getting-started.html", heading: /getting started/i },
  {
    slug: "release-overview",
    path: "/blog/2026-05-18-v0-3-0-release-overview.html",
    heading: /v0\.3\.0/i,
  },
  { slug: "results", path: "/results/", heading: /results/i, ready: /Recent Results/i },
] as const;
const MANIFEST = path.join(OUTPUT, "manifest.json");

// Each Results viewport can spend up to 46 seconds on bounded cold-snapshot
// recovery. Give the four independent waits enough aggregate budget while
// keeping the per-attempt limits in `waitForDataLoaded` unchanged.
test.describe.configure({ mode: "serial", timeout: 240_000 });
// The public-site suite requires the assembled Pages-shaped site. Keep it out
// of the Explorer-only blocking command unless that site is explicitly mounted.
test.skip(!process.env.E2E_PAGES_SHAPED || !process.env.E2E_SITE_DIR, "requires E2E_PAGES_SHAPED and E2E_SITE_DIR");

test("captures the public route and viewport matrix", async ({ browser }) => {
  await mkdir(OUTPUT, { recursive: true });
  const captures: VisualCapture[] = [];

  for (const width of VIEWPORTS) {
    for (const route of ROUTES) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      await page.goto(route.path, { waitUntil: "networkidle" });
      await expect(page.locator("body")).toContainText(route.heading);
      if ("ready" in route) await waitForDataLoaded(page, route.ready);
      if (route.slug === "landing") {
        for (const selector of [".feature-card", ".benchmark-card", ".install-step"]) {
          const cards = page.locator(selector);
          for (let index = 0; index < (await cards.count()); index += 1) {
            const card = cards.nth(index);
            await card.scrollIntoViewIfNeeded();
            await expect(card).toBeVisible();
            await expect
              .poll(() => card.evaluate((element) => getComputedStyle(element).opacity))
              .toBe("1");
            await expect
              .poll(() =>
                card.evaluate((element) => {
                  const transform = getComputedStyle(element).transform;
                  return transform === "none" || new DOMMatrixReadOnly(transform).isIdentity;
                }),
              )
              .toBe(true);
          }
        }
      }
      // Disable timing only after production IntersectionObserver behavior has
      // reached and proved the visible end state.
      await page.addStyleTag({
        content: `
          .feature-card, .benchmark-card, .install-step {
            transition: none !important;
            animation: none !important;
          }
        `,
      });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      expect(overflow, `${route.path} overflows at ${width}px`).toBe(false);

      const filename = `${route.slug}-${width}.png`;
      const screenshotPath = path.join(OUTPUT, filename);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      const digest = createHash("sha256").update(await readFile(screenshotPath)).digest("hex");
      captures.push({ digest, filename, route: route.path, viewport_width: width });
      await context.close();
    }
  }

  const manifest = {
    browser: "chromium",
    capture_profile: PUBLIC_SITE_CAPTURE_PROFILE,
    captures,
    source_sha: SOURCE_SHA,
    viewports: VIEWPORTS,
  };
  await writeFile(MANIFEST, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

  if (!REQUIRE_BASELINE) {
    expect(REQUIRE_BASELINE, "PUBLIC_SITE_VISUAL_BASELINE is required for comparison").toBe(false);
    return;
  }

  if (!BASELINE) {
    throw new Error("PUBLIC_SITE_VISUAL_BASELINE is required when comparison is enabled");
  }
  const baseline = JSON.parse(await readFile(path.join(BASELINE, "manifest.json"), "utf8")) as typeof manifest;
  expect(baseline.browser).toBe("chromium");
  if (process.env.PUBLIC_SITE_VISUAL_BASE_SHA) {
    expect(baseline.source_sha).toBe(process.env.PUBLIC_SITE_VISUAL_BASE_SHA);
  }
  const { missing, unexpected, changed } = compareVisualManifests(
    baseline as VisualManifest,
    manifest as VisualManifest,
  );
  expect(
    { missing, unexpected },
    "visual baseline route/viewport matrix must match exactly",
  ).toEqual({ missing: [], unexpected: [] });
  expect(changed, `visual baseline mismatch; changed captures: ${changed.join(", ")}`).toEqual([]);
});
