/**
 * The measurement basis as a cohort-level rule.
 *
 * Basis compatibility belongs next to benchmark, scale and phase for the same
 * reason those do: it is something a whole comparison must agree on, and a run
 * that cannot answer it is not comparable in this cohort. Putting it here
 * means a surface handles one kind of cohort violation, not two.
 */

import { describe, expect, it } from "vitest";

import {
  compareCohortMismatches,
  compareCohortPartition,
  compareCohortSignatureForRow,
  compareCohortSummary,
  lockCrossRunBasis,
  rowAnswersBasis,
} from "@/lib/compareCohort";
import { ALL_WARM, DEFAULT_BASIS, WARMUP, warmPass, type MeasurementBasis } from "@/lib/measurementBasis";

const CORPUS_BASES = "default,warmup,all_warm,warm_pass_1,warm_pass_2,warm_pass_3";
const NO_WARMUP_BASES = "default,all_warm,warm_pass_1,warm_pass_2,warm_pass_3";

const WARMUP_BASIS: MeasurementBasis = { passes: WARMUP, statistic: "median" };
const MIN_ALL_WARM: MeasurementBasis = { passes: ALL_WARM, statistic: "min" };
const PASS_4: MeasurementBasis = { passes: warmPass(4), statistic: "median" };

const cohortRow = (overrides: Record<string, unknown> = {}) => ({
  benchmark: "tpcds",
  scale_factor: 10,
  phase: "power",
  available_bases: CORPUS_BASES,
  ...overrides,
});

describe("the cohort signature records the basis in force", () => {
  it("locks no basis until one is given", () => {
    expect(compareCohortSignatureForRow(cohortRow()).basis).toBeNull();
  });

  it("carries the locked basis so a shared link reproduces the reduction", () => {
    const signature = compareCohortSignatureForRow(cohortRow(), WARMUP_BASIS);
    expect(signature.basis).toEqual(WARMUP_BASIS);
  });

  it("names the basis in the cohort summary once one is locked", () => {
    expect(compareCohortSummary(compareCohortSignatureForRow(cohortRow()))).toBe("TPC-DS SF 10 power");
    expect(compareCohortSummary(compareCohortSignatureForRow(cohortRow(), WARMUP_BASIS))).toBe(
      "TPC-DS SF 10 power at warmup pass",
    );
    expect(compareCohortSummary(compareCohortSignatureForRow(cohortRow(), MIN_ALL_WARM))).toBe(
      "TPC-DS SF 10 power at fastest warm pass",
    );
  });
});

describe("basis compatibility sits alongside benchmark, scale and phase", () => {
  const signature = compareCohortSignatureForRow(cohortRow(), WARMUP_BASIS);

  it("reports a run that cannot answer the locked basis as a mismatch", () => {
    const mismatches = compareCohortMismatches(
      cohortRow({ available_bases: NO_WARMUP_BASES }),
      signature,
    );
    expect(mismatches).toEqual(["measurement basis"]);
  });

  it("reports a basis mismatch alongside the other cohort fields, not instead of them", () => {
    const mismatches = compareCohortMismatches(
      cohortRow({ benchmark: "tpch", scale_factor: 1, available_bases: NO_WARMUP_BASES }),
      signature,
    );
    expect(mismatches).toEqual(["benchmark", "scale", "measurement basis"]);
  });

  it("accepts a run that publishes the locked basis", () => {
    expect(compareCohortMismatches(cohortRow(), signature)).toEqual([]);
  });

  it("partitions incompatible-basis rows out with every other incompatible row", () => {
    const rows = [
      cohortRow({ id: 1 }),
      cohortRow({ id: 2, available_bases: NO_WARMUP_BASES }),
      cohortRow({ id: 3 }),
    ];
    const { compatible, incompatible } = compareCohortPartition(rows, signature);
    expect(compatible).toHaveLength(2);
    expect(incompatible).toHaveLength(1);
  });
});

describe("unknown availability is compatible, not incompatible", () => {
  it("accepts a row that does not carry an availability list at all", () => {
    // A snapshot built before the basis columns existed must not have every
    // row declared incompatible. Value resolution reports unavailability per
    // query, where it can name the reason.
    expect(rowAnswersBasis({ benchmark: "tpch" }, WARMUP_BASIS)).toBe(true);
    expect(rowAnswersBasis({ benchmark: "tpch", available_bases: null }, WARMUP_BASIS)).toBe(true);
    expect(rowAnswersBasis({ benchmark: "tpch", available_bases: "" }, WARMUP_BASIS)).toBe(true);
  });

  it("accepts every row when no basis is locked", () => {
    expect(rowAnswersBasis(cohortRow({ available_bases: NO_WARMUP_BASES }), null)).toBe(true);
  });

  it("rejects a basis the run genuinely does not publish", () => {
    expect(rowAnswersBasis(cohortRow(), PASS_4)).toBe(false);
  });

  it("treats default and all_warm:median as the same locked basis", () => {
    expect(rowAnswersBasis(cohortRow({ available_bases: "all_warm" }), DEFAULT_BASIS)).toBe(true);
  });
});

describe("a cross-run comparison locks exactly one basis", () => {
  it("locks nothing when nothing is selected", () => {
    expect(lockCrossRunBasis([])).toEqual({ ok: true, basis: null });
  });

  it("locks the single basis it was given", () => {
    expect(lockCrossRunBasis([WARMUP_BASIS])).toEqual({ ok: true, basis: WARMUP_BASIS });
  });

  it("collapses repeats of the same basis rather than calling them a conflict", () => {
    expect(lockCrossRunBasis([DEFAULT_BASIS, DEFAULT_BASIS, DEFAULT_BASIS])).toEqual({
      ok: true,
      basis: DEFAULT_BASIS,
    });
  });

  it("refuses two different bases at the runtime boundary the types cannot reach", () => {
    // The types make this unrepresentable in the model. This is the same rule
    // where bases arrive as untyped strings from a URL, before the types see
    // them at all.
    const locked = lockCrossRunBasis([DEFAULT_BASIS, MIN_ALL_WARM]);
    expect(locked.ok).toBe(false);
    if (locked.ok) return;
    expect(locked.reason).toContain("one measurement basis");
    expect(locked.reason).toContain("published median");
    expect(locked.reason).toContain("fastest warm pass");
    expect(locked.reason).toContain("measures the basis, not the engine");
  });
});
