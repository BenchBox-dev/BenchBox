import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import type { DetailResult } from "@/types";
import { ComparabilityReceipt } from "@/components/ComparabilityReceipt";
import { expectNoAxeViolations } from "@/testing/axe-helper";

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
    funding: "unspecified",
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

describe("ComparabilityReceipt accessibility", () => {
  it("has no serious or critical axe violations with warning targets", async () => {
    const { container } = render(
      <ComparabilityReceipt
        results={[
          makeDetail(),
          makeDetail({
            result_id: "r2",
            platform: "SQLite",
            platform_id: "sqlite",
            driver_version: "2.0",
            run_date: "2026-04-03",
            environment: { os: "macOS", arch: "arm64", cpu_count: 10, memory_gb: 64, python: "3.11" },
          }),
        ]}
      />,
    );

    expect(screen.getByRole("region", { name: "Warning details" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});
