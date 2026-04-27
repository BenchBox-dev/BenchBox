/**
 * Tests for MethodologyDisclosure component.
 *
 * Cases:
 *   (a) Collapsed by default - content hidden on first render
 *   (b) Expands on click - all disclosure rows render
 *   (c) Null-safe rendering for older bundles missing extended fields
 *   (d) modeLabel / testTypeLabel helpers return expected strings
 */

import { fireEvent, render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import type { DetailResult } from "@/types";
import { MethodologyDisclosure, modeLabel, testTypeLabel } from "@/components/MethodologyDisclosure";

function makeDetail(overrides: Partial<DetailResult> = {}): DetailResult {
  const base = {
    result_id: "r1",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    platform_version: null,
    driver_version: null,
    run_date: "2026-04-01T00:00:00Z",
    trust_label: "maintainer-run",
    visibility: "public-curated",
    tuning_mode: "tuned",
    tuning_hash: null,
    execution_mode: "sql",
    test_type: "power",
    validation_status: "exact",
    has_tuning: true,
    bundle_download_url: null,
    power_score: null,
    total_duration_s: 0,
    geomean_ms: null,
    display_geomean_ms: null,
    environment: {},
    queries: [
      { query_id: "Q1", duration_ms: 10, status: "pass", run_type: null, iter: null, stream: null },
      { query_id: "Q2", duration_ms: 20, status: "pass", run_type: null, iter: null, stream: null },
    ],
    display_timings: [],
    phase_durations: null,
  } as unknown as DetailResult;
  return { ...base, ...overrides } as DetailResult;
}

describe("MethodologyDisclosure", () => {
  it("renders the toggle button collapsed by default", () => {
    render(<MethodologyDisclosure detail={makeDetail()} />);
    const btn = screen.getByRole("button", { name: /How this was measured/i });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/Primary metric/i)).toBeNull();
  });

  it("expands on click and renders every disclosure row", () => {
    render(<MethodologyDisclosure detail={makeDetail()} />);
    const btn = screen.getByRole("button", { name: /How this was measured/i });
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(/Primary metric/i)).toBeTruthy();
    expect(screen.getByText(/Execution mode/i)).toBeTruthy();
    expect(screen.getByText(/Test type/i)).toBeTruthy();
    expect(screen.getByText(/Tuning state/i)).toBeTruthy();
    expect(screen.getByText(/Query scope/i)).toBeTruthy();
    expect(screen.getByText(/Validation/i)).toBeTruthy();
  });

  it("falls back to 'Not recorded' when fields are null (old bundles)", () => {
    const detail = makeDetail({
      execution_mode: null,
      test_type: null,
      tuning_mode: null,
      validation_status: null,
    });
    render(<MethodologyDisclosure detail={detail} />);
    fireEvent.click(screen.getByRole("button"));
    const notRecorded = screen.getAllByText(/Not recorded/i);
    expect(notRecorded.length).toBeGreaterThanOrEqual(3);
  });

  it("uses singular 'query' for a single-query scope", () => {
    const detail = makeDetail({
      queries: [{ query_id: "Q1", duration_ms: 1, status: "pass", run_type: null, iter: null, stream: null }],
    });
    render(<MethodologyDisclosure detail={detail} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("1 query")).toBeTruthy();
  });

  it("modeLabel returns expected strings for known modes", () => {
    expect(modeLabel("sql")).toBe("SQL (query engine)");
    expect(modeLabel("dataframe")).toBe("DataFrame (in-process)");
    expect(modeLabel(null)).toBe("Not recorded");
    expect(modeLabel("exotic")).toBe("exotic");
  });

  it("testTypeLabel returns expected strings for known types", () => {
    expect(testTypeLabel("power")).toBe("Power test (single-stream sequential)");
    expect(testTypeLabel("throughput")).toBe("Throughput test (concurrent streams)");
    expect(testTypeLabel(null)).toBe("Not recorded");
    expect(testTypeLabel("future-mode")).toBe("future-mode");
  });
});
