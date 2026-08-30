/**
 * Type-level tests for the one-basis-per-cross-run-comparison invariant.
 *
 * These assertions are checked by `npm run typecheck` (tsc --noEmit), not by
 * Vitest. The `it` block exists only so the file reads as a test and is
 * discovered alongside its siblings; the real assertions are the
 * `@ts-expect-error` directives, and they run at compile time.
 *
 * WHY THIS DIRECTION MATTERS: `@ts-expect-error` fails the build when the line
 * beneath it compiles CLEANLY. So if someone later adds a `basis` field to
 * `CrossRunSeries`, relaxes the two-or-more tuple bound, or drops a `readonly`,
 * the directive becomes unused and tsc reports it as an error. The invariant
 * cannot be quietly weakened -- weakening it breaks the build.
 *
 * See _project/verification-logs/explorer-basis-frontend-model-and-invariant/
 * w1.log for the verbatim compiler output each of these produced when written
 * without the directive.
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_BASIS,
  type CrossRunComparison,
  type MeasurementBasis,
  type WithinRunComparison,
} from "@/lib/measurementBasis";

const MEDIAN_ALL_WARM: MeasurementBasis = DEFAULT_BASIS;
const MIN_ALL_WARM: MeasurementBasis = { passes: { kind: "all_warm" }, statistic: "min" };

// PROBE 1 - the invariant itself: a per-series basis in a cross-run comparison.
// TS2353: 'basis' does not exist in type 'CrossRunSeries'.
const _perSeriesBasis: CrossRunComparison = {
  kind: "cross_run",
  runs: [
    // @ts-expect-error - a cross-run series has no basis field, by construction
    { resultId: "a", basis: MEDIAN_ALL_WARM },
    // @ts-expect-error - a cross-run series has no basis field, by construction
    { resultId: "b", basis: MIN_ALL_WARM },
  ],
  basis: MEDIAN_ALL_WARM,
};

// PROBE 2 - two bases on the comparison itself. TS2739.
const _twoBases: CrossRunComparison = {
  kind: "cross_run",
  runs: [{ resultId: "a" }, { resultId: "b" }],
  // @ts-expect-error - a cross-run comparison holds exactly one basis, not a list
  basis: [MEDIAN_ALL_WARM, MIN_ALL_WARM],
};

// PROBE 3 - a "cross-run" comparison of a single run. TS2322.
const _oneRun: CrossRunComparison = {
  kind: "cross_run",
  // @ts-expect-error - a cross-run comparison requires at least two runs
  runs: [{ resultId: "a" }],
  basis: MEDIAN_ALL_WARM,
};

// PROBE 4 - a within-run comparison of a single basis. TS2322.
const _oneBasis: WithinRunComparison = {
  kind: "within_run",
  resultId: "a",
  // @ts-expect-error - a within-run comparison requires at least two bases
  series: [{ basis: MEDIAN_ALL_WARM }],
};

// PROBE 5 - reassigning the basis after construction. TS2540.
function _mutateBasis(comparison: CrossRunComparison): void {
  // @ts-expect-error - every field of the model is readonly
  comparison.basis = MIN_ALL_WARM;
}

// PROBE 6 - smuggling a second basis in under a plausible-looking key. TS2561.
const _smuggledBases: CrossRunComparison = {
  kind: "cross_run",
  runs: [{ resultId: "a" }, { resultId: "b" }],
  basis: MEDIAN_ALL_WARM,
  // @ts-expect-error - `bases` is the within-run URL key and has no place here
  bases: [MEDIAN_ALL_WARM, MIN_ALL_WARM],
};

describe("measurementBasis type-level invariant", () => {
  it("compiles only because every illegal construction above is rejected by tsc", () => {
    // Referencing the bindings keeps noUnusedLocals satisfied and documents
    // that these are real values, not erased type-only declarations.
    expect(_perSeriesBasis.kind).toBe("cross_run");
    expect(_twoBases.kind).toBe("cross_run");
    expect(_oneRun.kind).toBe("cross_run");
    expect(_oneBasis.kind).toBe("within_run");
    expect(_smuggledBases.kind).toBe("cross_run");
    expect(typeof _mutateBasis).toBe("function");
  });
});
