/**
 * The engine-and-hardware strip.
 *
 * Answers one question: of the things that could explain a difference in these
 * numbers, which ones actually differ? It must not replace or duplicate the
 * ComparabilityReceipt, and it must never disagree with it.
 */

import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { IdentityDiffStrip, axisValueForRun, identityStripDiffCount, identityStripFields } from "@/components/IdentityDiffStrip";
import { buildComparabilityFields } from "@/components/ComparabilityReceipt";
import type { DetailResult } from "@/types";

function run(overrides: Partial<DetailResult> = {}): DetailResult {
  return {
    result_id: "r1",
    benchmark: "tpch",
    scale_factor: 1,
    platform: "DuckDB",
    platform_id: "duckdb",
    platform_version: "1.4.3",
    driver_version: "1.4.3",
    run_date: "2026-08-01",
    total_duration_s: 10,
    geomean_ms: 10,
    display_geomean_ms: 10,
    power_score: null,
    has_display_timing: true,
    display_timings: [],
    queries: [],
    environment: { arch: "arm64", cpu_family: "apple_silicon", cpu_model: "Apple M4", cpu_count: 10, memory_gb: 16 },
    ...overrides,
  } as unknown as DetailResult;
}

describe("axis selection", () => {
  it("reports the seven selected identity axes", () => {
    const fields = identityStripFields([run(), run({ result_id: "r2" })]);
    expect(fields).toHaveLength(7);
    expect(fields.map((f) => f.label)).toEqual([
      "Platform version",
      "Driver version",
      "Architecture",
      "CPU family",
      "CPU model",
      "CPU evidence",
      "Memory",
    ]);
  });

  it("reads the same fields the receipt does rather than re-deriving them", () => {
    // A second, independently-derived summary would eventually disagree with
    // the receipt about whether an axis differs. Sharing one source makes that
    // impossible rather than unlikely.
    const results = [run(), run({ result_id: "r2", platform_version: "1.5.0" })];
    const receipt = new Map(buildComparabilityFields(results).map((f) => [f.label, f]));
    for (const field of identityStripFields(results)) {
      expect(field).toEqual(receipt.get(field.label));
    }
  });
});

describe("marking which axes differ", () => {
  it("counts only the axes that actually differ", () => {
    const results = [run(), run({ result_id: "r2", platform_version: "1.5.0" })];
    expect(identityStripDiffCount(results)).toBe(1);
  });

  it("says so plainly when nothing differs", () => {
    render(<IdentityDiffStrip results={[run(), run({ result_id: "r2" })]} />);
    expect(screen.getByText(/No differences were recorded for these 7 fields/)).toBeTruthy();
  });

  it("reports the differing count with correct grammar", () => {
    render(<IdentityDiffStrip results={[run(), run({ result_id: "r2", platform_version: "1.5.0" })]} />);
    expect(screen.getByText(/1 of 7 axis differs/)).toBeTruthy();
  });

  it("pluralises for several differing axes", () => {
    const other = run({ result_id: "r2", platform_version: "1.5.0", driver_version: "9.9.9" });
    render(<IdentityDiffStrip results={[run(), other]} />);
    expect(screen.getByText(/2 of 7 axes differ/)).toBeTruthy();
  });

  it("formats fractional memory values consistently", () => {
    const fractional = run({
      environment: {
        arch: "arm64",
        cpu_family: "apple_silicon",
        cpu_model: "Apple M4",
        cpu_count: 10,
        memory_gb: 15.613975524902344,
      },
    });
    expect(axisValueForRun("Memory", fractional)).toBe("15.6 GB");
  });
});

describe("runs without CPU data", () => {
  it("renders 'not recorded' rather than guessing a vendor from the architecture", () => {
    // Most of the historical corpus recorded arch only. A guessed vendor would
    // fabricate the very axis this strip exists to compare.
    const noCpu = run({
      result_id: "r2",
      environment: { arch: "arm64" },
    } as Partial<DetailResult>);
    render(<IdentityDiffStrip results={[noCpu, run({ result_id: "r3", environment: { arch: "arm64" } } as Partial<DetailResult>)]} />);
    expect(screen.getAllByText("Not recorded").length).toBeGreaterThan(0);
  });
});

describe("multi-run identity matrix (N > 2 runs)", () => {
  it("renders a matrix with one row per axis and one column per run", () => {
    const r1 = run({ result_id: "r1", platform_version: "1.0.0" });
    const r2 = run({ result_id: "r2", platform_version: "2.0.0" });
    const r3 = run({ result_id: "r3", platform_version: "1.0.0" });
    render(<IdentityDiffStrip results={[r1, r2, r3]} baselineIndex={0} runLabels={["Run 1", "Run 2", "Run 3"]} />);

    expect(screen.getByText("Run 1 (baseline)")).toBeTruthy();
    expect(screen.getByText("Run 2")).toBeTruthy();
    expect(screen.getByText("Run 3")).toBeTruthy();
    expect(screen.getByText("Engine version")).toBeTruthy();
    expect(screen.getByText("Architecture")).toBeTruthy();
    expect(screen.getByText(/1 of 7 axis varies across the whole selection/)).toBeTruthy();
  });

  it("marks differing cells relative to baseline and identifies matching cells", () => {
    const r1 = run({ result_id: "r1", platform_version: "1.0.0" });
    const r2 = run({ result_id: "r2", platform_version: "2.0.0" });
    const r3 = run({ result_id: "r3", platform_version: "1.0.0" });
    render(<IdentityDiffStrip results={[r1, r2, r3]} baselineIndex={0} runLabels={["Run 1", "Run 2", "Run 3"]} />);

    const cellDiff = screen.getByTestId("matrix-cell-Platform version-1");
    expect(cellDiff.textContent).toContain("Differs");
    expect(cellDiff.textContent).toContain("2.0.0");

    const cellMatch = screen.getByTestId("matrix-cell-Platform version-2");
    expect(cellMatch.textContent).toContain("Same");
    expect(cellMatch.textContent).toContain("1.0.0");
  });

  it("renders 'not recorded' rather than 'differs' when a run lacks CPU data", () => {
    const r1 = run({ result_id: "r1" });
    const r2 = run({ result_id: "r2", environment: { arch: "arm64" } as any });
    const r3 = run({ result_id: "r3" });
    render(<IdentityDiffStrip results={[r1, r2, r3]} baselineIndex={0} />);

    const missingCell = screen.getByTestId("matrix-cell-CPU family-1");
    expect(missingCell.textContent).toContain("Not recorded");
    expect(missingCell.textContent).not.toContain("Differs");
  });

  it("keeps a recorded candidate value visible when only the baseline is missing", () => {
    const baseline = run({ result_id: "r1", environment: { arch: "arm64" } as any });
    const candidate = run({ result_id: "r2" });
    const third = run({ result_id: "r3" });
    render(<IdentityDiffStrip results={[baseline, candidate, third]} baselineIndex={0} />);

    const candidateCell = screen.getByTestId("matrix-cell-CPU model-1");
    expect(candidateCell).toHaveTextContent("Apple M4");
    expect(candidateCell).toHaveTextContent("No baseline");
    expect(candidateCell).not.toHaveTextContent("Not recorded");
  });
});

describe("rendering guards", () => {
  it("renders nothing for a single run", () => {
    const { container } = render(<IdentityDiffStrip results={[run()]} />);
    expect(container.textContent).toBe("");
  });

  it("renders nothing for an empty selection", () => {
    const { container } = render(<IdentityDiffStrip results={[]} />);
    expect(container.textContent).toBe("");
  });
});
