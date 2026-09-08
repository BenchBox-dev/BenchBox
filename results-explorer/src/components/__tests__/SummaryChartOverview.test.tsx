/**
 * Tests for the long summary overview section chrome.
 *
 * Covers the artboard-parity additions around the shared charts: the cohort
 * section heading with its scope callout and section-link button, the
 * distribution population/key/boundary footer with matrix and exclusion
 * links, and the dynamic additional-analyses count.
 */

import { render, screen, fireEvent } from "@testing-library/preact";
import { describe, it, expect, vi } from "vitest";
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
  it("heads the section with the cohort question, scope callout, and link button", () => {
    const { container } = renderOverview();
    expect(screen.getByText("What does this cohort show?")).not.toBeNull();
    expect(screen.getByText(/Shared scope:/)).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Copy chart-section link" }),
    ).not.toBeNull();
    const root = container.querySelector("[data-testid='summary-chart-overview']");
    expect(root?.getAttribute("id")).toBe("cohort-charts");
  });

  it("copies the chart-section link with facets and confirms", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    window.history.replaceState({}, "", "/results/tpch/?scale_factor=0.1&phase=power");
    try {
      renderOverview();
      fireEvent.click(screen.getByRole("button", { name: "Copy chart-section link" }));
      await screen.findByRole("button", { name: /Link copied/ });
      expect(writeText).toHaveBeenCalledOnce();
      const copied = String(writeText.mock.calls[0]?.[0] ?? "");
      expect(copied).toContain("?scale_factor=0.1&phase=power");
      expect(copied.endsWith("#cohort-charts")).toBe(true);
    } finally {
      window.history.replaceState({}, "", "/");
      // @ts-expect-error jsdom has no clipboard; restore the missing default.
      delete navigator.clipboard;
    }
  });

  it("footers the distribution with boundary and links (key lives on the chart)", () => {
    renderOverview();
    // The whisker key belongs to DistributionBox's own footer; the overview
    // must not restate it.
    expect(screen.queryByText(/whiskers min\/max/)).toBeNull();
    const paragraphs = screen
      .getAllByText(/across different queries, not run-to-run variability/)
      .filter((el) => el.tagName === "P");
    expect(paragraphs).toHaveLength(1);
    const matrixLink = screen.getByText(/Open per-query matrix/) as HTMLAnchorElement;
    expect(matrixLink.getAttribute("href")).toBe("#evidence-matrix");
    const exclusionsLink = screen.getByText(/Inspect exclusions/) as HTMLAnchorElement;
    expect(exclusionsLink.getAttribute("href")).toBe("#provenance-legend");
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

  it("falls back to execCommand when the async clipboard is missing", async () => {
    const execCommand = vi.fn(() => true);
    const original = document.execCommand;
    // @ts-expect-error jsdom has no clipboard; ensure the fallback path runs.
    delete navigator.clipboard;
    document.execCommand = execCommand;
    try {
      renderOverview();
      fireEvent.click(screen.getByRole("button", { name: "Copy chart-section link" }));
      await screen.findByRole("button", { name: /Link copied/ });
      expect(execCommand).toHaveBeenCalledOnce();
    } finally {
      document.execCommand = original;
    }
  });

  it("reports failure when every copy path fails", async () => {
    const execCommand = vi.fn(() => false);
    const original = document.execCommand;
    // @ts-expect-error jsdom has no clipboard; ensure the fallback path runs.
    delete navigator.clipboard;
    document.execCommand = execCommand;
    try {
      renderOverview();
      fireEvent.click(screen.getByRole("button", { name: "Copy chart-section link" }));
      await screen.findByRole("button", { name: /Copy failed/ });
    } finally {
      document.execCommand = original;
    }
  });
});
