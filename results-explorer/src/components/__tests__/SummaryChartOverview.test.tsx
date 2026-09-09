/**
 * Tests for the long summary overview section chrome.
 *
 * Covers what the shared chart section commits to: leading with a chart
 * rather than a restatement of the page, consistent column naming, the
 * distribution boundary footnote, drawing each chart once, and the dynamic
 * additional-analyses count.
 */

import { render, screen, fireEvent, within } from "@testing-library/preact";
import { describe, it, expect } from "vitest";
import type { BenchmarkSummary, PlatformRow } from "@/types";

import { SummaryChartOverview } from "@/components/SummaryChartOverview";

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
    timing_eligibility:
      overrides.timing_eligibility ??
      Object.fromEntries(
        Object.entries(timings).map(([queryId, ms]) => [
          queryId,
          {
            is_valid_display_timing: ms !== null && ms > 0,
            timing_exclusion_reason: ms === null ? "missing_timing" : ms === 0 ? "zero_timing" : null,
          },
        ]),
      ),
    ...overrides,
  };
}

function makeSummary(overrides: Partial<BenchmarkSummary> = {}): BenchmarkSummary {
  return {
    benchmark: "tpch",
    scale_factor: 0.1,
    phase: "standard",
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

function renderOverview(summary: BenchmarkSummary = makeSummary()) {
  return render(<SummaryChartOverview context={{ kind: "summary", summary }} />);
}

describe("SummaryChartOverview section chrome", () => {
  it("leads with the first chart rather than a restatement of the page", () => {
    const { container } = renderOverview();
    // The section used to open with a question heading, a "shared scope"
    // callout, and a copy-link button, none of which said anything the charts
    // below do not say for themselves.
    expect(screen.queryByText("What does this cohort show?")).toBeNull();
    expect(screen.queryByText(/Shared scope:/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Copy chart-section link/ })).toBeNull();
    expect(screen.getByText("Which platforms lead on speed and throughput?")).not.toBeNull();
    const root = container.querySelector("[data-testid='summary-chart-overview']");
    expect(root?.getAttribute("id")).toBe("cohort-charts");
  });

  it("names the platform column consistently and puts each value beside its bar", () => {
    const { container } = renderOverview();
    const table = container.querySelector("table.summary-metric-table")!;
    expect(within(table as HTMLElement).getByText("Platform")).not.toBeNull();
    expect(within(table as HTMLElement).queryByText("Engine")).toBeNull();
    const cell = table.querySelector("td.summary-metric-cell")!;
    // Value and bar share one flex row; the bar is not stacked under the value.
    expect(cell.querySelector(".summary-metric-track")?.parentElement).toBe(
      cell.querySelector("div"),
    );
  });

  it("states the distribution boundary once and does not link exclusions to the provenance legend", () => {
    renderOverview();
    expect(screen.queryByText(/whiskers min\/max/)).toBeNull();
    const paragraphs = screen
      .getAllByText(/across different queries, not repeated runs/)
      .filter((el) => el.tagName === "P");
    expect(paragraphs).toHaveLength(1);
    const matrixLink = screen.getByText(/See the per-query matrix/) as HTMLAnchorElement;
    expect(matrixLink.getAttribute("href")).toBe("#evidence-matrix");
    // The old "Inspect exclusions" link pointed at the provenance legend,
    // which is not where a chart's excluded rows are named.
    expect(screen.queryByText(/Inspect exclusions/)).toBeNull();
  });

  it("drops the preview once the full chart is open, so the chart is drawn once", () => {
    const { container } = renderOverview();
    const card = container.querySelector<HTMLDetailsElement>("[data-testid^='summary-chart-preview-']")!;
    expect(card.querySelector(".summary-chart-thumbnail")).not.toBeNull();
    card.open = true;
    fireEvent(card, new Event("toggle"));
    expect(card.querySelector(".summary-chart-thumbnail")).toBeNull();
  });

  it("labels the more-views count from the rendered cards", () => {
    const { container } = renderOverview();
    const cards = container.querySelectorAll("[data-testid^='summary-chart-preview-']");
    expect(cards.length).toBeGreaterThan(0);
    expect(screen.getByText(`${cards.length} additional analyses`)).not.toBeNull();
  });

  it("omits the heatmap card when the matrix already shows it", () => {
    const { container } = render(
      <SummaryChartOverview context={{ kind: "summary", summary: makeSummary() }} excludeChartIds={["query_heatmap"]} />,
    );
    expect(container.querySelector("[data-testid='summary-chart-preview-query_heatmap']")).toBeNull();
    const cards = container.querySelectorAll("[data-testid^='summary-chart-preview-']");
    expect(screen.getByText(`${cards.length} additional analyses`)).not.toBeNull();
  });

  it("formats the analyses count label", async () => {
    const { additionalAnalysesLabel } = await import("@/components/SummaryChartOverview");
    expect(additionalAnalysesLabel(0)).toBe("0 additional analyses");
    expect(additionalAnalysesLabel(1)).toBe("1 additional analysis");
    expect(additionalAnalysesLabel(7)).toBe("7 additional analyses");
  });

});
