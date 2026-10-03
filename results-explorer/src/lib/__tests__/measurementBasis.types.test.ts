import { describe, expect, it } from "vitest";

import {
  DEFAULT_BASIS,
  type CrossRunComparison,
  type MeasurementBasis,
  type WithinRunComparison,
} from "@/lib/measurementBasis";

const MEDIAN_ALL_WARM: MeasurementBasis = DEFAULT_BASIS;
const MIN_ALL_WARM: MeasurementBasis = { passes: { kind: "all_warm" }, statistic: "min" };

const _perSeriesBasis: CrossRunComparison = {
  kind: "cross_run",
  runs: [
    // @ts-expect-error
    { resultId: "a", basis: MEDIAN_ALL_WARM },
    // @ts-expect-error
    { resultId: "b", basis: MIN_ALL_WARM },
  ],
  basis: MEDIAN_ALL_WARM,
};

const _twoBases: CrossRunComparison = {
  kind: "cross_run",
  runs: [{ resultId: "a" }, { resultId: "b" }],
  // @ts-expect-error
  basis: [MEDIAN_ALL_WARM, MIN_ALL_WARM],
};

const _oneRun: CrossRunComparison = {
  kind: "cross_run",
  // @ts-expect-error
  runs: [{ resultId: "a" }],
  basis: MEDIAN_ALL_WARM,
};

const _oneBasis: WithinRunComparison = {
  kind: "within_run",
  resultId: "a",
  // @ts-expect-error
  series: [{ basis: MEDIAN_ALL_WARM }],
};

function _mutateBasis(comparison: CrossRunComparison): void {
  // @ts-expect-error
  comparison.basis = MIN_ALL_WARM;
}

const _smuggledBases: CrossRunComparison = {
  kind: "cross_run",
  runs: [{ resultId: "a" }, { resultId: "b" }],
  basis: MEDIAN_ALL_WARM,
  // @ts-expect-error
  bases: [MEDIAN_ALL_WARM, MIN_ALL_WARM],
};

describe("measurementBasis type-level invariant", () => {
  it("compiles only because every illegal construction above is rejected by tsc", () => {
    expect(_perSeriesBasis.kind).toBe("cross_run");
    expect(_twoBases.kind).toBe("cross_run");
    expect(_oneRun.kind).toBe("cross_run");
    expect(_oneBasis.kind).toBe("within_run");
    expect(_smuggledBases.kind).toBe("cross_run");
    expect(typeof _mutateBasis).toBe("function");
  });
});
