import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/db", () => ({
  queryRows: vi.fn(),
}));

import { queryRows } from "@/db";

const mockedQueryRows = vi.mocked(queryRows);

// The schema probe is module-level cached, so reset the module between tests
// to force a fresh probe each time.
beforeEach(() => {
  vi.resetModules();
  mockedQueryRows.mockReset();
});

describe("duckdbSchema - introspection helpers", () => {
  it("getTableSchema probes bench schema, defaults to results table, orders by column_index", async () => {
    mockedQueryRows
      .mockResolvedValueOnce([{ schema_name: "main" }])
      .mockResolvedValueOnce([
        { name: "result_id", type: "VARCHAR" },
        { name: "benchmark", type: "VARCHAR" },
      ]);
    const { getTableSchema } = await import("@/lib/duckdbSchema");
    const columns = await getTableSchema();
    expect(columns).toEqual([
      { name: "result_id", type: "VARCHAR" },
      { name: "benchmark", type: "VARCHAR" },
    ]);
    const [probeSql] = mockedQueryRows.mock.calls[0]!;
    expect(probeSql).toMatch(/DISTINCT schema_name/);
    const [sql, params] = mockedQueryRows.mock.calls[1]!;
    expect(sql).toMatch(/duckdb_columns\(\)/);
    expect(sql).toMatch(/database_name = 'bench'/);
    expect(sql).toMatch(/schema_name = \?/);
    expect(sql).toMatch(/ORDER BY column_index/);
    expect(params).toEqual(["main", "results"]);
  });

  it("getTableSchema accepts a custom table name", async () => {
    mockedQueryRows
      .mockResolvedValueOnce([{ schema_name: "main" }])
      .mockResolvedValueOnce([]);
    const { getTableSchema } = await import("@/lib/duckdbSchema");
    await getTableSchema("benchmark_rankings");
    const [, params] = mockedQueryRows.mock.calls[1]!;
    expect(params).toEqual(["main", "benchmark_rankings"]);
  });

  it("listBenchTables returns bare table names in sorted order", async () => {
    mockedQueryRows
      .mockResolvedValueOnce([{ schema_name: "main" }])
      .mockResolvedValueOnce([
        { table_name: "benchmark_rankings" },
        { table_name: "cohort_metadata" },
        { table_name: "results" },
      ]);
    const { listBenchTables } = await import("@/lib/duckdbSchema");
    const names = await listBenchTables();
    expect(names).toEqual(["benchmark_rankings", "cohort_metadata", "results"]);
    const [sql, params] = mockedQueryRows.mock.calls[1]!;
    expect(sql).toMatch(/DISTINCT table_name/);
    expect(sql).toMatch(/ORDER BY table_name/);
    expect(params).toEqual(["main"]);
  });

  it("falls back to a non-system schema when 'main' is absent", async () => {
    mockedQueryRows
      .mockResolvedValueOnce([{ schema_name: "analytics" }])
      .mockResolvedValueOnce([]);
    const { getTableSchema } = await import("@/lib/duckdbSchema");
    await getTableSchema("results");
    const [, params] = mockedQueryRows.mock.calls[1]!;
    expect(params).toEqual(["analytics", "results"]);
  });
});
