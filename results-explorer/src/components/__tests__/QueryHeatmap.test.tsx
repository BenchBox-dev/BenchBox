/**
 * Tests for QueryHeatmap component.
 *
 * Cases:
 *   (a) Known timings produce stable color hue values
 *   (b) Null cells render "No run" with an explicit missing-run aria-label
 *   (c) Single-platform matrix degrades gracefully (no heat coloring)
 *   (d) Empty platforms list shows empty-state message
 *
 * Note: colorForCell / lightnessForCell math is now covered by the fixture-driven
 * parity suite at src/__tests__/parity/chartMath.parity.test.ts.
 * No hardcoded expected values remain here - the fixtures are the contract.
 */

import { fireEvent, render, screen, within } from "@testing-library/preact";
import { describe, it, expect } from "vitest";
import { expectNoAxeViolations } from "@/testing/axe-helper";
import { BENCHMARK_MATRIX_DENSITY_CONTRACT, QueryHeatmap } from "@/components/QueryHeatmap";
import type { BenchmarkSummary, PlatformRow } from "@/types";

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

const TIMING_ELIGIBLE = {
  has_display_timing: true,
  valid_query_count: 2,
  missing_query_count: 0,
  zero_timing_count: 0,
  display_exclusion_reason: null,
  comparison_exclusion_reason: null,
  ranking_exclusion_reason: null,
};

function timingEligibility(timings: Record<string, number | null>): PlatformRow["timing_eligibility"] {
  return Object.fromEntries(
    Object.entries(timings).map(([queryId, ms]) => [
      queryId,
      {
        is_valid_display_timing: ms !== null && ms > 0,
        timing_exclusion_reason: ms === null ? "missing_timing" : ms === 0 ? "zero_timing" : null,
      },
    ]),
  );
}

type PlatformRowFixture = Omit<PlatformRow, "timing_eligibility"> & Partial<Pick<PlatformRow, "timing_eligibility">>;
type SummaryFixtureOverrides = Partial<Omit<BenchmarkSummary, "platforms">> & {
  platforms?: PlatformRowFixture[];
};

function withTimingEligibility(row: PlatformRowFixture): PlatformRow {
  return {
    ...row,
    timing_eligibility: timingEligibility(row.timings),
  };
}

function makeSummary(overrides: SummaryFixtureOverrides = {}): BenchmarkSummary {
  const summary: Omit<BenchmarkSummary, "platforms"> & { platforms: PlatformRowFixture[] } = {
    benchmark: "tpch",
    scale_factor: 0.1,
    phase: "power",
    query_ids: ["Q1", "Q2"],
    platforms: [
      {
        result_id: "r1",
        short_id: "",
        platform_id: "duckdb",
        platform: "DuckDB",
        platform_version: null,
        tuning_mode: null,
        tuning_hash: null,
        execution_mode: null,
        trust_label: "maintainer-run",
        validation_status: "exact",
        run_date: "2026-04-01",
        is_ranking_eligible: true,
        ...TIMING_ELIGIBLE,
        power_score: 3000,
        display_geomean_ms: 10,
        compliance_class: null,
        sample_geomean_ms: 12,
        cost_usd: null,
        percentile_stats: null,
        phase_durations: null,
        timings: { Q1: 10, Q2: 20 },
        timing_eligibility: {},
      },
      {
        result_id: "r2",
        short_id: "",
        platform_id: "sqlite",
        platform: "SQLite",
        platform_version: null,
        tuning_mode: null,
        tuning_hash: null,
        execution_mode: null,
        trust_label: "maintainer-run",
        validation_status: "loose",
        run_date: "2026-04-01",
        is_ranking_eligible: true,
        ...TIMING_ELIGIBLE,
        power_score: 800,
        display_geomean_ms: 100,
        compliance_class: null,
        sample_geomean_ms: 120,
        cost_usd: null,
        percentile_stats: null,
        phase_durations: null,
        timings: { Q1: 100, Q2: 200 },
        timing_eligibility: {},
      },
    ],
    cell_reduction: "median_successful_measurement_ms",
    ranking: {
      primary_metric: "power_score",
      secondary_metric: "display_geomean_ms",
      primary_order: "desc",
    },
    ...overrides,
  };
  return {
    ...summary,
    platforms: summary.platforms.map(withTimingEligibility),
  };
}

function matrixThead(): HTMLElement {
  const thead = screen.getByTestId("query-heatmap-scroll-container").querySelector("thead");
  expect(thead).not.toBeNull();
  return thead as HTMLElement;
}

// ---------------------------------------------------------------------------
// (a) Known timings produce stable rendered output
// ---------------------------------------------------------------------------

describe("QueryHeatmap rendering", () => {
  it("renders platform names", () => {
    render(<QueryHeatmap summary={makeSummary()} />);
    expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SQLite").length).toBeGreaterThan(0);
  });

  it("renders query column headers", () => {
    render(<QueryHeatmap summary={makeSummary()} />);
    expect(screen.getByRole("button", { name: /^Q1/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Q2/ })).toBeTruthy();
  });

  it("sorts query headers naturally while preserving explicit labels", () => {
    const summary = makeSummary({
      query_ids: ["Q10", "Q2", "Q1"],
      platforms: [
        {
          ...makeSummary().platforms[0]!,
          timings: { Q1: 10, Q2: 20, Q10: 100 },
        },
      ],
    });
    render(<QueryHeatmap summary={summary} />);

    const labels = Array.from(matrixThead().querySelectorAll("button[data-query-label]")).map(
      (button) => button.getAttribute("data-query-label"),
    );
    expect(labels).toStrictEqual(["Q1", "Q2", "Q10"]);
    expect(screen.getByRole("button", { name: /^Q10/ })).toBeTruthy();
  });

  it("applies cumulative sticky-left offsets to the frozen header columns", () => {
    render(<QueryHeatmap summary={makeSummary()} />);
    const thead = matrixThead();
    const primaryHeader = within(thead).getByRole("columnheader", { name: /^Power Score/ });
    const platformHeader = within(thead).getByRole("columnheader", { name: /^Platform/ });
    expect(platformHeader.getAttribute("style")).toContain("left: 0rem");
    expect(platformHeader.className).toContain("sticky");
    expect(primaryHeader.getAttribute("style")).toContain("left: 11rem");
    expect(within(thead).queryByRole("columnheader", { name: "Trust" })).toBeNull();
  });

  it("shifts sticky offsets right by the checkbox column width when selection is enabled", () => {
    render(<QueryHeatmap summary={makeSummary()} selectedIds={new Set()} onSelectionChange={() => {}} />);
    const thead = matrixThead();
    const platformHeader = within(thead).getByRole("columnheader", { name: /^Platform/ });
    const primaryHeader = within(thead).getByRole("columnheader", { name: /^Power Score/ });
    expect(platformHeader.getAttribute("style")).toContain("left: 3rem");
    expect(primaryHeader.getAttribute("style")).toContain("left: 14rem");
  });

  it("renders the page-sticky header outside the horizontal scroll container", () => {
    render(<QueryHeatmap summary={makeSummary()} />);
    const pageStickyShell = screen.getByTestId("query-heatmap-page-sticky-header-shell");
    const scrollContainer = screen.getByTestId("query-heatmap-scroll-container");
    const tableHeaderRow = scrollContainer.querySelector("thead tr")!;
    const platformHeader = within(matrixThead()).getByRole("columnheader", { name: /^Platform/ });

    expect(pageStickyShell.className).toContain("sticky");
    expect(pageStickyShell.className).toContain("top-0");
    expect(pageStickyShell.className).toMatch(/\bz-40\b/);
    expect(pageStickyShell.closest(".overflow-x-auto")).toBeNull();
    expect(tableHeaderRow.className).not.toContain("top-0");
    expect(tableHeaderRow.className).not.toMatch(/\bsticky\b/);
    expect(platformHeader.className).toMatch(/\bz-30\b/);
  });

  it("keeps only identity and compact metadata affordance in the frozen platform cell", () => {
    const { container } = render(
      <QueryHeatmap
        summary={makeSummary({
          platforms: [{ ...makeSummary().platforms[0]!, platform_version: "V1.2.3" }],
        })}
      />,
    );
    const firstRow = container.querySelector("tbody tr");
    expect(firstRow).not.toBeNull();
    const cells = firstRow!.querySelectorAll('td[role="gridcell"]');
    expect(within(cells[0] as HTMLElement).getByText("V1.2.3")).toBeTruthy();
    expect(cells[0]?.textContent ?? "").not.toContain("vV1.2.3");
    const details = within(cells[0] as HTMLElement).getByText(
      BENCHMARK_MATRIX_DENSITY_CONTRACT.secondaryMetadataAffordance,
    ).closest("details");
    expect(details?.hasAttribute("open")).toBe(false);
    expect(firstRow!.querySelectorAll("td.sticky")).toHaveLength(3);
  });

  it("renders a nameable compliance marker instead of inline parenthetical text", () => {
    const noncompliantSummary = makeSummary({
      platforms: [
        {
          ...makeSummary().platforms[0]!,
          result_id: "platform-noncompliant",
          is_ranking_eligible: false,
          ranking_exclusion_reason: "compliance_not_rankable",
          compliance_class: "unofficial_subscale",
        },
      ],
    });
    render(<QueryHeatmap summary={noncompliantSummary} />);
    const marker = screen.getByTestId("heatmap-compliance-marker-platform-noncompliant");
    expect(marker.textContent).toBe("*");
    expect(marker.getAttribute("role")).toBe("img");
    expect(marker.getAttribute("title")).toContain("outside the ranked compliance class");
    expect(marker.getAttribute("aria-label")).toContain("outside the ranked compliance class");
    expect(screen.getAllByRole("img", { name: "Result is outside the ranked compliance class." })).toHaveLength(2);
    expect(screen.queryByText("(subscale)")).toBeNull();
  });

  it("renders compact receipt links and validation status badges", () => {
    render(<QueryHeatmap summary={makeSummary()} />);
    for (const details of screen.getAllByText(BENCHMARK_MATRIX_DENSITY_CONTRACT.secondaryMetadataAffordance)) {
      fireEvent.click(details);
    }
    const receiptLinks = screen.getAllByRole("link", { name: "Receipt →" }) as HTMLAnchorElement[];

    expect(receiptLinks[0]?.getAttribute("href")).toBe("/results/r/r1#run-receipt");
    expect(receiptLinks[1]?.getAttribute("href")).toBe("/results/r/r2#run-receipt");
    expect(screen.getAllByText("exact").length).toBeGreaterThan(0);
    expect(screen.getAllByText("loose").length).toBeGreaterThan(0);
  });

  it("clicking a query header sorts rows by that query", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} />);
    const rowOrder = () =>
      Array.from(container.querySelectorAll("tbody tr[data-testid]")).map(
        (row) => row.getAttribute("data-testid") ?? "",
      );

    expect(rowOrder()).toEqual(["r1", "r2"]);
    fireEvent.click(screen.getByRole("button", { name: /^Q1/ }));
    expect(rowOrder()).toEqual(["r1", "r2"]);
    fireEvent.click(screen.getByRole("button", { name: /^Q1/ }));
    expect(rowOrder()).toEqual(["r2", "r1"]);
  });

  it("heatmap cells keep visible values and color variables for multi-platform summaries", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} />);
    const heatCells = container.querySelectorAll(".heatmap-cell");
    // DuckDB Q1 (fastest) and SQLite Q1 (10× slower) = 2 cells; Q2 similarly
    expect(heatCells.length).toBeGreaterThan(0);
    for (const cell of Array.from(heatCells)) {
      expect((cell as HTMLElement).style.getPropertyValue("--cell-hue")).toBeTruthy();
      expect((cell as HTMLElement).style.getPropertyValue("--cell-lightness")).toBeTruthy();
      expect(cell.textContent).not.toBe("");
    }
  });

  it("exposes exact timing and relative-to-fastest accessible names", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} />);
    const fastest = container.querySelector<HTMLElement>('[data-cell="0-0"]');
    const slowest = container.querySelector<HTMLElement>('[data-cell="1-0"]');

    expect(fastest?.textContent).toBe("10 ms");
    expect(fastest?.getAttribute("aria-label")).toBe("10 ms, fastest in column");
    expect(slowest?.textContent).toBe("100 ms");
    expect(slowest?.getAttribute("aria-label")).toBe("100 ms, 10.0× fastest in column");
  });

  it("shows the metric/heatmap legend, excludes exact zeroes, and formats positive sub-millisecond timings", () => {
    const summary = makeSummary({
      platforms: [
        {
          ...makeSummary().platforms[0]!,
          timings: { Q1: 0, Q2: 20 },
        },
        {
          ...makeSummary().platforms[1]!,
          timings: { Q1: 0.4, Q2: 200 },
        },
      ],
    });
    const { container } = render(<QueryHeatmap summary={summary} />);

    const legend = screen.getByTestId("query-heatmap-legend");
    // Per `results-explorer-chart-panel-scope-and-labeling` w4, the legend
    // heading describes the cell metric (always per-query latency in ms),
    // not the cohort's primary score column. The primary score column
    // keeps its own metric/direction copy in the secondary line.
    expect(legend.textContent).toContain("Per-query latency (ms): lower is better");
    expect(legend.textContent).toContain("Power Score");
    expect(legend.textContent).toContain("higher is better");
    expect(legend.textContent).toContain("<1 ms");
    expect(legend.textContent).toContain("exact zero timings are");

    const zero = container.querySelector<HTMLElement>('[data-cell="0-0"]');
    const subMs = container.querySelector<HTMLElement>('[data-cell="1-0"]');
    expect(zero?.textContent).toBe("Excluded");
    expect(zero?.getAttribute("aria-label")).toContain("0 ms, excluded");
    expect(subMs?.textContent).toBe("<1 ms");
    expect(subMs?.getAttribute("aria-label")).toBe("<1 ms, fastest in column");
  });

  it("activates reduced-color class when high contrast is requested", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} highContrast />);
    expect(container.firstElementChild?.className).toContain("heatmap-reduced-color");
  });

  it("renders an explicit horizontal scroll affordance with stable matrix cell widths", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} />);

    const scrollContainer = screen.getByTestId("query-heatmap-scroll-container");
    const pageStickyHeader = screen.getByTestId("query-heatmap-page-sticky-header");
    expect(scrollContainer.className).toContain("overflow-x-auto");
    scrollContainer.scrollLeft = 96;
    fireEvent.scroll(scrollContainer);
    expect(pageStickyHeader.scrollLeft).toBe(96);
    expect(screen.getByTestId("query-heatmap-scroll-hint").textContent).toContain("Query columns");
    expect(screen.getByRole("grid").className).toContain("min-w-max");

    const queryHeaders = Array.from(matrixThead().querySelectorAll("th"));
    expect(queryHeaders.some((header) => header.className.includes("min-w-[7rem]"))).toBe(true);
    const queryCells = Array.from(container.querySelectorAll("tbody td[data-cell]"));
    expect(queryCells.every((cell) => cell.className.includes("min-w-[7rem]"))).toBe(true);
  });

  it("renders compact mobile cards grouped by platform with aggregate metric and query outliers", () => {
    render(<QueryHeatmap summary={makeSummary()} />);

    const cards = screen.getByTestId("query-heatmap-mobile-cards");
    expect(cards.querySelectorAll('[data-testid^="query-heatmap-mobile-card-"]')).toHaveLength(2);

    const sqliteCard = screen.getByTestId("query-heatmap-mobile-card-r2");
    expect(sqliteCard.textContent).toContain("SQLite");
    expect(sqliteCard.textContent).toContain("Power Score");
    expect(sqliteCard.textContent).toContain("800");
    expect(sqliteCard.textContent).toContain("Query outliers");
    expect(sqliteCard.textContent).toContain("Q2");
    expect(sqliteCard.textContent).toContain("200 ms");
    expect(sqliteCard.textContent).toContain("10.0× fastest");
  });

  it("uses the same comparison selection ids from compact mobile cards", () => {
    let selected: Set<string> | null = null;
    render(
      <QueryHeatmap
        summary={makeSummary()}
        selectedIds={new Set()}
        onSelectionChange={(ids) => {
          selected = ids;
        }}
      />,
    );

    const duckCard = screen.getByTestId("query-heatmap-mobile-card-r1");
    const checkbox = duckCard.querySelector("input[type='checkbox']") as HTMLInputElement;
    fireEvent.click(checkbox);

    expect([...(selected ?? [])]).toEqual(["r1"]);
  });

  it("does not allow comparison selection for rows excluded by the read-model contract", () => {
    let selected: Set<string> | null = null;
    const summary = makeSummary({
      platforms: [
        {
          ...makeSummary().platforms[0]!,
          comparison_exclusion_reason: "insufficient_valid_timings",
        },
      ],
    });
    render(
      <QueryHeatmap
        summary={summary}
        selectedIds={new Set()}
        onSelectionChange={(ids) => {
          selected = ids;
        }}
      />,
    );

    const checkbox = screen.getAllByRole("checkbox")[0] as HTMLInputElement;
    expect(checkbox.disabled).toBe(true);
    fireEvent.click(checkbox);
    expect(selected).toBeNull();
  });

  // -----------------------------------------------------------------------
  // (b) Null cells render "No run"
  // -----------------------------------------------------------------------

  it("null timing cell renders no-run copy with a missing-run aria-label", () => {
    const summary = makeSummary({
      platforms: [
        {
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
          ...TIMING_ELIGIBLE,
          missing_query_count: 1,
          comparison_exclusion_reason: "insufficient_valid_timings",
          power_score: 3000,
          display_geomean_ms: 10,
          compliance_class: null,
          sample_geomean_ms: 12,
          cost_usd: null,
          percentile_stats: null,
          phase_durations: null,
          timings: { Q1: 10, Q2: null },
        },
      ],
    });
    const { container } = render(<QueryHeatmap summary={summary} />);
    const cells = container.querySelectorAll('[aria-label="No published query run for DuckDB Q2"]');
    expect(cells.length).toBeGreaterThan(0);
    expect(cells[0]?.textContent).toBe("No run");
    expect(cells[0]?.getAttribute("title")).toBe("No published run for this query/platform cell.");
  });

  // -----------------------------------------------------------------------
  // (c) Single-platform matrix suppresses heat coloring
  // -----------------------------------------------------------------------

  it("single-platform matrix has no heatmap-cell class", () => {
    const summary = makeSummary({
      platforms: [
        {
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
          ...TIMING_ELIGIBLE,
          power_score: 3000,
          display_geomean_ms: 10,
          compliance_class: null,
          sample_geomean_ms: 12,
          cost_usd: null,
          percentile_stats: null,
          phase_durations: null,
          timings: { Q1: 10, Q2: 20 },
        },
      ],
    });
    const { container } = render(<QueryHeatmap summary={summary} />);
    expect(container.querySelectorAll(".heatmap-cell").length).toBe(0);
  });

  // -----------------------------------------------------------------------
  // (d) Empty platforms list shows empty-state message
  // -----------------------------------------------------------------------

  it("empty platforms list shows empty-state", () => {
    const summary = makeSummary({ platforms: [] });
    render(<QueryHeatmap summary={summary} />);
    expect(screen.getByText(/No results available/)).toBeTruthy();
  });

  // -----------------------------------------------------------------------
  // Ranking: eligible rows sort before ineligible
  // -----------------------------------------------------------------------

  it("ineligible platforms sort below eligible ones", () => {
    const summary = makeSummary({
      platforms: [
        {
          result_id: "r_ineligible",
          short_id: "",
          platform_id: "sqlite",
          platform: "SQLite",
          platform_version: null,
          tuning_mode: null,
          tuning_hash: null,
          execution_mode: null,
          trust_label: "community-submission",
          run_date: "2026-04-01",
          is_ranking_eligible: false,
          ...TIMING_ELIGIBLE,
          ranking_exclusion_reason: "trust_not_rankable",
          power_score: 9999,
          display_geomean_ms: 1,
          compliance_class: null,
          sample_geomean_ms: 1,
          cost_usd: null,
          percentile_stats: null,
          phase_durations: null,
          timings: { Q1: 1, Q2: 1 },
        },
        {
          result_id: "r_eligible",
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
          ...TIMING_ELIGIBLE,
          power_score: 100,
          display_geomean_ms: 100,
          compliance_class: null,
          sample_geomean_ms: 100,
          cost_usd: null,
          percentile_stats: null,
          phase_durations: null,
          timings: { Q1: 100, Q2: 200 },
        },
      ],
    });
    const { container } = render(<QueryHeatmap summary={summary} />);
    const rows = container.querySelectorAll("tbody tr");
    // DuckDB (eligible) must be first despite lower power_score
    expect(rows[0]?.textContent).toContain("DuckDB");
    expect(rows[1]?.textContent).toContain("SQLite");
  });

  // -----------------------------------------------------------------------
  // Keyboard navigation: roving tabindex
  // -----------------------------------------------------------------------

  it("ArrowRight moves focus to next column (tabIndex moves from [0,0] to [0,1])", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} />);
    const firstCell = container.querySelector('[data-cell="0-0"]') as HTMLElement;
    expect(firstCell).not.toBeNull();
    expect(firstCell.tabIndex).toBe(0);
    fireEvent.keyDown(firstCell, { key: "ArrowRight" });
    const nextCell = container.querySelector('[data-cell="0-1"]') as HTMLElement;
    expect(nextCell.tabIndex).toBe(0);
    expect(firstCell.tabIndex).toBe(-1);
  });

  it("ArrowDown moves focus to the row below (tabIndex moves from [0,0] to [1,0])", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} />);
    const firstCell = container.querySelector('[data-cell="0-0"]') as HTMLElement;
    fireEvent.keyDown(firstCell, { key: "ArrowDown" });
    const below = container.querySelector('[data-cell="1-0"]') as HTMLElement;
    expect(below.tabIndex).toBe(0);
    expect(firstCell.tabIndex).toBe(-1);
  });

  it("ArrowLeft at column 0 keeps focus at [0,0] (no crash, no negative index)", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} />);
    const firstCell = container.querySelector('[data-cell="0-0"]') as HTMLElement;
    fireEvent.keyDown(firstCell, { key: "ArrowLeft" });
    expect(firstCell.tabIndex).toBe(0);
  });

  it("ArrowUp at row 0 keeps focus at [0,0] (no crash, no negative index)", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} />);
    const firstCell = container.querySelector('[data-cell="0-0"]') as HTMLElement;
    fireEvent.keyDown(firstCell, { key: "ArrowUp" });
    expect(firstCell.tabIndex).toBe(0);
  });

  // -----------------------------------------------------------------------
  // Accessibility: selection-enabled path
  // -----------------------------------------------------------------------

  it("has no axe violations when selection is enabled (checkbox column header path)", async () => {
    const { container } = render(
      <QueryHeatmap summary={makeSummary()} selectedIds={new Set()} onSelectionChange={() => {}} />,
    );
    await expectNoAxeViolations(container);
  });
});
