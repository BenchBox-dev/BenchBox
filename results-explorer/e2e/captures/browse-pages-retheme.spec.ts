/**
 * Browse-page retheme post-fix re-audit captures.
 *
 * Records 390/768/1280/1600 screenshots for the four routes named by
 * `results-explorer-retheme-browse-pages` w1, on top of the
 * theme-system-foundation tokens. Skipped by default; opt in with
 * `RETHEME_CAPTURE=1` to refresh artifacts under
 * `_project/audits/screenshots/results-retheme-browse-pages-after-fix-<date>/`.
 */

import { mkdirSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { test } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../..");
const TODAY = new Date().toISOString().slice(0, 10);
const OUT = path.join(
  REPO_ROOT,
  "_project",
  "audits",
  "screenshots",
  `results-retheme-browse-pages-after-fix-${TODAY}`,
);

const ROUTES: Array<{ slug: string; url: string }> = [
  { slug: "benchmark-tpch-sf001", url: "/results/tpch/?sf=0.01&phase=standard" },
  { slug: "benchmark-star-schema-sf01", url: "/results/star_schema/?sf=0.1&phase=power" },
  { slug: "platform-duckdb", url: "/results/p/duckdb/" },
  { slug: "platform-polars", url: "/results/p/polars/" },
];
const WIDTHS = [390, 768, 1280, 1600];

test.describe("@retheme-capture browse-pages re-audit", () => {
  test.skip(process.env.RETHEME_CAPTURE !== "1", "set RETHEME_CAPTURE=1 to refresh");
  test.setTimeout(180_000);

  test("captures benchmark and platform routes at 4 widths", async ({ browser }) => {
    mkdirSync(OUT, { recursive: true });
    for (const { slug, url } of ROUTES) {
      for (const width of WIDTHS) {
        const context = await browser.newContext({ viewport: { width, height: 900 } });
        const page = await context.newPage();
        try {
          await page.goto(url, { waitUntil: "domcontentloaded" });
          await page.waitForLoadState("load", { timeout: 10_000 }).catch(() => {});
          await page.waitForTimeout(800);
          await page.screenshot({
            path: path.join(OUT, `${slug}-${width}.png`),
            fullPage: true,
          });
        } finally {
          await context.close();
        }
      }
    }
  });
});
