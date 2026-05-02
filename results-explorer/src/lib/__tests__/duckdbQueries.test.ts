import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/db", () => ({
  queryRows: vi.fn(),
}));

import { queryRows } from "@/db";
import {
  clearDuckdbQueryCachesForTests,
  listResults,
  getResultDetailMetrics,
  getQueryDisplayTimings,
  getBenchmarkMatrixCells,
  getBenchmarkRanking,
  getPlatformIndexRows,
  getCohort,
  getMetaLeaderboard,
  getMetaLeaderboardData,
  resolveShortId,
  toShortIds,
} from "@/lib/duckdbQueries";

const mockedQueryRows = vi.mocked(queryRows);

beforeEach(() => {
  mockedQueryRows.mockReset();
  clearDuckdbQueryCachesForTests();
});

describe("duckdbQueries - SQL targets and parameters", () => {
  it("listResults selects from bench.results", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await listResults();
    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/FROM bench\.results/);
    expect(params).toBeUndefined();
  });

  it("listResults accepts a parameterized facet WHERE clause", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await listResults({ sql: "WHERE benchmark IN (?)", params: ["tpch"] });
    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toContain("WHERE benchmark IN (?)");
    expect(params).toEqual(["tpch"]);
  });

  it("getResultDetailMetrics returns the single matching row or null", async () => {
    mockedQueryRows.mockResolvedValueOnce([{ result_id: "r1" }]);
    const row = await getResultDetailMetrics("r1");
    expect(row).toEqual({ result_id: "r1" });

    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/FROM bench\.result_detail_metrics/);
    expect(sql).toMatch(/result_id = \?/);
    expect(params).toEqual(["r1"]);

    mockedQueryRows.mockResolvedValueOnce([]);
    const missing = await getResultDetailMetrics("nope");
    expect(missing).toBeNull();
  });

  it("getQueryDisplayTimings orders by query_id", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await getQueryDisplayTimings("r1");
    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/FROM bench\.query_display_timings/);
    expect(sql).toMatch(/ORDER BY query_id/);
    expect(params).toEqual(["r1"]);
  });

  it("getBenchmarkMatrixCells scopes by (benchmark, scale_factor, phase)", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await getBenchmarkMatrixCells("tpch", 0.1, "power");
    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/FROM bench\.benchmark_matrix_cells/);
    expect(params).toEqual(["tpch", 0.1, "power"]);
  });

  it("getBenchmarkRanking sorts by rank NULLS LAST", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await getBenchmarkRanking("tpch", 0.1, "power");
    const [sql] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/FROM bench\.benchmark_rankings/);
    expect(sql).toMatch(/LEFT JOIN bench\.results/);
    expect(sql).toMatch(/normalized_cost_usd/);
    expect(sql).toMatch(/cost_model_version/);
    expect(sql).toMatch(/ORDER BY br\.rank NULLS LAST/);
  });

  it("getPlatformIndexRows omits the filter when platformId is undefined", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await getPlatformIndexRows();
    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/FROM bench\.results r/);
    expect(sql).toMatch(/COALESCE\(si\.short_id, ''\) AS short_id/);
    expect(sql).toMatch(/LEFT JOIN bench\.short_ids si ON si\.result_id = r\.result_id/);
    expect(sql).toMatch(/LEFT JOIN bench\.benchmark_rankings br ON br\.result_id = r\.result_id/);
    expect(sql).toMatch(/COALESCE\(br\.phase, r\.test_type, 'power'\) AS phase/);
    expect(sql).toMatch(/br\.primary_metric/);
    expect(sql).toMatch(/validation_status/);
    expect(sql).toMatch(/normalized_cost_usd/);
    expect(sql).toMatch(/cloud_provider/);
    expect(sql).toMatch(/storage_format/);
    expect(sql).not.toMatch(/WHERE/);
    expect(params).toBeUndefined();
  });

  it("getPlatformIndexRows filters by platform_id when provided", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await getPlatformIndexRows("duckdb");
    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/WHERE r\.platform_id = \?/);
    expect(params).toEqual(["duckdb"]);
  });

  it("getCohort selects all variants for a cohort_key", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await getCohort("tpch-sf0.1-power");
    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/FROM bench\.cohort_metadata/);
    expect(sql).toMatch(/WHERE cohort_key = \?/);
    expect(params).toEqual(["tpch-sf0.1-power"]);
  });

  it("getMetaLeaderboard orders by avg_rank NULLS LAST", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await getMetaLeaderboard();
    const [sql] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/FROM bench\.meta_leaderboard/);
    expect(sql).toMatch(/ORDER BY avg_rank NULLS LAST/);
  });

  it("memoizes stable metadata helper reads for the current snapshot", async () => {
    const rows = [{ platform_id: "duckdb", platform: "DuckDB", avg_rank: 1, n_cohorts: 2 }];
    mockedQueryRows.mockResolvedValueOnce(rows);

    const first = await getMetaLeaderboard();
    const second = await getMetaLeaderboard();

    expect(first).toBe(second);
    expect(mockedQueryRows).toHaveBeenCalledTimes(1);
  });

  it("evicts failed metadata helper reads so a retry can recover", async () => {
    mockedQueryRows.mockRejectedValueOnce(new Error("snapshot not ready"));
    await expect(getMetaLeaderboard()).rejects.toThrow("snapshot not ready");

    const rows = [{ platform_id: "duckdb", platform: "DuckDB", avg_rank: 1, n_cohorts: 2 }];
    mockedQueryRows.mockResolvedValueOnce(rows);

    await expect(getMetaLeaderboard()).resolves.toEqual(rows);
    expect(mockedQueryRows).toHaveBeenCalledTimes(2);
  });
});

describe("getMetaLeaderboardData", () => {
  function makeCohortRow(overrides: Partial<Record<string, unknown>>) {
    return {
      cohort_key: "clickbench-sf0.1-power",
      benchmark: "clickbench",
      scale_factor: 0.1,
      phase: "power",
      cohort_label: "ClickBench SF0.1",
      cohort_href: "/results/clickbench/",
      platform_count: 2,
      primary_metric: "display_geomean_ms",
      primary_order: "asc",
      platform_id: "duckdb",
      platform: "DuckDB",
      result_id: "r1",
      short_id: "",
      tuning_mode: "tuned",
      trust_label: "maintainer-run",
      rank: 1,
      metric_value: 10,
      speedup_vs_best: 1,
      ...overrides,
    };
  }

  it("returns null when cohort_metadata is empty", async () => {
    mockedQueryRows
      .mockResolvedValueOnce([]) // meta_leaderboard
      .mockResolvedValueOnce([]); // cohort_metadata
    await expect(getMetaLeaderboardData()).resolves.toBeNull();
  });

  it("pivots cohort rows into cohorts[] and platforms[].ranks by platform_id", async () => {
    mockedQueryRows
      .mockResolvedValueOnce([
        { platform_id: "duckdb", platform: "DuckDB", avg_rank: 1, n_cohorts: 2 },
        { platform_id: "sqlite", platform: "SQLite", avg_rank: 2, n_cohorts: 1 },
      ])
      .mockResolvedValueOnce([
        makeCohortRow({ platform_id: "duckdb", result_id: "r1", rank: 1 }),
        makeCohortRow({
          platform_id: "sqlite",
          platform: "SQLite",
          result_id: "r2",
          rank: 2,
          metric_value: 20,
          speedup_vs_best: 0.5,
          tuning_mode: "auto",
          trust_label: "community-submission",
        }),
        makeCohortRow({
          cohort_key: "tpch-sf1-power",
          benchmark: "tpch",
          scale_factor: 1,
          phase: "power",
          cohort_label: "TPC-H SF1",
          cohort_href: "/results/tpch/",
          platform_count: 1,
          primary_metric: "power_score",
          primary_order: "desc",
          platform_id: "duckdb",
          result_id: "r3",
          rank: 1,
          metric_value: 3000,
          speedup_vs_best: 1,
        }),
      ]);

    const data = await getMetaLeaderboardData();
    expect(data).not.toBeNull();
    expect(data!.cohorts).toHaveLength(2);
    const clickbench = data!.cohorts.find((c) => c.key === "clickbench-sf0.1-power")!;
    expect(clickbench.label).toBe("ClickBench SF0.1");
    expect(clickbench.platforms).toHaveLength(2);

    const duckdb = data!.platforms.find((p) => p.platform_id === "duckdb")!;
    expect(duckdb.ranks["clickbench-sf0.1-power"]?.rank).toBe(1);
    expect(duckdb.ranks["tpch-sf1-power"]?.rank).toBe(1);
    expect(duckdb.avg_rank).toBe(1);
    expect(duckdb.n_cohorts).toBe(2);

    const sqlite = data!.platforms.find((p) => p.platform_id === "sqlite")!;
    expect(sqlite.ranks["clickbench-sf0.1-power"]?.rank).toBe(2);
    expect(sqlite.ranks["tpch-sf1-power"]).toBeUndefined();
  });

  it("keeps the best (lowest) rank when a platform has multiple variants in one cohort", async () => {
    mockedQueryRows
      .mockResolvedValueOnce([{ platform_id: "duckdb", platform: "DuckDB", avg_rank: 1, n_cohorts: 1 }])
      .mockResolvedValueOnce([
        makeCohortRow({ result_id: "r-tuned", rank: 1, tuning_mode: "tuned" }),
        makeCohortRow({ result_id: "r-auto", rank: 3, tuning_mode: "auto" }),
      ]);

    const data = await getMetaLeaderboardData();
    const duckdb = data!.platforms.find((p) => p.platform_id === "duckdb")!;
    expect(duckdb.ranks["clickbench-sf0.1-power"]?.rank).toBe(1);
    // All variants are preserved in the per-cohort platforms[] list.
    expect(data!.cohorts[0]!.platforms).toHaveLength(2);
  });

  it("skips platforms with null rank when building the ranks map", async () => {
    mockedQueryRows
      .mockResolvedValueOnce([{ platform_id: "duckdb", platform: "DuckDB", avg_rank: null, n_cohorts: 0 }])
      .mockResolvedValueOnce([makeCohortRow({ rank: null, metric_value: null, speedup_vs_best: null })]);

    const data = await getMetaLeaderboardData();
    const duckdb = data!.platforms.find((p) => p.platform_id === "duckdb")!;
    expect(duckdb.ranks).toEqual({});
  });
});

describe("resolveShortId", () => {
  it("returns the input unchanged when it is not a short-id-shaped string", async () => {
    // Full result_ids contain hyphens and are never 8+ contiguous hex chars.
    const fullId = "tpch-duckdb-abcdef12";
    await expect(resolveShortId(fullId)).resolves.toBe(fullId);
    expect(mockedQueryRows).not.toHaveBeenCalled();
  });

  it("queries short_ids when input looks like a short id", async () => {
    mockedQueryRows.mockResolvedValueOnce([{ result_id: "full-result-id" }]);
    const out = await resolveShortId("abcdef12");
    expect(out).toBe("full-result-id");
    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    expect(sql).toMatch(/FROM bench\.short_ids WHERE short_id = \?/);
    expect(params).toEqual(["abcdef12"]);
  });

  it("returns the input unchanged when no match is found", async () => {
    mockedQueryRows.mockResolvedValueOnce([]);
    await expect(resolveShortId("deadbeef")).resolves.toBe("deadbeef");
  });
});

describe("toShortIds", () => {
  it("returns [] immediately for an empty input without issuing a query", async () => {
    await expect(toShortIds([])).resolves.toEqual([]);
    expect(mockedQueryRows).not.toHaveBeenCalled();
  });

  it("maps each full id to its short id, falling back to the full id on misses", async () => {
    mockedQueryRows.mockResolvedValueOnce([
      { result_id: "id-a", short_id: "aaaaaaaa" },
      { result_id: "id-c", short_id: "cccccccc" },
    ]);
    const out = await toShortIds(["id-a", "id-b", "id-c"]);
    expect(out).toEqual(["aaaaaaaa", "id-b", "cccccccc"]);
    const [sql, params] = mockedQueryRows.mock.calls[0]!;
    // 3 inputs → 3 ? placeholders
    expect(sql).toMatch(/IN \(\?, \?, \?\)/);
    expect(params).toEqual(["id-a", "id-b", "id-c"]);
  });
});
