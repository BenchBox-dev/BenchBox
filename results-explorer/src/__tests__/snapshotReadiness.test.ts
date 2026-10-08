import { describe, expect, it, vi } from "vitest";

vi.mock("@duckdb/duckdb-wasm", () => ({}));
vi.mock("@/lib/performanceMarks", () => ({
  EXPLORER_PERFORMANCE_MARKS: {},
  markExplorerPerformance: vi.fn(),
  markExplorerError: vi.fn(),
}));

import {
  _COLD_EMPTY_READ_MAX_DELAY_MS_FOR_TEST,
  _waitForSnapshotRowsForTest,
  shouldRetryColdEmptyRead,
  shouldRetryTransientQueryError,
} from "@/db";

interface FakeRow {
  result_id: string;
}

function fakeConnection(
  rowsByLabelOrSql: Record<string, FakeRow[]>,
  log: string[],
): { query: (sql: string) => Promise<{ toArray: () => Array<FakeRow | { n: number }> }> } {
  return {
    query: async (sql: string) => {
      log.push(sql);
      const tableMatch = sql.match(/FROM bench\.(\w+)/);
      const table = tableMatch?.[1] ?? "";
      const rows = rowsByLabelOrSql[table] ?? [];
      if (/COUNT\(\*\)/i.test(sql)) return { toArray: () => [{ n: rows.length }] };
      return { toArray: () => rows };
    },
  };
}

describe("waitForSnapshotRows / SNAPSHOT_READY_SCANS (w5)", () => {
  it("resolves when required scans return rows even if optional scans are empty", async () => {
    const log: string[] = [];
    const conn = fakeConnection(
      {
        results: [{ result_id: "r1" }],
        platform_index_rows: [{ result_id: "r1" }],
        benchmark_rankings: [{ result_id: "r1" }],
        benchmark_matrix_cells: [{ result_id: "r1" }],
        result_detail_metrics: [{ result_id: "r1" }],
        query_executions: [],
        query_display_timings: [],
        short_ids: [],
      },
      log,
    );

    await expect(_waitForSnapshotRowsForTest(conn as unknown as never)).resolves.toBeUndefined();
    expect(log.some((sql) => sql.includes("query_executions"))).toBe(true);
    expect(log.some((sql) => sql.includes("short_ids"))).toBe(true);
  });

  it("rejects when a required scan stays empty across retries", async () => {
    const log: string[] = [];
    const conn = fakeConnection(
      {
        results: [],
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

const READY_TABLES = [
  "results",
  "platform_index_rows",
  "benchmark_rankings",
  "benchmark_matrix_cells",
  "result_detail_metrics",
  "query_executions",
  "query_display_timings",
  "short_ids",
] as const;

function coldSnapshotConnection(
  options: { keyedReadyOnAttempt: number; probeId?: string },
  log: string[],
): { query: (sql: string) => Promise<{ toArray: () => Array<{ result_id: string } | { n: number }> }> } {
  const probeId = options.probeId ?? "zzz-last-result";
  let keyedProbes = 0;
  return {
    query: async (sql: string) => {
      log.push(sql);
      const isKeyed = /WHERE result_id =/.test(sql);
      if (isKeyed) {
        keyedProbes += 1;
        const ready = keyedProbes >= options.keyedReadyOnAttempt;
        return { toArray: () => (ready ? [{ result_id: probeId }] : []) };
      }
      const table = sql.match(/FROM bench\.(\w+)/)?.[1] ?? "";
      const known = READY_TABLES.includes(table as (typeof READY_TABLES)[number]);
      if (/COUNT\(\*\)/i.test(sql)) return { toArray: () => [{ n: known ? 1 : 0 }] };
      if (!known) return { toArray: () => [] };
      return { toArray: () => [{ result_id: probeId }] };
    },
  };
}

function partiallyReadableConnection(
  options: { total: number; visible: number; readyOnAttempt: number },
  log: string[],
): { query: (sql: string) => Promise<{ toArray: () => Array<{ result_id: string } | { n: number }> }> } {
  let passes = 0;
  const rows = (count: number) =>
    Array.from({ length: count }, (_, i) => ({ result_id: `r${i}` }));
  return {
    query: async (sql: string) => {
      log.push(sql);
      if (/COUNT\(\*\)/i.test(sql)) return { toArray: () => [{ n: options.total }] };
      if (/WHERE result_id =/.test(sql)) return { toArray: () => [{ result_id: "r0" }] };
      if (/ORDER BY result_id DESC/.test(sql)) return { toArray: () => [{ result_id: "r0" }] };
      if (/LIMIT 1/.test(sql)) return { toArray: () => rows(1) };
      passes += 1;
      const healed = passes > options.readyOnAttempt;
      return { toArray: () => rows(healed ? options.total : options.visible) };
    },
  };
}

describe("waitForSnapshotRows keyed probe (cold-snapshot zero-row race)", () => {
  it("rejects when unkeyed scans pass but keyed lookups stay empty", async () => {
    const log: string[] = [];
    const conn = coldSnapshotConnection({ keyedReadyOnAttempt: Number.MAX_SAFE_INTEGER }, log);

    await expect(_waitForSnapshotRowsForTest(conn as unknown as never)).rejects.toThrow(
      /keyed lookup .* returned no rows from result_detail_metrics/,
    );
    expect(log.some((sql) => /WHERE result_id =/.test(sql))).toBe(true);
  }, 10000);

  it("resolves once the keyed lookup starts answering", async () => {
    const log: string[] = [];
    const conn = coldSnapshotConnection({ keyedReadyOnAttempt: 2 }, log);

    await expect(_waitForSnapshotRowsForTest(conn as unknown as never)).resolves.toBeUndefined();
    expect(log.filter((sql) => /WHERE result_id =/.test(sql)).length).toBe(2);
  }, 10000);

  it("probes with the last id so it cannot reuse the row the cheap scans reached", async () => {
    const log: string[] = [];
    const conn = coldSnapshotConnection({ keyedReadyOnAttempt: 1 }, log);

    await _waitForSnapshotRowsForTest(conn as unknown as never);
    expect(
      log.some((sql) => /FROM bench\.results ORDER BY result_id DESC LIMIT 1/.test(sql)),
    ).toBe(true);
  }, 10000);

  it("escapes a quote in the probe id rather than breaking the SQL", async () => {
    const log: string[] = [];
    const conn = coldSnapshotConnection({ keyedReadyOnAttempt: 1, probeId: "o'brien" }, log);

    await _waitForSnapshotRowsForTest(conn as unknown as never);
    const keyed = log.find((sql) => /WHERE result_id =/.test(sql)) ?? "";
    expect(keyed).toContain("'o''brien'");
  }, 10000);

  it("rejects when results yields no probe id at all", async () => {
    const log: string[] = [];
    const conn = {
      query: async (sql: string) => {
        log.push(sql);
        if (/COUNT\(\*\)/i.test(sql)) return { toArray: () => [{ n: 1 }] };
        if (/ORDER BY result_id DESC/.test(sql)) return { toArray: () => [] };
        return { toArray: () => [{ result_id: "r1" }] };
      },
    };

    await expect(_waitForSnapshotRowsForTest(conn as unknown as never)).rejects.toThrow(
      /returned no probe id/,
    );
  }, 10000);
});

describe("waitForSnapshotRows completeness probe (partially readable snapshot)", () => {
  it("rejects while a table materializes fewer rows than COUNT(*) reports", async () => {
    const log: string[] = [];
    const conn = partiallyReadableConnection(
      { total: 10, visible: 3, readyOnAttempt: Number.MAX_SAFE_INTEGER },
      log,
    );

    await expect(_waitForSnapshotRowsForTest(conn as unknown as never)).rejects.toThrow(
      /materialized 3 of 10 row\(s\)/,
    );
  }, 10000);

  it("resolves once every row is readable", async () => {
    const log: string[] = [];
    const conn = partiallyReadableConnection({ total: 10, visible: 3, readyOnAttempt: 1 }, log);

    await expect(_waitForSnapshotRowsForTest(conn as unknown as never)).resolves.toBeUndefined();
  }, 10000);
});

describe("shouldRetryColdEmptyRead", () => {
  const READY_AT = 1_000_000;

  it("retries an empty read inside the warm-up window", () => {
    expect(shouldRetryColdEmptyRead(1, READY_AT + 1_000, READY_AT)).toBe(true);
  });

  it("believes an empty read once the window has passed", () => {
    expect(shouldRetryColdEmptyRead(1, READY_AT + 60_000, READY_AT)).toBe(false);
  });

  it("stops at the size-budget attempt so an empty result is returned, not looped", () => {
    expect(shouldRetryColdEmptyRead(100, READY_AT + 1_000, READY_AT)).toBe(false);
  });

  it("does not retry before the snapshot has ever been attached", () => {
    expect(shouldRetryColdEmptyRead(1, READY_AT, 0)).toBe(false);
  });

  it("retries exactly at the window boundary", () => {
    expect(shouldRetryColdEmptyRead(1, READY_AT + 15_000, READY_AT)).toBe(true);
    expect(shouldRetryColdEmptyRead(1, READY_AT + 15_001, READY_AT)).toBe(false);
  });

  it("bounds a genuinely empty query below the shortest browser recovery attempt", () => {
    expect(_COLD_EMPTY_READ_MAX_DELAY_MS_FOR_TEST).toBeLessThan(8_000);
  });
});

describe("shouldRetryTransientQueryError", () => {
  const transient = new Error("offset is out of bounds");

  it("keeps transient errors on the original three-attempt budget", () => {
    expect(shouldRetryTransientQueryError(transient, 1)).toBe(true);
    expect(shouldRetryTransientQueryError(transient, 2)).toBe(true);
    expect(shouldRetryTransientQueryError(transient, 3)).toBe(false);
  });

  it("does not retry non-transient errors", () => {
    expect(shouldRetryTransientQueryError(new Error("syntax error"), 1)).toBe(false);
  });
});

describe("a query the worker never answers (dropped-pending-request hang)", () => {
  it("times out instead of hanging forever, and the timeout is classified as retryable", async () => {
    vi.useFakeTimers();
    try {
      const hungConn = { query: () => new Promise<never>(() => {}) };

      let settled = false;
      let settledError: unknown;
      _waitForSnapshotRowsForTest(hungConn as unknown as Parameters<typeof _waitForSnapshotRowsForTest>[0]).then(
        () => {
          settled = true;
        },
        (error: unknown) => {
          settled = true;
          settledError = error;
        },
      );

      await vi.advanceTimersByTimeAsync(60_000);

      expect(settled).toBe(true);
      expect(String(settledError)).toMatch(/did not respond within \d+ms/i);
    } finally {
      vi.useRealTimers();
    }
  });
});
