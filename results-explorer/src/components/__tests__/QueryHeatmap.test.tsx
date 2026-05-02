/**
 * Tests for QueryHeatmap component.
 *
 * Cases:
 *   (a) Known timings produce stable color hue values
 *   (b) Null cells render "-" with aria-label="no data"
 *   (c) Single-platform matrix degrades gracefully (no heat coloring)
 *   (d) Empty platforms list shows empty-state message
 *
 * Note: colorForCell / lightnessForCell math is now covered by the fixture-driven
 * parity suite at src/__tests__/parity/chartMath.parity.test.ts.
 * No hardcoded expected values remain here - the fixtures are the contract.
 */

import { fireEvent, render, screen } from "@testing-library/preact";
import { describe, it, expect } from "vitest";
import { expectNoAxeViolations } from "@/testing/axe-helper";
import { QueryHeatmap } from "@/components/QueryHeatmap";
import type { BenchmarkSummary } from "@/types";

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

function makeSummary(overrides: Partial<BenchmarkSummary> = {}): BenchmarkSummary {
  return {
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
        power_score: 3000,
        display_geomean_ms: 10,
        compliance_class: null,
        sample_geomean_ms: 12,
        cost_usd: null,
        percentile_stats: null,
        phase_durations: null,
        timings: { Q1: 10, Q2: 20 },
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
        power_score: 800,
        display_geomean_ms: 100,
        compliance_class: null,
        sample_geomean_ms: 120,
        cost_usd: null,
        percentile_stats: null,
        phase_durations: null,
        timings: { Q1: 100, Q2: 200 },
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
}

// ---------------------------------------------------------------------------
// (a) Known timings produce stable rendered output
// ---------------------------------------------------------------------------

describe("QueryHeatmap rendering", () => {
  it("renders platform names", () => {
    render(<QueryHeatmap summary={makeSummary()} />);
    expect(screen.getByText("DuckDB")).toBeTruthy();
    expect(screen.getByText("SQLite")).toBeTruthy();
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
    const { container } = render(<QueryHeatmap summary={summary} />);

    const labels = Array.from(container.querySelectorAll("thead button[data-query-label]")).map(
      (button) => button.getAttribute("data-query-label"),
    );
    expect(labels).toStrictEqual(["Q1", "Q2", "Q10"]);
    expect(screen.getByRole("button", { name: /^Q10/ })).toBeTruthy();
  });

  it("renders compact receipt links and validation status badges", () => {
    render(<QueryHeatmap summary={makeSummary()} />);
    const receiptLinks = screen.getAllByRole("link", { name: "Receipt →" }) as HTMLAnchorElement[];

    expect(receiptLinks[0]?.getAttribute("href")).toBe("/results/r/r1#run-receipt");
    expect(receiptLinks[1]?.getAttribute("href")).toBe("/results/r/r2#run-receipt");
    expect(screen.getByText("exact")).toBeTruthy();
    expect(screen.getByText("loose")).toBeTruthy();
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

  it("activates reduced-color class when high contrast is requested", () => {
    const { container } = render(<QueryHeatmap summary={makeSummary()} highContrast />);
    expect(container.firstElementChild?.className).toContain("heatmap-reduced-color");
  });

  // -----------------------------------------------------------------------
  // (b) Null cells render "-"
  // -----------------------------------------------------------------------

  it("null timing cell renders em-dash with no-data aria-label", () => {
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
    const cells = container.querySelectorAll('[aria-label="no data"]');
    expect(cells.length).toBeGreaterThan(0);
    expect(cells[0]?.textContent).toBe("-");
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
