import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import type { BenchmarkSummary, PlatformRow } from "@/types";
import { DistributionBox } from "@/components/DistributionBox";

function makePlatform(overrides: Partial<PlatformRow> = {}): PlatformRow {
  return {
    result_id: "r-default",
    platform: "DataFusion",
    platform_id: "datafusion",
    platform_version: "v53.0.0",
    driver_version: null,
    run_date: "2026-05-06T12:00:00Z",
    trust_label: "maintainer-run",
    validation_status: "exact",
    deployment_class: null,
    instance_or_warehouse: null,
    is_ranking_eligible: true,
    compliance_class: null,
    has_plans: false,
    plans_published: false,
    has_tuning: false,
    bundle_download_url: "",
    cost_status: null,
    cost_scope: null,
    cost_model_version: null,
    cost_model_source: null,
    normalized_cost_usd: null,
    cloud_provider: null,
    cloud_region: null,
    storage_format: null,
    billing_unit: null,
    pricing_region: null,
    timings: { q1: 100, q2: 200, q3: 300 },
    visibility: "public-curated",
    test_type: null,
    tuning_mode: null,
    tuning_hash: null,
    cost_usd: null,
    power_score: null,
    geomean_ms: 200,
    display_geomean_ms: 200,
    total_duration_s: 1,
    query_count: 3,
    ...overrides,
  } as PlatformRow;
}

function makeSummary(): BenchmarkSummary {
  return {
    benchmark: "tpch",
    scale_factor: 1,
    phase: "power",
    query_ids: ["q1", "q2", "q3"],
    platforms: [
      makePlatform({
        result_id: "tpch-datafusion-sf1-20260506-3b8bbc42",
        run_date: "2026-05-06T12:00:00Z",
      }),
      makePlatform({
        result_id: "tpch-datafusion-sf1-20260507-deadbeef",
        run_date: "2026-05-07T12:00:00Z",
      }),
      makePlatform({
        result_id: "tpch-datafusion-sf1-20260508-cafefeed",
        run_date: "2026-05-08T12:00:00Z",
      }),
      makePlatform({
        result_id: "tpch-datafusion-sf1-20260509-feedface",
        run_date: "2026-05-09T12:00:00Z",
      }),
    ],
  } as BenchmarkSummary;
}

describe("DistributionBox label disambiguation (finding #7)", () => {
  it("preserves the disambiguator when the truncation budget would collide", () => {
    const { container } = render(<DistributionBox summary={makeSummary()} />);
    const labels = Array.from(container.querySelectorAll("text"))
      .map((node) => node.textContent ?? "")
      .filter((text) => text.includes("DataFusion"));
    // Four runs, four unique labels.
    expect(labels.length).toBeGreaterThanOrEqual(4);
    expect(new Set(labels).size).toBe(labels.length);
    // Each label still includes the date or short-id disambiguator from the
    // RunIdentity formatter; the truncation does not collapse to a common prefix.
    const collapsed = labels.filter((label) => label.startsWith("DataFusion v53.0.0 …"));
    expect(collapsed.length).toBe(0);
  });

  it("renders the full identity inside <title> for screen readers and tooltips", () => {
    const { container } = render(<DistributionBox summary={makeSummary()} />);
    const titles = Array.from(container.querySelectorAll("text > title"))
      .map((node) => node.textContent ?? "")
      .filter((text) => text.includes("DataFusion"));
    expect(titles.length).toBeGreaterThanOrEqual(4);
    // Titles include the run date qualifier even when the visible label is
    // a fallback short-id form.
    expect(titles.some((title) => title.includes("2026-05-06"))).toBe(true);
  });
});
