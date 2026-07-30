import { describe, expect, it, vi } from "vitest";

vi.mock("@duckdb/duckdb-wasm", () => ({}));
vi.mock("@/lib/performanceMarks", () => ({
  EXPLORER_PERFORMANCE_MARKS: {},
  markExplorerPerformance: vi.fn(),
  markExplorerError: vi.fn(),
}));

import { _waitForSnapshotRowsForTest, shouldRetryColdEmptyRead } from "@/db";

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
      // Match by table name in the SQL — readiness scans are
      // `SELECT result_id FROM bench.<table> LIMIT 1`.
      const tableMatch = sql.match(/FROM bench\.(\w+)/);
      const table = tableMatch?.[1] ?? "";
      const rows = rowsByLabelOrSql[table] ?? [];
      // The completeness probe asks COUNT(*) (metadata-satisfied) and then
      // materializes the column; a healthy snapshot agrees on both.
      if (/COUNT\(\*\)/i.test(sql)) return { toArray: () => [{ n: rows.length }] };
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

// ---------------------------------------------------------------------------
// Cold-snapshot zero-row race: an unkeyed `LIMIT 1` scan is satisfied by the
// first reachable row group while `WHERE result_id = ?` for a row further into
// the file still returns nothing. Readiness used to pass on the scans alone and
// hand the UI a snapshot whose keyed lookups render "No result found" for real
// ids. See docs/operations/browser-ci.md (2026-07-29 correction).
// ---------------------------------------------------------------------------

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

/**
 * Models a cold snapshot: every unkeyed scan answers, but keyed lookups stay
 * empty until `keyedReadyOnAttempt` keyed probes have been issued.
 */
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
      // Rows are fully readable here; these cases isolate the KEYED failure.
      if (/COUNT\(\*\)/i.test(sql)) return { toArray: () => [{ n: known ? 1 : 0 }] };
      if (!known) return { toArray: () => [] };
      return { toArray: () => [{ result_id: probeId }] };
    },
  };
}

/**
 * Models the partial-readability shape the completeness probe exists for:
 * COUNT(*) reports the true total from file metadata while the column
 * materializes fewer rows, until `readyOnAttempt` passes have been made.
 */
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
      // Full column materialization: short until the snapshot finishes
      // arriving. The probe returns on the FIRST mismatch, so one short read
      // happens per readiness attempt.
      passes += 1;
      const healed = passes > options.readyOnAttempt;
      return { toArray: () => rows(healed ? options.total : options.visible) };
    },
  };
}

describe("waitForSnapshotRows keyed probe (cold-snapshot zero-row race)", () => {
  it("rejects when unkeyed scans pass but keyed lookups stay empty", async () => {
    // The exact shape that used to slip through: every LIMIT 1 scan answers.
    const log: string[] = [];
    const conn = coldSnapshotConnection({ keyedReadyOnAttempt: Number.MAX_SAFE_INTEGER }, log);

    await expect(_waitForSnapshotRowsForTest(conn as unknown as never)).rejects.toThrow(
      /keyed lookup .* returned no rows from result_detail_metrics/,
    );
    expect(log.some((sql) => /WHERE result_id =/.test(sql))).toBe(true);
  }, 10000);

  it("resolves once the keyed lookup starts answering", async () => {
    // The snapshot warms up between attempts; readiness must retry, not fail.
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
        // Every scan answers except the ordered probe, which comes back empty.
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
    // The state that made Compare fail: unkeyed scans and a single keyed probe
    // both succeed, but most rows are still unreadable.
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

// ---------------------------------------------------------------------------
// Cold empty-read retry. Readiness gating alone cannot close this race:
// readability is not monotonic per query, so a surface that reads a range no
// probe forced still gets zero rows. The retry therefore lives at the read.
// ---------------------------------------------------------------------------

describe("shouldRetryColdEmptyRead", () => {
  const READY_AT = 1_000_000;

  it("retries an empty read inside the warm-up window", () => {
    expect(shouldRetryColdEmptyRead(1, READY_AT + 1_000, READY_AT)).toBe(true);
  });

  it("believes an empty read once the window has passed", () => {
    // A genuinely missing id must stay fast — no retry cost on not-found.
    expect(shouldRetryColdEmptyRead(1, READY_AT + 60_000, READY_AT)).toBe(false);
  });

  it("stops at the final attempt so an empty result is returned, not looped", () => {
    expect(shouldRetryColdEmptyRead(3, READY_AT + 1_000, READY_AT)).toBe(false);
  });

  it("does not retry before the snapshot has ever been attached", () => {
    expect(shouldRetryColdEmptyRead(1, READY_AT, 0)).toBe(false);
  });

  it("retries exactly at the window boundary", () => {
    expect(shouldRetryColdEmptyRead(1, READY_AT + 15_000, READY_AT)).toBe(true);
    expect(shouldRetryColdEmptyRead(1, READY_AT + 15_001, READY_AT)).toBe(false);
  });
});
