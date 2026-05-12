/**
 * PR #246 final remediation evidence gate.
 *
 * Skipped by default; opt in with PR246_FINAL_CAPTURE=1. Captures the full
 * baseline screenshot matrix into one dated final-evidence directory and logs
 * route, console, network, and loaded-state evidence for closeout review.
 */

import { execFileSync } from "child_process";
import { appendFileSync, mkdirSync, writeFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { expect, test, type Page } from "@playwright/test";
import { assertEvidenceCaptureMatchesDevelop } from "../../src/lib/evidenceGit";
import { waitForDataLoaded, waitForShell } from "../support/fixtures";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../..");
const TODAY = new Date().toISOString().slice(0, 10);
const OUT = path.join(
  REPO_ROOT,
  "_project",
  "audits",
  "screenshots",
  `results-explorer-pr246-final-${TODAY}`,
);
const LOG = path.join(OUT, `console-network-${TODAY}.log`);
const MANIFEST = path.join(OUT, "screenshot-manifest.json");

const DUCKDB_ID = "tpch-duckdb-sf0.01-20260403-010ee756";
const AWS_ID = "tpch-fixture-aws-sql-sf0.01-20260403-e73da6ce";
const DUCKDB_SF01_ID = "0820b170";
const WIDTHS = [390, 768, 1280, 1600] as const;

interface CaptureRoute {
  baseline: string;
  url: string;
  width: number;
  readyText: RegExp;
  highContrast?: boolean;
  openMobileFilters?: boolean;
  requireQueryNav?: boolean;
}

const ROUTES: CaptureRoute[] = [
  {
    baseline: "browser-use-home-live-fullpage.png",
    url: "/results/",
    width: 1280,
    readyText: /Cross-Benchmark Leaderboard/i,
  },
  ...WIDTHS.map((width) => ({
    baseline: `home-${width}.png`,
    url: "/results/",
    width,
    readyText: /Cross-Benchmark Leaderboard/i,
    requireQueryNav: width <= 768,
  })),
  {
    baseline: "home-speedup-mobile-390.png",
    url: "/results/?mode=speedup",
    width: 390,
    readyText: /Cross-Benchmark Leaderboard/i,
    requireQueryNav: true,
  },
  {
    baseline: "home-speedup-1280.png",
    url: "/results/?mode=speedup",
    width: 1280,
    readyText: /Cross-Benchmark Leaderboard/i,
  },
  ...WIDTHS.map((width) => ({
    baseline: `benchmark-tpch-${width}.png`,
    url: "/results/tpch/?sf=0.01&phase=standard",
    width,
    readyText: /TPC-H Results/i,
    requireQueryNav: width <= 768,
  })),
  {
    baseline: "benchmark-tpch-list-1280.png",
    url: "/results/tpch/?sf=0.01&phase=standard&view=list",
    width: 1280,
    readyText: /TPC-H Results/i,
  },
  {
    baseline: "benchmark-tpch-high-contrast-1280.png",
    url: "/results/tpch/?sf=0.01&phase=standard",
    width: 1280,
    readyText: /TPC-H Results/i,
    highContrast: true,
  },
  ...WIDTHS.map((width) => ({
    baseline: `benchmark-star-schema-${width}.png`,
    url: "/results/star_schema/?sf=0.01&phase=standard",
    width,
    readyText: /SSB Results/i,
    requireQueryNav: width <= 768,
  })),
  ...WIDTHS.map((width) => ({
    baseline: `platform-duckdb-${width}.png`,
    url: "/results/p/duckdb/",
    width,
    readyText: /DuckDB Results/i,
    requireQueryNav: width <= 768,
  })),
  ...WIDTHS.map((width) => ({
    baseline: `platform-datafusion-${width}.png`,
    url: "/results/p/datafusion/",
    width,
    readyText: /DataFusion Results|No results found for platform: datafusion/i,
    requireQueryNav: width <= 768,
  })),
  ...WIDTHS.map((width) => ({
    baseline: `result-detail-duckdb-${width}.png`,
    url: `/results/r/${DUCKDB_ID}`,
    width,
    readyText: /TPC-H\s+-\s+DuckDB|Query Timings/i,
    requireQueryNav: width <= 768,
  })),
  ...WIDTHS.map((width) => ({
    baseline: `compare-duckdb-aws-${width}.png`,
    url: `/results/compare?ids=${DUCKDB_ID},${AWS_ID}`,
    width,
    readyText: /TPC-H Comparison/i,
    requireQueryNav: width <= 768,
  })),
  {
    baseline: "compare-mixed-scale-valid-1280.png",
    url: `/results/compare?ids=${DUCKDB_ID},${DUCKDB_SF01_ID}`,
    width: 1280,
    readyText: /TPC-H Comparison/i,
  },
  ...WIDTHS.map((width) => ({
    baseline: `query-${width}.png`,
    url: "/results/query",
    width,
    readyText: /Results Query Workbench|matching result bundle/i,
    requireQueryNav: width <= 768,
  })),
  {
    baseline: "query-mobile-filter-drawer-390.png",
    url: "/results/query",
    width: 390,
    readyText: /Results Query Workbench|matching result bundle/i,
    openMobileFilters: true,
    requireQueryNav: true,
  },
];

function resolveDevelopSha(): string {
  execFileSync("git", ["fetch", "--no-tags", "origin", "develop"], { cwd: REPO_ROOT, stdio: "ignore" });
  return execFileSync("git", ["rev-parse", "origin/develop"], { cwd: REPO_ROOT, encoding: "utf8" }).trim();
}

function resolveHeadSha(): string {
  return execFileSync("git", ["rev-parse", "HEAD"], { cwd: REPO_ROOT, encoding: "utf8" }).trim();
}

function logEvent(message: string): void {
  appendFileSync(LOG, `${message}\n`);
}

test.describe("@pr246-capture final evidence gate", () => {
  test.skip(process.env.PR246_FINAL_CAPTURE !== "1", "set PR246_FINAL_CAPTURE=1 to refresh");
  test.setTimeout(900_000);

  test("captures every PR #246 baseline screenshot after remediation", async ({ browser }) => {
    mkdirSync(OUT, { recursive: true });
    const developSha = resolveDevelopSha();
    const headSha = resolveHeadSha();
    assertEvidenceCaptureMatchesDevelop({ developSha, headSha });
    writeFileSync(LOG, `# PR #246 final evidence log ${TODAY}\n# develop_sha: ${developSha}\n# head_sha: ${headSha}\n`);
    const captured: Array<{
      baseline: string;
      after: string;
      url: string;
      finalUrl: string;
      width: number;
      title: string;
      h1: string;
      highContrast: boolean;
      openMobileFilters: boolean;
      screenshotMode: "fullPage" | "viewport-fallback";
    }> = [];

    for (const route of ROUTES) {
      const context = await browser.newContext({ viewport: { width: route.width, height: 900 } });
      const page = await context.newPage();
      page.on("console", (msg) => {
        if (msg.type() === "error" || msg.type() === "warning") {
          logEvent(`[${route.baseline}] console.${msg.type()}: ${msg.text()}`);
        }
      });
      page.on("response", (response) => {
        if (response.status() >= 400) {
          logEvent(`[${route.baseline}] HTTP ${response.status()} ${response.url()}`);
        }
      });
      page.on("pageerror", (err) => {
        logEvent(`[${route.baseline}] pageerror: ${err.message}`);
      });

      try {
        await page.goto(route.url, { waitUntil: "domcontentloaded" });
        await waitForShell(page);
        await waitForDataLoaded(page, route.readyText);
        await page.waitForLoadState("load", { timeout: 10_000 }).catch(() => {});
        await expect(page.locator("body")).not.toContainText(
          /Binder Error|Stack trace|Results snapshot incomplete|undefined ID|raw internal error/i,
        );
        if (route.requireQueryNav) {
          await expect(page.getByTestId("results-explorer-nav").getByRole("link", { name: "Query" })).toBeVisible();
        }
        if (route.highContrast) {
          await page.getByRole("button", { name: /High contrast|Reduced color/ }).click({ timeout: 5_000 });
        }
        if (route.openMobileFilters) {
          await page.getByRole("button", { name: /^Filters/ }).click();
          await expect(page.getByRole("dialog", { name: "Filter results" })).toBeVisible();
        }
        await expectNoUnexpectedOverflow(page);
        await page.waitForTimeout(500);
        const screenshotMode = await captureScreenshot(page, path.join(OUT, route.baseline), route.baseline);
        captured.push({
          baseline: route.baseline,
          after: route.baseline,
          url: route.url,
          finalUrl: page.url(),
          width: route.width,
          title: await page.title(),
          h1: await firstHeadingText(page),
          highContrast: route.highContrast ?? false,
          openMobileFilters: route.openMobileFilters ?? false,
          screenshotMode,
        });
      } finally {
        await context.close();
      }
    }

    writeFileSync(
      MANIFEST,
      `${JSON.stringify(
        {
          captured_at: new Date().toISOString(),
          develop_sha: developSha,
          head_sha: headSha,
          baseline_audit: "_project/audits/results-explorer-hierarchy-usability-data-audit-20260507.md",
          screenshot_dir: path.relative(REPO_ROOT, OUT),
          console_network_log: path.relative(REPO_ROOT, LOG),
          routes: captured,
        },
        null,
        2,
      )}\n`,
      "utf8",
    );
  });
});

async function firstHeadingText(page: Page): Promise<string> {
  return page
    .locator("h1")
    .first()
    .textContent()
    .then((text) => (text ?? "").trim());
}

async function captureScreenshot(
  page: Page,
  screenshotPath: string,
  baseline: string,
): Promise<"fullPage" | "viewport-fallback"> {
  try {
    await page.screenshot({ path: screenshotPath, fullPage: true, timeout: 30_000 });
    return "fullPage";
  } catch (err) {
    logEvent(`[${baseline}] fullPage screenshot fallback: ${err instanceof Error ? err.message : String(err)}`);
    await page.screenshot({ path: screenshotPath, fullPage: false, timeout: 15_000 });
    return "viewport-fallback";
  }
}

async function expectNoUnexpectedOverflow(page: Page): Promise<void> {
  const offenders = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const isInsideHorizontalScroller = (element: HTMLElement) => {
      for (let current = element.parentElement; current && current !== document.body; current = current.parentElement) {
        const overflowX = window.getComputedStyle(current).overflowX;
        if ((overflowX === "auto" || overflowX === "scroll") && current.scrollWidth > current.clientWidth + 1) {
          return true;
        }
      }
      return false;
    };
    return Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .filter((element) => {
        if (element.closest("table")) return false;
        if (isInsideHorizontalScroller(element)) return false;
        if (element.closest(".overflow-x-auto") || element.closest("svg[role='img']")) return false;
        const rect = element.getBoundingClientRect();
        return rect.right > viewportWidth + 1 || rect.left < -1;
      })
      .map((element) => ({
        tag: element.tagName,
        text: (element.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 80),
      }))
      .slice(0, 5);
  });
  expect(offenders).toEqual([]);
}
