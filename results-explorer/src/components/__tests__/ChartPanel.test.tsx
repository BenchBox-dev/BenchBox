import { fireEvent, render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { ChartPanel } from "@/components/ChartPanel";
import type { ChartHistoricalEntry } from "@/lib/chartRegistry";
import type {
  BenchmarkSummary,
  DetailResult,
  PercentileStats,
  PlatformRow,
  RankingConfig,
} from "@/types";

const RANKING: RankingConfig = {
  primary_metric: "display_geomean_ms",
  secondary_metric: "platform",
  primary_order: "asc",
};

const PERCENTILES: PercentileStats = {
  p50: 10,
  p90: 18,
  p95: 21,
  p99: 25,
};

function makePlatformRow(overrides: Partial<PlatformRow> = {}): PlatformRow {
  return {
    result_id: overrides.result_id ?? "row-1",
    short_id: overrides.short_id ?? "row-1",
    platform_id: overrides.platform_id ?? "duckdb",
    platform: overrides.platform ?? "DuckDB",
    platform_version: overrides.platform_version ?? null,
    tuning_mode: overrides.tuning_mode ?? "default",
    tuning_hash: overrides.tuning_hash ?? null,
    execution_mode: overrides.execution_mode ?? "sql",
    trust_label: overrides.trust_label ?? "maintainer-run",
    run_date: overrides.run_date ?? "2026-04-17T12:00:00Z",
    is_ranking_eligible: overrides.is_ranking_eligible ?? true,
    power_score: overrides.power_score ?? 1000,
    display_geomean_ms: overrides.display_geomean_ms ?? 10,
    sample_geomean_ms: overrides.sample_geomean_ms ?? 10,
    cost_usd: overrides.cost_usd ?? 1.25,
    normalized_cost_usd: overrides.normalized_cost_usd ?? 1.25,
    cost_model_version: overrides.cost_model_version ?? "2026.05.0",
    cost_model_source: overrides.cost_model_source ?? "benchbox.core.cost.pricing",
    cost_scope: overrides.cost_scope ?? "compute_only",
    cost_status: overrides.cost_status ?? "normalized",
    billing_unit: overrides.billing_unit ?? "credit",
    pricing_region: overrides.pricing_region ?? "us-east-1",
    cloud_provider: overrides.cloud_provider ?? "aws",
    cloud_region: overrides.cloud_region ?? "us-east-1",
    instance_type: overrides.instance_type ?? null,
    warehouse_size: overrides.warehouse_size ?? "MEDIUM",
    node_count: overrides.node_count ?? null,
    cluster_size: overrides.cluster_size ?? null,
    storage_format: overrides.storage_format ?? null,
    storage_tier: overrides.storage_tier ?? null,
    compliance_class: overrides.compliance_class ?? null,
    percentile_stats: overrides.percentile_stats ?? PERCENTILES,
    phase_durations: overrides.phase_durations ?? { load: 1.2, power: 3.4 },
    timings: overrides.timings ?? { Q1: 10, Q2: 12 },
  };
}

function makeSummary(overrides: Partial<BenchmarkSummary> = {}): BenchmarkSummary {
  return {
    benchmark: overrides.benchmark ?? "nyctaxi",
    scale_factor: overrides.scale_factor ?? 0.01,
    phase: overrides.phase ?? "power",
    query_ids: overrides.query_ids ?? ["Q1", "Q2"],
    platforms:
      overrides.platforms ??
      [
        makePlatformRow(),
        makePlatformRow({
          result_id: "row-2",
          short_id: "row-2",
          platform_id: "sqlite",
          platform: "SQLite",
          display_geomean_ms: 18,
          sample_geomean_ms: 18,
          power_score: 650,
          cost_usd: 1.9,
          timings: { Q1: 18, Q2: 22 },
        }),
      ],
    cell_reduction: overrides.cell_reduction ?? "median",
    ranking: overrides.ranking ?? RANKING,
  };
}

function makeHistoricalEntry(
  overrides: Partial<ChartHistoricalEntry> = {},
): ChartHistoricalEntry {
  return {
    result_id: overrides.result_id ?? "hist-1",
    benchmark: overrides.benchmark ?? "nyctaxi",
    scale_factor: overrides.scale_factor ?? 0.01,
    platform: overrides.platform ?? "DuckDB",
    platform_id: overrides.platform_id ?? "duckdb",
    run_date: overrides.run_date ?? "2026-04-17T12:00:00Z",
    power_score: overrides.power_score ?? null,
    display_geomean_ms: overrides.display_geomean_ms ?? 10,
  };
}

function makeDetail(overrides: Partial<DetailResult> = {}): DetailResult {
  return {
    result_id: overrides.result_id ?? "detail-1",
    benchmark: overrides.benchmark ?? "nyctaxi",
    scale_factor: overrides.scale_factor ?? 0.01,
    platform: overrides.platform ?? "DuckDB",
    platform_id: overrides.platform_id ?? "duckdb",
    driver_version: overrides.driver_version ?? null,
    run_date: overrides.run_date ?? "2026-04-17T12:00:00Z",
    total_duration_s: overrides.total_duration_s ?? 10,
    geomean_ms: overrides.geomean_ms ?? 10,
    display_geomean_ms: overrides.display_geomean_ms ?? 10,
    power_score: overrides.power_score ?? 1000,
    environment: overrides.environment ?? { os: "macOS" },
    queries:
      overrides.queries ?? [
        { query_id: "Q1", duration_ms: 10, status: "pass", run_type: null, iter: 1, stream: null },
        { query_id: "Q2", duration_ms: 12, status: "pass", run_type: null, iter: 1, stream: null },
      ],
    display_timings:
      overrides.display_timings ?? [
        { query_id: "Q1", display_ms: 10, sample_count: 3 },
        { query_id: "Q2", display_ms: 12, sample_count: 3 },
      ],
    has_plans: overrides.has_plans ?? false,
    has_tuning: overrides.has_tuning ?? false,
    bundle_download_url: overrides.bundle_download_url ?? "/bundle.json",
    trust_label: overrides.trust_label ?? "maintainer-run",
    visibility: overrides.visibility ?? "public-curated",
    platform_version: overrides.platform_version ?? null,
    execution_mode: overrides.execution_mode ?? "sql",
    tuning_mode: overrides.tuning_mode ?? "default",
    tuning_hash: overrides.tuning_hash ?? null,
    test_type: overrides.test_type ?? "power",
    validation_status: overrides.validation_status ?? "exact",
    cost_usd: overrides.cost_usd ?? 1.25,
    normalized_cost_usd: overrides.normalized_cost_usd ?? 1.25,
    cost_model_version: overrides.cost_model_version ?? "2026.05.0",
    cost_model_source: overrides.cost_model_source ?? "benchbox.core.cost.pricing",
    cost_scope: overrides.cost_scope ?? "compute_only",
    cost_status: overrides.cost_status ?? "normalized",
    billing_unit: overrides.billing_unit ?? "credit",
    pricing_region: overrides.pricing_region ?? "us-east-1",
    cloud_provider: overrides.cloud_provider ?? "aws",
    cloud_region: overrides.cloud_region ?? "us-east-1",
    instance_type: overrides.instance_type ?? null,
    warehouse_size: overrides.warehouse_size ?? "MEDIUM",
    node_count: overrides.node_count ?? null,
    cluster_size: overrides.cluster_size ?? null,
    storage_format: overrides.storage_format ?? null,
    storage_tier: overrides.storage_tier ?? null,
    compliance_class: overrides.compliance_class ?? null,
  };
}

describe("ChartPanel", () => {
  it("groups summary charts by analytical question", () => {
    render(
      <ChartPanel
        context={{
          kind: "summary",
          summary: makeSummary(),
          historical: [
            makeHistoricalEntry(),
            makeHistoricalEntry({ result_id: "hist-2", run_date: "2026-04-18T12:00:00Z" }),
          ],
        }}
      />,
    );

    expect(screen.getByRole("tablist", { name: "Chart question groups" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toStrictEqual([
      "Overview",
      "Per-query",
      "Distribution",
      "Cost",
      "Trend",
      "Rank",
    ]);
    expect(screen.getByRole("button", { name: "Sparkline Table" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Query Heatmap" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Comparison Bar" })).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Trend" }));

    expect(screen.getByRole("tab", { name: "Trend" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("img", { name: "Geomean ms trend over time" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Sparkline Table" })).toBeNull();
  });

  it("hides charts whose ids are listed in excludeChartIds", () => {
    render(
      <ChartPanel
        context={{
          kind: "summary",
          summary: makeSummary(),
          historical: [
            makeHistoricalEntry(),
            makeHistoricalEntry({ result_id: "hist-2", run_date: "2026-04-18T12:00:00Z" }),
          ],
        }}
        excludeChartIds={["query_heatmap"]}
      />,
    );

    expect(screen.getByRole("tab", { name: "Per-query" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Query Heatmap" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Per-query" }));
    expect(screen.queryByRole("button", { name: "Query Heatmap" })).toBeNull();
    expect(screen.getByRole("tabpanel", { name: "Per-query chart" })).toBeTruthy();
  });

  it("threads cohort-aware labels into Compare per-query charts", () => {
    const details = [
      makeDetail({
        result_id: "df-44",
        platform: "DataFusion",
        platform_id: "datafusion-44",
        platform_version: "44",
        display_timings: [
          { query_id: "Q1", display_ms: 10, sample_count: 3 },
          { query_id: "Q2", display_ms: 30, sample_count: 3 },
        ],
      }),
      makeDetail({
        result_id: "df-45",
        platform: "DataFusion",
        platform_id: "datafusion-45",
        platform_version: "45",
        display_timings: [
          { query_id: "Q1", display_ms: 12, sample_count: 3 },
          { query_id: "Q2", display_ms: 15, sample_count: 3 },
        ],
      }),
    ];
    const { container } = render(
      <ChartPanel context={{ kind: "compare", results: details, primaryMetric: "display_geomean_ms" }} />,
    );

    expect(screen.getByText("DataFusion v44")).toBeTruthy();
    expect(screen.getByText("DataFusion v45")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Comparison Bar" }));
    const tooltips = Array.from(container.querySelectorAll("rect title")).map((title) => title.textContent ?? "");
    expect(tooltips.some((text) => text.includes("DataFusion v44"))).toBe(true);
    expect(tooltips.some((text) => text.includes("DataFusion v45"))).toBe(true);
  });

  it("uses responsive segmented chart controls with short visible labels", () => {
    render(
      <ChartPanel
        context={{
          kind: "summary",
          summary: makeSummary(),
          historical: [
            makeHistoricalEntry(),
            makeHistoricalEntry({ result_id: "hist-2", run_date: "2026-04-18T12:00:00Z" }),
          ],
        }}
      />,
    );

    const groupTabs = screen.getByRole("tablist", { name: "Chart question groups" });
    expect(groupTabs.className).toContain("flex");
    expect(groupTabs.className).toContain("flex-wrap");
    expect(screen.getByRole("tab", { name: "Per-query" }).className).toContain("min-h-9");

    const chartControls = screen.getByRole("group", { name: "Overview charts" });
    expect(chartControls.className).toContain("flex");
    expect(chartControls.className).toContain("flex-wrap");

    const sparkline = screen.getByRole("button", { name: "Sparkline Table" });
    const stacked = screen.getByRole("button", { name: "Stacked Phase Breakdown" });
    expect(sparkline.textContent).toBe("Sparklines");
    expect(stacked.textContent).toBe("Phases");
    expect(sparkline.className).toContain("min-h-9");
    expect(stacked.className).toContain("min-h-9");

    fireEvent.click(screen.getByRole("button", { name: "Performance Bar" }));
    expect(screen.getByRole("button", { name: "Performance Bar" }).className).toContain("min-h-9");
  });

  it("uses log scale for performance bars when latency spans an order of magnitude", () => {
    const { container } = render(
      <ChartPanel
        context={{
          kind: "summary",
          summary: makeSummary({
            platforms: [
              makePlatformRow({ result_id: "fast", platform: "FastDB", display_geomean_ms: 10 }),
              makePlatformRow({ result_id: "middle", platform: "MidDB", display_geomean_ms: 100 }),
              makePlatformRow({ result_id: "slow", platform: "SlowDB", display_geomean_ms: 1000 }),
            ],
          }),
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Performance Bar" }));

    expect(screen.getByRole("img", { name: "Geomean performance comparison (log scale)" })).toBeTruthy();
    expect(screen.getByText("Geomean query time (log scale) - lower is faster")).toBeTruthy();

    const widths = Array.from(
      container.querySelectorAll('svg[aria-label="Geomean performance comparison (log scale)"] rect'),
    ).map((rect) => Number(rect.getAttribute("width")));
    expect(widths).toHaveLength(3);
    expect(widths[0]).toBeGreaterThan(2);
    expect(widths[0]).toBeLessThan(widths[1]!);
    expect(widths[1]!).toBeLessThan(widths[2]!);
  });

  it("places performance labels away from cramped bar edges and keeps tooltip values", () => {
    const { container } = render(
      <ChartPanel
        context={{
          kind: "summary",
          summary: makeSummary({
            platforms: [
              makePlatformRow({ result_id: "fast", platform: "FastDB", display_geomean_ms: 10 }),
              makePlatformRow({ result_id: "slow", platform: "SlowDB", display_geomean_ms: 1000 }),
            ],
          }),
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Performance Bar" }));

    const valueLabels = Array.from(container.querySelectorAll("text[data-value-placement]"));
    expect(valueLabels.map((label) => label.getAttribute("data-value-placement"))).toContain("outside");
    expect(valueLabels.map((label) => label.getAttribute("data-value-placement"))).toContain("inside");
    expect(
      valueLabels.find((label) => label.textContent === "1000 ms")?.getAttribute("data-value-placement"),
    ).toBe("inside");

    const tooltips = Array.from(container.querySelectorAll("rect title")).map((title) => title.textContent);
    expect(tooltips).toContain("FastDB: 10 ms");
    expect(tooltips).toContain("SlowDB: 1000 ms");
  });

  it("hides the Cost tab when no cohort row carries normalized cost data", () => {
    // Updated contract for `results-explorer-chart-panel-scope-and-labeling`
    // w3: rather than rendering an empty Cost panel that forces users to
    // click through to discover "no cost recorded", the Cost tab now
    // disappears entirely when no row has `cost_status=normalized`. The
    // empty-state copy is preserved for the cost_scatter chart itself
    // when a normalized cohort partially lacks data.
    render(
      <ChartPanel
        context={{
          kind: "summary",
          summary: makeSummary({
            platforms: [
              makePlatformRow({
                cost_status: "unavailable",
                normalized_cost_usd: null,
                cloud_provider: null,
                cloud_region: null,
                pricing_region: null,
                warehouse_size: null,
              }),
            ],
          }),
        }}
      />,
    );

    expect(screen.queryByRole("tab", { name: "Cost" })).toBeNull();
  });

  it("renders compare-only tabs and hides historical-only charts", () => {
    render(
      <ChartPanel
        context={{
          kind: "compare",
          results: [
            makeDetail(),
            makeDetail({
              result_id: "detail-2",
              platform: "SQLite",
              platform_id: "sqlite",
              display_geomean_ms: 18,
              geomean_ms: 18,
              display_timings: [
                { query_id: "Q1", display_ms: 18, sample_count: 3 },
                { query_id: "Q2", display_ms: 22, sample_count: 3 },
              ],
            }),
          ],
        }}
      />,
    );

    expect(screen.getByRole("button", { name: "Comparison Bar" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Normalized Speedup" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Query Heatmap" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Per-query" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByRole("button", { name: "Performance Trend" })).toBeNull();
  });

  it("uses a controlled compare baseline without rendering a second selector", () => {
    render(
      <ChartPanel
        baselineIndex={1}
        onBaselineIndexChange={() => undefined}
        context={{
          kind: "compare",
          results: [
            makeDetail(),
            makeDetail({
              result_id: "detail-2",
              platform: "SQLite",
              platform_id: "sqlite",
              display_geomean_ms: 18,
              geomean_ms: 18,
              display_timings: [
                { query_id: "Q1", display_ms: 18, sample_count: 3 },
                { query_id: "Q2", display_ms: 22, sample_count: 3 },
              ],
            }),
          ],
        }}
      />,
    );

    expect(screen.queryByLabelText(/Baseline/i)).toBeNull();
    expect(screen.getByText("Baseline:")).toBeTruthy();
    expect(screen.getAllByText("SQLite").length).toBeGreaterThan(0);
  });

  it("preserves the compared run phase in compare-mode summary content", () => {
    render(
      <ChartPanel
        context={{
          kind: "compare",
          results: [
            makeDetail({ test_type: "throughput" }),
            makeDetail({
              result_id: "detail-2",
              platform: "SQLite",
              platform_id: "sqlite",
              display_geomean_ms: 18,
              geomean_ms: 18,
              test_type: "throughput",
              display_timings: [
                { query_id: "Q1", display_ms: 18, sample_count: 3 },
                { query_id: "Q2", display_ms: 22, sample_count: 3 },
              ],
            }),
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    fireEvent.click(screen.getByRole("button", { name: "Summary Box" }));
    expect(screen.getByText("throughput")).toBeTruthy();
  });

  it("renders detail charts without compare-only tabs", () => {
    render(
      <ChartPanel
        context={{
          kind: "detail",
          detail: makeDetail(),
        }}
      />,
    );

    expect(screen.getByRole("button", { name: "Query Histogram" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Rank" }));
    expect(screen.getByRole("table", { name: "Per-query platform rankings (1st = fastest)" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Normalized Speedup" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Performance Trend" })).toBeNull();
  });

  it("activates the Rank tab from the default Overview state on a fresh render (finding #5)", () => {
    render(
      <ChartPanel
        context={{
          kind: "summary",
          summary: makeSummary(),
        }}
      />,
    );

    // Fresh page load defaults to Overview. The audit reproducer was that
    // clicking Rank from this state did not switch the panel.
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true");

    fireEvent.click(screen.getByRole("tab", { name: "Rank" }));

    expect(screen.getByRole("tab", { name: "Rank" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("false");
    expect(screen.getByRole("table", { name: "Per-query platform rankings (1st = fastest)" })).toBeTruthy();
    // Overview's signature button should no longer be in the active group.
    expect(screen.queryByRole("button", { name: "Sparkline Table" })).toBeNull();
  });

  it("uses winner language by default in the summary box", () => {
    render(
      <ChartPanel
        context={{
          kind: "summary",
          summary: makeSummary(),
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Summary Box" }));
    expect(screen.getByText("Best geomean")).toBeTruthy();
    expect(screen.queryByText(/Lowest geomean in cohort/)).toBeNull();
    expect(screen.queryByText(/cohort mismatch/)).toBeNull();
  });

  it("suppresses winner language in the summary box when suppressWinnerClaims is on (w18)", () => {
    render(
      <ChartPanel
        context={{
          kind: "summary",
          summary: makeSummary(),
        }}
        suppressWinnerClaims
        suppressionReason="benchmarks differ across results"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Summary Box" }));
    expect(screen.queryByText("Best geomean")).toBeNull();
    expect(screen.getByText("Lowest geomean in cohort")).toBeTruthy();
    expect(screen.getByText(/cohort mismatch — not comparable/)).toBeTruthy();
  });
});
