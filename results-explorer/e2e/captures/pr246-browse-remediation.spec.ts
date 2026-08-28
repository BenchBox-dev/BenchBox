/**
 * PR #246 browse/platform remediation captures.
 *
 * Skipped by default; opt in with PR246_BROWSE_CAPTURE=1. The output mirrors
 * the PR #246 benchmark/platform evidence matrix and writes a small manifest
 * so the TODO closeout can cite durable after-screenshots.
 */

import { mkdirSync, writeFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { expect, test } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../..");
const TODAY = new Date().toISOString().slice(0, 10);
const OUT = path.join(
  REPO_ROOT,
  "_project",
  "audits",
  "screenshots",
  `results-explorer-pr246-browse-remediation-${TODAY}`,
);

interface CaptureRoute {
  filename: string;
  url: string;
  width: number;
  highContrast?: boolean;
}

const STANDARD_WIDTHS = [390, 768, 1280, 1600];

const ROUTES: CaptureRoute[] = [
  ...STANDARD_WIDTHS.map((width) => ({
    filename: `benchmark-tpch-${width}.png`,
    url: "/results/tpch/?sf=0.01&phase=standard",
    width,
  })),
  {
    filename: "benchmark-tpch-list-1280.png",
    url: "/results/tpch/?sf=0.01&phase=standard&view=list",
    width: 1280,
  },
  {
    filename: "benchmark-tpch-high-contrast-1280.png",
    url: "/results/tpch/?sf=0.01&phase=standard",
    width: 1280,
    highContrast: true,
  },
  ...STANDARD_WIDTHS.map((width) => ({
    filename: `benchmark-star-schema-${width}.png`,
    url: "/results/star_schema/?sf=0.01&phase=standard",
    width,
  })),
  ...STANDARD_WIDTHS.map((width) => ({
    filename: `platform-duckdb-${width}.png`,
    url: "/results/p/duckdb/",
    width,
  })),
  ...STANDARD_WIDTHS.map((width) => ({
    filename: `platform-datafusion-${width}.png`,
    url: "/results/p/datafusion/",
    width,
  })),
];

test.describe("@pr246-capture browse/platform remediation", () => {
  test.skip(process.env.PR246_BROWSE_CAPTURE !== "1", "set PR246_BROWSE_CAPTURE=1 to refresh");
  test.setTimeout(240_000);

  test("captures benchmark and platform PR #246 routes", async ({ browser }) => {
    mkdirSync(OUT, { recursive: true });
    const captured: Array<{ filename: string; url: string; width: number; highContrast: boolean }> = [];

    for (const route of ROUTES) {
      const context = await browser.newContext({ viewport: { width: route.width, height: 900 } });
      const page = await context.newPage();
      try {
        await page.goto(route.url, { waitUntil: "domcontentloaded" });
        await page.waitForLoadState("load", { timeout: 10_000 }).catch(() => {});
        await expect(page.locator("body")).not.toContainText(
          /Binder Error|Stack trace|No results found for platform|No published results yet/i,
        );
        if (route.highContrast) {
          await page.getByRole("button", { name: /High contrast|Reduced color/ }).click();
        }
        await page.waitForTimeout(800);
        await page.screenshot({
          path: path.join(OUT, route.filename),
          fullPage: true,
        });
        captured.push({
          filename: route.filename,
          url: route.url,
          width: route.width,
          highContrast: route.highContrast ?? false,
        });
      } finally {
        await context.close();
      }
    }

    writeFileSync(
      path.join(OUT, "screenshot-manifest.json"),
      `${JSON.stringify({ captured_at: new Date().toISOString(), routes: captured }, null, 2)}\n`,
      "utf8",
    );
  });
});
