import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import type { BenchmarkSummary, PlatformRow } from "@/types";
import { SparklineTable } from "@/components/SparklineTable";

function makePlatform(overrides: Partial<PlatformRow> = {}): PlatformRow {
  const timings = overrides.timings ?? { q1: 100, q2: 200 };
  return {
    result_id: "r-default",
    short_id: "",
    platform: "DuckDB",
    platform_id: "duckdb",
    platform_version: "1.4.3",
    tuning_mode: null,
    tuning_hash: null,
    execution_mode: null,
    trust_label: "maintainer-run",
    funding: "unspecified",
    validation_status: "exact",
    run_date: "2026-04-03",
    is_ranking_eligible: true,
    has_display_timing: true,
    valid_query_count: 2,
    missing_query_count: 0,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
    power_score: null,
    display_geomean_ms: 150,
    sample_geomean_ms: 150,
    cost_usd: null,
    compliance_class: null,
    percentile_stats: { p50: 100, p90: 200, p95: 250, p99: 300 },
    phase_durations: null,
    timings,
    timing_eligibility: Object.fromEntries(
      Object.entries(timings).map(([queryId, ms]) => [
        queryId,
        {
          is_valid_display_timing: ms !== null && ms > 0,
          timing_exclusion_reason: ms === null ? "missing_timing" : ms === 0 ? "zero_timing" : null,
        },
      ]),
    ),
    ...overrides,
  } as PlatformRow;
}

function makeSummary(overrides: Partial<BenchmarkSummary> = {}): BenchmarkSummary {
  return {
    benchmark: "tpch",
    scale_factor: 0.1,
    phase: "power",
    query_ids: ["q1", "q2"],
    platforms: [
      makePlatform({ result_id: "r1", platform: "DuckDB" }),
      makePlatform({ result_id: "r2", platform: "SQLite", display_geomean_ms: 900 }),
    ],
    ranking: { primary_metric: "display_geomean_ms", secondary_metric: null, primary_order: "asc" },
    ...overrides,
  } as BenchmarkSummary;
}

describe("SparklineTable", () => {
  it("gives the platform column only the width its content needs, not the leftover row space", () => {
    // Audit finding: at 1280px the platform cell rendered at 718px (mostly
    // empty) while the bar cell was squeezed into 389px. The platform column
    // should shrink to its content instead of soaking up unclaimed table
    // width, and the geomean bar column should carry the row's dominant
    // share of it.
    const { container } = render(<SparklineTable summary={makeSummary()} />);

    const headerCells = Array.from(container.querySelectorAll("thead th"));
    const platformHeader = headerCells[0]!;
    expect(platformHeader.className).toContain("w-px");
    // Nowrap only from `sm` up - a long duplicate-platform cohort label must
    // still be able to wrap below `sm`, or the table is forced into
    // horizontal scroll on a narrow pane (see SparklineTable.tsx).
    expect(platformHeader.className).toContain("whitespace-normal");
    expect(platformHeader.className).toContain("sm:whitespace-nowrap");

    const firstRowCells = Array.from(container.querySelectorAll("tbody tr")[0]!.querySelectorAll("td"));
    const platformCell = firstRowCells[0]!;
    const barCell = firstRowCells[1]!;
    expect(platformCell.className).toContain("w-px");
    expect(platformCell.className).toContain("whitespace-normal");
    expect(platformCell.className).toContain("sm:whitespace-nowrap");
    // The bar cell carries an explicit, dominant width share of the row -
    // specifically 2/5, not just any fraction (w-1/3 would also match a
    // looser `/w-\d+\/\d+/` pattern without locking in this value).
    expect(barCell.className).toContain("w-2/5");
  });

  it("renders one row per platform with a spark bar and a formatted geomean value", () => {
    const { container } = render(<SparklineTable summary={makeSummary()} />);
    const rows = container.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.textContent).toContain("DuckDB");
    expect(rows[0]!.textContent).toContain("150 ms");
    expect(rows[1]!.textContent).toContain("SQLite");
    expect(rows[1]!.textContent).toContain("900 ms");
  });
});
