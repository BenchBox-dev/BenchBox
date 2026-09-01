import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import type { DetailResult } from "@/types";
import { CompareSummary } from "@/components/CompareSummary";
import { buildCompareDecisionSummary } from "@/lib/compareSummary";

function makeResult(overrides: Partial<DetailResult> = {}): DetailResult {
  return {
    result_id: "r1",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: null,
    run_date: "2026-04-01",
    total_duration_s: 60,
    geomean_ms: 10,
    display_geomean_ms: 10,
    power_score: 3000,
    has_display_timing: true,
    valid_query_count: 2,
    missing_query_count: 0,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
    normalized_cost_usd: 0.5,
    cost_status: "normalized",
    environment: {},
    queries: [],
    display_timings: [
      { query_id: "Q1", display_ms: 10, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
      { query_id: "Q2", display_ms: 20, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
    ],
    has_plans: false,
    has_tuning: false,
    bundle_download_url: "",
    trust_label: "maintainer-run",
    visibility: "public-curated",
    funding: "unspecified",
    platform_version: null,
    execution_mode: null,
    tuning_mode: null,
    tuning_hash: null,
    test_type: null,
    validation_status: null,
    compliance_class: null,
    cost_usd: null,
    ...overrides,
  };
}

describe("CompareSummary", () => {
  it("renders the computed headline, query record, tail stats, and cost context", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult(),
        makeResult({
          result_id: "r2",
          platform: "SQLite",
          platform_id: "sqlite",
          power_score: 300,
          normalized_cost_usd: 1.5,
          display_timings: [
            { query_id: "Q1", display_ms: 100, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
            { query_id: "Q2", display_ms: 200, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
          ],
        }),
      ],
      "power_score",
    );

    render(<CompareSummary summary={summary} />);

    const summaryRegion = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    expect(summaryRegion).not.toBeNull();
    expect(summaryRegion).toHaveTextContent("DuckDB leads by 10.00x on power score.");
    expect(summaryRegion).toHaveTextContent("2 fastest of 2 comparable");
    expect(summaryRegion).toHaveTextContent("p50 15 ms");
    expect(summaryRegion).toHaveTextContent("winner cost $0.50");
    expect(summaryRegion).toHaveTextContent("30.00x cost/performance");
  });

  it("renders suppressed winner state for incomparable cohorts", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult(),
        makeResult({
          result_id: "r2",
          platform: "SQLite",
          platform_id: "sqlite",
          power_score: 300,
        }),
      ],
      "power_score",
      {
        suppressWinnerClaims: true,
        suppressionReason: "benchmarks differ",
      },
    );

    render(<CompareSummary summary={summary} />);

    const summaryRegion = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    expect(summaryRegion).toHaveTextContent("Not directly comparable: benchmarks differ.");
    expect(summaryRegion).toHaveTextContent("Claims suppressed");
    expect(summaryRegion).toHaveTextContent("Not claimed");
    expect(summaryRegion).toHaveTextContent("Winner claim suppressed");
  });

  // -----------------------------------------------------------------------
  // Live reproduction: DuckDB (validated) vs Pandas (validation_status
  // "not_run") at H2ODB SF0.01. The headline used to claim a confident
  // winner off an unvalidated candidate with no visible caveat. It must now
  // carry the caveat in the headline itself, plus a distinct warning badge
  // and callout - a reader who only sees the headline must not conclude the
  // comparison rests on validated data.
  // -----------------------------------------------------------------------

  it("caveats the winner claim when one selected candidate is unvalidated (not_run)", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({ result_id: "duck", platform: "DuckDB", power_score: 3000, validation_status: "passed" }),
        makeResult({
          result_id: "pandas",
          platform: "Pandas",
          platform_id: "pandas",
          power_score: 843,
          validation_status: "not_run",
          display_timings: [
            { query_id: "Q1", display_ms: 100, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
            { query_id: "Q2", display_ms: 200, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
          ],
        }),
      ],
      "power_score",
    );

    // The winner claim is not suppressed by this gap alone...
    expect(summary.claimSuppressed).toBe(false);
    expect(summary.winner?.platform).toBe("DuckDB");
    // ...but the headline itself must not read as a clean, confident claim.
    expect(summary.headline).toContain("DuckDB leads by");
    expect(summary.headline).toContain("Validation caution");
    expect(summary.headline).toContain("Pandas is no validation");

    render(<CompareSummary summary={summary} />);
    const summaryRegion = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    expect(summaryRegion).toHaveTextContent("Unvalidated result");
    expect(summaryRegion).toHaveTextContent("Validation caution:");
    expect(summaryRegion).toHaveTextContent("Pandas is no validation");
    expect(screen.getByTestId("compare-validation-caveat")).toBeTruthy();
  });

  it("does not show a validation caveat when both candidates are clean (passed)", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({ result_id: "duck", platform: "DuckDB", power_score: 3000, validation_status: "passed" }),
        makeResult({
          result_id: "r2",
          platform: "SQLite",
          platform_id: "sqlite",
          power_score: 300,
          validation_status: "passed",
          display_timings: [
            { query_id: "Q1", display_ms: 100, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
            { query_id: "Q2", display_ms: 200, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
          ],
        }),
      ],
      "power_score",
    );

    expect(summary.nonCleanValidation).toHaveLength(0);
    expect(summary.validationCaveat).toBeNull();
    expect(summary.headline).toBe("DuckDB leads by 10.00x on power score.");

    render(<CompareSummary summary={summary} />);
    const summaryRegion = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    expect(summaryRegion).not.toHaveTextContent("Unvalidated result");
    expect(screen.queryByTestId("compare-validation-caveat")).toBeNull();
  });

  it("does not show a validation caveat when validation_status is simply absent (not a non-clean status)", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({ result_id: "duck", platform: "DuckDB", power_score: 3000 }),
        makeResult({
          result_id: "r2",
          platform: "SQLite",
          platform_id: "sqlite",
          power_score: 300,
          display_timings: [
            { query_id: "Q1", display_ms: 100, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
            { query_id: "Q2", display_ms: 200, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
          ],
        }),
      ],
      "power_score",
    );

    expect(summary.nonCleanValidation).toHaveLength(0);
    render(<CompareSummary summary={summary} />);
    const summaryRegion = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    expect(summaryRegion).not.toHaveTextContent("Unvalidated result");
  });
});
