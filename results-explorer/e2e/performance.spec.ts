import { expect, test, type Page } from "@playwright/test";

import { waitForDataLoaded } from "./support/fixtures";

const SAMPLE_COUNT = 10;

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
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      for (let index = 0; index < SAMPLE_COUNT; index += 1) {
        homeSamples.push(await collectHomePerformanceSample(page, index));
        querySamples.push(await collectQueryPerformanceSample(page, index));
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

async function collectHomePerformanceSample(page: Page, index: number): Promise<HomePerformanceSample> {
  await page.goto(`/results/?bb_perf=1&perf_run=${index}`);
  await waitForDataLoaded(page, /Recent Results/i);
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
  await waitForDataLoaded(page, /matching result bundle/i);
  await waitForMeasure(page, MEASURES.QUERY_WORKBENCH_RENDER_AFTER_DB);

  return page.evaluate(({ measures }) => ({
    queryWorkbenchAfterDbMs: (() => {
      const entry = performance.getEntriesByName(measures.QUERY_WORKBENCH_RENDER_AFTER_DB, "measure").at(-1);
      if (!entry) throw new Error(`Missing performance measure: ${measures.QUERY_WORKBENCH_RENDER_AFTER_DB}`);
      return entry.duration;
    })(),
  }), { measures: MEASURES });
}

async function waitForMeasure(page: Page, name: string): Promise<void> {
  await page.waitForFunction(
    (measureName) => performance.getEntriesByName(measureName, "measure").length > 0,
    name,
    { timeout: 30_000 },
  );
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
