import { render, screen, within } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import type { DetailResult } from "@/types";
import { RunReceipt } from "@/components/RunReceipt";

function makeDetail(overrides: Partial<DetailResult> = {}): DetailResult {
  return {
    result_id: "abcdef1234567890",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: "1.2.0",
    run_date: "2026-04-01",
    total_duration_s: 60,
    geomean_ms: 15,
    display_geomean_ms: 12,
    power_score: 3000,
    environment: {
      os: "macOS",
      arch: "arm64",
      cpu_count: 10,
      memory_gb: 64,
      python: "3.12.4",
    },
    queries: [
      { query_id: "Q1", duration_ms: 10, status: "pass", run_type: "measurement", iter: 1, stream: null },
      { query_id: "Q1", duration_ms: 12, status: "pass", run_type: "measurement", iter: 2, stream: null },
      { query_id: "Q2", duration_ms: 20, status: "pass", run_type: "measurement", iter: 1, stream: null },
      { query_id: "Q2", duration_ms: 22, status: "pass", run_type: "measurement", iter: 2, stream: null },
      { query_id: "Q2", duration_ms: 24, status: "pass", run_type: "measurement", iter: 3, stream: null },
    ],
    display_timings: [
      { query_id: "Q1", display_ms: 11, sample_count: 2 },
      { query_id: "Q2", display_ms: 22, sample_count: 3 },
    ],
    has_plans: false,
    has_tuning: true,
    bundle_download_url: "https://example.test/bundles/abcdef1234567890.json",
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: "1.2.0",
    execution_mode: "sql",
    tuning_mode: "tuned",
    tuning_hash: "tuning123",
    test_type: "power",
    validation_status: "exact",
    cost_usd: null,
    compliance_class: "unofficial_subscale",
    ...overrides,
  };
}

describe("RunReceipt", () => {
  it("renders compact workload, platform, environment, integrity, artifact, and cost sections", () => {
    render(
      <RunReceipt
        detail={makeDetail()}
        shortId="abc12345"
        isRankingEligible={true}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    for (const section of ["Workload", "Platform", "Environment", "Integrity", "Artifacts", "Cost"]) {
      expect(within(receipt).getByRole("heading", { name: section })).toBeTruthy();
    }

    expect(within(receipt).getByText("TPC-H")).toBeTruthy();
    expect(within(receipt).getByText("SF 0.1")).toBeTruthy();
    expect(within(receipt).getByText("power")).toBeTruthy();
    expect(within(receipt).getByText("DuckDB")).toBeTruthy();
    expect(within(receipt).getByText("macOS")).toBeTruthy();
    expect(within(receipt).getByText("exact")).toBeTruthy();
    expect(within(receipt).getByText("Eligible")).toBeTruthy();
    expect(within(receipt).getByText("abc12345")).toBeTruthy();
    expect(within(receipt).getByText("Plans not published")).toBeTruthy();
    expect(within(receipt).getAllByText("Not available").length).toBe(3);
  });

  it("keeps logical query count separate from measurement samples", () => {
    render(<RunReceipt detail={makeDetail()} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("Query count")).toBeTruthy();
    expect(within(receipt).getByText("Measurement samples")).toBeTruthy();
    expect(within(receipt).getByText("2")).toBeTruthy();
    expect(within(receipt).getByText("5")).toBeTruthy();
  });

  it("renders bundle and reproduce artifacts without requiring public plans", () => {
    render(<RunReceipt detail={makeDetail({ has_plans: true })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByRole("link", { name: "Download bundle" })).toHaveAttribute(
      "href",
      "https://example.test/bundles/abcdef1234567890.json",
    );
    expect(within(receipt).getByText("Plans available")).toBeTruthy();
    expect(within(receipt).getByText("benchbox run --platform duckdb --benchmark tpch --scale 0.1 --phases power"))
      .toBeTruthy();
  });
});
