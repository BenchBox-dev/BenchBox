/**
 * G-3 driver - cross-surface metric parity.
 *
 * Every surface that reads a given (result, benchmark, scale_factor, phase)
 * must expose the same `power_score`, `display_geomean_ms`, `rank`,
 * `speedup_vs_best`, and `speedup_vs_slowest_in_cohort` values. In the
 * pipeline's canonical-browser contract those values originate from exactly
 * one DuckDB column per metric; no surface is allowed to recompute them.
 *
 * This test gates regressions by:
 *   1. Pinning the per-surface SQL to the canonical table/column it must
 *      read from - if a helper is rewritten to recompute via a derived
 *      expression the SELECT shape check fails.
 *   2. Running each helper against the SAME stubbed row and asserting the
 *      projected TS shape carries byte-identical values on every surface.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/db", () => ({
  queryRows: vi.fn(),
}));

import { queryRows } from "@/db";
import {
  getBenchmarkRanking,
  getCohort,
  getPlatformIndexRows,
  getResultDetailMetrics,
  listResults,
} from "@/lib/duckdbQueries";

const mockedQueryRows = vi.mocked(queryRows);

// Canonical fixture values - each metric appears in the mocked response
// for every surface so any drift in the projected field name is caught.
const FIXTURE = {
  result_id: "r1",
  short_id: "r1short01",
  benchmark: "tpch",
  scale_factor: 0.1,
  phase: "power",
  platform: "DuckDB",
  platform_id: "duckdb",
  power_score: 1234.56,
  display_geomean_ms: 5656.854249492381,
  rank: 1,
  speedup_vs_best: 1.0,
  speedup_vs_slowest_in_cohort: 4.05,
};

beforeEach(() => {
  mockedQueryRows.mockReset();
});

describe("G-3 cross-surface metric parity", () => {
  it("power_score column is selected by every surface that shows it", async () => {
    mockedQueryRows.mockResolvedValue([FIXTURE]);

    await listResults();
    await getResultDetailMetrics(FIXTURE.result_id);
    await getBenchmarkRanking(FIXTURE.benchmark, FIXTURE.scale_factor, FIXTURE.phase);
    await getPlatformIndexRows(FIXTURE.platform_id);

    for (const [sql] of mockedQueryRows.mock.calls) {
      expect(sql as string).toMatch(/\bbench\.\w+/);
      // Every surface's SQL must either SELECT * (inherits canonical column)
      // or explicitly name the canonical column - never a re-derived alias.
      const sqlLower = (sql as string).toLowerCase();
      const mentionsStar = /select\s+(?:\*|\w+\.\*)/.test(sqlLower);
      const namesPowerScore = /\bpower_score\b/.test(sqlLower);
      const surfaceDisplaysPowerScore = !sqlLower.includes("query_display_timings")
        && !sqlLower.includes("query_executions")
        && !sqlLower.includes("short_ids");
      if (surfaceDisplaysPowerScore) {
        expect(mentionsStar || namesPowerScore).toBe(true);
      }
    }
  });

  it("returns identical metric values across surfaces for the same result", async () => {
    mockedQueryRows.mockResolvedValue([FIXTURE]);

    const detail = await getResultDetailMetrics(FIXTURE.result_id);
    const ranking = await getBenchmarkRanking(
      FIXTURE.benchmark,
      FIXTURE.scale_factor,
      FIXTURE.phase,
    );
    const platformIdx = await getPlatformIndexRows(FIXTURE.platform_id);

    expect(detail).not.toBeNull();
    expect(ranking.length).toBeGreaterThan(0);
    expect(platformIdx.length).toBeGreaterThan(0);

    // Every surface projects the canonical metric values verbatim.
    expect(detail!.power_score).toBe(FIXTURE.power_score);
    expect(ranking[0]!.power_score).toBe(FIXTURE.power_score);
    expect(platformIdx[0]!.power_score).toBe(FIXTURE.power_score);

    expect(detail!.display_geomean_ms).toBe(FIXTURE.display_geomean_ms);
    expect(ranking[0]!.display_geomean_ms).toBe(FIXTURE.display_geomean_ms);
    expect(platformIdx[0]!.display_geomean_ms).toBe(FIXTURE.display_geomean_ms);
  });

  it("benchmark_rankings exposes speedup_vs_best and speedup_vs_slowest_in_cohort", async () => {
    // Guards C1: these are new columns - catch accidental removal or rename.
    mockedQueryRows.mockResolvedValue([FIXTURE]);
    const ranking = await getBenchmarkRanking(
      FIXTURE.benchmark,
      FIXTURE.scale_factor,
      FIXTURE.phase,
    );
    expect(ranking[0]!.speedup_vs_best).toBe(FIXTURE.speedup_vs_best);
    expect(ranking[0]!.speedup_vs_slowest_in_cohort).toBe(
      FIXTURE.speedup_vs_slowest_in_cohort,
    );
  });

  it("cohort_metadata surface exposes the same rank/metric_value as benchmark_rankings", async () => {
    const cohortRow = {
      cohort_key: "tpch-sf0.1-power",
      cohort_label: "TPC-H SF0.1",
      cohort_href: "/results/tpch/?scale=0.1",
      platform_count: 1,
      primary_metric: "power_score",
      primary_order: "desc",
      tuning_mode: null,
      trust_label: "maintainer-run",
      metric_value: FIXTURE.power_score,
      ...FIXTURE,
    };
    mockedQueryRows.mockResolvedValue([cohortRow]);
    const cohort = await getCohort("tpch-sf0.1-power");
    expect(cohort[0]!.rank).toBe(FIXTURE.rank);
    expect(cohort[0]!.metric_value).toBe(FIXTURE.power_score);
    expect(cohort[0]!.speedup_vs_best).toBe(FIXTURE.speedup_vs_best);
  });

  it("every reading surface targets the canonical bench.<table> path", async () => {
    // No surface may read metrics from a non-canonical view or synthesise a
    // column from a subquery. Every SELECT must come from `bench.<table>`.
    mockedQueryRows.mockResolvedValue([FIXTURE]);

    await listResults();
    await getResultDetailMetrics(FIXTURE.result_id);
    await getBenchmarkRanking(FIXTURE.benchmark, FIXTURE.scale_factor, FIXTURE.phase);
    await getPlatformIndexRows(FIXTURE.platform_id);
    await getCohort("tpch-sf0.1-power");

    for (const [sql] of mockedQueryRows.mock.calls) {
      expect(sql as string).toMatch(/FROM\s+bench\.[a-z_]+/i);
    }
  });
});
