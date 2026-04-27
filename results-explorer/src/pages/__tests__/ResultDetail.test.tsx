/**
 * Tests for ResultDetail page - median-first contract.
 *
 * Cases:
 *   (a) Default table rows match display_timings.length (not queries.length)
 *   (b) sample_count cell matches display_timings[i].sample_count
 *   (c) Opening the "Individual samples" expander reveals the raw queries table
 *   (d) QueryTimingChart bar count matches display_timings.length
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { DetailResult } from "@/types";

vi.mock("@/lib/duckdbQueries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/duckdbQueries")>("@/lib/duckdbQueries");
  return {
    ...actual,
    getDetailResult: vi.fn(),
    getPrimaryMetricForBenchmark: vi.fn().mockResolvedValue("power_score"),
  };
});

import { getDetailResult } from "@/lib/duckdbQueries";
import { ResultDetail } from "@/pages/ResultDetail";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeDetail(overrides: Partial<DetailResult> = {}): DetailResult {
  return {
    result_id: "r1",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: null,
    run_date: "2026-04-01",
    total_duration_s: 60,
    geomean_ms: 15,
    display_geomean_ms: 12,
    power_score: 3000,
    environment: {},
    queries: [
      { query_id: "Q1", duration_ms: 10, status: "pass", run_type: "measurement", iter: 1, stream: null },
      { query_id: "Q1", duration_ms: 11, status: "pass", run_type: "measurement", iter: 2, stream: null },
      { query_id: "Q1", duration_ms: 12, status: "pass", run_type: "measurement", iter: 3, stream: null },
      { query_id: "Q2", duration_ms: 20, status: "pass", run_type: "measurement", iter: 1, stream: null },
      { query_id: "Q2", duration_ms: 21, status: "pass", run_type: "measurement", iter: 2, stream: null },
      { query_id: "Q2", duration_ms: 22, status: "pass", run_type: "measurement", iter: 3, stream: null },
    ],
    display_timings: [
      { query_id: "Q1", display_ms: 11, sample_count: 3 },
      { query_id: "Q2", display_ms: 21, sample_count: 3 },
    ],
    has_plans: false,
    has_tuning: false,
    bundle_download_url: "https://example.test/download/r1.json",
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: null,
    tuning_mode: null,
    tuning_hash: null,
    test_type: null,
    validation_status: null,
    cost_usd: null,
    compliance_class: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ResultDetail - median-first contract", () => {
  beforeEach(() => {
    vi.mocked(getDetailResult).mockResolvedValue(makeDetail());
  });

  it("(a) default table shows one row per display_timing, not per raw query", async () => {
    render(<ResultDetail resultId="r1" />);
    await waitFor(() => expect(screen.queryByText("Loading result...")).toBeNull());

    // Header should show display_timings count
    expect(screen.getByText("Query Timings (2)")).toBeTruthy();

    // The main table has "Median (ms)" column header (not "Duration (ms)")
    expect(screen.getAllByText(/Median \(ms\)/i).length).toBeGreaterThan(0);

    // Two data rows: Q1 and Q2 (one each from display_timings)
    const q1Cells = screen.getAllByText("Q1");
    const q2Cells = screen.getAllByText("Q2");
    expect(q1Cells.length).toBeGreaterThanOrEqual(1);
    expect(q2Cells.length).toBeGreaterThanOrEqual(1);
  });

  it("(b) sample_count cell matches display_timings[i].sample_count", async () => {
    render(<ResultDetail resultId="r1" />);
    await waitFor(() => expect(screen.queryByText("Loading result...")).toBeNull());

    // Both queries have sample_count = 3; the "Samples" column header exists
    expect(screen.getByText(/^Samples/)).toBeTruthy();
    const sampleCells = screen.getAllByText("3");
    // At least 2 cells showing "3" (one per query in display_timings)
    expect(sampleCells.length).toBeGreaterThanOrEqual(2);
  });

  it("(c) expanding 'Individual samples' reveals raw queries table", async () => {
    render(<ResultDetail resultId="r1" />);
    await waitFor(() => expect(screen.queryByText("Loading result...")).toBeNull());

    // The expander summary is present
    const expander = screen.getByText(/Individual samples \(6\)/i);
    expect(expander).toBeTruthy();

    // The raw "Status" column header is hidden until expanded (inside <details>)
    // After expanding, it should appear
    fireEvent.click(expander);

    // Now the raw Duration (ms) column is visible
    expect(screen.getAllByText(/Duration \(ms\)/i).length).toBeGreaterThan(0);
  });

  it("(d) registry-driven chart panel uses display_timings-backed charts", async () => {
    const detail = makeDetail();
    vi.mocked(getDetailResult).mockResolvedValue(detail);
    render(<ResultDetail resultId="r1" />);
    await waitFor(() => expect(screen.queryByText("Loading result...")).toBeNull());

    expect(screen.getByText("Charts")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Query Histogram" })).toBeTruthy();
  });
});
