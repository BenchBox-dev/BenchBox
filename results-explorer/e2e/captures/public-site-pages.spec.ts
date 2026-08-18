import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

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
  const captures: Array<Record<string, unknown>> = [];

  for (const width of VIEWPORTS) {
    for (const route of ROUTES) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      await page.goto(route.path, { waitUntil: "networkidle" });
      await expect(page.locator("body")).toContainText(route.heading);
      if ("ready" in route) await waitForDataLoaded(page, route.ready);
      // The landing page fades in `.feature-card`/`.benchmark-card`/`.install-step`
      // via an IntersectionObserver (landing/script.js) independent of
      // `networkidle`, so capture timing races the fade-in transition and
      // produces a non-deterministic screenshot digest at viewports where
      // those elements start in view. Force the settled end state before
      // every capture so the digest reflects layout, not animation timing.
      // Trade-off: this also means a real CSS regression that leaves one of
      // these elements permanently mis-transformed or invisible can no
      // longer be caught here, since the override always paints the
      // settled state regardless of what the page actually renders.
      await page.addStyleTag({
        content: `
          .feature-card, .benchmark-card, .install-step {
            opacity: 1 !important;
            transform: none !important;
            transition: none !important;
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
  const expected = new Map(baseline.captures.map((capture) => [`${capture.route}@${capture.viewport_width}`, capture.digest]));
  // Baselines produced by the initial implementation may contain a
  // `cold_results_load` marker.  Ignore those legacy digests during the
  // transition so the first readiness-enforced develop baseline can replace
  // them without making every intervening PR fail against a skeleton image.
  const legacyColdKeys = new Set(
    baseline.captures
      .filter((capture) => capture.cold_results_load === true)
      .map((capture) => `${capture.route}@${capture.viewport_width}`),
  );
  const actualKeys = new Set(captures.map((capture) => `${capture.route}@${capture.viewport_width}`));
  const missing = [...expected.keys()].filter((key) => !actualKeys.has(key));
  const unexpected = [...actualKeys].filter((key) => !expected.has(key));
  expect(
    { missing, unexpected },
    "visual baseline route/viewport matrix must match exactly",
  ).toEqual({ missing: [], unexpected: [] });
  const changed = captures
    .filter((capture) => !legacyColdKeys.has(`${capture.route}@${capture.viewport_width}`))
    .filter((capture) => expected.get(`${capture.route}@${capture.viewport_width}`) !== capture.digest)
    .map((capture) => `${capture.route}@${capture.viewport_width}`);
  expect(changed, `visual baseline mismatch; changed captures: ${changed.join(", ")}`).toEqual([]);
});
