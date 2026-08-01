import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Shared helpers for the browser-functional suite.
 *
 * Kept deliberately small - tests should read like user stories. Put
 * anything here that becomes duplicated across two or more specs.
 */

/**
 * Wait until the explorer's initial Preact bundle has mounted. We pick
 * a selector that the Layout / page shell renders synchronously (the
 * `BenchBox` header link) so this does not race DuckDB-WASM init.
 */
export async function waitForShell(page: Page) {
  await expect(page.getByRole("link", { name: /BenchBox/i }).first()).toBeVisible();
}

/**
 * Per-attempt budgets for a data-bound wait, in order. Between attempts the
 * page is re-navigated to the URL it was on when the wait began.
 *
 * The failure this models is NOT slowness. Measured on an idle machine with
 * `--workers=1` and a 45s single-shot budget, every flaky spec burned the
 * ENTIRE budget and the element never appeared -- and in
 * compare-entrypoints.spec.ts the page heading rendered while the result rows
 * stayed empty. That is a cold DuckDB-WASM snapshot answering the first keyed
 * query with zero rows: the view renders "no data" and never re-queries, so no
 * single-shot budget, however large, can ever succeed. Only a fresh navigation
 * against the now-warm snapshot recovers it, which is why CI (retries: 2) went
 * green while the same specs still fail locally (retries: 0).
 *
 * The suite's own performance spec puts a healthy DuckDB-WASM cold init at
 * P50 564ms / P95 978ms and leaderboard data after init at P50 6ms, so a 10s
 * first attempt is ~10x headroom. Attempts are deliberately SHORTER than the
 * 45s single-shot budget they replace: a racing wait now costs ~10s before it
 * re-navigates instead of burning 45s, which matters because several specs
 * chain multiple data waits inside one 90s per-test timeout.
 *
 * Worst case for one wait is 10 + 8 + 8 plus two bounded re-navigations
 * (RENAVIGATE_TIMEOUT_MS each) = 46s, about the same as the 45s it replaces.
 *
 * The root-cause fix belongs in results-explorer/src (gate the first keyed
 * query on a queryable snapshot, or re-query when it returns zero rows); this
 * suite may not touch src/**. See docs/operations/browser-ci.md.
 */
const DATA_ATTEMPT_BUDGETS_MS = [10_000, 8_000, 8_000];

/** Bound each re-navigation so it cannot inherit Playwright's 30s default. */
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

/**
 * Wait for the DuckDB-WASM attach to complete and the page to render real
 * data, re-navigating between attempts to defeat the zero-row cold-snapshot
 * race described above.
 *
 * Re-navigation only fires while the page is still on the URL the wait started
 * from (ignoring the fragment). If something navigated in the meantime -- a
 * click, or the app canonicalizing its own query string -- the remaining
 * attempts just re-wait, so this never rewinds a page out from under a test
 * that had moved on.
 *
 * Even so, prefer to call this directly after `page.goto(...)`. State that a
 * test established by interacting with the page (a checkbox, a theme toggle)
 * and did NOT encode in the URL will not survive a re-navigation.
 *
 * IMPORTANT: this trades away one class of coverage. A regression that breaks
 * the FIRST load but works on a reload will now pass on attempt 2. Until the
 * src/** root cause is fixed, the blocking gate does not cover first-load-only
 * correctness. A regression that survives a reload still fails every attempt.
 */
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
        // Drop the fragment: navigating to a URL identical including its hash is
        // a same-document scroll, which would not re-initialize the snapshot.
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

/**
 * Wait until a results table has actually rendered rows.
 *
 * `waitForDataLoaded` is often handed a route heading ("TPC-H Results"), which
 * the page shell renders whether or not the snapshot answered -- so on its own
 * it is NOT a data gate, and any row-bound assertion after it races the cold
 * snapshot. Specs that go on to touch rows, headers, or the heatmap should wait
 * on the rows themselves through this helper.
 *
 * Pass the `scope` the test actually asserts against (the grid, the table).
 * A page-wide row selector would also match the excluded-runs disclosure and
 * the heatmap, so it could report "rows are here" about a different table.
 */
export async function waitForResultRows(page: Page, scope: Locator, minimum = 1) {
  await waitForDataElement(page, scope.locator("tbody tr[data-testid]").nth(minimum - 1));
}
