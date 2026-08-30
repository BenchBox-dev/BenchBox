/**
 * The six-axis engine-and-hardware strip.
 *
 * Answers one question: of the things that could explain a difference in these
 * numbers, which ones actually differ? It must not replace or duplicate the
 * ComparabilityReceipt, and it must never disagree with it.
 */

import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { IdentityDiffStrip, identityStripDiffCount, identityStripFields } from "@/components/IdentityDiffStrip";
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
  it("reports exactly six axes", () => {
    const fields = identityStripFields([run(), run({ result_id: "r2" })]);
    expect(fields).toHaveLength(6);
    expect(fields.map((f) => f.label)).toEqual([
      "Platform version",
      "Driver version",
      "Architecture",
      "CPU family",
      "CPU model",
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
    expect(screen.getByText(/match on every axis below/)).toBeTruthy();
  });

  it("reports the differing count with correct grammar", () => {
    render(<IdentityDiffStrip results={[run(), run({ result_id: "r2", platform_version: "1.5.0" })]} />);
    expect(screen.getByText(/1 of 6 axis differs/)).toBeTruthy();
  });

  it("pluralises for several differing axes", () => {
    const other = run({ result_id: "r2", platform_version: "1.5.0", driver_version: "9.9.9" });
    render(<IdentityDiffStrip results={[run(), other]} />);
    expect(screen.getByText(/2 of 6 axes differ/)).toBeTruthy();
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
