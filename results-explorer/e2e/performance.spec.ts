import { expect, test, type Page } from "@playwright/test";

const SAMPLE_COUNT = 10;
const MAX_SAMPLE_ATTEMPTS = SAMPLE_COUNT + 3;
const TRANSIENT_DUCKDB_WASM_INIT_ERROR =
  /Cannot read properties of null \(reading 'fieldsLength'\)|offset is out of bounds/i;

const MARKS = {
  DB_INIT_READY: "db-init-ready",
  HOME_LEADERBOARD_DATA_READY: "leaderboard-data-ready",
} as const;

const MEASURES = {
  DB_INIT: "db-init",
  LEADERBOARD_RENDER_AFTER_DATA: "leaderboard-render-after-data",
  QUERY_WORKBENCH_RENDER_AFTER_DB: "query-workbench-render-after-db",
} as const;

interface BudgetSummary {
  label: string;
  p50Ms: number;
  p95Ms: number;
  p50BudgetMs: number;
  p95BudgetMs: number;
  samplesMs: number[];
}

interface HomePerformanceSample {
  dbInitMs: number;
  leaderboardDataAfterDbMs: number;
  leaderboardRenderAfterDataMs: number;
}

interface QueryPerformanceSample {
  queryWorkbenchAfterDbMs: number;
}

test.describe("Performance smoke @performance", () => {
  test.describe.configure({ mode: "serial" });

  test("meets Results Explorer perceived-latency budgets", async ({ browser }, testInfo) => {
    test.setTimeout(180_000);

    const homeSamples: HomePerformanceSample[] = [];
    const querySamples: QueryPerformanceSample[] = [];
    const transientRetries: string[] = [];
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      for (let attempt = 0; homeSamples.length < SAMPLE_COUNT && attempt < MAX_SAMPLE_ATTEMPTS; attempt += 1) {
        try {
          const sample = await collectPerformanceSample(page, attempt);
          homeSamples.push(sample.home);
          querySamples.push(sample.query);
        } catch (error) {
          if (!isTransientPerformanceSampleError(error)) throw error;
          transientRetries.push(`attempt ${attempt}: ${error.message}`);
          await resetAfterTransientSample(page);
        }
      }
      if (homeSamples.length !== SAMPLE_COUNT || querySamples.length !== SAMPLE_COUNT) {
        throw new Error(
          `Collected ${homeSamples.length}/${SAMPLE_COUNT} successful performance samples after ` +
            `${MAX_SAMPLE_ATTEMPTS} attempts; retries=${transientRetries.join("; ")}`,
        );
      }
    } finally {
      await context.close();
    }

    const summaries: BudgetSummary[] = [
      summarizeBudget("DuckDB-WASM cold init", homeSamples.map((sample) => sample.dbInitMs), 4_000, 6_000),
      summarizeBudget(
        "Home leaderboard data after DB init",
        homeSamples.map((sample) => sample.leaderboardDataAfterDbMs),
        1_500,
        2_500,
      ),
      summarizeBudget(
        "Leaderboard render after data",
        homeSamples.map((sample) => sample.leaderboardRenderAfterDataMs),
        500,
        1_000,
      ),
      summarizeBudget(
        "Query Workbench first paint after DB init",
        querySamples.map((sample) => sample.queryWorkbenchAfterDbMs),
        600,
        1_200,
      ),
    ];

    console.info(formatBudgetSummary(summaries));
    await testInfo.attach("performance-summary.json", {
      contentType: "application/json",
      body: JSON.stringify(summaries, null, 2),
    });
    if (transientRetries.length > 0) {
      console.info(
        `Retried ${transientRetries.length} transient DuckDB-WASM init failure(s): ${transientRetries.join("; ")}`,
      );
      await testInfo.attach("performance-retries.json", {
        contentType: "application/json",
        body: JSON.stringify(transientRetries, null, 2),
      });
    }

    for (const summary of summaries) {
      expect(
        summary.p50Ms,
        `${summary.label} P50 ${formatMs(summary.p50Ms)} exceeded ${formatMs(summary.p50BudgetMs)}; samples=${formatSamples(
          summary.samplesMs,
        )}`,
      ).toBeLessThan(summary.p50BudgetMs);
      expect(
        summary.p95Ms,
        `${summary.label} P95 ${formatMs(summary.p95Ms)} exceeded ${formatMs(summary.p95BudgetMs)}; samples=${formatSamples(
          summary.samplesMs,
        )}`,
      ).toBeLessThan(summary.p95BudgetMs);
    }
  });
});

async function collectPerformanceSample(
  page: Page,
  attempt: number,
): Promise<{ home: HomePerformanceSample; query: QueryPerformanceSample }> {
  const home = await collectHomePerformanceSample(page, attempt);
  const query = await collectQueryPerformanceSample(page, attempt);
  return { home, query };
}

async function collectHomePerformanceSample(page: Page, index: number): Promise<HomePerformanceSample> {
  await page.goto(`/results/?bb_perf=1&perf_run=${index}`);
  await waitForPerformanceDataLoaded(page, /Recent Results/i);
  await waitForMeasure(page, MEASURES.DB_INIT);
  await waitForMeasure(page, MEASURES.LEADERBOARD_RENDER_AFTER_DATA);

  return page.evaluate(({ marks, measures }) => {
    const markStart = (name: string) => {
      const entry = performance.getEntriesByName(name, "mark").at(-1);
      if (!entry) throw new Error(`Missing performance mark: ${name}`);
      return entry.startTime;
    };
    const measureDuration = (name: string) => {
      const entry = performance.getEntriesByName(name, "measure").at(-1);
      if (!entry) throw new Error(`Missing performance measure: ${name}`);
      return entry.duration;
    };
    const dbReady = markStart(marks.DB_INIT_READY);
    const leaderboardDataReady = markStart(marks.HOME_LEADERBOARD_DATA_READY);
    return {
      dbInitMs: measureDuration(measures.DB_INIT),
      leaderboardDataAfterDbMs: leaderboardDataReady - dbReady,
      leaderboardRenderAfterDataMs: measureDuration(measures.LEADERBOARD_RENDER_AFTER_DATA),
    };
  }, { marks: MARKS, measures: MEASURES });
}

async function collectQueryPerformanceSample(page: Page, index: number): Promise<QueryPerformanceSample> {
  await page.goto(`/results/query?bb_perf=1&perf_run=${index}`);
  await waitForPerformanceDataLoaded(page, /matching result bundle/i);
  await waitForMeasure(page, MEASURES.QUERY_WORKBENCH_RENDER_AFTER_DB);

  return page.evaluate(({ measures }) => ({
    queryWorkbenchAfterDbMs: (() => {
      const entry = performance.getEntriesByName(measures.QUERY_WORKBENCH_RENDER_AFTER_DB, "measure").at(-1);
      if (!entry) throw new Error(`Missing performance measure: ${measures.QUERY_WORKBENCH_RENDER_AFTER_DB}`);
      return entry.duration;
    })(),
  }), { measures: MEASURES });
}

async function waitForPerformanceDataLoaded(page: Page, locator: string | RegExp): Promise<void> {
  const dataLocator = typeof locator === "string"
    ? page.locator(locator).first()
    : page.getByText(locator).first();
  const result = await Promise.race([
    dataLocator.waitFor({ state: "visible", timeout: 30_000 }).then(() => "ready" as const),
    page
      .getByText(TRANSIENT_DUCKDB_WASM_INIT_ERROR)
      .first()
      .waitFor({ state: "visible", timeout: 30_000 })
      .then(() => "transient-init-error" as const),
  ]);
  if (result === "transient-init-error") {
    throw new TransientPerformanceSampleError("DuckDB-WASM returned a transient snapshot-read error during cold init");
  }
}

async function waitForMeasure(page: Page, name: string): Promise<void> {
  await page.waitForFunction(
    (measureName) => performance.getEntriesByName(measureName, "measure").length > 0,
    name,
    { timeout: 30_000 },
  );
}

async function resetAfterTransientSample(page: Page): Promise<void> {
  await page.goto("about:blank");
  await page.waitForTimeout(250);
}

class TransientPerformanceSampleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TransientPerformanceSampleError";
  }
}

function isTransientPerformanceSampleError(error: unknown): error is TransientPerformanceSampleError {
  return error instanceof TransientPerformanceSampleError;
}

function summarizeBudget(
  label: string,
  samplesMs: number[],
  p50BudgetMs: number,
  p95BudgetMs: number,
): BudgetSummary {
  return {
    label,
    samplesMs,
    p50BudgetMs,
    p95BudgetMs,
    p50Ms: percentile(samplesMs, 50),
    p95Ms: percentile(samplesMs, 95),
  };
}

function percentile(samplesMs: number[], percentileValue: number): number {
  if (samplesMs.length === 0) throw new Error("Cannot calculate percentile without samples");
  const sorted = [...samplesMs].sort((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.ceil((percentileValue / 100) * sorted.length) - 1);
  return sorted[index]!;
}

function formatBudgetSummary(summaries: BudgetSummary[]): string {
  const rows = summaries.map(
    (summary) =>
      `${summary.label}: P50=${formatMs(summary.p50Ms)} / ${formatMs(summary.p50BudgetMs)}, P95=${formatMs(
        summary.p95Ms,
      )} / ${formatMs(summary.p95BudgetMs)}, samples=[${formatSamples(summary.samplesMs)}]`,
  );
  return `Results Explorer performance summary\n${rows.join("\n")}`;
}

function formatSamples(samplesMs: number[]): string {
  return samplesMs.map(formatMs).join(", ");
}

function formatMs(value: number): string {
  return `${Math.round(value)}ms`;
}
