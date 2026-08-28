/**
 * Cross-route responsive/a11y capture for
 * `results-explorer-retheme-responsive-accessibility` w7.
 *
 * Records 390/768/1280/1600 screenshots for every primary route on top
 * of the rethemed Explorer. Skipped by default; opt in with
 * `RETHEME_CAPTURE=1` to refresh artifacts under
 * `_project/audits/screenshots/results-retheme-responsive-a11y-<date>/`.
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
  `results-retheme-responsive-a11y-${TODAY}`,
);

const ROUTES: Array<{ slug: string; url: string }> = [
  { slug: "home", url: "/results/" },
  { slug: "benchmark-tpch", url: "/results/tpch/?sf=0.01&phase=standard" },
  { slug: "platform-duckdb", url: "/results/p/duckdb/" },
  { slug: "compare", url: "/results/compare" },
  { slug: "query", url: "/results/query" },
];
const WIDTHS = [390, 768, 1280, 1600];

test.describe("@retheme-capture responsive-a11y pass", () => {
  test.skip(process.env.RETHEME_CAPTURE !== "1", "set RETHEME_CAPTURE=1 to refresh");
  test.setTimeout(240_000);

  test("captures every primary route at 4 widths", async ({ browser }) => {
    mkdirSync(OUT, { recursive: true });
    for (const { slug, url } of ROUTES) {
      for (const width of WIDTHS) {
        const context = await browser.newContext({ viewport: { width, height: 900 } });
        const page = await context.newPage();
        try {
          await page.goto(url, { waitUntil: "domcontentloaded" });
          await page.waitForLoadState("load", { timeout: 10_000 }).catch(() => {});
          await page.waitForTimeout(1000);
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
