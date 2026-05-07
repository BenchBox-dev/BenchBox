/**
 * PR #246 Home leaderboard remediation captures.
 *
 * Skipped by default; opt in with PR246_HOME_CAPTURE=1. Captures the Home
 * times/ranks/speedup mode matrix named by the PR #246 evidence TODO.
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
  `results-explorer-pr246-home-remediation-${TODAY}`,
);

const WIDTHS = [390, 768, 1280, 1600];
const MODES = ["times", "ranks", "speedup"] as const;

type Mode = (typeof MODES)[number];

function filename(mode: Mode, width: number): string {
  if (mode === "times") return `home-${width}.png`;
  if (mode === "speedup" && width === 390) return "home-speedup-mobile-390.png";
  if (mode === "speedup" && width === 1280) return "home-speedup-1280.png";
  return `home-${mode}-${width}.png`;
}

function url(mode: Mode): string {
  return mode === "times" ? "/results/" : `/results/?mode=${mode}`;
}

test.describe("@pr246-capture Home remediation", () => {
  test.skip(process.env.PR246_HOME_CAPTURE !== "1", "set PR246_HOME_CAPTURE=1 to refresh");
  test.setTimeout(180_000);

  test("captures Home modes at PR #246 viewport widths", async ({ browser }) => {
    mkdirSync(OUT, { recursive: true });
    const captured: Array<{ filename: string; url: string; width: number; mode: Mode }> = [];

    for (const mode of MODES) {
      for (const width of WIDTHS) {
        const context = await browser.newContext({ viewport: { width, height: 900 } });
        const page = await context.newPage();
        try {
          const targetUrl = url(mode);
          await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
          await page.waitForLoadState("load", { timeout: 10_000 }).catch(() => {});
          await expect(page.getByRole("heading", { name: "BenchBox Database Leaderboards" })).toBeVisible();
          await expect(page.getByRole("grid", { name: "Cross-benchmark leaderboard" })).toBeVisible();
          await expect(page.locator("body")).not.toContainText(/Binder Error|Stack trace|Results snapshot incomplete/i);
          await page.waitForTimeout(800);
          const shot = filename(mode, width);
          await page.screenshot({ path: path.join(OUT, shot), fullPage: true });
          captured.push({ filename: shot, url: targetUrl, width, mode });
        } finally {
          await context.close();
        }
      }
    }

    writeFileSync(
      path.join(OUT, "screenshot-manifest.json"),
      `${JSON.stringify({ captured_at: new Date().toISOString(), routes: captured }, null, 2)}\n`,
      "utf8",
    );
  });
});
