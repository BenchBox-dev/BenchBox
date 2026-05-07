/**
 * PR #246 Result Detail / Compare remediation captures.
 *
 * Skipped by default; opt in with PR246_RESULT_COMPARE_CAPTURE=1. The output
 * mirrors the PR #246 Result Detail and Compare evidence matrix and writes a
 * small manifest so the TODO closeout can cite durable after-screenshots.
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
  `results-explorer-pr246-result-compare-remediation-${TODAY}`,
);

const DUCKDB_ID = "tpch-duckdb-sf0.01-20260403-010ee756";
const AWS_ID = "tpch-fixture-aws-sql-sf0.01-20260403-e73da6ce";
const DUCKDB_SF01_ID = "0820b170";
const WIDTHS = [390, 768, 1280, 1600];

interface CaptureRoute {
  filename: string;
  url: string;
  width: number;
  readyText: RegExp;
}

const ROUTES: CaptureRoute[] = [
  ...WIDTHS.map((width) => ({
    filename: `result-detail-duckdb-${width}.png`,
    url: `/results/r/${DUCKDB_ID}`,
    width,
    readyText: /TPC-H\s+-\s+DuckDB/,
  })),
  ...WIDTHS.map((width) => ({
    filename: `compare-duckdb-aws-${width}.png`,
    url: `/results/compare?ids=${DUCKDB_ID},${AWS_ID}`,
    width,
    readyText: /TPC-H Comparison/,
  })),
  {
    filename: "compare-mixed-scale-valid-1280.png",
    url: `/results/compare?ids=${DUCKDB_ID},${DUCKDB_SF01_ID}`,
    width: 1280,
    readyText: /TPC-H Comparison/,
  },
];

test.describe("@pr246-capture Result Detail / Compare remediation", () => {
  test.skip(
    process.env.PR246_RESULT_COMPARE_CAPTURE !== "1",
    "set PR246_RESULT_COMPARE_CAPTURE=1 to refresh",
  );
  test.setTimeout(240_000);

  test("captures Result Detail and Compare PR #246 routes", async ({ browser }) => {
    mkdirSync(OUT, { recursive: true });
    const captured: Array<{ filename: string; url: string; width: number }> = [];

    for (const route of ROUTES) {
      const context = await browser.newContext({ viewport: { width: route.width, height: 900 } });
      const page = await context.newPage();
      try {
        await page.goto(route.url, { waitUntil: "domcontentloaded" });
        await page.waitForLoadState("load", { timeout: 10_000 }).catch(() => {});
        await expect(page.getByText(route.readyText).first()).toBeVisible({ timeout: 30_000 });
        await expect(page.locator("body")).not.toContainText(/Binder Error|Stack trace|Cannot compare/i);
        await page.waitForTimeout(800);
        await page.screenshot({ path: path.join(OUT, route.filename), fullPage: true });
        captured.push({ filename: route.filename, url: route.url, width: route.width });
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
