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
import { CostScatter } from "@/components/CostScatter";
import { TimeSeries } from "@/components/TimeSeries";
import { NormalizedSpeedupChart } from "@/components/NormalizedSpeedupChart";
import { DivergingBarChart } from "@/components/DivergingBarChart";

const NARROW_COLUMN = 240;
const PHONE_COLUMN = 293;
/**
 * jsdom lays out no text, so a label's width has to be estimated. 0.6em per
 * character is a conservative bound for the proportional faces these charts
 * use, and it is what the assertion below compares against - not the constant
 * the production helper works to, which would make the check circular.
 */
function visibleLabel(text: Element): string {
  // `textContent` swallows the <title> child these charts attach for tooltips,
  // which is the full untruncated run identity and is never painted.
  return Array.from(text.childNodes)
    .filter((node) => node.nodeType === 3)
    .map((node) => node.textContent ?? "")
    .join("")
    .trim();
}

function estimatedTextWidth(text: Element): number {
  const label = visibleLabel(text);
  const styled = /font-size:\s*([\d.]+)/.exec(text.getAttribute("style") ?? "");
  const fontSize = Number(text.getAttribute("font-size") ?? styled?.[1] ?? 10);
  return label.length * fontSize * 0.6;
}
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

/**
 * Two runs whose per-query gap is far past either chart's clamp, so the value
 * label sits at the very end of the plot - the case that used to draw it
 * outside the drawing.
 */
function clampedCompare() {
  return {
    queries: ["Q1", "Q2", "Q3"].map((queryId, index) => ({
      queryId,
      timings: [
        { ms: 10 + index, status: "pass" },
        { ms: (10 + index) * 40, status: "pass" },
      ],
    })),
    results: [{ platform: "DuckDB" }, { platform: "SQLite" }],
  };
}

/** The same cohort with normalized cost recorded, so the scatter has points. */
function costCohort(): BenchmarkSummary {
  const base = wideCohort();
  return {
    ...base,
    platforms: base.platforms.map((platform, index) => ({
      ...platform,
      normalized_cost_usd: 0.02 * (index + 1),
      cost_status: "normalized" as const,
    })),
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

interface MarkExtent {
  readonly what: string;
  readonly x: number;
  readonly y: number;
}

/**
 * Every point a chart actually draws, in user units.
 *
 * Covers rects, lines, circles, path and polyline geometry, and text origins.
 * An earlier version looked only at rects, line endpoints and text x, which
 * left the CDF's plotted curves - its entire data layer - unexamined, and
 * checked no vertical extent at all.
 */
function drawnPoints(root: ParentNode): MarkExtent[] {
  const points: MarkExtent[] = [];
  const push = (what: string, x: number, y: number) => {
    if (Number.isFinite(x) && Number.isFinite(y)) points.push({ what, x, y });
  };
  const num = (el: Element, name: string) => Number(el.getAttribute(name) ?? NaN);

  for (const rect of Array.from(root.querySelectorAll("rect"))) {
    const x = num(rect, "x");
    const y = num(rect, "y");
    push("rect", x, y);
    push("rect", x + (num(rect, "width") || 0), y + (num(rect, "height") || 0));
  }
  for (const line of Array.from(root.querySelectorAll("line"))) {
    push("line", num(line, "x1"), num(line, "y1"));
    push("line", num(line, "x2"), num(line, "y2"));
  }
  for (const circle of Array.from(root.querySelectorAll("circle"))) {
    const r = num(circle, "r") || 0;
    push("circle", num(circle, "cx") - r, num(circle, "cy") - r);
    push("circle", num(circle, "cx") + r, num(circle, "cy") + r);
  }
  // Curves carry their geometry in an attribute, so read the coordinate pairs
  // straight out of it: jsdom lays out no SVG and has no getBBox.
  for (const el of Array.from(root.querySelectorAll("path, polyline"))) {
    const raw = el.getAttribute("d") ?? el.getAttribute("points") ?? "";
    const numbers = (raw.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
    for (let i = 0; i + 1 < numbers.length; i += 2) {
      push(el.tagName.toLowerCase(), numbers[i]!, numbers[i + 1]!);
    }
  }
  for (const text of Array.from(root.querySelectorAll("text"))) {
    push(`text "${(text.textContent ?? "").slice(0, 20)}"`, num(text, "x"), num(text, "y"));
  }
  return points;
}

/**
 * `minWidth` is the drawing floor a chart declares for itself. Below it the
 * frame scales down rather than cropping, which is a deliberate trade and not
 * the defect these tests guard. Omitted means the chart follows its container
 * exactly.
 */
const CHARTS: { name: string; render: () => { container: Element }; minWidth?: number }[] = [
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
            // p50 close to p99 puts the value label at the very end of the
            // plot, where a trailing label used to be drawn outside it.
            percentile_stats: {
              p50: 88 + index,
              p90: 89 + index,
              p95: 89.5 + index,
              p99: 90 + index,
            },
          }))}
        />,
      ),
  },
  {
    name: "PerformanceBar",
    render: () => render(<ChartPanel context={{ kind: "summary", summary: wideCohort() }} />),
  },
  { name: "CostScatter", render: () => render(<CostScatter summary={costCohort()} />) },
  {
    name: "NormalizedSpeedupChart",
    minWidth: 300,
    render: () => render(<NormalizedSpeedupChart {...clampedCompare()} baselineIdx={0} />),
  },
  {
    name: "DivergingBarChart",
    minWidth: 300,
    render: () => render(<DivergingBarChart {...clampedCompare()} baselineIdx={0} />),
  },
  {
    name: "TimeSeries",
    render: () =>
      render(
        <TimeSeries
          entries={wideCohort().platforms.flatMap((platform) =>
            // A trend needs at least two runs per platform.
            ["2026-03-01", "2026-06-01", "2026-09-01"].map((run_date, run) => ({
              result_id: `${platform.result_id}-${run}`,
              platform_id: platform.platform_id,
              platform: platform.platform,
              benchmark: "tpch",
              scale_factor: 1,
              run_date,
              power_score: (platform.power_score ?? 1000) - run * 50,
              display_geomean_ms: (platform.display_geomean_ms ?? 30) + run * 3,
              trust_label: platform.trust_label,
            })),
          )}
        />,
      ),
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
          const expected = Math.max(width, chart.minWidth ?? 0);

          await waitFor(() => {
            const svg = container.querySelector("svg");
            expect(svg?.getAttribute("width")).toBe("100%");
            expect(svg?.getAttribute("viewBox")).toMatch(new RegExp(`^0 0 ${expected} `));
          });
        },
      );

      it.each([NARROW_COLUMN, PHONE_COLUMN, DESKTOP_COLUMN])(
        "anchors labels so they cannot run off an edge at %spx",
        async (width) => {
          // jsdom lays out no text, so its extent cannot be measured here. What
          // can be checked is the rule that governs it: a label anchored at its
          // start, placed hard against the right edge, has nowhere to go but
          // outside the drawing. The same applies mirrored on the left.
          setContainerWidth(width);
          const { container } = chart.render();
          const expected = Math.max(width, chart.minWidth ?? 0);

          await waitFor(() => {
            expect(container.querySelector("svg")).not.toBeNull();
          });

          const offenders: string[] = [];
          for (const svg of Array.from(container.querySelectorAll("svg"))) {
            for (const text of Array.from(svg.querySelectorAll("text"))) {
              // A rotated label's x is expressed in its own rotated frame, so a
              // flat comparison against the drawing width says nothing useful.
              if (text.getAttribute("transform") !== null) continue;
              const x = Number(text.getAttribute("x") ?? NaN);
              if (!Number.isFinite(x)) continue;
              const label = visibleLabel(text);
              if (label === "") continue;
              const anchorAttr = text.getAttribute("text-anchor") ?? "start";
              const estimated = estimatedTextWidth(text);
              const left =
                anchorAttr === "end" ? x - estimated : anchorAttr === "middle" ? x - estimated / 2 : x;
              const right = left + estimated;
              if (left < -0.5 || right > expected + 0.5) {
                offenders.push(
                  `"${label.slice(0, 24)}" spans ${left.toFixed(1)}..${right.toFixed(1)} of ${expected}`,
                );
              }
            }
          }

          expect(offenders, offenders.join("\n")).toEqual([]);
        },
      );

      it("keeps every mark inside the drawing at a phone column width", async () => {
        setContainerWidth(PHONE_COLUMN);
        const { container } = chart.render();
        const expected = Math.max(PHONE_COLUMN, chart.minWidth ?? 0);

        await waitFor(() => {
          const svg = container.querySelector("svg");
          expect(svg?.getAttribute("viewBox")).toMatch(new RegExp(`^0 0 ${expected} `));
        });

        const svg = container.querySelector("svg")!;
        const [, , boxWidth, boxHeight] = (svg.getAttribute("viewBox") ?? "")
          .split(/\s+/)
          .map(Number);

        const outside = drawnPoints(svg)
          .filter(
            (point) =>
              point.x < -0.5 ||
              point.x > boxWidth! + 0.5 ||
              point.y < -0.5 ||
              point.y > boxHeight! + 0.5,
          )
          .map((point) => `${point.what} at (${point.x.toFixed(1)}, ${point.y.toFixed(1)})`);

        expect(outside, outside.join("\n")).toEqual([]);
      });
    });
  }
});
