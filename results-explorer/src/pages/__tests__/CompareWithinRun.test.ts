/**
 * Within-run comparison: grid construction and the same-query-set rule.
 *
 * This route is the only place a statistic may vary between series, because
 * engine and hardware are fixed by construction. For the same reason its
 * figures are not platform results.
 */

import { describe, expect, it } from "vitest";

import {
  WITHIN_RUN_FIGURES_ARE_RANKABLE,
  buildWithinRunRows,
} from "@/pages/CompareWithinRun";
import { clampReferenceIndex, withinRunCompareHref } from "@/lib/resultLinks";
import { ALL_WARM, DEFAULT_BASIS, WARMUP, warmPass, type BasisExecution, type MeasurementBasis } from "@/lib/measurementBasis";
import { geomeanMs } from "@/lib/chartMath";

const exec = (
  query_id: string,
  duration_ms: number,
  run_type: string | null,
  iter: number | null,
  status = "pass",
): BasisExecution => ({ query_id, duration_ms, status, run_type, iter });

const MIN_ALL_WARM: MeasurementBasis = { passes: ALL_WARM, statistic: "min" };
const PASS_2: MeasurementBasis = { passes: warmPass(2), statistic: "median" };

describe("structural exclusion from ranking", () => {
  it("declares its figures unrankable", () => {
    // A number here says "this run reads X% faster one way than another",
    // which is a statement about methodology, not about an engine.
    expect(WITHIN_RUN_FIGURES_ARE_RANKABLE).toBe(false);
  });
});

describe("the same-query-set rule across columns", () => {
  // Q2's pass 2 failed, so the warm_pass_2 column cannot answer it while the
  // all-warm columns can. This is the shape that produced a wrong 1.18x
  // reading in the design prototype, where each column averaged over whichever
  // queries it happened to have.
  const executions: BasisExecution[] = [
    exec("Q1", 10, "measurement", 1),
    exec("Q1", 20, "measurement", 2),
    exec("Q1", 30, "measurement", 3),
    exec("Q2", 100, "measurement", 1),
    exec("Q2", 5, "measurement", 2, "fail"),
    exec("Q2", 300, "measurement", 3),
  ];
  const display = new Map<string, number | null>([
    ["Q1", 20],
    ["Q2", 200],
  ]);

  it("marks the query unrecorded only in the column that cannot answer it", () => {
    const { rows } = buildWithinRunRows(executions, display, [DEFAULT_BASIS, PASS_2]);
    const q2 = rows.find((r) => r.queryId === "Q2")!;
    expect(q2.cells[0]!.ms).toBe(200);
    expect(q2.cells[1]!.ms).toBeNull();
    expect(q2.cells[1]!.unavailableReason).toBe("pass_not_recorded");
  });

  it("excludes it from EVERY column's shared set, not just its own", () => {
    const { sharedQueryIds } = buildWithinRunRows(executions, display, [DEFAULT_BASIS, PASS_2]);
    expect(sharedQueryIds).toEqual(["Q1"]);
  });

  it("changes every column's geomean denominator identically", () => {
    const { rows, sharedQueryIds } = buildWithinRunRows(executions, display, [DEFAULT_BASIS, PASS_2]);
    const shared = new Set(sharedQueryIds);
    const perColumn = [0, 1].map((i) =>
      rows.filter((r) => shared.has(r.queryId)).map((r) => r.cells[i]!.ms),
    );
    // Same denominator in both columns, and it is the shared count.
    expect(perColumn[0]!.length).toBe(sharedQueryIds.length);
    expect(perColumn[1]!.length).toBe(sharedQueryIds.length);
    expect(perColumn[0]!.every((v) => v !== null)).toBe(true);
    expect(perColumn[1]!.every((v) => v !== null)).toBe(true);
  });

  it("the stated query-set size matches the denominator actually used", () => {
    const { rows, sharedQueryIds } = buildWithinRunRows(executions, display, [DEFAULT_BASIS, PASS_2]);
    const shared = new Set(sharedQueryIds);
    const values = rows.filter((r) => shared.has(r.queryId)).map((r) => r.cells[0]!.ms!);
    expect(geomeanMs(values)).not.toBeNull();
    expect(values.length).toBe(sharedQueryIds.length);
  });

  it("keeps every query when all columns can answer them", () => {
    const clean: BasisExecution[] = [
      exec("Q1", 10, "measurement", 1),
      exec("Q1", 20, "measurement", 2),
      exec("Q2", 30, "measurement", 1),
      exec("Q2", 40, "measurement", 2),
    ];
    const { sharedQueryIds } = buildWithinRunRows(
      clean,
      new Map([["Q1", 15], ["Q2", 35]]),
      [DEFAULT_BASIS, MIN_ALL_WARM],
    );
    expect(sharedQueryIds).toEqual(["Q1", "Q2"]);
  });
});

describe("a column whose basis the run cannot answer", () => {
  it("reports unavailable rather than substituting another basis", () => {
    // Silently serving the nearest available basis would label a warm figure
    // as a warmup figure -- a fabricated comparison presented as real.
    const noWarmup: BasisExecution[] = [
      exec("Q1", 10, "measurement", 1),
      exec("Q1", 20, "measurement", 2),
    ];
    const { rows } = buildWithinRunRows(noWarmup, new Map([["Q1", 15]]), [
      DEFAULT_BASIS,
      { passes: WARMUP, statistic: "median" },
    ]);
    expect(rows[0]!.cells[1]!.ms).toBeNull();
    expect(rows[0]!.cells[1]!.unavailableReason).toBe("no_warmup_recorded");
  });
});

describe("the reference column", () => {
  it("stays valid as columns are removed", () => {
    // Clamping rather than resetting to 0 preserves the reader's choice
    // wherever it still exists.
    expect(clampReferenceIndex(3, 2)).toBe(1);
    expect(clampReferenceIndex(1, 4)).toBe(1);
  });

  it("never goes negative or non-integral", () => {
    expect(clampReferenceIndex(-2, 3)).toBe(0);
    expect(clampReferenceIndex(1.7, 3)).toBe(1);
    expect(clampReferenceIndex(Number.NaN, 3)).toBe(0);
  });

  it("is 0 for an empty column set rather than throwing", () => {
    expect(clampReferenceIndex(2, 0)).toBe(0);
  });
});

describe("the route URL", () => {
  it("carries the bases list and the reference index", () => {
    expect(withinRunCompareHref("r1", ["default", "warm_pass_1"], 1)).toBe(
      "/results/r/r1/passes?bases=default%2Cwarm_pass_1&ref=1",
    );
  });

  it("clamps an out-of-range reference into the link itself", () => {
    expect(withinRunCompareHref("r1", ["default", "warm_pass_1"], 9)).toContain("ref=1");
  });

  it("is a separate path from the cross-run compare route", () => {
    // Sharing a path would put both rule sets on one page and invite the
    // cross-run one-basis invariant to be relaxed "just for this case".
    expect(withinRunCompareHref("r1", ["default", "warmup"])).toContain("/results/r/r1/passes");
    expect(withinRunCompareHref("r1", ["default", "warmup"])).not.toContain("/results/compare");
  });
});
