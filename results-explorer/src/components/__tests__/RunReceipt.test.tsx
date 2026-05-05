import { render, screen, within } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import type { DetailResult } from "@/types";
import { RunReceipt, planDownloadUrl } from "@/components/RunReceipt";

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
    normalized_cost_usd: null,
    cost_model_version: "2026.05.0",
    cost_model_source: "benchbox.core.cost.pricing",
    cost_scope: "compute_only",
    cost_status: "unavailable",
    billing_unit: "unknown",
    pricing_region: "unknown",
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
    expect(within(receipt).getByText("Trust")).toBeTruthy();
    expect(within(receipt).getByText("maintainer-run")).toBeTruthy();
    expect(within(receipt).getByText("exact")).toBeTruthy();
    expect(within(receipt).getByText("Eligible")).toBeTruthy();
    expect(within(receipt).getByText("abc12345")).toBeTruthy();
    expect(within(receipt).getByText("Plans not published")).toBeTruthy();
    expect(within(receipt).getByText("unavailable")).toBeTruthy();
    expect(within(receipt).getByText("2026.05.0 (benchbox.core.cost.pricing)")).toBeTruthy();
    expect(within(receipt).getByText("compute only, billing: unknown, region: unknown")).toBeTruthy();
  });

  it("renders normalized cost metadata when it is present", () => {
    render(
      <RunReceipt
        detail={makeDetail({
          normalized_cost_usd: 0.42,
          cost_status: "normalized",
          billing_unit: "warehouse_hour",
          pricing_region: "us-east-1",
        })}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("$0.42")).toBeTruthy();
    expect(within(receipt).getByText("compute only, billing: warehouse_hour, region: us-east-1")).toBeTruthy();
  });

  it("keeps logical query count separate from measurement samples", () => {
    render(<RunReceipt detail={makeDetail()} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    const workload = within(receipt).getByRole("heading", { name: "Workload" }).closest("section");
    expect(workload).not.toBeNull();
    expect(workload).toHaveTextContent("Query count");
    expect(workload).toHaveTextContent("2");
    expect(workload).toHaveTextContent("Measurement samples");
    expect(workload).toHaveTextContent("5");
  });

  it("renders bundle and reproduce artifacts; only shows a Download plans link when plans are actually published", () => {
    render(<RunReceipt detail={makeDetail({ has_plans: true, plans_published: true })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByRole("link", { name: "Download bundle" })).toHaveAttribute(
      "href",
      "https://example.test/bundles/abcdef1234567890.json",
    );
    expect(within(receipt).getByRole("link", { name: "Download plans" })).toHaveAttribute(
      "href",
      "https://example.test/bundles/abcdef1234567890.plans.json",
    );
    expect(within(receipt).getByText("benchbox run --platform duckdb --benchmark tpch --scale 0.1 --phases power"))
      .toBeTruthy();
  });

  it("does NOT render a Download plans link when has_plans is true but plans were not published (w1 regression)", () => {
    render(<RunReceipt detail={makeDetail({ has_plans: true })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    // Download bundle link must still render — only the plans link is gated.
    expect(within(receipt).getByRole("link", { name: "Download bundle" })).toBeTruthy();
    expect(within(receipt).queryByRole("link", { name: "Download plans" })).toBeNull();
    // The non-link "Plans available" fallback string is shown instead.
    expect(within(receipt).getByText("Plans available")).toBeTruthy();
  });

  it("derives the plans companion URL only when publication is signaled (w1 regression)", () => {
    // Pre-w1 behavior gated only on has_plans; the URL would resolve to a
    // 404 for every published bundle because the explorer pipeline excludes
    // *.plans.json from bundle discovery. Post-w1, the link only renders
    // when plans_published is explicitly true.
    expect(planDownloadUrl(makeDetail({ has_plans: true, plans_published: true }))).toBe(
      "https://example.test/bundles/abcdef1234567890.plans.json",
    );
    expect(planDownloadUrl(makeDetail({ has_plans: true }))).toBeNull();
    expect(planDownloadUrl(makeDetail({ has_plans: true, plans_published: false }))).toBeNull();
    expect(planDownloadUrl(makeDetail({ has_plans: false, plans_published: true }))).toBeNull();
    expect(
      planDownloadUrl(
        makeDetail({ has_plans: true, plans_published: true, bundle_download_url: "" }),
      ),
    ).toBeNull();
  });
});
