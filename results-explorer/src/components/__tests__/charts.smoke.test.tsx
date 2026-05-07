/**
 * Smoke tests for the 10 chart components added by
 * explorer-close-chart-type-coverage-gaps.
 *
 * Each chart is tested for:
 *   (a) empty data - renders null or an empty-state message without throwing
 *   (b) realistic data - renders an <svg> or <table> without throwing
 *
 * Math correctness is already covered by the parity suite
 * (src/__tests__/parity/chartMath.parity.test.ts); these tests only guard
 * against rendering regressions (null-dereferences, layout crashes).
 */

import { render } from "@testing-library/preact";
import { describe, it, expect } from "vitest";
import type { BenchmarkSummary, PlatformRow } from "@/types";
import type { ChartHistoricalEntry } from "@/lib/chartRegistry";

import { PercentileLadder } from "@/components/PercentileLadder";
import { CDFChart } from "@/components/CDFChart";
import { RankTable } from "@/components/RankTable";
import { DistributionBox } from "@/components/DistributionBox";
import { QueryHistogram } from "@/components/QueryHistogram";
import { PowerBar } from "@/components/PowerBar";
import { StackedPhase } from "@/components/StackedPhase";
import { TimeSeries } from "@/components/TimeSeries";
import { CostScatter } from "@/components/CostScatter";
import { SparklineTable } from "@/components/SparklineTable";

function makePlatform(
  overrides: Partial<PlatformRow> = {},
): PlatformRow {
  return {
    result_id: "r1",
    short_id: "",
    platform_id: "duckdb",
    platform: "DuckDB",
    platform_version: null,
    tuning_mode: null,
    tuning_hash: null,
    execution_mode: null,
    trust_label: "maintainer-run",
    run_date: "2026-04-01",
    is_ranking_eligible: true,
    power_score: 3000,
    display_geomean_ms: 12,
    sample_geomean_ms: 12,
    cost_usd: null,
    compliance_class: null,
    percentile_stats: null,
    phase_durations: null,
    timings: { Q1: 10, Q2: 20, Q3: 30 },
    ...overrides,
  };
}

function makeSummary(overrides: Partial<BenchmarkSummary> = {}): BenchmarkSummary {
  return {
    benchmark: "tpch",
    scale_factor: 0.1,
    phase: "power",
    query_ids: ["Q1", "Q2", "Q3"],
    platforms: [
      makePlatform({ result_id: "r1", platform_id: "duckdb", platform: "DuckDB" }),
      makePlatform({
        result_id: "r2",
        platform_id: "sqlite",
        platform: "SQLite",
        power_score: 1500,
        display_geomean_ms: 25,
        timings: { Q1: 20, Q2: 40, Q3: 60 },
      }),
    ],
    cell_reduction: "median",
    ranking: null,
    ...overrides,
  };
}

function emptySummary(): BenchmarkSummary {
  return makeSummary({ platforms: [], query_ids: [] });
}

// ---------------------------------------------------------------------------
// PercentileLadder
// ---------------------------------------------------------------------------

describe("PercentileLadder", () => {
  it("renders nothing when given no rows", () => {
    const { container } = render(<PercentileLadder rows={[]} />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders an svg when given percentile rows", () => {
    const { container } = render(
      <PercentileLadder
        rows={[
          {
            result_id: "r-duckdb-tuned",
            platform: "DuckDB",
            percentile_stats: { p50: 10, p90: 25, p95: 40, p99: 90 },
          },
        ]}
      />,
    );
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("uses unique data-result-id even when two rows share a platform name", () => {
    // Variant-tuning case: same platform with different tuning_modes
    // produces two PlatformRows with the same `platform` display name but
    // different result_ids. Pre-w6-review, key={row.platform} collided.
    const { container } = render(
      <PercentileLadder
        rows={[
          {
            result_id: "r-duckdb-tuned",
            platform: "DuckDB",
            percentile_stats: { p50: 10, p90: 25, p95: 40, p99: 90 },
          },
          {
            result_id: "r-duckdb-notuning",
            platform: "DuckDB",
            percentile_stats: { p50: 12, p90: 28, p95: 45, p99: 100 },
          },
        ]}
      />,
    );
    const ids = Array.from(container.querySelectorAll("[data-result-id]")).map(
      (el) => el.getAttribute("data-result-id") ?? "",
    );
    expect(ids).toEqual(["r-duckdb-tuned", "r-duckdb-notuning"]);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

// ---------------------------------------------------------------------------
// CDFChart
// ---------------------------------------------------------------------------

describe("CDFChart", () => {
  it("renders nothing for empty summary", () => {
    const { container } = render(<CDFChart summary={emptySummary()} />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders an svg for a populated summary", () => {
    const { container } = render(<CDFChart summary={makeSummary()} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// RankTable
// ---------------------------------------------------------------------------

describe("RankTable", () => {
  it("renders nothing when platforms are empty", () => {
    const { container } = render(<RankTable summary={emptySummary()} />);
    expect(container.querySelector("table")).toBeNull();
  });

  it("assigns 1st/2nd rank per query and shows win counts", () => {
    const { container } = render(<RankTable summary={makeSummary()} />);
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(table!.textContent).toContain("1st");
    expect(table!.textContent).toContain("2nd");
  });

  it("ties - platforms with equal timings get equal rank", () => {
    const summary = makeSummary({
      platforms: [
        makePlatform({ result_id: "r1", platform: "A", timings: { Q1: 10 } }),
        makePlatform({ result_id: "r2", platform: "B", timings: { Q1: 10 } }),
      ],
      query_ids: ["Q1"],
    });
    const { container } = render(<RankTable summary={summary} />);
    const cells = container.querySelectorAll("td");
    const ranks = Array.from(cells).map((c) => c.textContent);
    expect(ranks.filter((r) => r === "1st").length).toBe(2);
  });

  it("sorts query rows naturally and preserves explicit labels", () => {
    const summary = makeSummary({
      query_ids: ["Q10", "Q2", "Q1"],
      platforms: [makePlatform({ timings: { Q1: 10, Q2: 20, Q10: 100 } })],
    });
    const { container } = render(<RankTable summary={summary} />);
    const labels = Array.from(container.querySelectorAll("tbody tr td:first-child")).map(
      (cell) => cell.textContent,
    );
    expect(labels).toStrictEqual(["Q1", "Q2", "Q10"]);
  });
});

// ---------------------------------------------------------------------------
// DistributionBox
// ---------------------------------------------------------------------------

describe("DistributionBox", () => {
  it("renders nothing for empty summary", () => {
    const { container } = render(<DistributionBox summary={emptySummary()} />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders an svg for a populated summary", () => {
    const { container } = render(<DistributionBox summary={makeSummary()} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// QueryHistogram
// ---------------------------------------------------------------------------

describe("QueryHistogram", () => {
  it("renders nothing for empty summary", () => {
    const { container } = render(<QueryHistogram summary={emptySummary()} />);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders bars for a populated summary", () => {
    const { container } = render(<QueryHistogram summary={makeSummary()} />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelectorAll("rect").length).toBeGreaterThan(0);
  });

  it("uses a mobile-safe responsive width instead of forcing horizontal overflow", () => {
    const { container } = render(<QueryHistogram summary={makeSummary()} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("100%");
    expect(svg?.getAttribute("viewBox")).toMatch(/^0 0 300 /);
  });

  it("auto-splits into multiple panels when query count > 33", () => {
    const query_ids = Array.from({ length: 70 }, (_, i) => `Q${i + 1}`);
    const timings: Record<string, number> = {};
    for (const qid of query_ids) timings[qid] = 10;
    const summary = makeSummary({
      query_ids,
      platforms: [makePlatform({ timings })],
    });
    const { container } = render(<QueryHistogram summary={summary} />);
    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThan(1);
  });

  it("sorts query labels naturally and does not strip prefixes", () => {
    const summary = makeSummary({
      query_ids: ["Q10", "Q2", "Q1"],
      platforms: [makePlatform({ timings: { Q1: 10, Q2: 20, Q10: 100 } })],
    });
    const { container } = render(<QueryHistogram summary={summary} />);
    const labels = Array.from(container.querySelectorAll("text[data-query-label]")).map(
      (label) => label.textContent,
    );
    expect(labels).toStrictEqual(["Q1", "Q2", "Q10"]);
  });
});

// ---------------------------------------------------------------------------
// PowerBar
// ---------------------------------------------------------------------------

describe("PowerBar", () => {
  it("shows a 'not available' message when no power_score", () => {
    const summary = makeSummary({
      platforms: [makePlatform({ power_score: null }), makePlatform({ power_score: 0 })],
    });
    const { container } = render(<PowerBar summary={summary} />);
    expect(container.textContent).toContain("not available");
  });

  it("renders bars sorted descending by power_score", () => {
    const summary = makeSummary({
      platforms: [
        makePlatform({ result_id: "r1", platform: "Low", power_score: 100 }),
        makePlatform({ result_id: "r2", platform: "High", power_score: 900 }),
        makePlatform({ result_id: "r3", platform: "Mid", power_score: 500 }),
      ],
    });
    const { container } = render(<PowerBar summary={summary} />);
    const labels = Array.from(container.querySelectorAll("text"))
      .map((t) => t.textContent)
      .filter((t): t is string => !!t);
    const highIdx = labels.indexOf("High");
    const midIdx = labels.indexOf("Mid");
    const lowIdx = labels.indexOf("Low");
    expect(highIdx).toBeGreaterThanOrEqual(0);
    expect(highIdx).toBeLessThan(midIdx);
    expect(midIdx).toBeLessThan(lowIdx);
  });
});

// ---------------------------------------------------------------------------
// StackedPhase
// ---------------------------------------------------------------------------

describe("StackedPhase", () => {
  it("shows a 'not available' message when no phase_durations", () => {
    const { container } = render(<StackedPhase summary={makeSummary()} />);
    expect(container.textContent).toContain("not available");
  });

  it("renders segments when phase_durations are populated", () => {
    const summary = makeSummary({
      platforms: [
        makePlatform({
          phase_durations: { data_loading: 10, power_test: 30, throughput_test: 5 },
        }),
      ],
    });
    const { container } = render(<StackedPhase summary={summary} />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelectorAll("rect").length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// TimeSeries
// ---------------------------------------------------------------------------

function makeEntry(
  overrides: Partial<ChartHistoricalEntry> = {},
): ChartHistoricalEntry {
  return {
    result_id: "r1",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    run_date: "2026-04-01",
    power_score: 3000,
    display_geomean_ms: 12,
    ...overrides,
  };
}

describe("TimeSeries", () => {
  it("shows an insufficient-data message when fewer than 2 runs per platform", () => {
    const { container } = render(
      <TimeSeries entries={[makeEntry({ result_id: "r1" })]} />,
    );
    expect(container.textContent).toContain("Not enough");
  });

  it("renders a line chart when ≥2 runs exist", () => {
    const entries = [
      makeEntry({ result_id: "r1", run_date: "2026-03-01", display_geomean_ms: 15 }),
      makeEntry({ result_id: "r2", run_date: "2026-04-01", display_geomean_ms: 10 }),
    ];
    const { container } = render(<TimeSeries entries={entries} />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelector("path")).not.toBeNull();
  });

  it("uses unique data-result-id per circle when two runs share a run_date", () => {
    // Pre-w6 behaviour: each <circle> used `key={p.date}`, so two runs on
    // the same date for the same platform collided. Preact still mounted
    // both circles but reconciliation broke and a duplicate-key warning
    // fired (in dev mode only). The structural check below is the true
    // regression guard: it asserts each circle's data-result-id is
    // unique across the rendered set, which is independent of Preact's
    // dev-mode warning channel and survives production tree-shaking.
    const entries = [
      makeEntry({ result_id: "r1", run_date: "2026-04-03", display_geomean_ms: 15 }),
      makeEntry({ result_id: "r2", run_date: "2026-04-03", display_geomean_ms: 12 }),
      makeEntry({ result_id: "r3", run_date: "2026-04-04", display_geomean_ms: 10 }),
    ];
    const { container } = render(<TimeSeries entries={entries} />);
    const ids = Array.from(container.querySelectorAll("[data-result-id]")).map(
      (el) => el.getAttribute("data-result-id") ?? "",
    );
    expect(ids.length).toBe(3);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("dedupes duplicate result_id entries before plotting", () => {
    // Defence in depth: if a future JOIN regression in an upstream query
    // emits the same result_id twice, the chart should render one circle
    // for that result, not two stacked at the same coordinates.
    const entries = [
      makeEntry({ result_id: "r1", run_date: "2026-03-01", display_geomean_ms: 15 }),
      makeEntry({ result_id: "r1", run_date: "2026-03-01", display_geomean_ms: 15 }),
      makeEntry({ result_id: "r2", run_date: "2026-04-01", display_geomean_ms: 10 }),
    ];
    const { container } = render(<TimeSeries entries={entries} />);
    const ids = Array.from(container.querySelectorAll("[data-result-id]")).map(
      (el) => el.getAttribute("data-result-id") ?? "",
    );
    expect(new Set(ids).size).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// CostScatter
// ---------------------------------------------------------------------------

describe("CostScatter", () => {
  it("shows why normalized cost is unavailable when metadata is missing", () => {
    const summary = makeSummary({
      platforms: [
        makePlatform({
          cost_status: "unavailable",
          normalized_cost_usd: null,
          cloud_provider: null,
          cloud_region: null,
          pricing_region: null,
          warehouse_size: null,
        }),
      ],
    });
    const { container } = render(<CostScatter summary={summary} />);
    expect(container.textContent).toContain("No normalized cost data");
    expect(container.textContent).toContain("cloud provider");
    expect(container.textContent).toContain("region");
  });

  it("shows a legacy-schema message when normalized cost fields are absent", () => {
    const { container } = render(<CostScatter summary={makeSummary()} />);
    expect(container.textContent).toContain("predate the normalized_cost contract");
  });

  it("renders points when normalized cost is populated", () => {
    const summary = makeSummary({
      platforms: [
        makePlatform({
          result_id: "r1",
          platform: "A",
          cost_usd: 0.5,
          normalized_cost_usd: 0.5,
          cost_status: "normalized",
          cost_scope: "compute_only",
          cost_model_version: "2026.05.0",
        }),
        makePlatform({
          result_id: "r2",
          platform: "B",
          cost_usd: 1.25,
          normalized_cost_usd: 1.25,
          cost_status: "normalized",
          cost_scope: "compute_only",
          cost_model_version: "2026.05.0",
        }),
      ],
    });
    const { container } = render(<CostScatter summary={summary} />);
    expect(container.querySelector("svg")).not.toBeNull();
    const circles = container.querySelectorAll("circle");
    expect(circles.length).toBe(2);
    expect(container.textContent).toContain("model 2026.05.0");
  });
});

// ---------------------------------------------------------------------------
// SparklineTable
// ---------------------------------------------------------------------------

describe("SparklineTable", () => {
  it("renders nothing when platforms are empty", () => {
    const { container } = render(<SparklineTable summary={emptySummary()} />);
    expect(container.querySelector("table")).toBeNull();
  });

  it("renders one row per platform", () => {
    const { container } = render(<SparklineTable summary={makeSummary()} />);
    const bodyRows = container.querySelectorAll("tbody tr");
    expect(bodyRows.length).toBe(2);
  });

  it("hides the normalized cost column when no normalized cost data is present", () => {
    const { container } = render(<SparklineTable summary={makeSummary()} />);
    expect(container.textContent).not.toContain("Normalized cost");
  });

  it("shows the normalized cost column when normalized cost data is present", () => {
    const summary = makeSummary({
      platforms: [
        makePlatform({
          cost_usd: 0.5,
          normalized_cost_usd: 0.5,
          cost_status: "normalized",
          cost_scope: "compute_only",
          cost_model_version: "2026.05.0",
        }),
        makePlatform({ result_id: "r2", cost_status: "unavailable", normalized_cost_usd: null }),
      ],
    });
    const { container } = render(<SparklineTable summary={summary} />);
    expect(container.textContent).toContain("Normalized cost");
    expect(container.textContent).toContain("unavailable");
  });
});
