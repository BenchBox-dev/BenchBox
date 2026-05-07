/**
 * PR #246 responsive/navigation/overflow remediation captures.
 *
 * Skipped by default; opt in with PR246_RESPONSIVE_CAPTURE=1. Captures the
 * mobile/tablet route matrix named by the remediation TODO and writes a small
 * manifest for closeout evidence.
 */

import { mkdirSync, writeFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { expect, test, type Page } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../..");
const TODAY = new Date().toISOString().slice(0, 10);
const OUT = path.join(
  REPO_ROOT,
  "_project",
  "audits",
  "screenshots",
  `results-explorer-pr246-responsive-remediation-${TODAY}`,
);

const SHORT_DUCKDB = "ba6a8c83";
const SHORT_DATAFUSION = "5e6c5eba";
const DETAIL_ID = "tpch-duckdb-sf0.01-20260403-010ee756";
const WIDTHS = [390, 768] as const;

interface CaptureRoute {
  filename: string;
  url: string;
  width: number;
  ready: RegExp;
  drawer?: boolean;
  hintTestId?: string;
}

const ROUTES: CaptureRoute[] = [
  ...WIDTHS.map((width) => ({
    filename: `home-${width}.png`,
    url: "/results/",
    width,
    ready: /Recent Results/i,
    hintTestId: "recent-results-scroll-hint",
  })),
  ...WIDTHS.map((width) => ({
    filename: `benchmark-tpch-${width}.png`,
    url: "/results/tpch/?sf=0.01&phase=standard",
    width,
    ready: /TPC-H Results/i,
    hintTestId: width >= 768 ? "query-heatmap-scroll-hint" : undefined,
  })),
  ...WIDTHS.map((width) => ({
    filename: `benchmark-star-schema-${width}.png`,
    url: "/results/star_schema/?sf=0.01&phase=standard",
    width,
    ready: /SSB Results/i,
    hintTestId: width >= 768 ? "query-heatmap-scroll-hint" : undefined,
  })),
  ...WIDTHS.map((width) => ({
    filename: `platform-duckdb-${width}.png`,
    url: "/results/p/duckdb/",
    width,
    ready: /DuckDB Results/i,
  })),
  ...WIDTHS.map((width) => ({
    filename: `platform-datafusion-${width}.png`,
    url: "/results/p/datafusion/",
    width,
    ready: /DataFusion Results/i,
  })),
  ...WIDTHS.map((width) => ({
    filename: `result-detail-duckdb-${width}.png`,
    url: `/results/r/${DETAIL_ID}`,
    width,
    ready: /Query Timings/i,
    hintTestId: "detail-timings-scroll-hint",
  })),
  ...WIDTHS.map((width) => ({
    filename: `compare-duckdb-datafusion-${width}.png`,
    url: `/results/compare?ids=${SHORT_DUCKDB},${SHORT_DATAFUSION}`,
    width,
    ready: /TPC-H Comparison/i,
    hintTestId: "query-diff-scroll-hint",
  })),
  ...WIDTHS.map((width) => ({
    filename: `query-${width}.png`,
    url: "/results/query",
    width,
    ready: /matching result bundle/i,
    hintTestId: "query-results-scroll-hint",
  })),
  {
    filename: "query-mobile-filter-drawer-390.png",
    url: "/results/query",
    width: 390,
    ready: /matching result bundle/i,
    drawer: true,
  },
];

test.describe("@pr246-capture responsive remediation", () => {
  test.skip(process.env.PR246_RESPONSIVE_CAPTURE !== "1", "set PR246_RESPONSIVE_CAPTURE=1 to refresh");
  test.setTimeout(180_000);

  test("captures mobile and tablet responsive evidence", async ({ browser }) => {
    mkdirSync(OUT, { recursive: true });
    const captured: Array<{ filename: string; url: string; width: number; drawer: boolean }> = [];

    for (const route of ROUTES) {
      const context = await browser.newContext({ viewport: { width: route.width, height: 900 } });
      const page = await context.newPage();
      try {
        await page.goto(route.url, { waitUntil: "domcontentloaded" });
        await page.waitForLoadState("load", { timeout: 10_000 }).catch(() => {});
        await expect(page.locator("body")).not.toContainText(/Binder Error|Stack trace|No published results yet/i);
        await expect(page.getByTestId("results-explorer-nav").getByRole("link", { name: "Query" })).toBeVisible();
        await expect(page.getByText(route.ready).first()).toBeVisible({ timeout: 20_000 });
        await expectNoUnexpectedOverflow(page);
        if (route.hintTestId) {
          await expect(page.getByTestId(route.hintTestId).first()).toBeVisible();
        }
        if (route.drawer) {
          await page.getByTestId("query-mobile-filter-drawer").getByRole("button", { name: /^Filters/ }).click();
          await expect(page.getByRole("dialog", { name: "Filter results" })).toBeVisible();
        }
        await page.waitForTimeout(800);
        await page.screenshot({ path: path.join(OUT, route.filename), fullPage: true });
        captured.push({ filename: route.filename, url: route.url, width: route.width, drawer: route.drawer ?? false });
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

async function expectNoUnexpectedOverflow(page: Page) {
  const offenders = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    return Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .filter((element) => {
        if (element.closest(".overflow-x-auto") || element.closest("svg[role='img']")) return false;
        const rect = element.getBoundingClientRect();
        return rect.right > viewportWidth + 1 || rect.left < -1;
      })
      .map((element) => ({ tag: element.tagName, text: (element.textContent ?? "").trim().slice(0, 80) }))
      .slice(0, 5);
  });
  expect(offenders).toEqual([]);
}
