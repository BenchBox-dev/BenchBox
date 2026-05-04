import { describe, expect, it, vi } from "vitest";

vi.mock("@duckdb/duckdb-wasm", () => ({}));
vi.mock("@/lib/performanceMarks", () => ({
  EXPLORER_PERFORMANCE_MARKS: {},
  markExplorerPerformance: vi.fn(),
  markExplorerError: vi.fn(),
}));

import { _waitForSnapshotRowsForTest } from "@/db";

interface FakeRow {
  result_id: string;
}

function fakeConnection(
  rowsByLabelOrSql: Record<string, FakeRow[]>,
  log: string[],
): { query: (sql: string) => Promise<{ toArray: () => FakeRow[] }> } {
  return {
    query: async (sql: string) => {
      log.push(sql);
      // Match by table name in the SQL — readiness scans are
      // `SELECT result_id FROM bench.<table> LIMIT 1`.
      const tableMatch = sql.match(/FROM bench\.(\w+)/);
      const table = tableMatch?.[1] ?? "";
      const rows = rowsByLabelOrSql[table] ?? [];
      return { toArray: () => rows };
    },
  };
}

describe("waitForSnapshotRows / SNAPSHOT_READY_SCANS (w5)", () => {
  it("resolves when required scans return rows even if optional scans are empty", async () => {
    // Required scans get 1 row; optional scans (query_executions,
    // query_display_timings, short_ids) return [].
    const log: string[] = [];
    const conn = fakeConnection(
      {
        results: [{ result_id: "r1" }],
        platform_index_rows: [{ result_id: "r1" }],
        benchmark_rankings: [{ result_id: "r1" }],
        benchmark_matrix_cells: [{ result_id: "r1" }],
        result_detail_metrics: [{ result_id: "r1" }],
        // Optional tables intentionally empty.
        query_executions: [],
        query_display_timings: [],
        short_ids: [],
      },
      log,
    );

    await expect(_waitForSnapshotRowsForTest(conn as unknown as never)).resolves.toBeUndefined();
    // All scans were probed (we still want to know the table is queryable
    // even if it's optional).
    expect(log.some((sql) => sql.includes("query_executions"))).toBe(true);
    expect(log.some((sql) => sql.includes("short_ids"))).toBe(true);
  });

  it("rejects when a required scan stays empty across retries", async () => {
    const log: string[] = [];
    const conn = fakeConnection(
      {
        results: [], // required: empty → must fail readiness
        platform_index_rows: [{ result_id: "r1" }],
        benchmark_rankings: [{ result_id: "r1" }],
        benchmark_matrix_cells: [{ result_id: "r1" }],
        result_detail_metrics: [{ result_id: "r1" }],
        query_executions: [{ result_id: "r1" }],
        query_display_timings: [{ result_id: "r1" }],
        short_ids: [{ result_id: "r1" }],
      },
      log,
    );

    await expect(_waitForSnapshotRowsForTest(conn as unknown as never)).rejects.toThrow(
      /empty required scan/,
    );
  }, 10000);
});
