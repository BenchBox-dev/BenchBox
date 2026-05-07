/**
 * Final release-gate capture for `results-explorer-retheme-release-gate` w3.
 *
 * Records 390/768/1280/1600 screenshots for every route in the QA matrix
 * after the full retheme is on develop. Skipped by default; opt in with
 * `RETHEME_CAPTURE=1` to refresh artifacts under
 * `_project/audits/screenshots/results-explorer-retheme-final-<date>/`.
 *
 * Console messages and non-2xx network responses are captured to a
 * sibling `console-network-<date>.log` so the readiness report has
 * concrete evidence (w2 cold-load checks).
 */

import { mkdirSync, appendFileSync, writeFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { test } from "@playwright/test";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../..");
const TODAY = new Date().toISOString().slice(0, 10);
const OUT = path.join(
  REPO_ROOT,
  "_project",
  "audits",
  "screenshots",
  `results-explorer-retheme-final-${TODAY}`,
);
const LOG = path.join(OUT, `console-network-${TODAY}.log`);

const ROUTES: Array<{ slug: string; url: string; readyText: RegExp }> = [
  { slug: "home", url: "/results/", readyText: /Cross-Benchmark Leaderboard/ },
  { slug: "benchmark-tpch-sf001", url: "/results/tpch/?sf=0.01&phase=standard", readyText: /TPC-H Results/ },
  {
    slug: "benchmark-star-schema-sf01",
    url: "/results/star_schema/?sf=0.1&phase=power",
    readyText: /SSB Results/,
  },
  { slug: "platform-duckdb", url: "/results/p/duckdb/", readyText: /DuckDB Results/ },
  { slug: "platform-datafusion", url: "/results/p/datafusion/", readyText: /DataFusion Results/ },
  { slug: "platform-polars", url: "/results/p/polars/", readyText: /Polars Results/ },
  {
    slug: "result-detail-tpch-duckdb",
    url: "/results/r/tpch-duckdb-sf0.01-20260403-010ee756",
    readyText: /Query Timings/,
  },
  { slug: "compare-same-cohort", url: "/results/compare?ids=ba6a8c83,5e6c5eba", readyText: /TPC-H Comparison/ },
  {
    slug: "compare-mismatch-benchmark",
    url: "/results/compare?ids=ba6a8c83,0f0add9f",
    readyText: /Mixed Benchmark Comparison/,
  },
  { slug: "compare-empty", url: "/results/compare", readyText: /Cannot compare/ },
  { slug: "query", url: "/results/query", readyText: /matching result bundle/ },
  { slug: "not-found", url: "/results/clickbench/", readyText: /No published results yet/ },
];
const WIDTHS = [390, 768, 1280, 1600];

test.describe("@retheme-capture release-final", () => {
  test.skip(process.env.RETHEME_CAPTURE !== "1", "set RETHEME_CAPTURE=1 to refresh");
  test.setTimeout(360_000);

  test("captures every QA matrix route at 4 widths with console + network log", async ({ browser }) => {
    mkdirSync(OUT, { recursive: true });
    writeFileSync(LOG, `# Release-gate cold-load log ${TODAY}\n`);

    for (const { slug, url, readyText } of ROUTES) {
      for (const width of WIDTHS) {
        const context = await browser.newContext({ viewport: { width, height: 900 } });
        const page = await context.newPage();
        page.on("console", (msg) => {
          if (msg.type() === "error" || msg.type() === "warning") {
            appendFileSync(LOG, `[${slug}-${width}] console.${msg.type()}: ${msg.text()}\n`);
          }
        });
        page.on("response", (response) => {
          if (response.status() >= 400) {
            appendFileSync(
              LOG,
              `[${slug}-${width}] HTTP ${response.status()} ${response.url()}\n`,
            );
          }
        });
        page.on("pageerror", (err) => {
          appendFileSync(LOG, `[${slug}-${width}] pageerror: ${err.message}\n`);
        });

        try {
          await page.goto(url, { waitUntil: "domcontentloaded" });
          await waitForShell(page);
          await waitForDataLoaded(page, readyText);
          await page.waitForLoadState("load", { timeout: 10_000 }).catch(() => {});
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
