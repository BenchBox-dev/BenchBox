/**
 * PR #246 Query Workbench remediation captures.
 *
 * Skipped by default; opt in with PR246_QUERY_CAPTURE=1. The output mirrors
 * the PR #246 Query evidence matrix and writes a small manifest so the TODO
 * closeout can cite durable after-screenshots.
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
  `results-explorer-pr246-query-remediation-${TODAY}`,
);

interface CaptureRoute {
  filename: string;
  url: string;
  width: number;
  openMobileFilters?: boolean;
}

const WIDTHS = [390, 768, 1280, 1600];
const ROUTES: CaptureRoute[] = [
  ...WIDTHS.map((width) => ({
    filename: `query-${width}.png`,
    url: "/results/query",
    width,
  })),
  {
    filename: "query-mobile-filter-drawer-390.png",
    url: "/results/query",
    width: 390,
    openMobileFilters: true,
  },
];

test.describe("@pr246-capture Query Workbench remediation", () => {
  test.skip(process.env.PR246_QUERY_CAPTURE !== "1", "set PR246_QUERY_CAPTURE=1 to refresh");
  test.setTimeout(180_000);

  test("captures Query Workbench PR #246 routes", async ({ browser }) => {
    mkdirSync(OUT, { recursive: true });
    const captured: Array<{ filename: string; url: string; width: number; openMobileFilters: boolean }> = [];

    for (const route of ROUTES) {
      const context = await browser.newContext({ viewport: { width: route.width, height: 900 } });
      const page = await context.newPage();
      try {
        await page.goto(route.url, { waitUntil: "domcontentloaded" });
        await page.waitForLoadState("load", { timeout: 10_000 }).catch(() => {});
        await expect(page.getByRole("heading", { name: "Results Query Workbench" })).toBeVisible();
        await expect(page.getByTestId("query-result-summary")).toContainText(/matching result bundle/);
        await expect(page.locator("body")).not.toContainText(/Binder Error|Stack trace|Results snapshot incomplete/i);

        if (route.openMobileFilters) {
          await page.getByRole("button", { name: /^Filters/ }).click();
          await expect(page.getByRole("dialog", { name: "Filter results" })).toBeVisible();
        }

        await page.waitForTimeout(800);
        await page.screenshot({ path: path.join(OUT, route.filename), fullPage: true });
        captured.push({
          filename: route.filename,
          url: route.url,
          width: route.width,
          openMobileFilters: route.openMobileFilters ?? false,
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
