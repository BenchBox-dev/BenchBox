import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/db", () => ({
  queryRows: vi.fn(),
}));

import { queryRows } from "@/db";
import { clearDuckdbQueryCachesForTests } from "@/lib/duckdbQueries";
import {
  EXPLORER_PERFORMANCE_MARKS,
  EXPLORER_PERFORMANCE_MEASURES,
  clearExplorerPerformanceEntriesForTests,
} from "@/lib/performanceMarks";
import { toggleFacetValue } from "@/lib/facetMatching";
import { Home } from "@/pages/Home";

const TIMING_ELIGIBLE = {
  has_display_timing: true,
  valid_query_count: 2,
  missing_query_count: 0,
  zero_timing_count: 0,
  display_exclusion_reason: null,
  comparison_exclusion_reason: null,
  ranking_exclusion_reason: null,
};

/**
 * ResultRow fixtures - shape mirrors the explicit `bench.results` projection
 * used by `listResults()`.
 */
const RESULT_ROWS = [
  {
    result_id: "r1",
    benchmark: "clickbench",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: null,
    run_date: "2026-04-17T12:00:00Z",
    power_score: null,
    total_duration_s: 12,
    geomean_ms: 10,
    display_geomean_ms: 10,
    query_count: 2,
    ...TIMING_ELIGIBLE,
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: "sql",
    tuning_mode: "tuned",
    tuning_hash: null,
    test_type: "power",
    validation_status: "exact",
    cost_usd: 1.1,
    normalized_cost_usd: 1.1,
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
    plans_published: false,
    has_tuning: true,
    bundle_download_url: "",
  },
  {
    result_id: "r2",
    benchmark: "clickbench",
    scale_factor: 0.1,
    platform: "SQLite",
    platform_id: "sqlite",
    driver_version: null,
    run_date: "2026-04-17T12:00:00Z",
    power_score: null,
    total_duration_s: 24,
    geomean_ms: 20,
    display_geomean_ms: 20,
    query_count: 2,
    ...TIMING_ELIGIBLE,
    trust_label: "community-submission",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: "sql",
    tuning_mode: "auto",
    tuning_hash: null,
    test_type: "power",
    validation_status: "exact",
    cost_usd: 2.3,
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
    is_ranking_eligible: true,
    has_plans: false,
    plans_published: false,
    has_tuning: false,
    bundle_download_url: "",
  },
  {
    result_id: "r3",
    benchmark: "tpch",
    scale_factor: 1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: null,
    run_date: "2026-04-16T12:00:00Z",
    power_score: 3000,
    total_duration_s: 60,
    geomean_ms: 30,
    display_geomean_ms: 30,
    query_count: 22,
    has_display_timing: true,
    valid_query_count: 22,
    missing_query_count: 0,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: "sql",
    tuning_mode: "tuned",
    tuning_hash: null,
    test_type: "power",
    validation_status: "exact",
    cost_usd: 5.5,
    normalized_cost_usd: 5.5,
    cost_status: "normalized",
    cost_scope: "compute_only",
    cost_model_version: "2026.05.0",
    deployment_class: "cloud",
    cloud_provider: "gcp",
    cloud_region: "us-central1",
    instance_or_warehouse: "LARGE",
    warehouse_size: "LARGE",
    storage_format: "parquet",
    compliance_class: null,
    is_ranking_eligible: true,
    has_plans: false,
    plans_published: false,
    has_tuning: true,
    bundle_download_url: "",
  },
  {
    result_id: "r4",
    benchmark: "star_schema",
    scale_factor: 1,
    platform: "Postgres",
    platform_id: "postgres",
    driver_version: null,
    run_date: "2026-04-15T12:00:00Z",
    power_score: null,
    total_duration_s: 42,
    geomean_ms: 21,
    display_geomean_ms: 21,
    query_count: 13,
    ...TIMING_ELIGIBLE,
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: "sql",
    tuning_mode: null,
    tuning_hash: null,
    test_type: "power",
    validation_status: "exact",
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
    is_ranking_eligible: true,
    has_plans: false,
    plans_published: false,
    has_tuning: false,
    bundle_download_url: "",
  },
];

/** Per-platform summary rows - shape mirrors `bench.meta_leaderboard`. */
const META_LEADERBOARD_ROWS = [
  { platform_id: "duckdb", platform: "DuckDB", avg_rank: 1, n_cohorts: 2 },
  { platform_id: "sqlite", platform: "SQLite", avg_rank: 2, n_cohorts: 1 },
];

/**
 * Per-variant cohort rows - shape mirrors `bench.cohort_metadata`.
 * The pivot in `getMetaLeaderboardData` reconstructs the nested MetaLeaderboard
 * from these rows.
 */
const COHORT_ROWS = [
  {
    cohort_key: "clickbench-sf0.1-power",
    benchmark: "clickbench",
    scale_factor: 0.1,
    phase: "power",
    cohort_label: "ClickBench SF0.1",
    cohort_href: "/results/clickbench/",
    platform_count: 2,
    cohort_ranked_count: 2,
    cohort_ranking_exclusion_reason: null,
    primary_metric: "display_geomean_ms",
    primary_order: "asc",
    platform_id: "duckdb",
    platform: "DuckDB",
    result_id: "r1",
    short_id: "",
    tuning_mode: "tuned",
    trust_label: "maintainer-run",
    ...TIMING_ELIGIBLE,
    rank: 1,
    metric_value: 10,
    speedup_vs_best: 1,
  },
  {
    cohort_key: "clickbench-sf0.1-power",
    benchmark: "clickbench",
    scale_factor: 0.1,
    phase: "power",
    cohort_label: "ClickBench SF0.1",
    cohort_href: "/results/clickbench/",
    platform_count: 2,
    cohort_ranked_count: 2,
    cohort_ranking_exclusion_reason: null,
    primary_metric: "display_geomean_ms",
    primary_order: "asc",
    platform_id: "sqlite",
    platform: "SQLite",
    result_id: "r2",
    short_id: "",
    tuning_mode: "auto",
    trust_label: "community-submission",
    ...TIMING_ELIGIBLE,
    rank: 2,
    metric_value: 20,
    speedup_vs_best: 0.5,
  },
  {
    cohort_key: "tpch-sf1-power",
    benchmark: "tpch",
    scale_factor: 1,
    phase: "power",
    cohort_label: "TPC-H SF1",
    cohort_href: "/results/tpch/",
    platform_count: 1,
    cohort_ranked_count: 1,
    cohort_ranking_exclusion_reason: null,
    primary_metric: "power_score",
    primary_order: "desc",
    platform_id: "duckdb",
    platform: "DuckDB",
    result_id: "r3",
    short_id: "",
    tuning_mode: "tuned",
    trust_label: "maintainer-run",
    has_display_timing: true,
    valid_query_count: 22,
    missing_query_count: 0,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
    rank: 1,
    metric_value: 3000,
    speedup_vs_best: 1,
  },
];

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function expectDocumentOrder(first: Element, second: Element) {
  expect(Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
}

beforeEach(() => {
  vi.clearAllMocks();
  clearDuckdbQueryCachesForTests();
  clearExplorerPerformanceEntriesForTests();
  window.history.replaceState(null, "", "/results/");
  vi.mocked(queryRows).mockImplementation(async (sql: string) => {
    const s = String(sql).replace(/\s+/g, " ").trim();
    if (s.includes("FROM bench.results")) return RESULT_ROWS;
    if (s.startsWith("SELECT platform_id, platform, avg_rank, n_cohorts FROM bench.meta_leaderboard")) {
      return META_LEADERBOARD_ROWS;
    }
    if (s.includes("FROM bench.cohort_metadata")) return COHORT_ROWS;
    return [];
  });
});

describe("Home", () => {
  it("renders the results shell when no meta leaderboard cohorts are available", async () => {
    vi.mocked(queryRows).mockImplementation(async (sql: string) => {
      const s = String(sql).replace(/\s+/g, " ").trim();
      if (s.includes("FROM bench.results")) return RESULT_ROWS;
      if (s.startsWith("SELECT platform_id, platform, avg_rank, n_cohorts FROM bench.meta_leaderboard")) return [];
      if (s.includes("FROM bench.cohort_metadata")) return [];
      return [];
    });

    render(<Home />);

    await waitFor(() => expect(screen.getByText("Recent Results")).toBeTruthy());
    expect(document.title).toBe("Results · BenchBox");
    expect(screen.queryByText("Initializing static DuckDB snapshot...")).toBeNull();
    expect(screen.queryByText("Cross-Benchmark Leaderboard")).toBeNull();
  });

  it("shows normalized cost in recent results only when normalized cost metadata is present", async () => {
    const rows = RESULT_ROWS.map((row, index) =>
      index === 0
        ? {
            ...row,
            normalized_cost_usd: 1.1,
            cost_status: "normalized",
            cost_scope: "compute_only",
            cost_model_version: "2026.05.0",
          }
        : row,
    );
    vi.mocked(queryRows).mockImplementation(async (sql: string) => {
      const s = String(sql).replace(/\s+/g, " ").trim();
      if (s.includes("FROM bench.results")) return rows;
      if (s.startsWith("SELECT platform_id, platform, avg_rank, n_cohorts FROM bench.meta_leaderboard")) {
        return [];
      }
      if (s.includes("FROM bench.cohort_metadata")) return [];
      return [];
    });

    render(<Home />);

    await waitFor(() => expect(screen.getByText("Recent Results")).toBeTruthy());
    expect(screen.getByText("Normalized cost")).toBeTruthy();
    expect(screen.getByText("$1.10")).toBeTruthy();
  });

  it("keeps the loading state while an empty result snapshot conflicts with leaderboard metadata", async () => {
    const metaRows = deferred<typeof META_LEADERBOARD_ROWS>();
    const cohortRows = deferred<typeof COHORT_ROWS>();
    const retryRows = deferred<typeof RESULT_ROWS>();
    let resultCalls = 0;

    vi.mocked(queryRows).mockImplementation(async (sql: string) => {
      const s = String(sql).replace(/\s+/g, " ").trim();
      if (s.includes("FROM bench.results")) {
        resultCalls += 1;
        return resultCalls === 1 ? [] : retryRows.promise;
      }
      if (s.startsWith("SELECT platform_id, platform, avg_rank, n_cohorts FROM bench.meta_leaderboard")) {
        return metaRows.promise;
      }
      if (s.includes("FROM bench.cohort_metadata")) {
        return cohortRows.promise;
      }
      return [];
    });

    render(<Home />);

    await waitFor(() => expect(resultCalls).toBe(1));
    await waitFor(() => expect(screen.getByText("Initializing static DuckDB snapshot...")).toBeTruthy());
    expect(screen.getByRole("heading", { level: 1, name: "BenchBox Database Leaderboards" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Cross-benchmark leaderboard loading" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(screen.queryByText("Recent Results")).toBeNull();
    expect(screen.queryByText("No leaderboard cells match the current filters.")).toBeNull();

    metaRows.resolve(META_LEADERBOARD_ROWS);
    cohortRows.resolve(COHORT_ROWS);

    await waitFor(() => expect(resultCalls).toBe(2));
    expect(screen.getByText("Initializing static DuckDB snapshot...")).toBeTruthy();
    expect(screen.queryByText("Recent Results")).toBeNull();
    expect(screen.queryByText("No leaderboard cells match the current filters.")).toBeNull();

    retryRows.resolve(RESULT_ROWS);

    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());
    expect(screen.queryByText("Initializing static DuckDB snapshot...")).toBeNull();
    expect(screen.queryByText("No leaderboard cells match the current filters.")).toBeNull();
  });

  it("renders a recoverable error when the empty result snapshot persists after retry", async () => {
    let resultCalls = 0;

    vi.mocked(queryRows).mockImplementation(async (sql: string) => {
      const s = String(sql).replace(/\s+/g, " ").trim();
      if (s.includes("FROM bench.results")) {
        resultCalls += 1;
        return [];
      }
      if (s.startsWith("SELECT platform_id, platform, avg_rank, n_cohorts FROM bench.meta_leaderboard")) {
        return META_LEADERBOARD_ROWS;
      }
      if (s.includes("FROM bench.cohort_metadata")) {
        return COHORT_ROWS;
      }
      return [];
    });

    render(<Home />);

    await waitFor(() => expect(resultCalls).toBe(2));
    expect(screen.getByText("Results snapshot incomplete")).toBeTruthy();
    expect(screen.getByText(/Reload the page to retry the DuckDB snapshot load/)).toBeTruthy();
    expect(screen.queryByText("Initializing static DuckDB snapshot...")).toBeNull();
    expect(screen.queryByText("Recent Results")).toBeNull();
  });

  it("renders the leaderboard-first product identity and dense cohort controls", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    expect(screen.getByRole("heading", { level: 1, name: "BenchBox Database Leaderboards" })).toBeTruthy();
    expect(
      screen.getByText("Reproducible OLAP benchmark rankings from rankable leaderboard cohorts, with public corpus browse below."),
    ).toBeTruthy();

    const selector = screen.getByRole("region", { name: "Leaderboard cohort selector" });
    expect(within(selector).getByLabelText("Cohort benchmark")).toBeTruthy();
    expect(within(selector).getByLabelText("Cohort scale")).toBeTruthy();
    expect(within(selector).getByLabelText("Cohort phase")).toBeTruthy();
    expect(within(selector).getByText("Leaderboard scope")).toBeTruthy();
    expect(within(selector).getByText("Ranked cohort filters")).toBeTruthy();

    fireEvent.click(screen.getByText("Advanced filters"));
    expect(within(selector).getByRole("button", { name: "All tuning labels" })).toBeTruthy();
    expect(within(selector).getByRole("button", { name: "Not labelled" })).toBeTruthy();
  });

  it("distinguishes supported benchmark coverage from published public corpus counts", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const summary = screen.getByRole("region", { name: "Corpus summary" });
    expect(within(summary).getByText("supported benchmarks")).toBeTruthy();
    expect(within(summary).getByText("3 with public results")).toBeTruthy();
    expect(within(summary).getByText("public result bundles")).toBeTruthy();
    expect(within(summary).getByText("platforms with public results")).toBeTruthy();
    expect(within(summary).getByText("leaderboard cohorts")).toBeTruthy();
    expect(within(summary).getByText("2 visible; 2/2 leaderboard-scope platforms")).toBeTruthy();
    expect(within(summary).queryByText(/^Benchmarks$/)).toBeNull();
  });

  it("states leaderboard cohort scope separately from public browse scope", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    expect(screen.getByText("Showing 2 of 2 leaderboard-scope platforms across 2 leaderboard cohorts")).toBeTruthy();
    expect(screen.getByText(/Benchmark options cover 2 of 3 public coverage benchmark sets/)).toBeTruthy();
    expect(screen.getAllByText(/SSB/).length).toBeGreaterThan(0);
    expect(screen.getByText(/1 public platform ID is outside the current leaderboard scope/)).toBeTruthy();
    expect(screen.getByText(/1 of 4 public results is not labelled for tuning/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Browse Public Benchmark Results" })).toBeTruthy();
    expect(
      screen.getByText("3 public benchmark set(s). Leaderboard filters above include 2 leaderboard-scope cohort(s)."),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Browse Public Platform Results" })).toBeTruthy();
  });

  it("keeps the home filter band on the dark surface and data sections on the light surface", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const hero = screen.getByTestId("home-hero-filter-band");
    const selector = within(hero).getByRole("region", { name: "Leaderboard cohort selector" });
    const dataSurface = screen.getByTestId("home-data-surface");

    expect(hero.className).toContain("surface-hero");
    expect(selector.className).toContain("bg-[var(--bb-bg-panel)]");
    expect(dataSurface.className).toContain("surface-app");
    expect(dataSurface.contains(selector)).toBe(false);
  });

  it("keeps the leaderboard region before secondary workflow and recent-result sections", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const headline = screen.getByRole("heading", { level: 1, name: "BenchBox Database Leaderboards" });
    const activeSummary = screen.getByRole("region", { name: "Active leaderboard filters" });
    const leaderboard = screen.getByRole("region", { name: "Cross-Benchmark Leaderboard" });
    const selector = screen.getByRole("region", { name: "Leaderboard cohort selector" });
    const workflow = screen.getByRole("navigation", { name: "Result contribution workflow" });
    const recentHeading = screen.getByRole("heading", { name: "Recent Results" });

    expect(within(activeSummary).getByText("All leaderboard cohorts")).toBeTruthy();
    expect(within(activeSummary).getByText("All cohort scales")).toBeTruthy();
    expect(within(activeSummary).getByText("All cohort phases")).toBeTruthy();
    expectDocumentOrder(headline, activeSummary);
    expectDocumentOrder(activeSummary, selector);
    expectDocumentOrder(selector, leaderboard);
    expectDocumentOrder(leaderboard, workflow);
    expectDocumentOrder(leaderboard, recentHeading);
  });

  it("records first leaderboard data and render performance entries", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    await waitFor(() => {
      expect(performance.getEntriesByName(EXPLORER_PERFORMANCE_MARKS.HOME_LEADERBOARD_DATA_READY, "mark"))
        .toHaveLength(1);
      expect(performance.getEntriesByName(EXPLORER_PERFORMANCE_MARKS.LEADERBOARD_RENDERED, "mark"))
        .toHaveLength(1);
      expect(performance.getEntriesByName(EXPLORER_PERFORMANCE_MEASURES.HOME_LEADERBOARD_DATA, "measure"))
        .toHaveLength(1);
      expect(performance.getEntriesByName(EXPLORER_PERFORMANCE_MEASURES.LEADERBOARD_RENDER_AFTER_DATA, "measure"))
        .toHaveLength(1);
    });
  });

  it("restores and updates Home leaderboard mode through the URL", async () => {
    window.history.replaceState(null, "", "/results/?mode=speedup");

    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    expect(screen.getByRole("radio", { name: "Speedup" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("0.50x")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "Ranks" }));

    await waitFor(() => expect(new URL(window.location.href).searchParams.get("mode")).toBe("ranks"));
  });

  it("renders a Compare entrypoint inside the leaderboard cohort selector", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const entrypoint = screen.getByTestId("home-compare-entrypoint");
    expect(entrypoint).toHaveAttribute("href", "/results/compare/");
    const selector = screen.getByRole("region", { name: "Leaderboard cohort selector" });
    expect(selector.contains(entrypoint)).toBe(true);
  });

  it("renders a compact run-compare-submit workflow near the leaderboard", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    expect(screen.getByText("Run -> Compare -> Submit")).toBeTruthy();
    const workflow = screen.getByRole("navigation", { name: "Result contribution workflow" });
    expect(within(workflow).getByRole("link", { name: "Run a benchmark" })).toHaveAttribute(
      "href",
      "/docs/usage/installation.html",
    );
    expect(within(workflow).getByRole("link", { name: "Compare your result" })).toHaveAttribute(
      "href",
      "/results/compare",
    );
    expect(within(workflow).getByRole("link", { name: "Submit a bundle" })).toHaveAttribute(
      "href",
      "/docs/contributing-results.html",
    );
    expect(screen.queryByText("Run BenchBox on your platform and submit your results")).toBeNull();
  });

  it("treats a benchmark selector change as isolate-not-exclude from the default all state", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const grid = screen.getByRole("grid", { name: "Cross-benchmark leaderboard" });
    expect(within(grid).getByRole("link", { name: /^ClickBench SF0.1/ })).toBeTruthy();
    expect(within(grid).getByRole("link", { name: /^TPC-H SF1/ })).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Cohort benchmark"), { target: { value: "clickbench" } });

    await waitFor(() => {
      expect(within(grid).getByRole("link", { name: /^ClickBench SF0.1/ })).toBeTruthy();
      expect(within(grid).queryByRole("link", { name: /^TPC-H SF1/ })).toBeNull();
    });
  });

  it("shows active facet combination and targeted reset actions when filters remove all coverage", async () => {
    window.history.replaceState(null, "", "/results/?sf=999&platform=duckdb");

    render(<Home />);

    const emptyState = await screen.findByRole("region", {
      name: "No leaderboard cells match the current filters",
    });
    expect(within(emptyState).getByText("Scale factor")).toBeTruthy();
    expect(within(emptyState).getByText("SF 999")).toBeTruthy();
    expect(within(emptyState).getByText("Platform")).toBeTruthy();
    expect(within(emptyState).getByText("DuckDB")).toBeTruthy();
    expect(within(emptyState).getByRole("button", { name: "Clear scale factor" })).toBeTruthy();
    expect(within(emptyState).getByRole("button", { name: "Clear platform" })).toBeTruthy();
    expect(within(emptyState).getByRole("button", { name: "Reset all" })).toBeTruthy();

    fireEvent.click(within(emptyState).getByRole("button", { name: "Clear scale factor" }));

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("sf")).toBeNull();
      expect(screen.queryByRole("region", { name: "No leaderboard cells match the current filters" })).toBeNull();
    });
    expect(new URLSearchParams(window.location.search).get("platform")).toBe("duckdb");
    expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy();
  });

  it("restores canonical URL facets and applies them to the Home result query", async () => {
    window.history.replaceState(
      null,
      "",
      "/results/?benchmark=clickbench&sf=0.1&phase=power&platform=DuckDB&deployment=cloud&cost_status=normalized",
    );

    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const grid = screen.getByRole("grid", { name: "Cross-benchmark leaderboard" });
    expect(within(grid).getByText("DuckDB")).toBeTruthy();
    expect(within(grid).queryByText("SQLite")).toBeNull();
    expect(within(grid).queryByRole("link", { name: /^TPC-H SF1/ })).toBeNull();

    const resultCall = vi
      .mocked(queryRows)
      .mock.calls.find(([sql]) => String(sql).replace(/\s+/g, " ").trim().includes("FROM bench.results WHERE"));
    expect(String(resultCall?.[0])).toContain("benchmark IN (?)");
    expect(String(resultCall?.[0])).toContain("scale_factor IN (?)");
    expect(String(resultCall?.[0])).toContain("test_type IN (?)");
    expect(String(resultCall?.[0])).toContain("(platform IN (?) OR platform_id IN (?))");
    expect(String(resultCall?.[0])).toContain("deployment_class IN (?)");
    expect(String(resultCall?.[0])).toContain("cost_status IN (?)");
    expect(resultCall?.[1]).toEqual(["clickbench", 0.1, "power", "DuckDB", "DuckDB", "cloud", "normalized"]);

    const cohortLink = within(grid).getByRole("link", { name: /^ClickBench SF0.1/ }) as HTMLAnchorElement;
    expect(cohortLink.getAttribute("href")).toContain("sf=0.1");
    expect(cohortLink.getAttribute("href")).toContain("phase=power");
    expect(cohortLink.getAttribute("href")).toContain("platform=DuckDB");
    expect(cohortLink.getAttribute("href")).toContain("deployment=cloud");
    expect(cohortLink.getAttribute("href")).toContain("cost_status=normalized");
  });

  it("restores URL facet aliases while keeping coverage labels visible", async () => {
    window.history.replaceState(
      null,
      "",
      "/results/?bm=clickbench&scale_factor=0.1&trust_tier=maintainer-run",
    );

    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    await waitFor(() => {
      const params = new URL(window.location.href).searchParams;
      expect(params.get("benchmark")).toBe("clickbench");
      expect(params.get("sf")).toBe("0.1");
      expect(params.get("trust")).toBe("maintainer-run");
      expect(params.get("bm")).toBeNull();
      expect(params.get("scale_factor")).toBeNull();
      expect(params.get("trust_tier")).toBeNull();
    });

    const grid = screen.getByRole("grid", { name: "Cross-benchmark leaderboard" });
    expect(within(grid).getByRole("columnheader", { name: "Avg rank over covered cohorts" })).toBeTruthy();
    expect(within(grid).getByText("1/1 cohorts")).toBeTruthy();
    expect(within(grid).getByText("over 1/1")).toBeTruthy();
  });

  it("surfaces leaderboard receipt links with trust and validation metadata", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const grid = screen.getByRole("grid", { name: "Cross-benchmark leaderboard" });
    const receiptLink = within(grid).getByRole("link", { name: "10 ms" }) as HTMLAnchorElement;

    expect(receiptLink.getAttribute("href")).toBe("/results/r/r1#run-receipt");
    expect(within(grid).getAllByText("Maintainer").length).toBeGreaterThan(0);
    expect(within(grid).getAllByText("Community").length).toBeGreaterThan(0);
    expect(within(grid).getAllByText("exact").length).toBeGreaterThan(0);
  });


  it("filters the matrix by trust tier and preserves tuning in cohort links", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const grid = screen.getByRole("grid", { name: "Cross-benchmark leaderboard" });
    expect(within(grid).getByText("DuckDB")).toBeTruthy();
    expect(within(grid).getByText("SQLite")).toBeTruthy();

    fireEvent.click(screen.getByText("Advanced filters"));
    fireEvent.click(screen.getByRole("button", { name: "auto" }));
    fireEvent.click(screen.getByRole("button", { name: "community-submission" }));

    await waitFor(() => {
      expect(within(grid).queryByText("DuckDB")).toBeNull();
    });
    expect(within(grid).getByText("SQLite")).toBeTruthy();

    const cohortLink = within(grid).getByRole("link", { name: /^ClickBench SF0.1/ }) as HTMLAnchorElement;
    expect(cohortLink.getAttribute("href")).toContain("/results/clickbench/");
    expect(cohortLink.getAttribute("href")).toContain("sf=0.1");
    expect(cohortLink.getAttribute("href")).toContain("phase=power");
    expect(cohortLink.getAttribute("href")).toContain("tuning=auto");
  });
});

describe("toggleFacetValue (w13)", () => {
  it("removes a value when it is already selected, leaving siblings intact", () => {
    // Pre-w13 the dropdown handler did `[value]` (single-element replacement),
    // collapsing ?bm=tpch,clickbench to just one entry on any subsequent click.
    expect(toggleFacetValue(["tpch", "clickbench"], "tpch")).toEqual(["clickbench"]);
    expect(toggleFacetValue(["tpch", "clickbench"], "clickbench")).toEqual(["tpch"]);
  });

  it("adds a value when it is not already selected", () => {
    expect(toggleFacetValue(["tpch"], "clickbench")).toEqual(["tpch", "clickbench"]);
  });

  it("returns an empty list when toggling the only selected value", () => {
    expect(toggleFacetValue(["tpch"], "tpch")).toEqual([]);
  });

  it("does not mutate the input list", () => {
    const input = ["tpch", "clickbench"];
    toggleFacetValue(input, "tpch");
    expect(input).toEqual(["tpch", "clickbench"]);
  });
});
