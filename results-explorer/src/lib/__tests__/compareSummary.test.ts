import { describe, expect, it } from "vitest";
import type { DetailResult } from "@/types";
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
    environment: {},
    queries: [],
    display_timings: [
      { query_id: "Q1", display_ms: 10, sample_count: 3 },
      { query_id: "Q2", display_ms: 20, sample_count: 3 },
    ],
    has_plans: false,
    has_tuning: false,
    bundle_download_url: "",
    trust_label: "maintainer-run",
    visibility: "public-curated",
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

describe("buildCompareDecisionSummary", () => {
  it("selects the power-score winner and counts winner query wins", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({
          result_id: "duck",
          platform: "DuckDB",
          power_score: 3000,
          normalized_cost_usd: 0.5,
          cost_status: "normalized",
        }),
        makeResult({
          result_id: "sqlite",
          platform: "SQLite",
          platform_id: "sqlite",
          power_score: 300,
          normalized_cost_usd: 1.5,
          cost_status: "normalized",
          display_timings: [
            { query_id: "Q1", display_ms: 100, sample_count: 3 },
            { query_id: "Q2", display_ms: 200, sample_count: 3 },
          ],
        }),
      ],
      "power_score",
    );

    expect(summary.winner?.platform).toBe("DuckDB");
    expect(summary.comparisonRatio).toBe(10);
    expect(summary.headline).toBe("DuckDB leads by 10.00x on power score.");
    expect(summary.queryRecord).toMatchObject({
      totalQueries: 2,
      comparableQueries: 2,
      wins: 2,
      losses: 0,
      ties: 0,
      missing: 0,
    });
    expect(summary.percentiles[0]).toMatchObject({
      platform: "DuckDB",
      p50: 15,
      p90: 19,
    });
    expect(summary.percentiles[0]?.p99).toBeCloseTo(19.9);
    expect(summary.cost).toMatchObject({
      normalizedResultCount: 2,
      winnerCostUsd: 0.5,
      winnerIsBestCostPerformance: true,
    });
    expect(summary.cost?.winnerCostPerformanceRatioVsWorst).toBe(30);
  });

  it("uses lower geomean as better and tracks losses against faster query rows", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({
          result_id: "fast",
          platform: "FastDB",
          display_geomean_ms: 10,
          display_timings: [
            { query_id: "Q1", display_ms: 10, sample_count: 3 },
            { query_id: "Q2", display_ms: 40, sample_count: 3 },
            { query_id: "Q3", display_ms: 5, sample_count: 3 },
          ],
        }),
        makeResult({
          result_id: "slow",
          platform: "SlowDB",
          platform_id: "slow",
          display_geomean_ms: 40,
          display_timings: [
            { query_id: "Q1", display_ms: 20, sample_count: 3 },
            { query_id: "Q2", display_ms: 10, sample_count: 3 },
            { query_id: "Q3", display_ms: 5, sample_count: 3 },
          ],
        }),
      ],
      "display_geomean_ms",
    );

    expect(summary.winner?.platform).toBe("FastDB");
    expect(summary.comparisonRatio).toBe(4);
    expect(summary.headline).toBe("FastDB is 4.00x faster by geomean query time.");
    expect(summary.queryRecord).toMatchObject({
      comparableQueries: 3,
      wins: 1,
      losses: 1,
      ties: 1,
    });
  });

  it("counts missing query evidence when winner or competitors lack timings", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({
          result_id: "winner",
          platform: "WinnerDB",
          display_timings: [
            { query_id: "Q1", display_ms: 10, sample_count: 3 },
            { query_id: "Q2", display_ms: 20, sample_count: 3 },
          ],
        }),
        makeResult({
          result_id: "candidate",
          platform: "CandidateDB",
          platform_id: "candidate",
          power_score: 300,
          display_timings: [
            { query_id: "Q1", display_ms: 100, sample_count: 3 },
            { query_id: "Q3", display_ms: 300, sample_count: 3 },
          ],
        }),
      ],
      "power_score",
    );

    expect(summary.queryRecord).toMatchObject({
      totalQueries: 3,
      comparableQueries: 1,
      wins: 1,
      losses: 0,
      ties: 0,
      missing: 2,
    });
  });

  it("suppresses winner claims when every selected result lacks the primary metric", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({ display_geomean_ms: null }),
        makeResult({ result_id: "r2", platform: "SQLite", display_geomean_ms: null }),
      ],
      "display_geomean_ms",
    );

    expect(summary.winner).toBeNull();
    expect(summary.headline).toBe("No winner claim: selected results are missing the primary metric.");
    expect(summary.queryRecord.missing).toBe(2);
  });

  it("uses only cost_status=normalized rows for cost/performance context", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({
          result_id: "duck",
          normalized_cost_usd: 0.5,
          cost_status: "normalized",
        }),
        makeResult({
          result_id: "legacy",
          platform: "LegacyDB",
          platform_id: "legacy",
          power_score: 300,
          normalized_cost_usd: 0.01,
          cost_status: "unavailable",
        }),
      ],
      "power_score",
    );

    expect(summary.cost).toMatchObject({
      normalizedResultCount: 1,
      winnerCostUsd: 0.5,
      winnerCostPerformanceRatioVsWorst: 1,
    });
  });

  it("omits cost context when no selected rows have normalized cost", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({
          result_id: "duck",
          normalized_cost_usd: null,
          cost_status: "not_applicable_local",
        }),
        makeResult({
          result_id: "sqlite",
          platform: "SQLite",
          platform_id: "sqlite",
          power_score: 300,
          normalized_cost_usd: null,
          cost_status: "unavailable",
        }),
      ],
      "power_score",
    );

    expect(summary.cost).toBeNull();
  });

  it("suppresses winner language when cohort guardrails mark the selection incomparable", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({ result_id: "duck", platform: "DuckDB" }),
        makeResult({ result_id: "sqlite", platform: "SQLite", power_score: 300 }),
      ],
      "power_score",
      {
        suppressWinnerClaims: true,
        suppressionReason: "benchmarks differ",
      },
    );

    expect(summary.claimSuppressed).toBe(true);
    expect(summary.winner).toBeNull();
    expect(summary.headline).toBe(
      "Not directly comparable: benchmarks differ. Winner language is suppressed; raw query evidence remains available.",
    );
  });

  it("renders tie copy when same-platform comparison rounds to 1.00x (finding #8)", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({ result_id: "polars-a", platform: "Polars", power_score: 1000 }),
        makeResult({ result_id: "polars-b", platform: "Polars", power_score: 1000 }),
      ],
      "power_score",
    );

    expect(summary.isTie).toBe(true);
    expect(summary.headline).toContain("tie threshold");
    expect(summary.headline).not.toContain("leads by");
    expect(summary.headline).not.toContain("faster");
  });

  it("uses the cohort-aware run label in the headline when runLabels are provided", () => {
    const summary = buildCompareDecisionSummary(
      [
        makeResult({ result_id: "polars-a", platform: "Polars", power_score: 1500 }),
        makeResult({ result_id: "polars-b", platform: "Polars", power_score: 1000 }),
      ],
      "power_score",
      {
        runLabels: {
          "polars-a": "Polars 2026-05-08 (deadbeef)",
          "polars-b": "Polars 2026-05-02 (0093bb7a)",
        },
      },
    );

    expect(summary.isTie).toBe(false);
    expect(summary.winnerLabel).toBe("Polars 2026-05-08 (deadbeef)");
    expect(summary.headline).toContain("Polars 2026-05-08 (deadbeef)");
    expect(summary.headline).not.toMatch(/^Polars leads/);
  });
});
