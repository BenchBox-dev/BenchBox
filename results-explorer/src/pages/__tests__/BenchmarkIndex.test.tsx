/**
 * Integration tests for BenchmarkIndex page.
 *
 * Cases:
 *   (a) Renders the matrix view by default (QueryHeatmap present)
 *   (b) Trust filter toggles rows without refetching the cohort
 *   (c) List-view toggle switches rendered component
 *   (d) Empty platforms list renders QueryHeatmap empty-state
 *   (e) axe-core: no serious/critical violations on a fully-loaded matrix
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/preact";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { BenchmarkSummary } from "@/types";
import { expectNoAxeViolations } from "@/testing/axe-helper";

// ---------------------------------------------------------------------------
// Mock `@/db.queryRows` so pages load canonical DuckDB rows from fixtures.
// ---------------------------------------------------------------------------

vi.mock("@/db", () => ({
  queryRows: vi.fn(),
}));

import { queryRows } from "@/db";
import { BenchmarkIndex } from "@/pages/BenchmarkIndex";

// ---------------------------------------------------------------------------
// Fixtures - raw DuckDB row shapes
// ---------------------------------------------------------------------------

const RESULT_ROWS = [
  {
    result_id: "r1",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: null,
    run_date: "2026-04-01",
    power_score: 3000,
    total_duration_s: 60,
    geomean_ms: 10,
    display_geomean_ms: 10,
    query_count: 2,
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: null,
    tuning_mode: null,
    tuning_hash: null,
    test_type: "power",
    validation_status: null,
    cost_usd: null,
    compliance_class: null,
    is_ranking_eligible: true,
    has_plans: false,
    has_tuning: false,
    bundle_download_url: "",
  },
  {
    result_id: "r2",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "SQLite",
    platform_id: "sqlite",
    driver_version: null,
    run_date: "2026-04-01",
    power_score: null,
    total_duration_s: 600,
    geomean_ms: 200,
    display_geomean_ms: 200,
    query_count: 2,
    trust_label: "community-submission",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: null,
    tuning_mode: null,
    tuning_hash: null,
    test_type: "power",
    validation_status: null,
    cost_usd: null,
    compliance_class: null,
    is_ranking_eligible: false,
    has_plans: false,
    has_tuning: false,
    bundle_download_url: "",
  },
];

const RANKING_ROWS = [
  {
    benchmark: "tpch",
    scale_factor: 0.1,
    phase: "power",
    result_id: "r1",
    platform_id: "duckdb",
    platform: "DuckDB",
    short_id: "",
    trust_label: "maintainer-run",
    tuning_mode: null,
    tuning_hash: null,
    execution_mode: null,
    compliance_class: null,
    run_date: "2026-04-01",
    is_ranking_eligible: true,
    power_score: 3000,
    display_geomean_ms: 10,
    sample_geomean_ms: 12,
    cost_usd: null,
    primary_metric: "power_score",
    primary_order: "desc",
    rank: 1,
    total_in_cohort: 2,
    percentile_p50: null,
    percentile_p90: null,
    percentile_p95: null,
    percentile_p99: null,
  },
  {
    benchmark: "tpch",
    scale_factor: 0.1,
    phase: "power",
    result_id: "r2",
    platform_id: "sqlite",
    platform: "SQLite",
    short_id: "",
    trust_label: "community-submission",
    tuning_mode: null,
    tuning_hash: null,
    execution_mode: null,
    compliance_class: null,
    run_date: "2026-04-01",
    is_ranking_eligible: false,
    power_score: null,
    display_geomean_ms: 200,
    sample_geomean_ms: 220,
    cost_usd: null,
    primary_metric: "power_score",
    primary_order: "desc",
    rank: 2,
    total_in_cohort: 2,
    percentile_p50: null,
    percentile_p90: null,
    percentile_p95: null,
    percentile_p99: null,
  },
];

const CELL_ROWS = [
  { benchmark: "tpch", scale_factor: 0.1, phase: "power", result_id: "r1", platform_id: "duckdb", query_id: "Q1", display_ms: 10 },
  { benchmark: "tpch", scale_factor: 0.1, phase: "power", result_id: "r1", platform_id: "duckdb", query_id: "Q2", display_ms: 20 },
  { benchmark: "tpch", scale_factor: 0.1, phase: "power", result_id: "r2", platform_id: "sqlite", query_id: "Q1", display_ms: 100 },
  { benchmark: "tpch", scale_factor: 0.1, phase: "power", result_id: "r2", platform_id: "sqlite", query_id: "Q2", display_ms: 200 },
];

// The legacy SUMMARY fixture remains useful for the direct-component axe test.
const SUMMARY: BenchmarkSummary = {
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
      trust_label: "community-submission",
      run_date: "2026-04-01",
      is_ranking_eligible: false,
      power_score: null,
      display_geomean_ms: 200,
      compliance_class: null,
      sample_geomean_ms: 220,
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
};

// ---------------------------------------------------------------------------
// Mock dispatch - match by SQL-prefix of the canonical helpers in
// `src/lib/duckdbQueries.ts`. Tests override the default behaviour via
// `vi.mocked(queryRows).mockImplementationOnce(...)` for edge cases.
// ---------------------------------------------------------------------------

type QueryRowsImpl = (sql: string, params?: unknown[]) => Promise<unknown[]>;

function defaultImpl(rows: typeof RESULT_ROWS, rankings: typeof RANKING_ROWS, cells: typeof CELL_ROWS): QueryRowsImpl {
  return async (sql: string) => {
    const s = String(sql).replace(/\s+/g, " ").trim();
    if (s.startsWith("SELECT * FROM bench.results")) return rows;
    if (s.startsWith("SELECT * FROM bench.benchmark_rankings")) return rankings;
    if (s.startsWith("SELECT benchmark, scale_factor, phase, result_id, platform_id, query_id, display_ms")) {
      return cells;
    }
    if (s.startsWith("SELECT result_id, phase, duration_s FROM bench.result_phase_durations")) return [];
    return [];
  };
}

beforeEach(() => {
  window.history.replaceState(null, "", "/results/tpch/");
  vi.mocked(queryRows).mockImplementation(defaultImpl(RESULT_ROWS, RANKING_ROWS, CELL_ROWS));
});

function getRenderedResultOrder(container: ParentNode): string[] {
  return Array.from(container.querySelectorAll("tbody tr[data-testid]")).map(
    (row) => row.getAttribute("data-testid") ?? "",
  );
}

// ---------------------------------------------------------------------------
// (a) Matrix view is the default
// ---------------------------------------------------------------------------

describe("BenchmarkIndex", () => {
  it("renders the page title", async () => {
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => expect(screen.getByText("TPC-H Results")).toBeTruthy());
  });

  it("shows QueryHeatmap (query column headers) by default", async () => {
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Q1/ })).toBeTruthy();
      expect(screen.getByRole("button", { name: /^Q2/ })).toBeTruthy();
    });
  });

  it("matrix view sorts rows from query headers", async () => {
    const { container } = render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => expect(screen.getByRole("button", { name: /^Q1/ })).toBeTruthy());

    expect(getRenderedResultOrder(container)).toEqual(["r1", "r2"]);
    fireEvent.click(screen.getByRole("button", { name: /^Q1/ }));
    expect(getRenderedResultOrder(container)).toEqual(["r1", "r2"]);
    fireEvent.click(screen.getByRole("button", { name: /^Q1/ }));
    expect(getRenderedResultOrder(container)).toEqual(["r2", "r1"]);
  });

  it("shows platform names from the summary", async () => {
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
      expect(screen.getAllByText("SQLite").length).toBeGreaterThan(0);
    });
  });

  // -----------------------------------------------------------------------
  // (c) List view toggle
  // -----------------------------------------------------------------------

  it("list-view toggle hides query columns and shows geomean column", async () => {
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("DuckDB"));

    // Switch to list view
    const listBtn = screen.getByText("List");
    fireEvent.click(listBtn);

    // List view shows a table with Geomean column but no query columns
    await waitFor(() => expect(screen.getByRole("button", { name: /Geomean/ })).toBeTruthy());
    expect(screen.queryByRole("button", { name: /^Q1/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Q2/ })).toBeNull();
  });

  it("list view sorts rows from table headers", async () => {
    const { container } = render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("DuckDB"));
    fireEvent.click(screen.getByText("List"));

    await waitFor(() => expect(screen.getByRole("button", { name: /Geomean/ })).toBeTruthy());
    expect(getRenderedResultOrder(container)).toEqual(["r1", "r2"]);
    fireEvent.click(screen.getByRole("button", { name: /Geomean/ }));
    expect(getRenderedResultOrder(container)).toEqual(["r2", "r1"]);
  });

  // -----------------------------------------------------------------------
  // (b) Trust filter hides rows without refetching
  // -----------------------------------------------------------------------

  it("trust filter chips appear when multiple trust tiers are present", async () => {
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("DuckDB"));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /maintainer/i })).toBeTruthy();
      expect(screen.getByRole("button", { name: /community/i })).toBeTruthy();
    });
  });

  it("deselecting community chip hides community rows without extra fetch", async () => {
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("SQLite"));

    const callsBefore = vi.mocked(queryRows).mock.calls.length;

    // Click the community chip to deselect it
    const communityBtn = screen.getByRole("button", { name: /community/i });
    fireEvent.click(communityBtn);

    // SQLite (community-submission) should now be gone
    await waitFor(() => expect(screen.queryByText("SQLite")).toBeNull());

    // DuckDB (maintainer-run) should still be visible
    expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);

    // No additional queryRows calls - client-side filtering only.
    expect(vi.mocked(queryRows).mock.calls.length).toBe(callsBefore);
  });

  // -----------------------------------------------------------------------
  // (d) Empty ranking cohort shows the informational empty state
  // -----------------------------------------------------------------------

  it("empty cohort shows empty-state message", async () => {
    vi.mocked(queryRows).mockImplementation(defaultImpl(RESULT_ROWS, [], []));
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() =>
      expect(screen.getByText(/No benchmark data available/)).toBeTruthy(),
    );
  });

  // -----------------------------------------------------------------------
  // (e) axe-core: no serious/critical violations
  // -----------------------------------------------------------------------

  it("has no serious/critical axe violations when matrix is loaded", async () => {
    const { container } = render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("DuckDB"));
    await expectNoAxeViolations(container);
  });

  it("QueryHeatmap has no serious/critical axe violations", async () => {
    const { QueryHeatmap } = await import("@/components/QueryHeatmap");
    const { container } = render(<QueryHeatmap summary={SUMMARY} />);
    await expectNoAxeViolations(container);
  });

  // -----------------------------------------------------------------------
  // Phase guard: when only "standard" phase is available, the page must
  // request the "standard" cohort (not the stale phaseFilter="power" default).
  // -----------------------------------------------------------------------

  it("loads standard-phase cohort when only standard is available for the SF", async () => {
    const standardRows = RESULT_ROWS.map((r) => ({ ...r, test_type: "standard" }));
    const standardRankings = RANKING_ROWS.map((r) => ({ ...r, phase: "standard" }));
    const standardCells = CELL_ROWS.map((c) => ({ ...c, phase: "standard" }));
    vi.mocked(queryRows).mockImplementation(defaultImpl(standardRows, standardRankings, standardCells));

    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("DuckDB"));
    await waitFor(() =>
      expect(new URL(window.location.href).searchParams.get("phase")).toBe("standard"),
    );

    // Verify the last benchmark_rankings call targets "standard" (any earlier
    // call may still use the default phase filter before results resolve).
    const rankingCalls = vi.mocked(queryRows).mock.calls.filter(([sql]) =>
      String(sql).replace(/\s+/g, " ").includes("FROM bench.benchmark_rankings"),
    );
    expect(rankingCalls[rankingCalls.length - 1]?.[1]).toEqual(["tpch", 0.1, "standard"]);
  });

  it("coerces an unavailable phase URL value to the rendered cohort phase", async () => {
    window.history.replaceState(null, "", "/results/tpch/?sf=0.1&phase=standard");

    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("DuckDB"));

    // "power" is the useUrlState default, so correcting to it strips the
    // phase key rather than leaving a redundant `?phase=power` param.
    await waitFor(() =>
      expect(new URL(window.location.href).searchParams.get("phase")).toBeNull(),
    );

    const rankingCalls = vi.mocked(queryRows).mock.calls.filter(([sql]) =>
      String(sql).replace(/\s+/g, " ").includes("FROM bench.benchmark_rankings"),
    );
    expect(rankingCalls[rankingCalls.length - 1]?.[1]).toEqual(["tpch", 0.1, "power"]);
  });
});
