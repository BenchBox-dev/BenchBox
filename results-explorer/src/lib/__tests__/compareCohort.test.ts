import { describe, it, expect } from "vitest";
import {
  compareCohortPartition,
  compareCohortSignatureForRow,
  compareSelectionLabel,
  hiddenIncompatibleSuffix,
} from "@/lib/compareCohort";

describe("compareCohortPartition", () => {
  const sig = compareCohortSignatureForRow({
    benchmark: "tpch",
    scale_factor: 0.1,
    phase: "power",
  });

  it("treats every row as compatible when no signature is locked", () => {
    const rows = [
      { id: 1, benchmark: "tpch", scale_factor: 0.1, phase: "power" },
      { id: 2, benchmark: "ssb", scale_factor: 1, phase: "power" },
    ];
    const out = compareCohortPartition(rows, null);
    expect(out.compatible).toEqual(rows);
    expect(out.incompatible).toEqual([]);
  });

  it("partitions rows against a locked signature in stable order", () => {
    const rows = [
      { id: 1, benchmark: "ssb", scale_factor: 1, phase: "power" },
      { id: 2, benchmark: "tpch", scale_factor: 0.1, phase: "power" },
      { id: 3, benchmark: "tpch", scale_factor: 1, phase: "power" },
      { id: 4, benchmark: "tpch", scale_factor: 0.1, phase: "power" },
    ];
    const { compatible, incompatible } = compareCohortPartition(rows, sig);
    expect(compatible.map((r) => r.id)).toEqual([2, 4]);
    expect(incompatible.map((r) => r.id)).toEqual([1, 3]);
  });

  it("ignores primary_metric when one side is missing", () => {
    const rows = [
      { id: 1, benchmark: "tpch", scale_factor: 0.1, phase: "power" },
      { id: 2, benchmark: "tpch", scale_factor: 0.1, phase: "power", primary_metric: "power_score" },
    ];
    const out = compareCohortPartition(rows, sig);
    expect(out.compatible.map((r) => r.id)).toEqual([1, 2]);
  });
});

describe("compareSelectionLabel", () => {
  it("includes platform, benchmark, scale, phase, run date, and short id", () => {
    const label = compareSelectionLabel({
      platform: "Polars",
      benchmark: "tpch",
      scaleFactor: 0.1,
      phase: "power",
      runDate: "2026-05-02T18:11:00Z",
      resultId: "tpch-polars-sf0.1-20260502-0093bb7a",
    });
    expect(label).toBe("Select Polars TPC-H SF 0.1 power 2026-05-02 (0093bb7a) for comparison");
  });

  it("disambiguates two rows with the same platform via short id and date", () => {
    const a = compareSelectionLabel({
      platform: "DataFusion",
      benchmark: "tpch",
      scaleFactor: 1,
      phase: "power",
      runDate: "2026-05-06",
      resultId: "tpch-datafusion-sf1-20260506-3b8bbc42",
    });
    const b = compareSelectionLabel({
      platform: "DataFusion",
      benchmark: "tpch",
      scaleFactor: 1,
      phase: "power",
      runDate: "2026-05-08",
      resultId: "tpch-datafusion-sf1-20260508-deadbeef",
    });
    expect(a).not.toBe(b);
  });

  it("relabels SSB legacy slug via formatBenchmarkLabel", () => {
    const legacy = compareSelectionLabel({ platform: "DuckDB", benchmark: "ssb" });
    const canonical = compareSelectionLabel({ platform: "DuckDB", benchmark: "star_schema" });
    expect(legacy).toContain("SSB (legacy slug)");
    expect(canonical).toContain("SSB");
    expect(canonical).not.toContain("legacy");
  });

  it("falls back to a generic label when no inputs are provided", () => {
    expect(compareSelectionLabel({})).toBe("Select run for comparison");
  });

  it("truncates ISO-timestamp run dates to YYYY-MM-DD", () => {
    const label = compareSelectionLabel({
      platform: "Polars",
      runDate: "2026-05-02T18:11:00Z",
      resultId: "abc-1234",
    });
    expect(label).toBe("Select Polars 2026-05-02 (1234) for comparison");
  });
});

describe("hiddenIncompatibleSuffix", () => {
  it("returns an empty string for non-positive counts", () => {
    expect(hiddenIncompatibleSuffix(0)).toBe("");
    expect(hiddenIncompatibleSuffix(-1)).toBe("");
  });

  it("uses singular and plural forms correctly", () => {
    expect(hiddenIncompatibleSuffix(1)).toBe(" 1 incompatible row hidden.");
    expect(hiddenIncompatibleSuffix(7)).toBe(" 7 incompatible rows hidden.");
  });

  it("trims null/undefined inputs without leaving stray separators", () => {
    const label = compareSelectionLabel({
      platform: "Polars",
      benchmark: null,
      scaleFactor: null,
      phase: undefined,
      runDate: undefined,
      resultId: "abc12345",
    });
    expect(label).toBe("Select Polars (abc12345) for comparison");
  });
});
