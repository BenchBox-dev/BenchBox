import { fireEvent, render, screen, within } from "@testing-library/preact";
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
    has_display_timing: true,
    valid_query_count: 2,
    missing_query_count: 0,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
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
      { query_id: "Q1", display_ms: 11, sample_count: 2, is_valid_display_timing: true, timing_exclusion_reason: null },
      { query_id: "Q2", display_ms: 22, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
    ],
    has_plans: false,
    has_tuning: true,
    bundle_download_url: "https://example.test/bundles/abcdef1234567890.json",
    trust_label: "maintainer-run",
    visibility: "public-curated",
    funding: "unspecified",
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
    // `results-explorer-result-detail-metadata-density` w4 wires
    // RunReceipt onto the shared display-label formatters so the
    // hyphenated source slug renders as a humanized label here too.
    expect(within(receipt).getByText("maintainer run")).toBeTruthy();
    expect(within(receipt).getByText("public (curated)")).toBeTruthy();
    expect(within(receipt).getByText("exact")).toBeTruthy();
    expect(within(receipt).getByText("Eligible")).toBeTruthy();
    expect(within(receipt).getByText("abc12345")).toBeTruthy();
    expect(within(receipt).getByText("Plans not published")).toBeTruthy();
    expect(within(receipt).getByText("unavailable")).toBeTruthy();
    expect(within(receipt).getByText("2026.05.0 (benchbox.core.cost.pricing)")).toBeTruthy();
    // Sentinel "unknown" for billing/region is suppressed (finding #12);
    // only the cost scope renders.
    expect(within(receipt).getByText("compute only")).toBeTruthy();
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
    expect(within(receipt).getByText("compute only, billing: warehouse hour, region: us-east-1")).toBeTruthy();
  });

  it("does not leak raw not_applicable enum into the Cost section copy (finding #12)", () => {
    render(
      <RunReceipt
        detail={makeDetail({
          cost_status: "not_applicable_local",
          cost_scope: "compute_only",
          billing_unit: "not_applicable",
          pricing_region: "not_applicable",
        })}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("compute only")).toBeTruthy();
    expect(receipt.textContent ?? "").not.toMatch(/not_applicable/);
    expect(receipt.textContent ?? "").not.toMatch(/billing: not applicable/);
    expect(receipt.textContent ?? "").not.toMatch(/region: not applicable/);
  });

  it("counts placeholder cost summaries as missing receipt metadata", () => {
    render(
      <RunReceipt
        detail={makeDetail({
          cost_model_version: null,
          cost_model_source: null,
          cost_scope: null,
          billing_unit: null,
          pricing_region: null,
        })}
        shortId="abc12345"
        isRankingEligible={true}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    const cost = within(receipt).getByRole("heading", { name: "Cost" }).closest("section");
    expect(cost).not.toBeNull();
    const costSection = within(cost as HTMLElement);

    expect(within(receipt).getByText("2 fields not recorded for this run.")).toBeTruthy();
    expect(costSection.getByText("2 fields not recorded")).toBeTruthy();
    expect(costSection.queryByText("Cost model")).toBeNull();
    expect(costSection.queryByText("Cost scope")).toBeNull();
    expect(costSection.getByText("unavailable")).toBeTruthy();

    fireEvent.click(within(receipt).getByRole("button", { name: /Show missing metadata/ }));
    expect(costSection.getByText("Cost model")).toBeTruthy();
    expect(costSection.getByText("Cost scope")).toBeTruthy();
    expect(costSection.getAllByText("Not recorded")).toHaveLength(2);
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

  it("hides missing metadata behind the Show missing metadata disclosure (w3)", () => {
    // Sparse-metadata fixture: trust + visibility recorded, the entire
    // Platform/Environment surface unrecorded, validation/compliance
    // missing, no normalized cost. The default view should expose
    // recorded fields plus per-section "N field(s) not recorded"
    // counters; clicking the global disclosure reveals the actual
    // Not-recorded rows so audit users can still see them.
    render(
      <RunReceipt
        detail={makeDetail({
          platform_version: null,
          driver_version: null,
          execution_mode: null,
          tuning_mode: null,
          tuning_hash: null,
          environment: { os: undefined, arch: undefined, cpu_count: undefined, memory_gb: undefined, python: undefined },
          test_type: null,
          validation_status: null,
          compliance_class: null,
          has_tuning: false,
        })}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    // Recorded fields (Benchmark, Scale, Platform name, Trust, Visibility)
    // remain visible without expanding the disclosure.
    expect(within(receipt).getByText("TPC-H")).toBeTruthy();
    expect(within(receipt).getByText("DuckDB")).toBeTruthy();
    expect(within(receipt).getByText("maintainer run")).toBeTruthy();
    expect(within(receipt).getByText("public (curated)")).toBeTruthy();

    // Missing rows are NOT in the default DOM.
    expect(within(receipt).queryByText("Platform version")).toBeNull();
    expect(within(receipt).queryByText("Driver version")).toBeNull();
    expect(within(receipt).queryByText("OS")).toBeNull();
    expect(within(receipt).queryByText("Validation")).toBeNull();
    // Per-section counters still surface the missing count so users
    // know there is more behind the disclosure.
    expect(within(receipt).getAllByText(/\d+ fields? not recorded/).length).toBeGreaterThan(0);

    // Click the global disclosure — every previously-hidden field
    // becomes visible.
    const toggle = within(receipt).getByRole("button", { name: /Show missing metadata/ });
    fireEvent.click(toggle);
    expect(within(receipt).getByText("Platform version")).toBeTruthy();
    expect(within(receipt).getByText("OS")).toBeTruthy();
    expect(within(receipt).getByText("Validation")).toBeTruthy();
    expect(within(receipt).getAllByText("Not recorded").length).toBeGreaterThan(0);

    // The button copy flips and the disclosure round-trips.
    const hideToggle = within(receipt).getByRole("button", { name: /Hide missing metadata/ });
    fireEvent.click(hideToggle);
    expect(within(receipt).queryByText("Platform version")).toBeNull();
  });

  it("does not render the missing-metadata disclosure when every field is recorded (w3)", () => {
    render(
      <RunReceipt
        detail={makeDetail({ plans_published: true })}
        shortId="abc12345"
        isRankingEligible={true}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    // No "Show missing metadata" toggle, no per-section "N field(s)
    // not recorded" footer when every row is populated.
    expect(within(receipt).queryByRole("button", { name: /Show missing metadata/ })).toBeNull();
    expect(within(receipt).queryByText(/\d+ fields? not recorded/)).toBeNull();
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
