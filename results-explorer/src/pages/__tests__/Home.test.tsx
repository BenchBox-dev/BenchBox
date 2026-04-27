import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/db", () => ({
  queryRows: vi.fn(),
}));

import { queryRows } from "@/db";
import { Home } from "@/pages/Home";

/**
 * ResultRow fixtures - shape mirrors `bench.results` (SELECT * FROM bench.results).
 * Home consumes these via `listResults()`.
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
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: "sql",
    tuning_mode: "tuned",
    tuning_hash: null,
    test_type: "power",
    validation_status: "exact",
    cost_usd: 1.1,
    compliance_class: null,
    is_ranking_eligible: true,
    has_plans: false,
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
    trust_label: "community-submission",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: "sql",
    tuning_mode: "auto",
    tuning_hash: null,
    test_type: "power",
    validation_status: "exact",
    cost_usd: 2.3,
    compliance_class: null,
    is_ranking_eligible: true,
    has_plans: false,
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
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: "sql",
    tuning_mode: "tuned",
    tuning_hash: null,
    test_type: "power",
    validation_status: "exact",
    cost_usd: 5.5,
    compliance_class: null,
    is_ranking_eligible: true,
    has_plans: false,
    has_tuning: true,
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
    primary_metric: "display_geomean_ms",
    primary_order: "asc",
    platform_id: "duckdb",
    platform: "DuckDB",
    result_id: "r1",
    short_id: "",
    tuning_mode: "tuned",
    trust_label: "maintainer-run",
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
    primary_metric: "display_geomean_ms",
    primary_order: "asc",
    platform_id: "sqlite",
    platform: "SQLite",
    result_id: "r2",
    short_id: "",
    tuning_mode: "auto",
    trust_label: "community-submission",
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
    primary_metric: "power_score",
    primary_order: "desc",
    platform_id: "duckdb",
    platform: "DuckDB",
    result_id: "r3",
    short_id: "",
    tuning_mode: "tuned",
    trust_label: "maintainer-run",
    rank: 1,
    metric_value: 3000,
    speedup_vs_best: 1,
  },
];

beforeEach(() => {
  window.history.replaceState(null, "", "/results/");
  vi.mocked(queryRows).mockImplementation(async (sql: string) => {
    const s = String(sql).replace(/\s+/g, " ").trim();
    if (s.startsWith("SELECT * FROM bench.results")) return RESULT_ROWS;
    if (s.startsWith("SELECT platform_id, platform, avg_rank, n_cohorts FROM bench.meta_leaderboard")) {
      return META_LEADERBOARD_ROWS;
    }
    if (s.startsWith("SELECT * FROM bench.cohort_metadata")) return COHORT_ROWS;
    return [];
  });
});

describe("Home", () => {
  it("treats a benchmark chip click as isolate-not-exclude from the default all state", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const grid = screen.getByRole("grid", { name: "Cross-benchmark leaderboard" });
    expect(within(grid).getByRole("link", { name: "ClickBench SF0.1" })).toBeTruthy();
    expect(within(grid).getByRole("link", { name: "TPC-H SF1" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "ClickBench" }));

    await waitFor(() => {
      expect(within(grid).getByRole("link", { name: "ClickBench SF0.1" })).toBeTruthy();
      expect(within(grid).queryByRole("link", { name: "TPC-H SF1" })).toBeNull();
    });
  });

  it("filters the matrix by trust tier and preserves tuning in cohort links", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Cross-Benchmark Leaderboard")).toBeTruthy());

    const grid = screen.getByRole("grid", { name: "Cross-benchmark leaderboard" });
    expect(within(grid).getByText("DuckDB")).toBeTruthy();
    expect(within(grid).getByText("SQLite")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "auto" }));
    fireEvent.click(screen.getByRole("button", { name: "community-submission" }));

    await waitFor(() => {
      expect(within(grid).queryByText("DuckDB")).toBeNull();
    });
    expect(within(grid).getByText("SQLite")).toBeTruthy();

    const cohortLink = within(grid).getByRole("link", { name: "ClickBench SF0.1" }) as HTMLAnchorElement;
    expect(cohortLink.getAttribute("href")).toContain("/results/clickbench/");
    expect(cohortLink.getAttribute("href")).toContain("sf=0.1");
    expect(cohortLink.getAttribute("href")).toContain("phase=power");
    expect(cohortLink.getAttribute("href")).toContain("tuning=auto");
  });
});
