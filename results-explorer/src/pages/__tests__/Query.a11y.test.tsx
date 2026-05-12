import { render, screen, waitFor } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/testing/axe-helper";

vi.mock("@/db", () => ({
  getDb: vi.fn(),
  queryRows: vi.fn(),
}));

import { getDb, queryRows } from "@/db";
import { clearDuckdbQueryCachesForTests } from "@/lib/duckdbQueries";
import { Query } from "@/pages/Query";

const SCHEMA_COLUMNS = [
  { name: "result_id", type: "VARCHAR" },
  { name: "benchmark", type: "VARCHAR" },
  { name: "platform", type: "VARCHAR" },
  { name: "scale_factor", type: "DOUBLE" },
  { name: "run_date", type: "VARCHAR" },
  { name: "geomean_ms", type: "DOUBLE" },
  { name: "trust_label", type: "VARCHAR" },
  { name: "test_type", type: "VARCHAR" },
  { name: "primary_metric", type: "VARCHAR" },
  { name: "comparison_exclusion_reason", type: "VARCHAR" },
];

const RESULT_ROWS = [
  {
    result_id: "blocked-a",
    benchmark: "tpch",
    platform: "DuckDB",
    scale_factor: 0.1,
    run_date: "2026-04-17T12:00:00Z",
    geomean_ms: 10,
    trust_label: "maintainer-run",
    test_type: "power",
    primary_metric: "power_score",
    comparison_exclusion_reason: "insufficient_query_coverage",
  },
  {
    result_id: "blocked-b",
    benchmark: "tpch",
    platform: "SQLite",
    scale_factor: 0.1,
    run_date: "2026-04-18T12:00:00Z",
    geomean_ms: 20,
    trust_label: "maintainer-run",
    test_type: "power",
    primary_metric: "power_score",
    comparison_exclusion_reason: "insufficient_query_coverage",
  },
];

function normalizeSql(sql: unknown): string {
  return String(sql).replace(/\s+/g, " ").trim();
}

describe("Query visible disabled reasons accessibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearDuckdbQueryCachesForTests();
    window.history.replaceState(null, "", "/results/query");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ columns: SCHEMA_COLUMNS }),
      }),
    );
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
    vi.mocked(getDb).mockResolvedValue({
      connect: vi.fn().mockResolvedValue({
        prepare: vi.fn(),
        close: vi.fn(),
      }),
      copyFileToBuffer: vi.fn(),
      dropFile: vi.fn(),
    } as unknown as Awaited<ReturnType<typeof getDb>>);
    vi.mocked(queryRows).mockImplementation(async (sql: string) => {
      const normalized = normalizeSql(sql);
      if (normalized.includes("FROM duckdb_columns()")) return SCHEMA_COLUMNS;
      if (normalized.includes("COUNT(*)")) return [];
      return RESULT_ROWS;
    });
  });

  it("keeps zero-selectable query reasons accessible", async () => {
    const { container } = render(<Query />);

    await waitFor(() => expect(screen.getByTestId("query-zero-selectable")).toBeTruthy());
    expect(screen.getAllByTestId("query-disabled-reason").length).toBeGreaterThan(0);
    await expectNoAxeViolations(container);
  });
});
