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

import { render, screen, fireEvent, waitFor, within } from "@testing-library/preact";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { BenchmarkSummary } from "@/types";
import { expectNoAxeViolations } from "@/testing/axe-helper";

// ---------------------------------------------------------------------------
// Mock `@/db.queryRows` so pages load canonical DuckDB rows from fixtures.
// ---------------------------------------------------------------------------

vi.mock("@/db", () => ({
  queryRows: vi.fn(),
}));

vi.mock("preact-router", async () => {
  const actual = await vi.importActual<typeof import("preact-router")>("preact-router");
  return {
    ...actual,
    route: vi.fn(),
  };
});

vi.mock("@/components/QueryHeatmap", async () => {
  const actual = await vi.importActual<typeof import("@/components/QueryHeatmap")>("@/components/QueryHeatmap");
  type QueryHeatmapProps = Parameters<typeof actual.QueryHeatmap>[0];

  return {
    ...actual,
    QueryHeatmap: (props: QueryHeatmapProps) => {
      const testWindow = window as Window & { __benchboxCompareSelectionTest?: boolean };
      if (!testWindow.__benchboxCompareSelectionTest) {
        return <actual.QueryHeatmap {...props} />;
      }
      return (
        <div>
          <actual.QueryHeatmap {...props} />
          <button
            type="button"
            onClick={() => props.onSelectionChange?.(new Set(["aaaaaaaa", "bbbbbbbb"]))}
          >
            Select fixture compare rows
          </button>
        </div>
      );
    },
  };
});

import { queryRows } from "@/db";
import { clearDuckdbQueryCachesForTests } from "@/lib/duckdbQueries";
import { BenchmarkIndex } from "@/pages/BenchmarkIndex";

// ---------------------------------------------------------------------------
// Fixtures - raw DuckDB row shapes
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

const TIMING_CELL_ELIGIBLE = {
  is_valid_display_timing: true,
  timing_exclusion_reason: null,
};

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
    ...TIMING_ELIGIBLE,
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: null,
    tuning_mode: null,
    tuning_hash: null,
    test_type: "power",
    validation_status: "exact",
    cost_usd: null,
    normalized_cost_usd: 1.25,
    cost_status: "normalized",
    cost_scope: "compute_only",
    cost_model_version: "2026.05.0",
    deployment_class: "cloud",
    cloud_provider: "aws",
    cloud_region: "us-east-1",
    instance_or_warehouse: "MEDIUM",
    warehouse_size: "MEDIUM",
    storage_format: "parquet",
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
    ...TIMING_ELIGIBLE,
    ranking_exclusion_reason: "trust_not_rankable",
    trust_label: "community-submission",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: null,
    tuning_mode: null,
    tuning_hash: null,
    test_type: "power",
    validation_status: "loose",
    cost_usd: null,
    normalized_cost_usd: null,
    cost_status: "not_applicable_local",
    cost_scope: null,
    cost_model_version: null,
    deployment_class: "local",
    cloud_provider: null,
    cloud_region: null,
    instance_or_warehouse: null,
    warehouse_size: null,
    storage_format: null,
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
    short_id: "aaaaaaaa",
    trust_label: "maintainer-run",
    tuning_mode: null,
    tuning_hash: null,
    execution_mode: null,
    compliance_class: null,
    run_date: "2026-04-01",
    is_ranking_eligible: true,
    ...TIMING_ELIGIBLE,
    power_score: 3000,
    display_geomean_ms: 10,
    sample_geomean_ms: 12,
    cost_usd: null,
    normalized_cost_usd: 1.25,
    cost_status: "normalized",
    cost_scope: "compute_only",
    cost_model_version: "2026.05.0",
    deployment_class: "cloud",
    cloud_provider: "aws",
    cloud_region: "us-east-1",
    instance_or_warehouse: "MEDIUM",
    warehouse_size: "MEDIUM",
    storage_format: "parquet",
    primary_metric: "power_score",
    primary_order: "desc",
    rank: 1,
    total_in_cohort: 1,
    cohort_ranked_count: 1,
    cohort_ranking_exclusion_reason: null,
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
    short_id: "bbbbbbbb",
    trust_label: "community-submission",
    tuning_mode: null,
    tuning_hash: null,
    execution_mode: null,
    compliance_class: null,
    run_date: "2026-04-01",
    is_ranking_eligible: false,
    ...TIMING_ELIGIBLE,
    ranking_exclusion_reason: "trust_not_rankable",
    power_score: null,
    display_geomean_ms: 200,
    sample_geomean_ms: 220,
    cost_usd: null,
    normalized_cost_usd: null,
    cost_status: "not_applicable_local",
    cost_scope: null,
    cost_model_version: null,
    deployment_class: "local",
    cloud_provider: null,
    cloud_region: null,
    instance_or_warehouse: null,
    warehouse_size: null,
    storage_format: null,
    primary_metric: "power_score",
    primary_order: "desc",
    rank: null,
    total_in_cohort: 1,
    cohort_ranked_count: 1,
    cohort_ranking_exclusion_reason: null,
    percentile_p50: null,
    percentile_p90: null,
    percentile_p95: null,
    percentile_p99: null,
  },
];

const CELL_ROWS = [
  { benchmark: "tpch", scale_factor: 0.1, phase: "power", result_id: "r1", platform_id: "duckdb", query_id: "Q1", display_ms: 10, ...TIMING_CELL_ELIGIBLE },
  { benchmark: "tpch", scale_factor: 0.1, phase: "power", result_id: "r1", platform_id: "duckdb", query_id: "Q2", display_ms: 20, ...TIMING_CELL_ELIGIBLE },
  { benchmark: "tpch", scale_factor: 0.1, phase: "power", result_id: "r2", platform_id: "sqlite", query_id: "Q1", display_ms: 100, ...TIMING_CELL_ELIGIBLE },
  { benchmark: "tpch", scale_factor: 0.1, phase: "power", result_id: "r2", platform_id: "sqlite", query_id: "Q2", display_ms: 200, ...TIMING_CELL_ELIGIBLE },
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
      ...TIMING_ELIGIBLE,
      power_score: 3000,
      display_geomean_ms: 10,
      compliance_class: null,
      sample_geomean_ms: 12,
      cost_usd: null,
      deployment_class: "cloud",
      instance_or_warehouse: "MEDIUM",
      percentile_stats: null,
      phase_durations: null,
      timings: { Q1: 10, Q2: 20 },
      timing_eligibility: {
        Q1: { is_valid_display_timing: true, timing_exclusion_reason: null },
        Q2: { is_valid_display_timing: true, timing_exclusion_reason: null },
      },
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
      ...TIMING_ELIGIBLE,
      ranking_exclusion_reason: "trust_not_rankable",
      power_score: null,
      display_geomean_ms: 200,
      compliance_class: null,
      sample_geomean_ms: 220,
      cost_usd: null,
      deployment_class: "local",
      instance_or_warehouse: null,
      percentile_stats: null,
      phase_durations: null,
      timings: { Q1: 100, Q2: 200 },
      timing_eligibility: {
        Q1: { is_valid_display_timing: true, timing_exclusion_reason: null },
        Q2: { is_valid_display_timing: true, timing_exclusion_reason: null },
      },
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
    if (s.includes("FROM bench.results")) return rows;
    if (s.includes("FROM bench.benchmark_rankings")) return rankings;
    if (s.startsWith("SELECT benchmark, scale_factor, phase, result_id, platform_id, query_id, display_ms")) {
      return cells;
    }
    if (s.startsWith("SELECT result_id, phase, duration_s FROM bench.result_phase_durations")) return [];
    return [];
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  clearDuckdbQueryCachesForTests();
  delete (window as Window & { __benchboxCompareSelectionTest?: boolean }).__benchboxCompareSelectionTest;
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
    expect(document.title).toBe("TPC-H · BenchBox Results");
  });

  it("sets the not-found title for unknown benchmark slugs", async () => {
    render(<BenchmarkIndex benchmark="does-not-exist" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "404" })).toBeTruthy());
    await waitFor(() => expect(document.title).toBe("Not found · BenchBox Results"));
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

  it("matrix rows expose receipt links and validation status from result metadata", async () => {
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });

    const receiptLinks = screen.getAllByRole("link", { name: "Receipt →" }) as HTMLAnchorElement[];
    expect(receiptLinks[0]?.getAttribute("href")).toBe("/results/r/r1#run-receipt");
    expect(screen.getAllByText("exact").length).toBeGreaterThan(0);
    expect(screen.getAllByText("loose").length).toBeGreaterThan(0);
  });

  it("shows persistent compare guidance before any rows are selected", async () => {
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => expect(screen.getByTestId("benchmark-compare-guidance")).toBeTruthy());

    const guidance = screen.getByTestId("benchmark-compare-guidance");
    expect(guidance.textContent).toContain("Select two or more platforms");
    const disabledAction = screen.getByRole("button", { name: "Select 2 comparable results" }) as HTMLButtonElement;
    expect(disabledAction.disabled).toBe(true);
  });

  it("renders a Benchmark switcher that routes to a sibling and clears benchmark-specific params", async () => {
    const preactRouter = await import("preact-router");
    const routeMock = vi.mocked(preactRouter.route);
    routeMock.mockClear();
    window.history.replaceState(null, "", "/results/tpch/?sf=10&phase=power&view=ranks");

    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => expect(screen.getByText("TPC-H Results")).toBeTruthy());

    const switcher = screen.getByTestId("benchmark-switcher") as HTMLSelectElement;
    expect(switcher.value).toBe("tpch");
    expect(within(switcher).getByRole("option", { name: "ClickBench" })).toBeTruthy();
    expect(within(switcher).getByRole("option", { name: "TPC-H" })).toBeTruthy();

    fireEvent.change(switcher, { target: { value: "clickbench" } });
    expect(routeMock).toHaveBeenCalledTimes(1);
    expect(routeMock).toHaveBeenCalledWith("/results/clickbench/?view=ranks");
  });

  it.each([
    ["ssb", "star_schema"],
    ["tsbs_devops", "tsbs-devops"],
  ])("keeps legacy benchmark slug %s selected even when deduped from canonical %s", async (legacySlug, canonicalSlug) => {
    const legacyRows = RESULT_ROWS.map((row) => ({ ...row, benchmark: legacySlug }));
    const legacyRankings = RANKING_ROWS.map((row) => ({ ...row, benchmark: legacySlug }));
    const legacyCells = CELL_ROWS.map((row) => ({ ...row, benchmark: legacySlug }));
    vi.mocked(queryRows).mockImplementation(defaultImpl(legacyRows, legacyRankings, legacyCells));

    render(<BenchmarkIndex benchmark={legacySlug} />);
    await waitFor(() => expect(screen.getByTestId("benchmark-switcher")).toBeTruthy());

    const switcher = screen.getByTestId("benchmark-switcher") as HTMLSelectElement;
    const optionValues = Array.from(switcher.options).map((option) => option.value);
    expect(switcher.value).toBe(legacySlug);
    expect(optionValues).toContain(canonicalSlug);
    expect(optionValues).toContain(legacySlug);
  });

  it("labels the Star Schema Benchmark and SSB equivalence explicitly", async () => {
    const ssbRows = RESULT_ROWS.map((row) => ({ ...row, benchmark: "star_schema" }));
    const ssbRankings = RANKING_ROWS.map((row) => ({ ...row, benchmark: "star_schema" }));
    const ssbCells = CELL_ROWS.map((row) => ({ ...row, benchmark: "star_schema" }));
    vi.mocked(queryRows).mockImplementation(defaultImpl(ssbRows, ssbRankings, ssbCells));

    render(<BenchmarkIndex benchmark="star_schema" />);
    await waitFor(() => expect(screen.getByText("SSB Results")).toBeTruthy());

    expect(screen.getByTestId("benchmark-context-note").textContent).toContain("Star Schema Benchmark (SSB)");
  });

  it("compare tray shows selected metadata and links with short IDs", async () => {
    (window as Window & { __benchboxCompareSelectionTest?: boolean }).__benchboxCompareSelectionTest = true;
    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Select fixture compare rows" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Select fixture compare rows" }));

    await waitFor(() => expect(screen.getByTestId("compare-tray-row-aaaaaaaa")).toBeTruthy());

    const duckRow = screen.getByTestId("compare-tray-row-aaaaaaaa");
    const sqliteRow = screen.getByTestId("compare-tray-row-bbbbbbbb");
    expect(duckRow.textContent).toContain("DuckDB");
    expect(duckRow.textContent).toContain("TPC-H");
    expect(duckRow.textContent).toContain("SF 0.1");
    expect(duckRow.textContent).toContain("power");
    expect(duckRow.textContent).toContain("2026-04-01");
    expect(duckRow.textContent).toContain("ID aaaaaaaa");
    expect(sqliteRow.textContent).toContain("SQLite");

    const compareLink = screen.getByRole("link", { name: /Compare 2 selected/ }) as HTMLAnchorElement;
    expect(compareLink.getAttribute("href")).toBe("/results/compare?ids=aaaaaaaa,bbbbbbbb");
  });

  it("restores benchmark URL facets without letting cohort facets block option recovery", async () => {
    window.history.replaceState(
      null,
      "",
      "/results/tpch/?sf=0.1&phase=power&platform=duckdb&deployment=cloud&cost_status=normalized",
    );

    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("DuckDB"));

    expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    expect(screen.queryByText("SQLite")).toBeNull();

    const resultCall = vi
      .mocked(queryRows)
      .mock.calls.find(([sql]) => String(sql).replace(/\s+/g, " ").trim().includes("FROM bench.results WHERE"));
    const resultSql = String(resultCall?.[0]);
    expect(resultSql).toContain("benchmark IN (?)");
    expect(resultSql).toContain("(platform IN (?) OR platform_id IN (?))");
    expect(resultSql).toContain("deployment_class IN (?)");
    expect(resultSql).toContain("cost_status IN (?)");
    expect(resultSql).not.toContain("scale_factor IN (?)");
    expect(resultSql).not.toContain("test_type IN (?)");
    expect(resultCall?.[1]).toEqual(["tpch", "duckdb", "duckdb", "cloud", "normalized"]);

    const rankingCalls = vi.mocked(queryRows).mock.calls.filter(([sql]) =>
      String(sql).replace(/\s+/g, " ").includes("FROM bench.benchmark_rankings"),
    );
    expect(rankingCalls[rankingCalls.length - 1]?.[1]).toEqual(["tpch", 0.1, "power"]);
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
    expect(new URL(window.location.href).searchParams.get("view")).toBe("list");
    expect(screen.queryByRole("button", { name: /^Q1/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Q2/ })).toBeNull();
  });

  it("restores benchmark view mode from the URL", async () => {
    window.history.replaceState(null, "", "/results/tpch/?view=list");

    render(<BenchmarkIndex benchmark="tpch" />);

    await waitFor(() => expect(screen.getByRole("button", { name: /Geomean/ })).toBeTruthy());
    expect(screen.queryByRole("button", { name: /^Q1/ })).toBeNull();
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

  it("list view caps rendered rows and expands them with Show more", async () => {
    const manyRows = Array.from({ length: 205 }, (_, index) => ({
      ...RESULT_ROWS[0]!,
      result_id: `r-list-${index}`,
      platform: `DuckDB ${index}`,
      platform_id: `duckdb-${index}`,
      display_geomean_ms: index + 1,
      geomean_ms: index + 1,
    }));
    vi.mocked(queryRows).mockImplementation(defaultImpl(manyRows, RANKING_ROWS, CELL_ROWS));

    const { container } = render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("DuckDB"));
    fireEvent.click(screen.getByText("List"));

    await waitFor(() => expect(screen.getByText("Showing 200 of 205 results for SF 0.1")).toBeTruthy());
    expect(getRenderedResultOrder(container)).toHaveLength(200);

    fireEvent.click(screen.getByRole("button", { name: "Show more results" }));

    expect(getRenderedResultOrder(container)).toHaveLength(205);
    expect(screen.getByText("Showing 205 of 205 results for SF 0.1")).toBeTruthy();
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

  it("coerces an invalid scale-factor URL value to the rendered scale", async () => {
    window.history.replaceState(null, "", "/results/tpch/?sf=abc");

    render(<BenchmarkIndex benchmark="tpch" />);
    await waitFor(() => screen.getAllByText("DuckDB"));

    await waitFor(() =>
      expect(new URL(window.location.href).searchParams.get("sf")).toBe("0.1"),
    );

    const rankingCalls = vi.mocked(queryRows).mock.calls.filter(([sql]) =>
      String(sql).replace(/\s+/g, " ").includes("FROM bench.benchmark_rankings"),
    );
    expect(rankingCalls[rankingCalls.length - 1]?.[1]).toEqual(["tpch", 0.1, "power"]);
  });
});
