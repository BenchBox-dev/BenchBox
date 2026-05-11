/**
 * Verifies the bench.results column-readiness guard. The guard converts a
 * dropped-column snapshot from a deep "Binder Error" into an actionable
 * init-time failure naming the missing column(s).
 */

import { describe, expect, it } from "vitest";
import {
  _verifyBenchResultsColumnsForTest,
  _BENCH_RESULTS_REQUIRED_COLUMNS_FOR_TEST,
} from "@/db";

interface QueryResult {
  toArray(): { toJSON(): { column_name: string } }[];
}

interface FakeConn {
  query(sql: string): Promise<QueryResult>;
}

function makeConn(columns: string[]): FakeConn {
  return {
    async query(_sql: string): Promise<QueryResult> {
      return {
        toArray: () =>
          columns.map((column_name) => ({
            toJSON: () => ({ column_name }),
          })),
      };
    },
  };
}

describe("verifyBenchResultsColumns guard", () => {
  it("resolves when every required column is present", async () => {
    const conn = makeConn([..._BENCH_RESULTS_REQUIRED_COLUMNS_FOR_TEST, "extra_column"]);
    await expect(
      _verifyBenchResultsColumnsForTest(conn as unknown as Parameters<typeof _verifyBenchResultsColumnsForTest>[0]),
    ).resolves.toBeUndefined();
  });

  it("rejects with the missing column names when normalized cost is dropped", async () => {
    const present = _BENCH_RESULTS_REQUIRED_COLUMNS_FOR_TEST.filter(
      (column) => column !== "normalized_cost_usd" && column !== "cost_status",
    );
    const conn = makeConn(present);
    await expect(
      _verifyBenchResultsColumnsForTest(conn as unknown as Parameters<typeof _verifyBenchResultsColumnsForTest>[0]),
    ).rejects.toThrow(/normalized_cost_usd/);
    await expect(
      _verifyBenchResultsColumnsForTest(conn as unknown as Parameters<typeof _verifyBenchResultsColumnsForTest>[0]),
    ).rejects.toThrow(/cost_status/);
  });

  it("rejects with the missing column names when eligibility contract columns are dropped", async () => {
    const present = _BENCH_RESULTS_REQUIRED_COLUMNS_FOR_TEST.filter(
      (column) => column !== "comparison_exclusion_reason" && column !== "is_ranking_eligible",
    );
    const conn = makeConn(present);
    await expect(
      _verifyBenchResultsColumnsForTest(conn as unknown as Parameters<typeof _verifyBenchResultsColumnsForTest>[0]),
    ).rejects.toThrow(/comparison_exclusion_reason/);
    await expect(
      _verifyBenchResultsColumnsForTest(conn as unknown as Parameters<typeof _verifyBenchResultsColumnsForTest>[0]),
    ).rejects.toThrow(/is_ranking_eligible/);
  });

  it("rejects mentioning the regenerator command for missing identity columns", async () => {
    const present = _BENCH_RESULTS_REQUIRED_COLUMNS_FOR_TEST.filter(
      (column) => column !== "result_id",
    );
    const conn = makeConn(present);
    await expect(
      _verifyBenchResultsColumnsForTest(conn as unknown as Parameters<typeof _verifyBenchResultsColumnsForTest>[0]),
    ).rejects.toThrow(/benchbox explorer build/);
  });
});
