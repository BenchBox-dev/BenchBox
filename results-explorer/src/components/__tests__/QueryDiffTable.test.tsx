import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import type { DetailResult } from "@/types";
import { buildQueryDiffRows, QueryDiffTable } from "@/components/QueryDiffTable";

function makeResult(overrides: Partial<DetailResult> = {}): DetailResult {
  return {
    result_id: "baseline",
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
    missing_query_count: 1,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
    environment: {},
    queries: [],
    display_timings: [
      { query_id: "Q1", display_ms: 10, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
      { query_id: "Q2", display_ms: 20, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
      { query_id: "Q3", display_ms: null, sample_count: 0, is_valid_display_timing: false, timing_exclusion_reason: "missing_timing" },
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

describe("buildQueryDiffRows", () => {
  it("builds baseline-to-candidate ratios, deltas, and statuses", () => {
    const rows = buildQueryDiffRows([
      makeResult(),
      makeResult({
        result_id: "candidate",
        platform: "SQLite",
        platform_id: "sqlite",
        display_timings: [
          { query_id: "Q1", display_ms: 20, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
          { query_id: "Q2", display_ms: 10, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
          { query_id: "Q3", display_ms: null, sample_count: 0, is_valid_display_timing: false, timing_exclusion_reason: "missing_timing" },
        ],
      }),
    ]);

    expect(rows).toEqual([
      {
        queryId: "Q1",
        candidateResultId: "candidate",
        candidatePlatform: "SQLite",
        baselineMs: 10,
        candidateMs: 20,
        ratio: 2,
        deltaMs: 10,
        status: "slower",
      },
      {
        queryId: "Q2",
        candidateResultId: "candidate",
        candidatePlatform: "SQLite",
        baselineMs: 20,
        candidateMs: 10,
        ratio: 0.5,
        deltaMs: -10,
        status: "faster",
      },
      {
        queryId: "Q3",
        candidateResultId: "candidate",
        candidatePlatform: "SQLite",
        baselineMs: null,
        candidateMs: null,
        ratio: null,
        deltaMs: null,
        status: "missing",
      },
    ]);
  });

  it("normalizes an out-of-range baseline index before selecting candidates", () => {
    const rows = buildQueryDiffRows(
      [
        makeResult({ result_id: "baseline", platform: "DuckDB" }),
        makeResult({
          result_id: "candidate",
          platform: "SQLite",
          platform_id: "sqlite",
          display_timings: [{ query_id: "Q1", display_ms: 20, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null }],
        }),
      ],
      99,
    );

    expect(rows).toHaveLength(3);
    expect(rows[0]).toMatchObject({
      queryId: "Q1",
      candidateResultId: "candidate",
      baselineMs: 10,
      candidateMs: 20,
    });
    expect(rows.some((row) => row.candidateResultId === "baseline")).toBe(false);
  });

  it("builds one query row per non-baseline candidate for multi-result compares", () => {
    const rows = buildQueryDiffRows([
      makeResult({
        result_id: "baseline",
        display_timings: [
          { query_id: "Q1", display_ms: 10, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
          { query_id: "Q2", display_ms: 20, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
        ],
      }),
      makeResult({
        result_id: "candidate-a",
        platform: "SQLite",
        platform_id: "sqlite",
        display_timings: [
          { query_id: "Q1", display_ms: 20, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
          { query_id: "Q2", display_ms: 40, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
        ],
      }),
      makeResult({
        result_id: "candidate-b",
        platform: "PostgreSQL",
        platform_id: "postgresql",
        display_timings: [
          { query_id: "Q1", display_ms: 5, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
          { query_id: "Q2", display_ms: 10, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
        ],
      }),
    ]);

    expect(rows).toHaveLength(4);
    expect(rows.map((row) => `${row.queryId}:${row.candidateResultId}`)).toEqual([
      "Q1:candidate-a",
      "Q1:candidate-b",
      "Q2:candidate-a",
      "Q2:candidate-b",
    ]);
  });
});

describe("QueryDiffTable", () => {
  it("renders a dense diff table with baseline and candidate evidence", () => {
    render(
      <QueryDiffTable
        results={[
          makeResult(),
          makeResult({
            result_id: "candidate",
            platform: "SQLite",
            platform_id: "sqlite",
            display_timings: [
              { query_id: "Q1", display_ms: 20, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
              { query_id: "Q2", display_ms: 10, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
            ],
          }),
        ]}
      />,
    );

    const table = screen.getByRole("heading", { name: "Query-Level Diff" }).closest("section");
    expect(table).not.toBeNull();
    expect(table).toHaveTextContent("Baseline: DuckDB");
    expect(table).toHaveTextContent("3 comparisons");
    expect(table).toHaveTextContent("Q1");
    expect(table).toHaveTextContent("SQLite");
    expect(table).toHaveTextContent("2.00x");
    expect(table).toHaveTextContent("+10 ms");
    expect(table).toHaveTextContent("Slower");
    expect(table).toHaveTextContent("0.50x");
    expect(table).toHaveTextContent("-10 ms");
    expect(table).toHaveTextContent("Faster");
    expect(table).toHaveTextContent("Missing");
  });
});
