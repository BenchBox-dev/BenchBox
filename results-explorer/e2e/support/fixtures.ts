import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type Locator, type Page } from "@playwright/test";

export type FixtureRole =
  | "awsCloud"
  | "cedardb"
  | "containerLocal"
  | "datafusion"
  | "datafusionPartial"
  | "duckdb"
  | "duckdbCommunity"
  | "duckdbSf01"
  | "duckdbTuned"
  | "gcpServerless"
  | "pandas"
  | "pandasTuned"
  | "pandasVendor"
  | "polars"
  | "polarsTuned"
  | "spark"
  | "starSchema"
  | "zeroTiming";

type FixtureIds = {
  ids: Record<FixtureRole, string>;
  shortIds: Record<FixtureRole, string>;
};

const FIXTURE_IDS_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "test-fixtures",
  ".generated",
  "data",
  "fixture-ids.json",
);

let loadedFixtureIds: FixtureIds | null = null;

function loadFixtureIds(): FixtureIds {
  if (loadedFixtureIds === null) {
    try {
      loadedFixtureIds = JSON.parse(readFileSync(FIXTURE_IDS_PATH, "utf8")) as FixtureIds;
    } catch (cause) {
      throw new Error(
        `Could not read ${FIXTURE_IDS_PATH}. Run \`npm run test:e2e:fixtures\` first - ` +
          "the browser suite needs the generated fixture corpus.",
        { cause },
      );
    }
  }
  return loadedFixtureIds;
}

export const fixtureIds: FixtureIds = new Proxy({} as FixtureIds, {
  get: (_target, property) => Reflect.get(loadFixtureIds(), property),
  has: (_target, property) => Reflect.has(loadFixtureIds(), property),
  ownKeys: () => Reflect.ownKeys(loadFixtureIds()),
  getOwnPropertyDescriptor: (_target, property) =>
    Reflect.getOwnPropertyDescriptor(loadFixtureIds(), property),
});

export async function waitForShell(page: Page) {
  await expect(page.getByRole("link", { name: /BenchBox/i }).first()).toBeVisible();
}

const DATA_ATTEMPT_BUDGETS_MS = [10_000, 8_000, 8_000];

const RENAVIGATE_TIMEOUT_MS = 10_000;

function navigationKey(url: string): string {
  const parsed = new URL(url);
  parsed.hash = "";
  return parsed.toString();
}

export function dataWaitNavigationAction(
  entryUrl: string,
  currentUrl: string,
): "renavigate" | "rewait" {
  return navigationKey(currentUrl) === navigationKey(entryUrl) ? "renavigate" : "rewait";
}

export async function waitForDataElement(page: Page, target: Locator) {
  const entryUrl = page.url();
  if (!/^https?:/.test(entryUrl)) {
    throw new Error(`waitForDataElement requires a navigated page; the page is on "${entryUrl}"`);
  }
  const entryKey = navigationKey(entryUrl);
  const startedAt = Date.now();
  let lastError: Error = new Error("waitForDataElement made no attempts");

  for (const [attempt, budget] of DATA_ATTEMPT_BUDGETS_MS.entries()) {
    if (attempt > 0) {
      if (dataWaitNavigationAction(entryUrl, page.url()) === "renavigate") {
        await page.goto(entryKey, { timeout: RENAVIGATE_TIMEOUT_MS });
      }
    }
    try {
      await expect(target).toBeVisible({ timeout: budget });
      return;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }

  const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
  throw new Error(
    `Data-bound wait failed after ${DATA_ATTEMPT_BUDGETS_MS.length} attempts ` +
      `(budgets ${DATA_ATTEMPT_BUDGETS_MS.map((ms) => `${ms / 1000}s`).join(" + ")}, ` +
      `${elapsed}s elapsed) on ${entryUrl}. Re-navigation, or re-waiting after intervening navigation, ` +
      `did not help, so this is ` +
      `NOT the cold-snapshot zero-row race that budget is sized for -- do not "fix" it by widening ` +
      `the budget. See docs/operations/browser-ci.md.\n\nLast attempt: ${lastError.message}`,
    { cause: lastError },
  );
}

export async function waitForDataLoaded(page: Page, locator: string | RegExp) {
  const target = typeof locator === "string" ? page.locator(locator) : page.getByText(locator);
  await waitForDataElement(page, target.first());
}

export async function waitForResultRows(page: Page, scope: Locator, minimum = 1) {
  await waitForDataElement(page, scope.locator("tbody tr[data-testid]").nth(minimum - 1));
}

export async function openAnalysisCard(page: Page, chartId: string): Promise<Locator> {
  const details = page.locator(`[data-testid="summary-chart-preview-${chartId}"]`).first();
  await waitForDataElement(page, details);
  const isOpen = await details.evaluate((el) => (el as HTMLDetailsElement).open);
  if (!isOpen) {
    await details.locator("summary").click();
  }
  return details;
}
