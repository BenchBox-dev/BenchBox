/**
 * Routing by selection shape (w1).
 *
 * Selection COUNT picks the layout, so nobody has to choose a page before
 * choosing runs, and the existing `?ids=` grammar keeps working untouched.
 */

import { describe, expect, it } from "vitest";

import { compareLayoutForSelection } from "@/pages/Compare";

describe("compareLayoutForSelection", () => {
  it("routes two distinct runs to the head-to-head layout", () => {
    expect(compareLayoutForSelection(["a", "b"])).toEqual({
      kind: "head_to_head",
      runIds: ["a", "b"],
    });
  });

  it("routes three and four runs to the multi-run layout", () => {
    expect(compareLayoutForSelection(["a", "b", "c"]).kind).toBe("multi_run");
    expect(compareLayoutForSelection(["a", "b", "c", "d"]).kind).toBe("multi_run");
  });

  it("routes a single distinct run to the within-run route", () => {
    expect(compareLayoutForSelection(["a"])).toEqual({ kind: "within_run", resultId: "a" });
  });

  it("treats ids that alias to one run as one run, not a head-to-head", () => {
    // Two ids resolving to the same result is one run. Rendering that as a
    // head-to-head would compare a run against itself and report a 1.00x
    // speedup as though it meant something.
    expect(compareLayoutForSelection(["a", "a"])).toEqual({ kind: "within_run", resultId: "a" });
  });

  it("collapses duplicates before counting", () => {
    expect(compareLayoutForSelection(["a", "b", "a"])).toEqual({
      kind: "head_to_head",
      runIds: ["a", "b"],
    });
  });

  it("reports an empty selection rather than guessing a layout", () => {
    expect(compareLayoutForSelection([])).toEqual({ kind: "empty" });
    expect(compareLayoutForSelection([""])).toEqual({ kind: "empty" });
  });

  it("preserves selection order in the routed run list", () => {
    // Baseline defaults to the first selected run, so order is meaningful.
    expect(compareLayoutForSelection(["b", "a"])).toEqual({
      kind: "head_to_head",
      runIds: ["b", "a"],
    });
  });
});
