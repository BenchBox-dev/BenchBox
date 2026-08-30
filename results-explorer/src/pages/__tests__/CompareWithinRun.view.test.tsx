import { fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CompareWithinRun } from "@/pages/CompareWithinRun";
import type { DetailResult } from "@/types";

vi.mock("@/lib/duckdbQueries", () => ({
  getDetailResult: vi.fn(),
}));

import { getDetailResult } from "@/lib/duckdbQueries";

function makeDetail(): DetailResult {
  return {
    result_id: "res-123",
    benchmark: "tpch",
    scale_factor: 1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: "1.0",
    run_date: "2026-04-18T00:00:00Z",
    total_duration_s: 10,
    geomean_ms: 25,
    display_geomean_ms: 25,
    power_score: null,
    has_display_timing: true,
    valid_query_count: 2,
    missing_query_count: 0,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
    environment: {
      cpu_model: "Apple M1",
      os: "Darwin",
      logical_cores: 8,
      physical_cores: 8,
      memory_gb: 16,
    } as any,
    queries: [
      { query_id: "Q1", duration_ms: 50, status: "pass", run_type: "warmup", iter: null, stream: 0 },
      { query_id: "Q1", duration_ms: 20, status: "pass", run_type: "measurement", iter: 1, stream: 0 },
      { query_id: "Q1", duration_ms: 10, status: "pass", run_type: "measurement", iter: 2, stream: 0 },
      { query_id: "Q2", duration_ms: 100, status: "pass", run_type: "warmup", iter: null, stream: 0 },
      { query_id: "Q2", duration_ms: 40, status: "pass", run_type: "measurement", iter: 1, stream: 0 },
      { query_id: "Q2", duration_ms: 30, status: "pass", run_type: "measurement", iter: 2, stream: 0 },
    ],
    display_timings: [
      { query_id: "Q1", display_ms: 15, is_valid_display_timing: true, timing_exclusion_reason: null, sample_count: 1 },
      { query_id: "Q2", display_ms: 35, is_valid_display_timing: true, timing_exclusion_reason: null, sample_count: 1 },
    ],
    has_plans: false,
    has_tuning: false,
    bundle_download_url: "",
    trust_label: "certified",
    visibility: "public",
    funding: "self",
    platform_version: "1.0",
    execution_mode: null,
    tuning_mode: null,
    tuning_hash: null,
    compliance_class: null, test_type: "standard", validation_status: "valid", cost_usd: null,
  };
}

describe("CompareWithinRun page component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (getDetailResult as any).mockResolvedValue(makeDetail());
    window.history.replaceState(null, "", "/results/r/res-123/passes");
  });

  it("renders within-run comparisons with reference badge and ratio calculations", async () => {
    render(<CompareWithinRun resultId="res-123" />);

    await waitFor(() => {
      expect(screen.getByText("DuckDB — measurement bases compared")).toBeTruthy();
    });

    // Check table headers and cells
    expect(screen.getByText("Q1")).toBeTruthy();
    expect(screen.getByText("Q2")).toBeTruthy();
    expect(screen.getAllByText(/Geomean query time/i).length).toBeGreaterThan(0);
  });

  it("changes reference basis when clicking the reference radio button", async () => {
    window.history.replaceState(null, "", "/results/r/res-123/passes?bases=default,warm_pass_1&ref=0");
    render(<CompareWithinRun resultId="res-123" />);

    await waitFor(() => {
      expect(screen.getByText("DuckDB — measurement bases compared")).toBeTruthy();
    });

    const radioWarmPass1 = screen.getByTestId("reference-radio-warm_pass_1");
    fireEvent.click(radioWarmPass1);

    expect(window.location.search).toContain("ref=1");
  });

  it("allows removing a basis column when more than 2 are present", async () => {
    window.history.replaceState(null, "", "/results/r/res-123/passes?bases=default,warm_pass_1,warm_pass_2&ref=0");
    render(<CompareWithinRun resultId="res-123" />);

    await waitFor(() => {
      expect(screen.getByText("DuckDB — measurement bases compared")).toBeTruthy();
    });

    const removeButtons = screen.getAllByRole("button", { name: /^Remove / });
    expect(removeButtons.length).toBe(3);

    fireEvent.click(removeButtons[2]!);

    await waitFor(() => {
      expect(window.location.search).not.toContain("warm_pass_2");
    });
  });

  it("allows adding an available basis column", async () => {
    window.history.replaceState(null, "", "/results/r/res-123/passes?bases=default,warm_pass_1&ref=0");
    render(<CompareWithinRun resultId="res-123" />);

    await waitFor(() => {
      expect(screen.getByText("DuckDB — measurement bases compared")).toBeTruthy();
    });

    const addButton = screen.getByRole("button", { name: "+ Add basis" });
    fireEvent.click(addButton);

    await waitFor(() => {
      // Third column added
      expect(screen.getAllByRole("radio").length).toBe(3);
    });
  });

  it("suppresses aggregate direction when only one query is comparable", async () => {
    const detail = makeDetail();
    (getDetailResult as any).mockResolvedValue({
      ...detail,
      queries: detail.queries.filter(
        (query) => query.query_id === "Q1" || query.run_type !== "measurement" || query.iter !== 1,
      ),
    });
    window.history.replaceState(null, "", "/results/r/res-123/passes?bases=default,warm_pass_1&ref=0");

    render(<CompareWithinRun resultId="res-123" />);

    await waitFor(() => {
      expect(screen.getByText("1 of 2 queries comparable")).toBeTruthy();
    });
    expect(screen.queryByText("faster")).toBeNull();
    expect(screen.queryByText("slower")).toBeNull();
    expect(screen.queryByText("parity")).toBeNull();
    expect(screen.queryByText("0.50x")).toBeNull();
    expect(screen.queryByText("0.50x (-50.0 ms)")).toBeNull();
  });

  it("does not style tie-band query ratios as faster", async () => {
    const detail = makeDetail();
    (getDetailResult as any).mockResolvedValue({
      ...detail,
      queries: detail.queries.map((query) => {
        if (query.run_type !== "measurement" || query.iter !== 1) return query;
        return {
          ...query,
          duration_ms: query.query_id === "Q1" ? 14.97 : 34.93,
        };
      }),
    });
    window.history.replaceState(null, "", "/results/r/res-123/passes?bases=default,warm_pass_1&ref=0");

    render(<CompareWithinRun resultId="res-123" />);

    await waitFor(() => {
      expect(screen.getByText("DuckDB — measurement bases compared")).toBeTruthy();
    });
    const displayedTieRatios = screen.getAllByText(/^1\.00x \(/);
    expect(displayedTieRatios.length).toBeGreaterThan(0);
    for (const ratio of displayedTieRatios) {
      expect(ratio.className).not.toContain("bb-tone-success-fg");
      expect(ratio.className).not.toContain("font-medium");
    }
  });
});
