import { render, screen, within } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import type { DetailResult } from "@/types";
import {
  COMPARABILITY_WARNING_TARGET_ID,
  buildComparabilityFields,
  comparabilityWarningFields,
  ComparabilityReceipt,
} from "@/components/ComparabilityReceipt";

function makeDetail(overrides: Partial<DetailResult> = {}): DetailResult {
  return {
    result_id: "r1",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: "1.0",
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
    environment: { os: "Linux", arch: "x64", cpu_count: 8, memory_gb: 32, python: "3.12" },
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
    platform_version: "0.10",
    execution_mode: "sql",
    tuning_mode: "default",
    tuning_hash: null,
    test_type: "power",
    validation_status: "exact",
    compliance_class: null,
    cost_usd: null,
    normalized_cost_usd: null,
    cost_model_version: "2026.05.0",
    cost_model_source: "benchbox.core.cost.pricing",
    cost_scope: "compute_only",
    cost_status: "unavailable",
    billing_unit: "unknown",
    pricing_region: "unknown",
    ...overrides,
  };
}

describe("ComparabilityReceipt", () => {
  it("renders workload matches and published cost metadata", () => {
    render(<ComparabilityReceipt results={[makeDetail(), makeDetail({ result_id: "r2", platform: "SQLite" })]} />);

    const receipt = screen.getByRole("region", { name: "Comparability receipt" });
    expect(receipt.getAttribute("id")).toBe("comparability-receipt");
    expect(within(receipt).getByText("No differences")).toBeTruthy();
    expect(receipt).toHaveTextContent("Benchmark");
    expect(receipt).toHaveTextContent("TPC-H");
    expect(receipt).toHaveTextContent("Query scope");
    expect(receipt).toHaveTextContent("2 queries");
    expect(receipt).toHaveTextContent("Cost model");
    expect(receipt).toHaveTextContent("2026.05.0 (benchbox.core.cost.pricing)");
  });

  it("flags normalized cost metadata differences", () => {
    const fields = buildComparabilityFields([
      makeDetail({ normalized_cost_usd: 0.42, cost_status: "normalized" }),
      makeDetail({
        result_id: "r2",
        platform: "SQLite",
        platform_id: "sqlite",
        normalized_cost_usd: null,
        cost_status: "unavailable",
      }),
    ]);

    expect(fields.find((field) => field.label === "Normalized cost")).toMatchObject({
      status: "diff",
      detail: "DuckDB: $0.42; SQLite: unavailable",
    });
  });

  it("warns when selected runs differ in methodology or environment fields", () => {
    const duckdb = makeDetail();
    const sqlite = makeDetail({
      result_id: "r2",
      platform: "SQLite",
      platform_id: "sqlite",
      driver_version: "2.0",
      run_date: "2026-04-03",
      environment: { os: "macOS", arch: "arm64", cpu_count: 10, memory_gb: 64, python: "3.11" },
      tuning_mode: "manual",
    });

    render(<ComparabilityReceipt results={[duckdb, sqlite]} />);

    const receipt = screen.getByRole("region", { name: "Comparability receipt" });
    expect(within(receipt).getAllByText("4 warnings")).toHaveLength(2);
    const warningTarget = screen.getByTestId("comparability-warning-target");
    expect(warningTarget.getAttribute("id")).toBe(COMPARABILITY_WARNING_TARGET_ID);
    expect(warningTarget.getAttribute("tabindex")).toBe("-1");
    expect(warningTarget).toHaveTextContent("Driver version");
    expect(warningTarget).toHaveTextContent("Date window");
    expect(receipt).toHaveTextContent("Driver version");
    expect(receipt).toHaveTextContent("DuckDB: 1.0; SQLite: 2.0");
    expect(receipt).toHaveTextContent("Date window");
    expect(receipt).toHaveTextContent("2026-04-01 to 2026-04-03");
    expect(receipt).toHaveTextContent("Tuning");
    expect(receipt).toHaveTextContent("DuckDB: default; SQLite: manual");
    expect(receipt).toHaveTextContent("Environment");
    expect(receipt).toHaveTextContent("DuckDB: Linux, x64, 8 CPU");
    expect(receipt).toHaveTextContent("SQLite: macOS, arm64, 10 CPU");
  });

  it("builds explicit warning fields for compare-page consumers", () => {
    const fields = buildComparabilityFields([
      makeDetail(),
      makeDetail({
        result_id: "r2",
        platform: "SQLite",
        platform_id: "sqlite",
        test_type: "throughput",
        display_timings: [{ query_id: "Q1", display_ms: 10, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null }],
      }),
    ]);

    expect(fields.find((field) => field.label === "Phase")?.status).toBe("diff");
    expect(fields.find((field) => field.label === "Query scope")?.status).toBe("diff");
    expect(comparabilityWarningFields(fields).map((field) => field.label)).toEqual(["Phase", "Query scope"]);
  });

  it("uses singular count copy for one warning and one query", () => {
    const duckdb = makeDetail({
      display_timings: [
        { query_id: "Q1", display_ms: 10, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
      ],
    });
    const sqlite = makeDetail({
      result_id: "r2",
      platform: "SQLite",
      platform_id: "sqlite",
      platform_version: "3.45",
      display_timings: [
        { query_id: "Q1", display_ms: 15, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
      ],
    });

    render(<ComparabilityReceipt results={[duckdb, sqlite]} />);

    const receipt = screen.getByRole("region", { name: "Comparability receipt" });
    expect(within(receipt).getAllByText("1 warning")).toHaveLength(2);
    expect(receipt).not.toHaveTextContent("1 warnings");
    expect(receipt).toHaveTextContent("1 query");
    expect(receipt).not.toHaveTextContent("1 queries");
  });

  it("flags benchmark and scale differences as explicit warning fields", () => {
    const fields = buildComparabilityFields([
      makeDetail(),
      makeDetail({
        result_id: "r2",
        benchmark: "clickbench",
        scale_factor: 1,
        platform: "SQLite",
        platform_id: "sqlite",
      }),
    ]);

    expect(fields.find((field) => field.label === "Benchmark")).toMatchObject({
      status: "diff",
      detail: "DuckDB: TPC-H; SQLite: ClickBench",
    });
    expect(fields.find((field) => field.label === "Scale factor")).toMatchObject({
      status: "diff",
      detail: "DuckDB: SF 0.1; SQLite: SF 1",
    });
  });
});
