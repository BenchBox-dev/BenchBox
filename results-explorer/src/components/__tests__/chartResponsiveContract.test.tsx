/**
 * The Explorer's SVG charts share one sizing contract: draw in a coordinate
 * system as wide as the measured container, publish it as `width="100%"` plus a
 * matching viewBox, and keep every mark inside it.
 *
 * These are regression tests for a defect that shipped: charts authored at a
 * fixed 400-unit floor with no viewBox were reduced to the column width by
 * `.bb-chart-svg { max-width: 100% }` without their coordinate system moving
 * with them. On a 293px phone column that silently discarded the right-hand
 * quarter of the drawing and the bottom quarter of the rows - the slowest runs,
 * the axis, and the caption naming the scale. The wrapping `overflow-x-auto`
 * could not scroll to them either, because the box now fitted its parent.
 *
 * e2e/responsive.spec.ts deliberately exempts elements inside `svg[role="img"]`
 * from its overflow audit, so nothing else in the suite would catch a return.
 */

import { render, waitFor } from "@testing-library/preact";
import { describe, it, expect, afterEach } from "vitest";
import type { BenchmarkSummary, PlatformRow } from "@/types";

import { PowerBar } from "@/components/PowerBar";
import { DistributionBox } from "@/components/DistributionBox";
import { CDFChart } from "@/components/CDFChart";
import { StackedPhase } from "@/components/StackedPhase";
import { PercentileLadder } from "@/components/PercentileLadder";
import { ChartPanel } from "@/components/ChartPanel";

const PHONE_COLUMN = 293;
const DESKTOP_COLUMN = 1166;

function setContainerWidth(width: number): void {
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get: () => width,
  });
}

afterEach(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get: () => 0,
  });
});

function makePlatform(overrides: Partial<PlatformRow> = {}): PlatformRow {
  const timings = overrides.timings ?? { Q1: 10, Q2: 20, Q3: 30 };
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
    funding: "unspecified",
    run_date: "2026-04-01",
    is_ranking_eligible: true,
    has_display_timing: true,
    valid_query_count: 3,
    missing_query_count: 0,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
    power_score: 3000,
    display_geomean_ms: 12,
    sample_geomean_ms: 12,
    cost_usd: null,
    compliance_class: null,
    percentile_stats: null,
    phase_durations: null,
    timings,
    timing_eligibility: Object.fromEntries(
      Object.entries(timings).map(([queryId, ms]) => [
        queryId,
        {
          is_valid_display_timing: ms !== null && ms > 0,
          timing_exclusion_reason: null,
        },
      ]),
    ),
    ...overrides,
  };
}

/** A cohort wide enough that a fixed label gutter cannot fit a phone column. */
function wideCohort(): BenchmarkSummary {
  const names = [
    "DuckDB",
    "DuckLake",
    "Polars",
    "DataFusion",
    "ClickHouse Local",
    "SQLite",
    "Spark",
    "PySpark",
  ];
  return {
    benchmark: "tpch",
    scale_factor: 1,
    phase: "power",
    query_ids: ["Q1", "Q2", "Q3"],
    platforms: names.map((platform, index) =>
      makePlatform({
        result_id: `r${index}`,
        platform_id: platform.toLowerCase().replace(/\s+/g, "-"),
        platform,
        power_score: 100000 - index * 12000,
        display_geomean_ms: 35 * (index + 1) ** 2,
        timings: { Q1: 10 * (index + 1), Q2: 20 * (index + 1), Q3: 30 * (index + 1) },
        phase_durations: { load: 4 + index, power: 12 + index },
      }),
    ),
    cell_reduction: "median",
    ranking: null,
  };
}

/** Every x coordinate a chart draws, in user units. */
function drawnRightEdges(root: ParentNode): number[] {
  const edges: number[] = [];
  for (const rect of Array.from(root.querySelectorAll("rect"))) {
    const x = Number(rect.getAttribute("x") ?? 0);
    const width = Number(rect.getAttribute("width") ?? 0);
    if (Number.isFinite(x) && Number.isFinite(width)) edges.push(x + width);
  }
  for (const line of Array.from(root.querySelectorAll("line"))) {
    for (const attr of ["x1", "x2"]) {
      const value = Number(line.getAttribute(attr) ?? 0);
      if (Number.isFinite(value)) edges.push(value);
    }
  }
  for (const text of Array.from(root.querySelectorAll("text"))) {
    const value = Number(text.getAttribute("x") ?? 0);
    if (Number.isFinite(value)) edges.push(value);
  }
  return edges;
}

const CHARTS: { name: string; render: () => { container: Element } }[] = [
  { name: "PowerBar", render: () => render(<PowerBar summary={wideCohort()} />) },
  { name: "DistributionBox", render: () => render(<DistributionBox summary={wideCohort()} />) },
  { name: "CDFChart", render: () => render(<CDFChart summary={wideCohort()} />) },
  { name: "StackedPhase", render: () => render(<StackedPhase summary={wideCohort()} />) },
  {
    name: "PercentileLadder",
    render: () =>
      render(
        <PercentileLadder
          rows={wideCohort().platforms.map((platform, index) => ({
            ...platform,
            colorIdx: index,
            displayLabel: platform.platform,
            percentile_stats: { p50: 20 + index, p90: 40 + index, p95: 60 + index, p99: 90 + index },
          }))}
        />,
      ),
  },
  {
    name: "PerformanceBar",
    render: () => render(<ChartPanel context={{ kind: "summary", summary: wideCohort() }} />),
  },
];

describe("chart responsive contract", () => {
  for (const chart of CHARTS) {
    describe(chart.name, () => {
      it.each([PHONE_COLUMN, DESKTOP_COLUMN])(
        "draws at the measured container width at %spx",
        async (width) => {
          setContainerWidth(width);
          const { container } = chart.render();

          await waitFor(() => {
            const svg = container.querySelector("svg");
            expect(svg?.getAttribute("width")).toBe("100%");
            expect(svg?.getAttribute("viewBox")).toMatch(new RegExp(`^0 0 ${width} `));
          });
        },
      );

      it("keeps every mark inside the drawing at a phone column width", async () => {
        setContainerWidth(PHONE_COLUMN);
        const { container } = chart.render();

        await waitFor(() => {
          const svg = container.querySelector("svg");
          expect(svg?.getAttribute("viewBox")).toMatch(new RegExp(`^0 0 ${PHONE_COLUMN} `));
        });

        const svg = container.querySelector("svg")!;
        const overflowing = drawnRightEdges(svg).filter((edge) => edge > PHONE_COLUMN + 0.5);
        expect(overflowing).toEqual([]);
      });
    });
  }
});
